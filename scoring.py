"""Convert a raw Sleeper stat line into fantasy points under league rules.

Works on both projection rows and actual-result rows -- Sleeper uses the same
key names for each. Keys absent from a row are treated as zero, so a kicker
row and a WR row can go through the same function.
"""

from config import SCORING


def _g(row: dict, *keys: str) -> float:
    """First present, non-null key among `keys`, as a float (else 0.0)."""
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _points_allowed_points(row: dict) -> float:
    """DST points-allowed scoring.

    Sleeper exposes per-bucket fields that behave as probabilities for a single
    week (they sum to ~1). Using them gives the correct expectation; bucketing
    the scalar `pts_allow` average would throw away the distribution and, for a
    convex payout table like this one, bias the result.
    """
    buckets = [
        ("pts_allow_0", "dst_pa_0"),
        ("pts_allow_1_6", "dst_pa_1_6"),
        ("pts_allow_7_13", "dst_pa_7_13"),
        ("pts_allow_14_20", "dst_pa_14_20"),
        ("pts_allow_21_27", "dst_pa_21_27"),
        ("pts_allow_28_34", "dst_pa_28_34"),
        ("pts_allow_35p", "dst_pa_35_plus"),
    ]
    weight = sum(_g(row, field) for field, _ in buckets)
    if weight > 0:
        return sum(_g(row, field) * SCORING[key] for field, key in buckets)

    # Fallback: no bucket fields, so bucket the scalar.
    pa = _g(row, "pts_allow", "points_allowed")
    if pa <= 0:
        return SCORING["dst_pa_0"]
    if pa <= 6:
        return SCORING["dst_pa_1_6"]
    if pa <= 13:
        return SCORING["dst_pa_7_13"]
    if pa <= 20:
        return SCORING["dst_pa_14_20"]
    if pa <= 27:
        return SCORING["dst_pa_21_27"]
    if pa <= 34:
        return SCORING["dst_pa_28_34"]
    return SCORING["dst_pa_35_plus"]


def score_offense(row: dict) -> float:
    s = SCORING
    pts = 0.0
    pts += _g(row, "pass_yd") * s["pass_yds"]
    pts += _g(row, "pass_td") * s["pass_td"]
    pts += _g(row, "pass_int") * s["pass_int"]
    pts += _g(row, "rush_yd") * s["rush_yds"]
    pts += _g(row, "rush_td") * s["rush_td"]
    pts += _g(row, "rec") * s["rec"]
    pts += _g(row, "rec_yd") * s["rec_yds"]
    pts += _g(row, "rec_td") * s["rec_td"]

    # Sleeper files kick returns under def_kr_* and punt returns under pr_*
    # even for offensive players.
    ret_yds = _g(row, "def_kr_yd") + _g(row, "pr_yd") + _g(row, "def_pr_yd")
    ret_tds = _g(row, "def_kr_td") + _g(row, "pr_td") + _g(row, "def_pr_td")
    pts += ret_yds * s["ret_yds"]
    pts += ret_tds * s["ret_td"]

    two_pt = _g(row, "pass_2pt") + _g(row, "rush_2pt") + _g(row, "rec_2pt")
    pts += two_pt * s["two_pt"]

    pts += _g(row, "fum_lost") * s["fum_lost"]
    pts += _g(row, "def_fum_td") * s["off_fum_td"]
    return pts


def score_kicker(row: dict) -> float:
    s = SCORING
    pts = 0.0
    pts += _g(row, "fgm_yds", "fg_yds") * s["fg_yds"]

    # Every distance bucket is -1 in this league, so total misses is enough and
    # is more robust than summing the sparse per-bucket miss fields.
    misses = sum(
        _g(row, f"fgmiss_{b}")
        for b in ("0_19", "20_29", "30_39", "40_49", "50p", "50_plus")
    )
    attempts, made = _g(row, "fga"), _g(row, "fgm")
    if misses == 0 and attempts > 0:
        misses = max(attempts - made, 0.0)
    pts += misses * s["fg_miss"]

    pts += _g(row, "xpm", "pat_made") * s["pat_made"]
    xp_missed = _g(row, "xpmiss", "xpmissed", "pat_miss")
    if xp_missed == 0:
        xp_missed = max(_g(row, "xpa") - _g(row, "xpm"), 0.0)
    pts += xp_missed * s["pat_miss"]
    return pts


def score_dst(row: dict) -> float:
    s = SCORING
    pts = 0.0
    pts += _g(row, "sack") * s["sack"]
    pts += _g(row, "int") * s["dst_int"]
    pts += _g(row, "fum_rec") * s["dst_fum_rec"]
    pts += _g(row, "def_td") * s["dst_td"]
    pts += _g(row, "safe", "safety") * s["dst_safety"]
    pts += _g(row, "blk_kick", "block_kick") * s["dst_block_kick"]
    # st_td already covers kick and punt return scores; adding def_kr_td /
    # def_pr_td on top would double-count them.
    pts += _g(row, "st_td") * s["dst_ret_td"]
    pts += _g(row, "xp_ret", "def_xp_ret") * s["dst_xp_ret"]
    pts += _points_allowed_points(row)
    return pts


def score_row(row: dict, pos: str) -> float:
    """Fantasy points for one stat line, given the player's position."""
    if not isinstance(row, dict):
        return 0.0
    if pos == "K":
        return score_kicker(row)
    if pos == "DEF":
        return score_dst(row)
    return score_offense(row)
