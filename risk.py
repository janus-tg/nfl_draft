"""Availability and volatility modelling.

Last year's board treated the spread of Sleeper's *projections* as risk. It
isn't: projections are smoothed forecasts, so a boom/bust WR and a metronome TE
came out looking nearly identical, and summing 18 weekly projections quietly
assumed every player suits up 18 times -- systematically overrating exactly the
fragile players the season turned on.

This module replaces that with two things measured from actual results:

  availability -- P(a player is active for a given game), from his own
                  games-played history, his current injury designation, the
                  specific body part, and an age curve.
  volatility   -- the real week-to-week spread of his scoring, shrunk toward
                  the positional mean so small samples don't masquerade as
                  signal.
"""

from __future__ import annotations

import time

import numpy as np

from config import (
    AGE_AVAILABILITY_PENALTY,
    AGE_CLIFF,
    AGE_DECAY_PER_YEAR,
    DEPTH_CHART_CV_BUMP,
    DEPTH_CHART_CV_BUMP_DEFAULT,
    DURABILITY_PRIOR_GAMES,
    GAMES_PER_TEAM,
    INJURY_SEVERITY,
    INJURY_STATUS_EFFECT,
    MIN_GAMES_FOR_DURABILITY_SEASON,
    OL_RATING,
    POS_BASE_AVAILABILITY,
    QB_OL_ADJUSTMENT_CLIP,
    QB_OL_ADJUSTMENT_STRENGTH,
    RB_MOVER_OL_ADJUSTMENT_STRENGTH,
    RECENT_TEAM_CHANGE_DAYS,
    SUSPENSION_GAMES_OVERRIDE,
    VOLATILITY_PRIOR_GAMES,
)
from logger import logger
from scoring import score_row


# --------------------------------------------------------------- history
def build_history(actuals_by_season: dict[int, dict[int, dict]],
                  players: dict) -> dict[str, dict]:
    """Per-player game logs of real fantasy points, keyed by player_id.

    Returns {pid: {"points": [...], "games_played": n, "seasons": {yr: n},
                   "snap_share": float|None}}
    """
    hist: dict[str, dict] = {}
    for season, weeks in actuals_by_season.items():
        for _week, payload in weeks.items():
            for pid, row in (payload or {}).items():
                if not isinstance(row, dict):
                    continue
                # `gp` marks that the player actually suited up. Rows exist for
                # inactive players too, so this is the gate that matters.
                if not row.get("gp"):
                    continue
                pos = (players.get(pid) or {}).get("position")
                if pos not in POS_BASE_AVAILABILITY:
                    continue
                rec = hist.setdefault(
                    pid, {"points": [], "seasons": {}, "snaps": [], "team_snaps": []}
                )
                rec["points"].append(score_row(row, pos))
                rec["seasons"][season] = rec["seasons"].get(season, 0) + 1
                if row.get("off_snp") and row.get("tm_off_snp"):
                    rec["snaps"].append(float(row["off_snp"]))
                    rec["team_snaps"].append(float(row["tm_off_snp"]))

    for _pid, rec in hist.items():
        rec["games_played"] = len(rec["points"])
        team_snaps = sum(rec["team_snaps"])
        rec["snap_share"] = (sum(rec["snaps"]) / team_snaps) if team_snaps else None
    logger.info(f"Built game logs for {len(hist)} players from actual results.")
    return hist


# --------------------------------------------------------------- durability
def durability_rate(pid: str, pos: str, hist: dict) -> tuple[float, int]:
    """Measured availability rate, shrunk toward the positional base rate.

    Only seasons where the player was a genuine contributor count. Without that
    filter a healthy third-string RB looks as fragile as a starter who tore an
    ACL, because both simply fail to appear in most weeks.
    """
    base = POS_BASE_AVAILABILITY.get(pos, 0.88)
    rec = hist.get(pid)
    if not rec:
        return base, 0

    played = possible = 0
    for _season, games in rec["seasons"].items():
        if games < MIN_GAMES_FOR_DURABILITY_SEASON:
            continue
        played += games
        possible += GAMES_PER_TEAM
    if possible == 0:
        return base, 0

    prior = DURABILITY_PRIOR_GAMES
    rate = (played + base * prior) / (possible + prior)
    return float(np.clip(rate, 0.35, 0.99)), possible


# --------------------------------------------------------------- injuries
def _severity_hit(info: dict) -> tuple[float, float, str]:
    """Extra games missed, rust multiplier, and a label, from the injury text."""
    text = " ".join(
        str(info.get(k) or "") for k in ("injury_body_part", "injury_notes")
    ).lower()
    if not text.strip():
        return 0.0, 1.0, ""
    extra, rust, labels = 0.0, 1.0, []
    for keyword, effect in INJURY_SEVERITY.items():
        if keyword in text:
            labels.append(keyword)
            # Take the single worst matching condition rather than stacking
            # "Knee - ACL" into both a knee hit and an ACL hit.
            if effect["extra_missed"] > extra:
                extra, rust = effect["extra_missed"], effect["rust"]
    return extra, rust, ", ".join(sorted(set(labels)))


def injury_adjustment(pid: str, pos: str, players: dict) -> dict:
    """Games expected to be missed and the post-return efficiency multiplier."""
    info = players.get(pid) or {}
    status = info.get("injury_status")
    roster_status = info.get("status")

    missed, rust = 0.0, 1.0
    if status == "Sus" and pid in SUSPENSION_GAMES_OVERRIDE:
        # A real suspension is public and known-length; trust that over the
        # generic "Sus" placeholder below (replaces it, not adds to it).
        missed += SUSPENSION_GAMES_OVERRIDE[pid]
        rust *= INJURY_STATUS_EFFECT["Sus"]["rust"]
    elif status and status in INJURY_STATUS_EFFECT:
        missed += INJURY_STATUS_EFFECT[status]["games_missed"]
        rust *= INJURY_STATUS_EFFECT[status]["rust"]
    elif roster_status in ("Inactive", "Injured Reserve"):
        missed += INJURY_STATUS_EFFECT["IR"]["games_missed"]
        rust *= INJURY_STATUS_EFFECT["IR"]["rust"]

    extra, sev_rust, label = _severity_hit(info)
    # A body-part note only means something alongside an actual designation;
    # stale notes hang around on healthy players all offseason.
    if status or roster_status in ("Inactive", "Injured Reserve"):
        missed += extra
        rust *= sev_rust
    else:
        label = ""

    return {
        "injury_status": status or "",
        "injury_detail": (info.get("injury_body_part") or ""),
        "injury_label": label,
        "injury_games_missed": round(missed, 2),
        "rust_multiplier": round(rust, 3),
    }


# --------------------------------------------------------------- age
def age_multiplier(pid: str, pos: str, players: dict) -> float:
    info = players.get(pid) or {}
    age = info.get("age")
    if not age:
        return 1.0
    cliff = AGE_CLIFF.get(pos, 99)
    if age <= cliff:
        return 1.0
    decay = AGE_DECAY_PER_YEAR.get(pos, 0.04)
    return float(max(0.55, 1.0 - decay * (age - cliff)))


# --------------------------------------------------------------- offensive line
_OL_RATINGS_ARR = np.array(list(OL_RATING.values()), dtype=float)
_OL_MEAN = float(_OL_RATINGS_ARR.mean()) if _OL_RATINGS_ARR.size else 0.0
_OL_SD = float(_OL_RATINGS_ARR.std(ddof=0)) if _OL_RATINGS_ARR.size else 0.0


def _recently_changed_team(info: dict) -> bool:
    """True if Sleeper shows a team change within the current offseason window."""
    ts = info.get("team_changed_at")
    if not ts:
        return False
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return False
    age_days = (time.time() * 1000 - ts) / 86_400_000
    return 0 <= age_days <= RECENT_TEAM_CHANGE_DAYS


def offensive_line_multiplier(pos: str, team: str | None,
                              info: dict | None = None) -> tuple[float, float | None]:
    """Production multiplier from the team's offensive line quality.

    The weekly projection has no visibility into pass protection: a QB behind
    an elite line gets a clean pocket and more time to throw, one behind a bad
    line takes more sacks and rushed throws no matter how talented he is. Every
    QB gets this.

    RBs are left alone by default -- offensive line effects on the run game are
    already embedded in each RB's own historical rate -- UNLESS he just changed
    teams (trade/free agency this offseason), in which case that history
    belongs to his OLD line and the same adjustment QBs get applies in full.

    Returns (multiplier, ol_rating) so the rating itself can be surfaced on the
    board alongside the adjustment it produced.
    """
    if _OL_SD <= 1e-9:
        return 1.0, None
    if pos == "QB":
        strength = QB_OL_ADJUSTMENT_STRENGTH
    elif pos == "RB" and info is not None and _recently_changed_team(info):
        strength = RB_MOVER_OL_ADJUSTMENT_STRENGTH
    else:
        return 1.0, None
    rating = OL_RATING.get(team) if team else None
    if rating is None:
        return 1.0, None
    z = (rating - _OL_MEAN) / _OL_SD
    mult = 1.0 + strength * z
    lo, hi = QB_OL_ADJUSTMENT_CLIP
    return float(np.clip(mult, lo, hi)), float(rating)


# --------------------------------------------------------------- assembly
def player_risk_profile(pid: str, pos: str, players: dict, hist: dict) -> dict:
    """Expected games, per-game availability, and the production multiplier."""
    info = players.get(pid) or {}
    dur_rate, sample_games = durability_rate(pid, pos, hist)
    inj = injury_adjustment(pid, pos, players)
    age_mult = age_multiplier(pid, pos, players)
    team = info.get("team")
    ol_mult, ol_rating = offensive_line_multiplier(pos, team, info)

    # Healthy-season expectation, then subtract the games this specific injury
    # is expected to cost.
    #
    # Age is charged against AVAILABILITY ONLY. The projections already price
    # decline into a player's per-game rate -- a 32-year-old back is projected
    # as a 32-year-old back -- so taking another bite out of production would
    # count the same decline twice. What projections capture far less well is
    # that older players break down more often, which is a games-played effect.
    healthy_games = dur_rate * GAMES_PER_TEAM
    healthy_games *= (1.0 - AGE_AVAILABILITY_PENALTY * (1.0 - age_mult))
    exp_games = float(
        np.clip(healthy_games - inj["injury_games_missed"], 0.0, GAMES_PER_TEAM)
    )

    return {
        "durability_rate": round(dur_rate, 3),
        "durability_sample_games": sample_games,
        "age": (players.get(pid) or {}).get("age"),
        "age_multiplier": round(age_mult, 3),
        "expected_games": round(exp_games, 2),
        "availability": round(exp_games / GAMES_PER_TEAM, 3),
        # Injury rust and the QB offensive-line adjustment both scale per-game
        # output; age deliberately does not (see above).
        "production_multiplier": round(inj["rust_multiplier"] * ol_mult, 3),
        "ol_rating": ol_rating,
        "ol_multiplier": round(ol_mult, 3),
        **inj,
    }


# --------------------------------------------------------------- volatility
def positional_cv(hist: dict, players: dict) -> dict[str, float]:
    """Median CV per position -- the prior each player is shrunk toward."""
    buckets: dict[str, list[float]] = {}
    for pid, rec in hist.items():
        if rec["games_played"] < 8:
            continue
        pos = (players.get(pid) or {}).get("position")
        if pos not in POS_BASE_AVAILABILITY:
            continue
        pts = np.asarray(rec["points"], dtype=float)
        if pts.mean() <= 3.0:
            continue
        buckets.setdefault(pos, []).append(float(pts.std(ddof=1) / pts.mean()))
    out = {pos: float(np.median(vals)) for pos, vals in buckets.items() if vals}
    logger.info("Measured per-game CV by position: " +
                ", ".join(f"{p}={v:.2f}" for p, v in sorted(out.items())))
    return out


def volatility_profile(pid: str, pos: str, hist: dict, pos_cv: dict[str, float],
                       players: dict | None = None) -> dict:
    """Coefficient of variation of real per-game scoring, shrunk to position.

    CV rather than raw stdev, so the estimate transfers when a player's role or
    projection changes between seasons.
    """
    rec = hist.get(pid)
    prior_cv = pos_cv.get(pos, 0.55)
    if not rec or rec["games_played"] < 3:
        # No real track record to measure -- the positional prior is all there
        # is. Skew it by depth-chart slot: a backup's fantasy output is a bet
        # on someone else's opportunity, not a role, which is inherently more
        # boom/bust than a penciled-in starter even before either has played.
        if players is not None:
            order = (players.get(pid) or {}).get("depth_chart_order")
            try:
                order = int(order)
            except (TypeError, ValueError):
                order = None
            bump = (DEPTH_CHART_CV_BUMP.get(order, DEPTH_CHART_CV_BUMP_DEFAULT)
                   if order else DEPTH_CHART_CV_BUMP_DEFAULT)
            prior_cv = float(np.clip(prior_cv * bump, 0.15, 1.6))
        sample_games = rec["games_played"] if rec else 0
        return {"cv": round(prior_cv, 3), "cv_sample_games": sample_games}

    pts = np.asarray(rec["points"], dtype=float)
    mean = float(pts.mean())
    if mean <= 1.0:
        return {"cv": round(prior_cv, 3), "cv_sample_games": len(pts)}

    raw_cv = float(pts.std(ddof=1) / mean) if len(pts) > 1 else prior_cv
    n = len(pts)
    weight = n / (n + VOLATILITY_PRIOR_GAMES)
    cv = weight * raw_cv + (1 - weight) * prior_cv
    return {"cv": round(float(np.clip(cv, 0.15, 1.6)), 3), "cv_sample_games": n}
