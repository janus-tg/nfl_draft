"""Validate the model against public analyst consensus, and against reality.

Two different questions, and they are not the same question:

  agreement -- how far does this board sit from the FantasyPros expert
               consensus (ECR), and where does it disagree most? Agreement is a
               sanity check, not a score. A model that matches consensus
               everywhere has no edge; one that disagrees everywhere is broken.

  accuracy  -- backtest. Rebuild the board as it would have looked before the
               2025 season using only information available then, and score it
               against what actually happened. This is the only test that says
               whether the risk adjustment helps or hurts.

Run: py validate.py
"""

from __future__ import annotations

import json
import re
import unicodedata

import numpy as np
import pandas as pd
import requests

import fetch
from config import HISTORY_SEASONS, POSITIONS, REGULAR_SEASON_WEEKS, SEASON
from logger import logger
from scoring import score_row

FP_URLS = {
    "PPR": "https://www.fantasypros.com/nfl/rankings/ppr-cheatsheets.php",
    "consensus": "https://www.fantasypros.com/nfl/rankings/consensus-cheatsheets.php",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(name: str) -> str:
    """Normalise a player name so two sources can be joined on it.

    Strips accents, punctuation, and generational suffixes -- the three things
    that otherwise make 'Marvin Harrison Jr.' and 'Marvin Harrison' look like
    different players.
    """
    if not isinstance(name, str):
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z ]", "", text).lower().strip()
    parts = [p for p in text.split() if p not in SUFFIXES]
    return "".join(parts)


# ----------------------------------------------------- analyst consensus
def fetch_expert_consensus(scoring: str = "PPR") -> pd.DataFrame:
    """FantasyPros Expert Consensus Rankings, from the page's embedded JSON.

    The visible table is rendered client-side, so the table markup is empty on
    fetch; the data lives in a `var ecrData = {...}` blob in the page source.
    """
    url = FP_URLS[scoring]
    logger.info(f"Fetching FantasyPros {scoring} expert consensus ...")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    match = re.search(r"var\s+ecrData\s*=\s*(\{.*?\});", resp.text, re.S)
    if not match:
        raise RuntimeError("FantasyPros page layout changed: ecrData not found")
    data = json.loads(match.group(1))

    rows = []
    for p in data.get("players", []):
        pos = re.sub(r"\d+", "", str(p.get("player_position_id") or "")).upper()
        if pos == "DST":
            pos = "DEF"
        rows.append(
            {
                "fp_rank": p.get("rank_ecr"),
                "player": p.get("player_name"),
                "key": norm_name(p.get("player_name")),
                "team": p.get("player_team_id"),
                "pos": pos,
                "fp_best": p.get("rank_min"),
                "fp_worst": p.get("rank_max"),
                "fp_stdev": p.get("rank_std"),
                "fp_tier": p.get("tier"),
            }
        )
    df = pd.DataFrame(rows).dropna(subset=["fp_rank"])
    for col in ("fp_rank", "fp_best", "fp_worst", "fp_stdev"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info(f"Expert consensus: {len(df)} players (source: {url})")
    return df


def compare_to_consensus(board: pd.DataFrame, ecr: pd.DataFrame,
                         top_n: int = 150) -> dict:
    """Join the board to ECR and measure agreement plus biggest disagreements."""
    b = board.copy()
    b["key"] = b["player"].map(norm_name)
    # Team defences are named differently everywhere; drop them from the join
    # rather than pretend to match them.
    b = b[b["pos"] != "DEF"]
    e = ecr[ecr["pos"] != "DEF"].copy()

    merged = b.merge(e[["key", "fp_rank", "fp_best", "fp_worst", "fp_stdev", "pos"]],
                     on="key", how="inner", suffixes=("", "_fp"))
    merged = merged[merged["pos"] == merged["pos_fp"]]

    # Rank within the joined set so both scales mean the same thing.
    merged["model_rank_j"] = merged["champ_score"].rank(ascending=False, method="first")
    merged["fp_rank_j"] = merged["fp_rank"].rank(method="first")
    merged["adp_rank_j"] = merged["adp_filled"].rank(method="first")
    merged["delta"] = merged["fp_rank_j"] - merged["model_rank_j"]

    head = merged.nsmallest(top_n, "fp_rank_j")
    # These columns are already ranks, so Pearson on them IS Spearman's rho --
    # no need to pull in scipy just to re-rank data that is already ranked.
    out = {
        "n_matched": len(merged),
        "spearman_all": float(merged["model_rank_j"].corr(merged["fp_rank_j"])),
        "spearman_top": float(head["model_rank_j"].corr(head["fp_rank_j"])),
        "adp_vs_ecr_spearman": float(merged["adp_rank_j"].corr(merged["fp_rank_j"])),
        "mean_abs_delta_top": float(head["delta"].abs().mean()),
        "median_abs_delta_top": float(head["delta"].abs().median()),
        "table": merged,
        "head": head,
    }
    return out


# ----------------------------------------------------- backtest
def backtest_prior_season(target_season: int = 2025) -> pd.DataFrame:
    """Score preseason approaches against what actually happened.

    Compares, for the same player pool:
      naive  -- sum of preseason weekly projections, the old method, which
                implicitly assumes a full 17-game season for everybody
      risk   -- the same projections converted to a per-game rate and
                multiplied by the model's expected games

    against actual realised fantasy points under this league's scoring.
    """
    logger.info(f"Backtesting {target_season} using only pre-{target_season} information ...")
    players = fetch.get_players()

    proj = fetch.get_season_projections(target_season, REGULAR_SEASON_WEEKS)
    actual = fetch.get_season_actuals(target_season, REGULAR_SEASON_WEEKS)
    prior = {s: fetch.get_season_actuals(s, REGULAR_SEASON_WEEKS)
             for s in range(target_season - 2, target_season)}

    # Preseason expectation: per-game rate from week-1 projections only, so no
    # in-season information can leak backwards into the "forecast".
    week1 = proj.get(1, {})
    rate = {}
    for pid, row in week1.items():
        if not isinstance(row, dict):
            continue
        pos = (players.get(pid) or {}).get("position")
        if pos not in POSITIONS:
            continue
        gp = float(row.get("gp") or 0)
        if gp <= 0:
            continue
        rate[pid] = (score_row(row, pos) / gp, pos)

    # Durability from the two seasons BEFORE the target season only.
    from risk import build_history, durability_rate
    hist = build_history(prior, players)

    # What actually happened.
    realised: dict[str, float] = {}
    games: dict[str, int] = {}
    for _week, payload in actual.items():
        for pid, row in (payload or {}).items():
            if not isinstance(row, dict) or not row.get("gp"):
                continue
            pos = (players.get(pid) or {}).get("position")
            if pos not in POSITIONS:
                continue
            realised[pid] = realised.get(pid, 0.0) + score_row(row, pos)
            games[pid] = games.get(pid, 0) + 1

    rows = []
    for pid, (ppg, pos) in rate.items():
        if pid not in realised:
            continue
        dur, sample = durability_rate(pid, pos, hist)
        rows.append(
            {
                "player_id": pid,
                "player": (players.get(pid) or {}).get("full_name") or pid,
                "pos": pos,
                "naive_pred": ppg * 17.0,
                "risk_pred": ppg * dur * 17.0,
                "durability": dur,
                "durability_sample": sample,
                "actual": realised[pid],
                "actual_games": games.get(pid, 0),
            }
        )
    df = pd.DataFrame(rows)
    # Restrict to players with a real preseason expectation; the tail is noise.
    df = df[df["naive_pred"] > 60].reset_index(drop=True)
    logger.info(f"Backtest pool: {len(df)} players with {target_season} projections and results.")
    return df


def score_backtest(df: pd.DataFrame) -> pd.DataFrame:
    """Error metrics per method, overall and by position."""
    def metrics(sub: pd.DataFrame, label: str, pos: str) -> dict:
        out = {"pos": pos, "n": len(sub)}
        for method in ("naive_pred", "risk_pred"):
            err = sub[method] - sub["actual"]
            out[f"{label}{method[:-5]}_MAE"] = float(err.abs().mean())
            out[f"{label}{method[:-5]}_RMSE"] = float(np.sqrt((err ** 2).mean()))
            out[f"{label}{method[:-5]}_bias"] = float(err.mean())
        return out

    rows = [metrics(df, "", "ALL")]
    for pos in ["QB", "RB", "WR", "TE"]:
        sub = df[df["pos"] == pos]
        if len(sub) >= 10:
            rows.append(metrics(sub, "", pos))
    return pd.DataFrame(rows)


def main() -> None:
    board = pd.read_excel(f"output/draft_board_{SEASON}.xlsx", sheet_name="Overall")
    board = board.rename(columns={"Player": "player", "Pos": "pos", "ADP": "adp_filled",
                                  "Rank": "champ_rank"})
    board["champ_score"] = -board["champ_rank"]

    ecr = fetch_expert_consensus("PPR")
    cmp_ = compare_to_consensus(board, ecr)

    print("\n" + "=" * 74)
    print("AGREEMENT WITH FANTASYPROS EXPERT CONSENSUS (PPR)")
    print("=" * 74)
    print(f"players matched            : {cmp_['n_matched']}")
    print(f"Spearman, all matched      : {cmp_['spearman_all']:.3f}")
    print(f"Spearman, top 150 by ECR   : {cmp_['spearman_top']:.3f}")
    print(f"ADP vs ECR (reference)     : {cmp_['adp_vs_ecr_spearman']:.3f}")
    print(f"median |rank gap|, top 150 : {cmp_['median_abs_delta_top']:.1f}")

    head = cmp_["head"]
    cols = ["player", "pos", "fp_rank_j", "model_rank_j", "delta", "adp_filled",
            "ExpGames", "Injury", "P(bust)"]
    cols = [c for c in cols if c in head.columns]
    print("\n-- Model MUCH higher than the experts (model likes, experts don't) --")
    print(head.nlargest(12, "delta")[cols].to_string(index=False))
    print("\n-- Experts MUCH higher than the model (experts like, model doesn't) --")
    print(head.nsmallest(12, "delta")[cols].to_string(index=False))

    bt = backtest_prior_season(2025)
    scores = score_backtest(bt)
    print("\n" + "=" * 74)
    print("BACKTEST: 2025 preseason forecast vs 2025 actual results")
    print("=" * 74)
    print(scores.round(1).to_string(index=False))

    naive_mae = scores.loc[scores["pos"] == "ALL", "naive_MAE"].iloc[0]
    risk_mae = scores.loc[scores["pos"] == "ALL", "risk_MAE"].iloc[0]
    print(f"\nMAE improvement from the availability adjustment: "
          f"{100 * (naive_mae - risk_mae) / naive_mae:+.1f}%")

    with pd.ExcelWriter("output/validation.xlsx", engine="openpyxl") as xl:
        cmp_["head"][cols + ["fp_stdev"]].to_excel(xl, sheet_name="vs_Experts", index=False)
        scores.to_excel(xl, sheet_name="Backtest_Scores", index=False)
        bt.sort_values("naive_pred", ascending=False).to_excel(
            xl, sheet_name="Backtest_Detail", index=False)
    logger.info("Wrote output/validation.xlsx")


if __name__ == "__main__":
    main()
