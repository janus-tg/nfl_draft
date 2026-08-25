"""Player valuation: availability-adjusted projections, Monte Carlo season
outcomes, VORP, and the blend with market consensus.

The chain is:
  1. 2026 weekly projections -> a full-health per-game rate under league rules
  2. risk.py -> expected games and a production multiplier
  3. Monte Carlo -> a distribution of season outcomes, not a point estimate
  4. VORP against a replacement level that accounts for FLEX
  5. blend with ADP, because consensus prices in situations box scores can't see
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    CHAMP_WEIGHTS,
    FANTASY_PLAYOFF_WEEKS,
    FLEX_POSITIONS,
    GAMES_PER_TEAM,
    LEAGUE_TEAMS,
    MARKET_FADE_ASYMMETRY,
    MARKET_WEIGHT,
    N_SIMS,
    POSITIONS,
    PROJECTION_SIGMA_BASE,
    PROJECTION_SIGMA_MARKET_GAP,
    PROJECTION_SIGMA_ROOKIE,
    RANDOM_SEED,
    SEASON,
    SEASON_ENDING_SHARE,
    STARTERS,
    TIER_DROP,
)
from logger import logger
from risk import (
    build_history,
    player_risk_profile,
    positional_cv,
    volatility_profile,
)
from scoring import score_row


# ------------------------------------------------------- base projections
def build_base_projections(proj_by_week: dict[int, dict], players: dict) -> pd.DataFrame:
    """Full-health per-game scoring rate from the 2026 weekly projections.

    Dividing by projected games rather than summing raw weeks is what keeps the
    injury adjustment honest: the rate is "points when he plays", and games
    played is then supplied separately by the risk model.
    """
    totals: dict[str, dict] = {}
    for week, payload in proj_by_week.items():
        for pid, row in (payload or {}).items():
            if not isinstance(row, dict):
                continue
            info = players.get(pid) or {}
            pos = info.get("position")
            if pos not in POSITIONS:
                continue
            gp = float(row.get("gp") or 0.0)
            if gp <= 0:
                continue
            rec = totals.setdefault(
                pid, {"points": 0.0, "games": 0.0, "adp": np.nan, "pos_adp": np.nan}
            )
            rec["points"] += score_row(row, pos)
            rec["games"] += gp
            adp = row.get("adp_dd_ppr")
            if adp is not None and float(adp) < 999 and np.isnan(rec["adp"]):
                rec["adp"] = float(adp)
            padp = row.get("pos_adp_dd_ppr")
            if padp is not None and float(padp) < 999 and np.isnan(rec["pos_adp"]):
                rec["pos_adp"] = float(padp)

    rows = []
    for pid, rec in totals.items():
        if rec["games"] < 1:
            continue
        info = players.get(pid) or {}
        name = info.get("full_name") or info.get("last_name") or info.get("team") or pid
        rows.append(
            {
                "player_id": pid,
                "player": name,
                "team": info.get("team") or "",
                "pos": info.get("position"),
                "ppg_healthy": rec["points"] / rec["games"],
                "proj_weeks": rec["games"],
                "adp": rec["adp"],
                "pos_adp": rec["pos_adp"],
                "search_rank": info.get("search_rank"),
                "depth_chart_order": info.get("depth_chart_order"),
                "years_exp": info.get("years_exp"),
                "bye_risk_weeks": np.nan,
            }
        )
    df = pd.DataFrame(rows)
    logger.info(f"Base projections built for {len(df)} players ({SEASON}).")
    return df


# ------------------------------------------------------- risk attachment
def attach_risk(df: pd.DataFrame, players: dict, hist: dict) -> pd.DataFrame:
    pos_cv = positional_cv(hist, players)
    records = []
    for row in df.itertuples(index=False):
        profile = player_risk_profile(row.player_id, row.pos, players, hist)
        profile.update(volatility_profile(row.player_id, row.pos, hist, pos_cv))
        profile["player_id"] = row.player_id
        # Historical role: snap share separates a starter from a committee back.
        rec = hist.get(row.player_id) or {}
        profile["snap_share"] = rec.get("snap_share")
        profile["hist_games"] = rec.get("games_played", 0)
        profile["hist_ppg"] = (
            float(np.mean(rec["points"])) if rec.get("points") else np.nan
        )
        records.append(profile)
    risk_df = pd.DataFrame(records)
    out = df.merge(risk_df, on="player_id", how="left")

    # Expected points = rate when playing, degraded by rust/age, times games.
    out["ppg_adj"] = out["ppg_healthy"] * out["production_multiplier"]
    out["proj_points"] = out["ppg_adj"] * out["expected_games"]
    # What the old pipeline reported: everyone plays every game, no rust.
    out["naive_points"] = out["ppg_healthy"] * GAMES_PER_TEAM
    out["risk_cost"] = out["naive_points"] - out["proj_points"]
    return out


# ------------------------------------------------------- simulation
def _split_absence_risk(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Split expected missed games into a season-ending hazard and soft misses.

    Returns (weekly_hazard, soft_miss_prob), calibrated so that the resulting
    expected games played still matches the risk model's number. The split is
    what creates a realistic left tail without moving the mean.
    """
    weeks = GAMES_PER_TEAM
    avail = df["availability"].to_numpy(dtype=float).clip(0.02, 1.0)
    share = df["pos"].map(SEASON_ENDING_SHARE).fillna(0.35).to_numpy(dtype=float)

    missed = (1.0 - avail) * weeks
    se_missed = missed * share

    # A season-ending injury at a uniformly random week costs ~half a season on
    # average, so the per-season probability of one is roughly 2*se_missed/weeks.
    p_season_ending = np.clip(2.0 * se_missed / weeks, 0.0, 0.85)
    hazard = 1.0 - np.power(1.0 - p_season_ending, 1.0 / weeks)

    # Expected games surviving the hazard alone, then solve soft misses to hit
    # the target availability exactly.
    survive = np.array(
        [np.sum(np.power(1.0 - h, np.arange(weeks))) for h in hazard]
    )
    target_games = avail * weeks
    soft_keep = np.clip(target_games / np.maximum(survive, 1e-6), 0.0, 1.0)
    return hazard, 1.0 - soft_keep


def simulate_seasons(df: pd.DataFrame, n_sims: int = N_SIMS,
                     seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Monte Carlo the season, week by week, for every player at once.

    Three sources of uncertainty, in rough order of how much they matter:

      projection error -- one draw per simulated season for a player's true
                          per-game rate. Whether the role and the projection are
                          right at all dominates everything else.
      season-ending injury -- a weekly hazard that, once it fires, zeroes every
                          remaining week. This is what produces a real left tail.
      week-to-week noise -- gamma-distributed, because fantasy scoring is
                          non-negative and right-skewed; a normal would
                          understate ceilings and invent negative games.
    """
    rng = np.random.default_rng(seed)
    n = len(df)
    weeks = GAMES_PER_TEAM
    playoff_weeks = min(len(FANTASY_PLAYOFF_WEEKS), weeks)

    ppg = df["ppg_adj"].to_numpy(dtype=float).clip(min=0.01)
    cv = df["cv"].to_numpy(dtype=float).clip(0.15, 1.6)
    hazard, soft_miss = _split_absence_risk(df)

    # Projection uncertainty: wider for unproven players and for players the
    # market and the model disagree about.
    sigma = df["pos"].map(PROJECTION_SIGMA_BASE).fillna(0.30).to_numpy(dtype=float)
    unproven = (df["hist_games"].fillna(0).to_numpy() < 8)
    sigma = sigma + unproven * PROJECTION_SIGMA_ROOKIE
    if "market_gap_z" in df.columns:
        sigma = sigma + df["market_gap_z"].abs().clip(0, 3).to_numpy() * PROJECTION_SIGMA_MARKET_GAP

    # Method-of-moments gamma: shape k = 1/cv^2.
    shape = 1.0 / np.square(cv)

    season_totals = np.empty((n, n_sims), dtype=np.float32)
    playoff_ppg = np.empty(n, dtype=np.float64)
    dud_rate = np.empty(n, dtype=np.float64)
    season_ended = np.empty(n, dtype=np.float64)

    # The full (players, weeks, sims) cube is several hundred MB, so walk it in
    # player chunks and keep only the reductions.
    chunk = max(1, int(4_000_000 // (weeks * n_sims)) or 1)
    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        m = stop - start
        sl = slice(start, stop)

        # One true-rate draw per simulated season, shared across that season's
        # weeks (median-preserving, so the mean projection is not inflated).
        sig = sigma[sl][:, None]
        true_rate = ppg[sl][:, None] * np.exp(
            rng.normal(-0.5 * sig ** 2, sig, size=(m, n_sims))
        )

        sh = shape[sl][:, None, None]
        sc = (true_rate / shape[sl][:, None])[:, None, :]

        # Season-ending injury: first week it fires, and everything after is 0.
        hit = rng.random((m, weeks, n_sims)) < hazard[sl][:, None, None]
        alive = np.cumsum(hit, axis=1) == 0
        active = alive & (rng.random((m, weeks, n_sims)) >= soft_miss[sl][:, None, None])

        weekly = np.where(active, rng.gamma(sh, sc, size=(m, weeks, n_sims)), 0.0)

        season_totals[sl] = weekly.sum(axis=1, dtype=np.float64).astype(np.float32)
        playoff_ppg[sl] = (
            weekly[:, -playoff_weeks:, :].sum(axis=1).mean(axis=1) / playoff_weeks
        )
        # Weeks that score essentially nothing -- injury or a true zero.
        dud_rate[sl] = (weekly < 3.0).mean(axis=(1, 2))
        season_ended[sl] = (~alive[:, -1, :]).mean(axis=1)
        del hit, alive, active, weekly, true_rate

    df = df.copy()
    df["sim_mean"] = season_totals.mean(axis=1)
    df["sim_p10"] = np.percentile(season_totals, 10, axis=1)
    df["sim_p50"] = np.percentile(season_totals, 50, axis=1)
    df["sim_p90"] = np.percentile(season_totals, 90, axis=1)
    df["sim_sd"] = season_totals.std(axis=1)
    df["playoff_ppg"] = playoff_ppg
    df["dud_week_rate"] = dud_rate
    df["p_season_ending_injury"] = season_ended

    _attach_finish_probabilities(df, season_totals)
    logger.info(f"Simulated {n_sims} seasons for {n} players.")
    return df


def _attach_finish_probabilities(df: pd.DataFrame, totals: np.ndarray) -> None:
    """P(top-N at position) and P(bust), computed jointly across each sim.

    Ranking within a simulation -- rather than comparing marginal distributions
    -- is what makes these real probabilities: they account for the fact that a
    player only finishes as the RB1 if he beats the other RBs in that same world.
    """
    df["p_positional_elite"] = 0.0
    df["p_positional_starter"] = 0.0
    df["p_bust"] = 0.0

    for pos in POSITIONS:
        mask = (df["pos"] == pos).to_numpy()
        if mask.sum() == 0:
            continue
        sub = totals[mask]                                  # (n_pos, n_sims)
        # Rank 1 = best in that simulated season.
        order = np.argsort(np.argsort(-sub, axis=0), axis=0) + 1

        starters = STARTERS.get(pos, 1) * LEAGUE_TEAMS
        elite = max(3, starters // 4)

        df.loc[mask, "p_positional_elite"] = (order <= elite).mean(axis=1)
        df.loc[mask, "p_positional_starter"] = (order <= starters).mean(axis=1)
        # A bust is a player who fails to return even startable production.
        df.loc[mask, "p_bust"] = (order > starters * 1.5).mean(axis=1)


# ------------------------------------------------------- replacement / VORP
def compute_vorp(df: pd.DataFrame, teams: int = LEAGUE_TEAMS) -> pd.DataFrame:
    """VORP against a replacement level that accounts for the FLEX slot.

    A naive baseline of "starters x teams" understates RB/WR scarcity, because
    the flex is filled from that same pool. Here the flex demand is allocated
    across RB/WR/TE in proportion to how often each actually wins the slot.
    """
    df = df.copy()
    demand = {pos: STARTERS.get(pos, 0) * teams for pos in POSITIONS}

    # Allocate the league's flex slots to whichever position supplies them.
    flex_slots = teams
    pool = []
    for pos in FLEX_POSITIONS:
        sub = df[df["pos"] == pos].sort_values("proj_points", ascending=False)
        pool.append(sub.iloc[demand[pos]:][["pos", "proj_points"]])
    if pool:
        flex_pool = pd.concat(pool).sort_values("proj_points", ascending=False)
        for pos, count in flex_pool.head(flex_slots)["pos"].value_counts().items():
            demand[pos] += int(count)

    baselines = {}
    for pos in POSITIONS:
        sub = df[df["pos"] == pos].sort_values("proj_points", ascending=False)
        if sub.empty:
            baselines[pos] = 0.0
            continue
        idx = min(demand[pos], len(sub) - 1)
        baselines[pos] = float(sub["proj_points"].iloc[idx])

    logger.info("Replacement baselines: " +
                ", ".join(f"{p}={baselines[p]:.0f} (n={demand[p]})" for p in POSITIONS))

    df["replacement"] = df["pos"].map(baselines)
    df["VORP"] = df["proj_points"] - df["replacement"]
    df["VORP_ceiling"] = df["sim_p90"] - df["replacement"]
    df["VORP_floor"] = df["sim_p10"] - df["replacement"]
    # What last year's model would have said, for comparison.
    naive_base = {
        pos: float(
            df[df["pos"] == pos]
            .sort_values("naive_points", ascending=False)["naive_points"]
            .iloc[min(STARTERS.get(pos, 1) * teams, max(len(df[df["pos"] == pos]) - 1, 0))]
        )
        if len(df[df["pos"] == pos]) else 0.0
        for pos in POSITIONS
    }
    df["VORP_naive"] = df["naive_points"] - df["pos"].map(naive_base)
    return df


# ------------------------------------------------------- market blend
def blend_market(df: pd.DataFrame, teams: int = LEAGUE_TEAMS) -> pd.DataFrame:
    """Reconcile the model with consensus ADP.

    Consensus prices in things a stat line cannot: camp reports, holdouts,
    scheme changes, and how a rehab is actually going. So where the market is
    far more pessimistic than the model, it usually knows something -- that
    direction gets extra weight (MARKET_FADE_ASYMMETRY). The disagreement
    itself is the useful output: it names your targets and your fades.
    """
    df = df.copy()
    max_adp = float(teams * 16)
    adp = df["adp"].fillna(max_adp).clip(upper=max_adp)
    df["adp_filled"] = adp

    # Translate ADP into points by reading the model's own value curve at the
    # rank the market assigns. This puts both opinions in the same units.
    ranked = df.sort_values("VORP", ascending=False).reset_index(drop=True)
    value_curve = ranked["VORP"].to_numpy()
    positions = np.arange(1, len(value_curve) + 1)
    market_vorp = np.interp(adp.to_numpy(), positions, value_curve)
    df["market_VORP"] = market_vorp

    weight = np.full(len(df), MARKET_WEIGHT)
    # Market lower than model -> trust the market more.
    fade = market_vorp < df["VORP"].to_numpy()
    weight[fade] += MARKET_FADE_ASYMMETRY
    weight = np.clip(weight, 0.0, 0.9)

    df["blended_VORP"] = (1 - weight) * df["VORP"] + weight * market_vorp
    df["market_gap"] = df["VORP"] - df["market_VORP"]

    df["model_rank"] = df["blended_VORP"].rank(ascending=False, method="first").astype(int)
    df["market_rank"] = adp.rank(method="first").astype(int)
    df["rank_edge"] = df["market_rank"] - df["model_rank"]
    return df


# ------------------------------------------------------- championship score
def championship_score(df: pd.DataFrame) -> pd.DataFrame:
    """Rank on title equity rather than raw expected points.

    Championships are won by rosters with league-winning outcomes at a couple
    of positions, not by rosters with the best average. So upside (P of an
    elite positional finish) is priced alongside expected value, and bust risk
    is charged against it.
    """
    df = df.copy()

    def z(series: pd.Series) -> pd.Series:
        s = series.astype(float)
        sd = s.std(ddof=0)
        return (s - s.mean()) / sd if sd > 1e-9 else s * 0.0

    w = CHAMP_WEIGHTS
    df["champ_score"] = (
        w["vorp"] * z(df["blended_VORP"])
        + w["upside"] * z(df["VORP_ceiling"] * df["p_positional_elite"])
        - w["bust"] * z(df["p_bust"] * df["replacement"].clip(lower=1))
    )
    df["champ_rank"] = df["champ_score"].rank(ascending=False, method="first").astype(int)
    return df


# ------------------------------------------------------- tiers
def assign_tiers(df: pd.DataFrame, tier_drop: float = TIER_DROP) -> pd.DataFrame:
    """Break each position into tiers wherever value falls off a cliff.

    Tiers are what you actually draft from: reaching for the last player in a
    tier is fine, reaching for the first player in the next one is not.
    """
    parts = []
    for pos in POSITIONS:
        sub = df[df["pos"] == pos].sort_values("blended_VORP", ascending=False).copy()
        if sub.empty:
            continue
        tier, prev, tiers = 1, None, []
        for value in sub["blended_VORP"]:
            if prev is not None and (prev - value) >= tier_drop:
                tier += 1
            tiers.append(tier)
            prev = value
        sub["tier"] = tiers
        sub["pos_rank"] = range(1, len(sub) + 1)
        parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else df


def build_valuation(proj_by_week: dict[int, dict],
                    actuals_by_season: dict[int, dict[int, dict]],
                    players: dict) -> pd.DataFrame:
    """Full pipeline: projections -> risk -> simulation -> VORP -> market."""
    hist = build_history(actuals_by_season, players)
    df = build_base_projections(proj_by_week, players)
    df = attach_risk(df, players, hist)
    df = simulate_seasons(df)
    df = compute_vorp(df)
    df = blend_market(df)
    df = championship_score(df)
    df = assign_tiers(df)
    return df.sort_values("champ_rank").reset_index(drop=True)
