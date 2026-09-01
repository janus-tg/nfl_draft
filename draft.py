"""Draft simulation and plan generation.

A ranked list is not a plan. What decides a draft is which players actually
survive to your pick, so this module simulates the whole room: eleven opponents
drafting to consensus ADP with noise, against a value function that knows your
roster needs and how steep the drop-off is at each position.

Outputs:
  * availability curves -- P(player is there at pick N)
  * a round-by-round plan for every draft slot, with fallbacks
  * positional run detection -- where the board tends to break
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

from config import (
    ADP_NOISE_SD,
    BENCH_SLOTS,
    DEF_EARLIEST_ROUND,
    DRAFT_ROUNDS,
    FLEX_POSITIONS,
    K_EARLIEST_ROUND,
    LEAGUE_TEAMS,
    POSITION_LIMITS,
    POSITIONS,
    QB_EARLIEST_ROUND,
    RANDOM_SEED,
    ROUND_UPSIDE_TILT,
    STARTERS,
    TE_EARLIEST_ROUND,
)
from logger import logger

EARLIEST_ROUND = {
    "QB": QB_EARLIEST_ROUND,
    "TE": TE_EARLIEST_ROUND,
    "K": K_EARLIEST_ROUND,
    "DEF": DEF_EARLIEST_ROUND,
}


def pick_number(slot: int, rnd: int, teams: int = LEAGUE_TEAMS) -> int:
    """Overall pick number for a slot in a snake draft (1-indexed)."""
    if rnd % 2 == 1:
        return (rnd - 1) * teams + slot
    return (rnd - 1) * teams + (teams - slot + 1)


def slot_picks(slot: int, teams: int = LEAGUE_TEAMS,
               rounds: int = DRAFT_ROUNDS) -> list[int]:
    return [pick_number(slot, r, teams) for r in range(1, rounds + 1)]


# ------------------------------------------------------- roster logic
class Roster:
    """Tracks what a team has and what it still needs."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = defaultdict(int)
        self.players: list[str] = []

    def add(self, pos: str, pid: str) -> None:
        self.counts[pos] += 1
        self.players.append(pid)

    def total(self) -> int:
        return len(self.players)

    def starters_missing(self) -> dict[str, int]:
        return {p: max(0, STARTERS.get(p, 0) - self.counts[p]) for p in POSITIONS}

    def flex_filled(self) -> bool:
        surplus = sum(
            max(0, self.counts[p] - STARTERS.get(p, 0)) for p in FLEX_POSITIONS
        )
        return surplus >= 1

    def bench_used(self) -> int:
        """Players on the roster that aren't occupying a starter or the flex
        slot. Only positional limits gated bench size before this -- e.g.
        RB/WR limits alone allow 6+7=13 bench-eligible players, so nothing
        stopped a roster from stacking bench past BENCH_SLOTS while leaving no
        picks for K/DEF."""
        starters_filled = sum(
            min(self.counts[p], STARTERS.get(p, 0)) for p in POSITIONS
        )
        flex_used = 1 if self.flex_filled() else 0
        return max(0, self.total() - starters_filled - flex_used)

    def can_take(self, pos: str, rnd: int, rounds: int = DRAFT_ROUNDS) -> bool:
        if self.counts[pos] >= POSITION_LIMITS.get(pos, 99):
            return False
        if rnd < EARLIEST_ROUND.get(pos, 0):
            return False
        missing = self.starters_missing()
        # Don't head into the final rounds still missing a starting slot.
        rounds_left = rounds - rnd + 1
        total_missing = sum(missing.values())
        if rounds_left <= total_missing and missing.get(pos, 0) == 0:
            return False
        # Once the bench is full, only a pick that fills a starter or the
        # flex slot is allowed -- otherwise the roster overfills the bench.
        fills_starter = missing.get(pos, 0) > 0
        fills_flex = pos in FLEX_POSITIONS and not self.flex_filled()
        if not fills_starter and not fills_flex and self.bench_used() >= BENCH_SLOTS:
            return False
        return True


def _need_multiplier(roster: Roster, pos: str, rnd: int,
                    rounds: int = DRAFT_ROUNDS) -> float:
    """How much this roster wants another player at `pos` right now.

    Depth has to diminish as a position stacks up. A flat bonus lets a scarce
    position keep winning picks long after the roster stops needing it -- which
    is how a board ends up spending four straight rounds on backup RBs while
    the flex-eligible WR pool empties out.
    """
    if roster.starters_missing().get(pos, 0) > 0:
        return 1.30
    if pos in FLEX_POSITIONS and not roster.flex_filled():
        # A second TE can technically fill the flex, but the position scores
        # far less per flex slot than an RB or WR does, so it should only win
        # that slot when it is clearly the better player -- not by default.
        return 0.95 if pos == "TE" else 1.12

    # One kicker, one defence, ever.
    if pos in ("K", "DEF"):
        return 0.0 if roster.counts[pos] >= 1 else 1.0

    # A backup QB or TE only earns a roster spot at the very end of the draft,
    # and only as a lottery ticket -- this is a one-QB, one-TE lineup.
    if pos in ("QB", "TE") and roster.counts[pos] >= 1:
        if roster.counts[pos] >= 2 or rnd < rounds - 2:
            return 0.0
        return 0.45

    # RB/WR bench depth: valuable for the first couple of spots, then sharply
    # less so. Backups are insurance, and you can only use so much insurance.
    extra = roster.counts[pos] - STARTERS.get(pos, 0)
    return float(max(0.30, 1.05 * (0.72 ** max(extra, 0))))


def _scarcity_bonus(pool: pd.DataFrame, pos: str, teams: int = LEAGUE_TEAMS) -> float:
    """Value lost by waiting: this player minus what's left a round from now.

    This is the whole point of positional scarcity -- an RB worth 20 more than
    the next twelve RBs is a better pick than a WR worth 25 more in the
    abstract but with an identical WR right behind him.
    """
    sub = pool[pool["pos"] == pos]
    if len(sub) < 2:
        return 0.0
    values = sub["blended_VORP"].to_numpy()
    nxt = values[min(teams, len(values) - 1)]
    return float(max(values[0] - nxt, 0.0))


# ------------------------------------------------------- the simulation
def simulate_drafts(board: pd.DataFrame, my_slot: int, n_sims: int = 300,
                    teams: int = LEAGUE_TEAMS, rounds: int = DRAFT_ROUNDS,
                    seed: int = RANDOM_SEED) -> dict:
    """Simulate the draft `n_sims` times from one seat.

    Opponents draft to ADP with gaussian noise -- the standard model of a real
    room, where managers mostly follow consensus but reach and slide.
    """
    rng = np.random.default_rng(seed + my_slot)

    pool = board.sort_values("champ_rank").reset_index(drop=True)
    pids = pool["player_id"].to_numpy()
    pos_arr = pool["pos"].to_numpy()
    adp = pool["adp_filled"].to_numpy(dtype=float)
    champ = pool["champ_score"].to_numpy(dtype=float)
    vorp = pool["blended_VORP"].to_numpy(dtype=float)
    ceiling = pool["VORP_ceiling"].to_numpy(dtype=float)
    idx_of = {pid: i for i, pid in enumerate(pids)}

    my_picks = slot_picks(my_slot, teams, rounds)
    my_pick_set = set(my_picks)

    round_choices: dict[int, list[str]] = defaultdict(list)
    roster_shapes: list[dict[str, int]] = []
    team_values: list[float] = []
    # P(available) measured inside the same simulation that makes the picks.
    # An ADP-only curve disagrees with it badly at QB and TE, because those
    # positions slide once every roster already has one.
    seen_available = np.zeros((rounds + 1, len(pool)), dtype=np.float64)

    for _ in range(n_sims):
        taken = np.zeros(len(pool), dtype=bool)
        rosters = {t: Roster() for t in range(1, teams + 1)}
        noisy_adp = adp + rng.normal(0.0, ADP_NOISE_SD, size=len(pool))

        for rnd in range(1, rounds + 1):
            order = range(1, teams + 1) if rnd % 2 else range(teams, 0, -1)
            for slot in order:
                overall = pick_number(slot, rnd, teams)
                roster = rosters[slot]
                available = ~taken
                if not available.any():
                    continue

                if overall in my_pick_set and slot == my_slot:
                    seen_available[rnd] += available
                    nxt = my_picks[rnd] if rnd < len(my_picks) else None
                    choice = _my_choice(
                        pool, available, roster, rnd, champ, vorp, ceiling,
                        pos_arr, teams, adp, nxt, rounds
                    )
                    if choice is not None:
                        round_choices[rnd].append(pids[choice])
                else:
                    choice = _opponent_choice(
                        available, roster, rnd, noisy_adp, pos_arr, rounds
                    )
                if choice is None:
                    continue
                taken[choice] = True
                rosters[slot].add(pos_arr[choice], pids[choice])

        mine = rosters[my_slot]
        roster_shapes.append(dict(mine.counts))
        team_values.append(
            float(sum(vorp[idx_of[p]] for p in mine.players if p in idx_of))
        )

    return {
        "slot": my_slot,
        "picks": my_picks,
        "round_choices": round_choices,
        "roster_shapes": roster_shapes,
        "team_value_mean": float(np.mean(team_values)) if team_values else 0.0,
        "p_available": seen_available / max(n_sims, 1),
        "pool_pids": pids,
    }


def _opponent_choice(available: np.ndarray, roster: Roster, rnd: int,
                     noisy_adp: np.ndarray, pos_arr: np.ndarray,
                     rounds: int) -> int | None:
    """Best-ADP player the opponent's roster rules allow."""
    order = np.argsort(noisy_adp)
    for i in order:
        if not available[i]:
            continue
        if not roster.can_take(pos_arr[i], rnd, rounds):
            continue
        return int(i)
    # Roster rules boxed them in; fall back to raw ADP.
    for i in order:
        if available[i]:
            return int(i)
    return None


def _survival_probability(adp: np.ndarray, next_pick: int) -> np.ndarray:
    """P(a player is still on the board at `next_pick`), from his ADP.

    Closed-form normal tail rather than another nested simulation -- inside the
    pick loop this gets evaluated tens of thousands of times.
    """
    if next_pick is None:
        return np.zeros_like(adp)
    z = (adp - next_pick) / (ADP_NOISE_SD * 1.4142)
    return 0.5 * (1.0 + np.vectorize(math.erf)(z))


def _my_choice(pool: pd.DataFrame, available: np.ndarray, roster: Roster, rnd: int,
               champ: np.ndarray, vorp: np.ndarray, ceiling: np.ndarray,
               pos_arr: np.ndarray, teams: int, adp: np.ndarray,
               next_pick: int | None, rounds: int = DRAFT_ROUNDS) -> int | None:
    """Value function for our seat.

    Raw value is only half the question. The other half is opportunity cost: a
    player who will still be there at your next pick is worth less *now* than
    one who certainly will not, because taking him spends a pick you could have
    used on the player about to disappear. Scoring value alone is what makes a
    board reach thirty picks ahead of ADP.
    """
    tilt = ROUND_UPSIDE_TILT.get(rnd, 1.0)
    avail_idx = np.flatnonzero(available)
    if avail_idx.size == 0:
        return None

    remaining = pool.iloc[avail_idx]
    # `pool` is champ_rank-ordered, so the first slice of what's available is
    # the only part any sane pick comes from. Capping it keeps the inner loop
    # cheap without changing the decision.
    avail_idx = avail_idx[:80]
    scarcity = {p: _scarcity_bonus(remaining, p, teams) for p in POSITIONS}
    scarcity_scale = max(max(scarcity.values()), 1.0)
    ceiling_scale = max(float(np.abs(ceiling).max()), 1.0)

    survive = _survival_probability(adp[avail_idx], next_pick)
    urgency = 1.0 - survive  # 1.0 = gone if you pass, 0.0 = certain to last

    best, best_score = None, -1e18
    for k, i in enumerate(avail_idx):
        pos = pos_arr[i]
        if not roster.can_take(pos, rnd, rounds):
            continue
        need = _need_multiplier(roster, pos, rnd, rounds)
        if need <= 0:
            continue
        # champ_score is already z-scaled; ceiling gets the round tilt, and
        # scarcity is normalised so it nudges rather than dominates.
        value = (
            champ[i]
            + 0.35 * tilt * (ceiling[i] / ceiling_scale)
            + 0.30 * (scarcity[pos] / scarcity_scale)
        ) * need
        # Keep most of the raw value so the best player is still usually the
        # pick, but let urgency break ties and stop the obvious reaches.
        score = value * (0.55 + 0.45 * urgency[k])
        if score > best_score:
            best, best_score = int(i), score
    return best


# ------------------------------------------------------- availability curves
def availability_curves(board: pd.DataFrame, n_sims: int = 400,
                        teams: int = LEAGUE_TEAMS, rounds: int = DRAFT_ROUNDS,
                        seed: int = RANDOM_SEED) -> pd.DataFrame:
    """P(each player is still on the board) at every pick in the draft.

    On draft day this is the number that matters: not "is he good" but "will he
    still be here next time it's my turn, or do I have to take him now".
    """
    rng = np.random.default_rng(seed)
    pool = board.sort_values("adp_filled").reset_index(drop=True)
    adp = pool["adp_filled"].to_numpy(dtype=float)
    n_players, total_picks = len(pool), teams * rounds

    gone_by = np.zeros((n_players, total_picks + 1), dtype=np.float64)
    for _ in range(n_sims):
        noisy = adp + rng.normal(0.0, ADP_NOISE_SD, size=n_players)
        order = np.argsort(noisy)[:total_picks]
        drafted_at = np.full(n_players, total_picks + 1, dtype=int)
        drafted_at[order] = np.arange(1, len(order) + 1)
        for p in range(1, total_picks + 1):
            gone_by[:, p] += (drafted_at <= p)
    gone_by /= n_sims

    out = pool[["player_id", "player", "pos", "adp_filled", "champ_rank"]].copy()
    # Store the full curve; the plan builder reads whatever picks it needs.
    out.attrs["curve"] = 1.0 - gone_by
    return out


def p_available(curve_df: pd.DataFrame, pid: str, pick: int) -> float:
    curve = curve_df.attrs.get("curve")
    if curve is None:
        return np.nan
    row = curve_df.index[curve_df["player_id"] == pid]
    if len(row) == 0:
        return np.nan
    pick = min(max(pick, 0), curve.shape[1] - 1)
    return float(curve[row[0], pick])


# ------------------------------------------------------- plan assembly
def build_plan_for_slot(board: pd.DataFrame, curve_df: pd.DataFrame, slot: int,
                        n_sims: int = 300, teams: int = LEAGUE_TEAMS,
                        rounds: int = DRAFT_ROUNDS) -> pd.DataFrame:
    """Round-by-round plan for one seat: primary target plus real fallbacks."""
    sim = simulate_drafts(board, slot, n_sims=n_sims, teams=teams, rounds=rounds)
    by_pid = board.set_index("player_id")
    pool_index = {pid: i for i, pid in enumerate(sim["pool_pids"])}
    avail = sim["p_available"]

    rows = []
    # Modal picks are counted independently per round, so the same player can
    # top two different rounds. Carrying a used-set makes the printed plan a
    # single coherent path instead of a list that appears to draft someone twice.
    used: set[str] = set()
    for rnd in range(1, rounds + 1):
        pick = pick_number(slot, rnd, teams)
        picks = sim["round_choices"].get(rnd, [])
        if not picks:
            continue
        counts = pd.Series(picks).value_counts()
        counts = counts[~counts.index.isin(used)]
        top = counts.head(4)
        if not top.empty:
            used.add(top.index[0])
        for order, (pid, count) in enumerate(top.items(), start=1):
            if pid not in by_pid.index:
                continue
            p = by_pid.loc[pid]
            rows.append(
                {
                    "Slot": slot,
                    "Round": rnd,
                    "Pick": pick,
                    "Choice": "PRIMARY" if order == 1 else f"fallback {order - 1}",
                    "Frequency": round(count / len(picks), 3),
                    "Player": p["player"],
                    "Team": p["team"],
                    "Pos": p["pos"],
                    "Tier": int(p["tier"]),
                    "Bye": int(p["bye_week"]) if pd.notna(p.get("bye_week")) else None,
                    "ADP": round(float(p["adp_filled"]), 1),
                    "P(available)": round(
                        float(avail[rnd, pool_index[pid]]) if pid in pool_index else float("nan"), 3
                    ),
                    "ProjPts": round(float(p["proj_points"]), 1),
                    "VORP": round(float(p["blended_VORP"]), 1),
                    "Ceiling": round(float(p["sim_p90"]), 1),
                    "Floor": round(float(p["sim_p10"]), 1),
                    "P(elite)": round(float(p["p_positional_elite"]), 3),
                    "P(bust)": round(float(p["p_bust"]), 3),
                    "Injury": p["injury_status"] if isinstance(p["injury_status"], str) else "",
                }
            )

    plan = pd.DataFrame(rows)
    shapes = pd.DataFrame(sim["roster_shapes"]).fillna(0)
    if not shapes.empty:
        shape = ", ".join(
            f"{p}{int(round(shapes[p].mean()))}" for p in POSITIONS if p in shapes
        )
        logger.info(f"Slot {slot:2d}: typical roster {shape} "
                    f"| mean team VORP {sim['team_value_mean']:.0f}")

    if not plan.empty and "Bye" in plan.columns:
        primary = plan[(plan["Choice"] == "PRIMARY") & plan["Bye"].notna()]
        for (pos, bye), grp in primary.groupby(["Pos", "Bye"]):
            if len(grp) >= 2:
                logger.info(
                    f"Slot {slot:2d}: bye-week clash -- {len(grp)}x {pos} out "
                    f"week {int(bye)} ({', '.join(grp['Player'])})"
                )
    return plan


def build_all_slot_plans(board: pd.DataFrame, curve_df: pd.DataFrame,
                         n_sims: int = 250, teams: int = LEAGUE_TEAMS,
                         rounds: int = DRAFT_ROUNDS) -> pd.DataFrame:
    parts = []
    for slot in range(1, teams + 1):
        parts.append(
            build_plan_for_slot(board, curve_df, slot, n_sims=n_sims,
                                teams=teams, rounds=rounds)
        )
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def positional_run_table(curve_df: pd.DataFrame, teams: int = LEAGUE_TEAMS,
                         rounds: int = DRAFT_ROUNDS) -> pd.DataFrame:
    """Expected number of each position gone by the end of every round.

    Reading this alongside your own pick numbers tells you when a position is
    about to break -- the moment to take the last player in a tier rather than
    the first player in the next one.
    """
    curve = curve_df.attrs.get("curve")
    if curve is None:
        return pd.DataFrame()
    rows = []
    for rnd in range(1, rounds + 1):
        pick = min(rnd * teams, curve.shape[1] - 1)
        gone = 1.0 - curve[:, pick]
        row = {"Round": rnd, "ThroughPick": pick}
        for pos in POSITIONS:
            mask = (curve_df["pos"] == pos).to_numpy()
            row[pos] = round(float(gone[mask].sum()), 1)
        rows.append(row)
    return pd.DataFrame(rows)
