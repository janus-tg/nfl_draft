"""Build the 2026 draft board.

Run: py main.py

Produces output/draft_board_2026.xlsx with:
  Cheatsheet      -- the one page to have open on draft day
  Overall         -- every player, risk-adjusted, championship-ranked
  QB/RB/WR/TE/K/DEF -- per-position tiers
  Targets         -- model likes them more than the room does
  Fades           -- the room likes them more than the model does
  InjuryRisk      -- what the injury adjustment actually cost each player
  DraftPlan       -- round-by-round plan for all 12 slots
  PositionRuns    -- when each position comes off the board
  NaiveVsAdjusted -- what last year's method would have told you
"""

from __future__ import annotations

import os

import pandas as pd

import fetch
from config import (
    HISTORY_SEASONS,
    LEAGUE_TEAMS,
    OUTPUT_DIR,
    POSITIONS,
    REGULAR_SEASON_WEEKS,
    SEASON,
)
from draft import availability_curves, build_all_slot_plans, positional_run_table
from logger import logger
from valuation import build_valuation

OUTPUT_PATH = os.path.join(OUTPUT_DIR, f"draft_board_{SEASON}.xlsx")

BOARD_COLS = [
    "player_id", "champ_rank", "player", "team", "pos", "pos_rank", "tier",
    "adp_filled", "market_rank", "rank_edge",
    "proj_points", "blended_VORP", "VORP", "market_VORP",
    "sim_p10", "sim_p50", "sim_p90",
    "p_positional_elite", "p_positional_starter", "p_bust",
    "expected_games", "availability", "p_season_ending_injury",
    "injury_status", "injury_detail", "injury_games_missed",
    "durability_rate", "age", "cv", "dud_week_rate", "playoff_ppg",
    "naive_points", "risk_cost", "snap_share", "hist_ppg", "hist_games",
]

RENAME = {
    "player_id": "Id", "champ_rank": "Rank", "player": "Player", "team": "Tm", "pos": "Pos",
    "pos_rank": "PosRank", "tier": "Tier", "adp_filled": "ADP",
    "market_rank": "MktRank", "rank_edge": "Edge",
    "proj_points": "ProjPts", "blended_VORP": "VORP",
    "VORP": "ModelVORP", "market_VORP": "MktVORP",
    "sim_p10": "Floor", "sim_p50": "Median", "sim_p90": "Ceiling",
    "p_positional_elite": "P(elite)", "p_positional_starter": "P(starter)",
    "p_bust": "P(bust)", "expected_games": "ExpGames",
    "availability": "Avail", "p_season_ending_injury": "P(seasonEnd)",
    "injury_status": "Injury", "injury_detail": "InjuryDetail",
    "injury_games_missed": "InjGamesLost", "durability_rate": "Durability",
    "age": "Age", "cv": "CV", "dud_week_rate": "DudWk%",
    "playoff_ppg": "PlayoffPPG", "naive_points": "NaivePts",
    "risk_cost": "RiskCost", "snap_share": "SnapShare",
    "hist_ppg": "HistPPG", "hist_games": "HistGm",
}


def _present(df: pd.DataFrame, cols: list[str]) -> list[str]:
    return [c for c in cols if c in df.columns]


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    out = df[_present(df, BOARD_COLS)].rename(columns=RENAME)
    return out.round(3)


def build_targets(board: pd.DataFrame, n: int = 40) -> pd.DataFrame:
    """Players the model rates well above their draft cost.

    `Edge` is market rank minus model rank, so a positive number means the room
    is letting him fall. Filtered to players with a real role, because most
    extreme edges are otherwise just noise on deep-bench players.
    """
    # Requiring positive VORP is what separates a real target from noise. Edge
    # on a replacement-level player just measures how arbitrary the back of the
    # ADP list is; it is not a market inefficiency you can draft.
    pool = board[
        (board["adp_filled"] < LEAGUE_TEAMS * 14)
        & (board["blended_VORP"] > 0)
        & (board["p_positional_starter"] > 0.25)
    ]
    return pool.sort_values("rank_edge", ascending=False).head(n)


def build_fades(board: pd.DataFrame, n: int = 40) -> pd.DataFrame:
    """Players going earlier than the risk-adjusted model can justify.

    These are the picks that cost people leagues: the name is worth more than
    the projection once availability and bust risk are priced in.
    """
    pool = board[board["adp_filled"] <= LEAGUE_TEAMS * 10]
    return pool.sort_values("rank_edge").head(n)


def build_injury_sheet(board: pd.DataFrame, n: int = 60) -> pd.DataFrame:
    """Where the injury adjustment bit hardest -- last year's blind spot."""
    pool = board[board["adp_filled"] <= LEAGUE_TEAMS * 15]
    return pool.sort_values("risk_cost", ascending=False).head(n)


def build_cheatsheet(board: pd.DataFrame, n: int = 200) -> pd.DataFrame:
    """The single page to keep open while drafting."""
    cols = [
        "champ_rank", "player", "team", "pos", "pos_rank", "tier", "adp_filled",
        "rank_edge", "proj_points", "blended_VORP", "sim_p10", "sim_p90",
        "p_positional_elite", "p_bust", "expected_games", "injury_status",
    ]
    out = board.sort_values("champ_rank").head(n)[_present(board, cols)]
    return out.rename(columns=RENAME).round(2)


def build_naive_comparison(board: pd.DataFrame, n: int = 50) -> pd.DataFrame:
    """Side-by-side of last year's method and this one.

    The old board summed 18 weeks of projections with no availability term, so
    it ranked players as though every one of them plays a full season. This
    sheet is the list of players that assumption would have mispriced.
    """
    df = board.copy()
    df["naive_rank"] = df["VORP_naive"].rank(ascending=False, method="first").astype(int)
    df["rank_shift"] = df["naive_rank"] - df["champ_rank"]
    cols = [
        "player", "team", "pos", "adp_filled", "naive_rank", "champ_rank",
        "rank_shift", "naive_points", "proj_points", "risk_cost",
        "expected_games", "injury_status", "injury_detail",
    ]
    out = df[df["naive_rank"] <= 120].sort_values("rank_shift")
    return out[_present(out, cols)].head(n).round(2)


def write_workbook(board: pd.DataFrame, plans: pd.DataFrame,
                   runs: pd.DataFrame, path: str = OUTPUT_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        build_cheatsheet(board).to_excel(xl, sheet_name="Cheatsheet", index=False)
        _fmt(board.sort_values("champ_rank")).to_excel(
            xl, sheet_name="Overall", index=False
        )
        for pos in POSITIONS:
            sub = board[board["pos"] == pos].sort_values("champ_rank")
            if sub.empty:
                continue
            _fmt(sub).to_excel(xl, sheet_name=pos, index=False)

        _fmt(build_targets(board)).to_excel(xl, sheet_name="Targets", index=False)
        _fmt(build_fades(board)).to_excel(xl, sheet_name="Fades", index=False)
        _fmt(build_injury_sheet(board)).to_excel(
            xl, sheet_name="InjuryRisk", index=False
        )
        build_naive_comparison(board).to_excel(
            xl, sheet_name="NaiveVsAdjusted", index=False
        )
        if not plans.empty:
            plans.to_excel(xl, sheet_name="DraftPlan", index=False)
        if not runs.empty:
            runs.to_excel(xl, sheet_name="PositionRuns", index=False)
    logger.info(f"Draft board written to {path}")


def main() -> None:
    logger.info(f"Building {SEASON} draft board for a {LEAGUE_TEAMS}-team league.")

    players = fetch.get_players()
    projections = fetch.get_season_projections(SEASON, REGULAR_SEASON_WEEKS)
    actuals = {
        season: fetch.get_season_actuals(season, REGULAR_SEASON_WEEKS)
        for season in HISTORY_SEASONS
    }

    board = build_valuation(projections, actuals, players)

    logger.info("Simulating draft-day availability ...")
    curves = availability_curves(board)
    runs = positional_run_table(curves)

    logger.info(f"Building draft plans for all {LEAGUE_TEAMS} slots ...")
    plans = build_all_slot_plans(board, curves)

    write_workbook(board, plans, runs)

    top = board.sort_values("champ_rank").head(15)
    logger.info(
        "Top 15 overall:\n"
        + top[["champ_rank", "player", "team", "pos", "tier", "adp_filled",
               "proj_points", "blended_VORP", "p_positional_elite", "p_bust"]]
        .round(2).to_string(index=False)
    )


if __name__ == "__main__":
    main()
