"""Export the draft board to JSON for the React app.

Run after main.py:  py export_web.py
Writes web/src/data/board.json
"""

from __future__ import annotations

import json
import math
import os

import pandas as pd

from config import (
    ADP_NOISE_SD,
    BENCH_SLOTS,
    DEF_EARLIEST_ROUND,
    DRAFT_ROUNDS,
    FLEX_POSITIONS,
    K_EARLIEST_ROUND,
    LEAGUE_TEAMS,
    OUTPUT_DIR,
    POSITION_LIMITS,
    QB_EARLIEST_ROUND,
    SEASON,
    STARTERS,
    TE_EARLIEST_ROUND,
)
from logger import logger

WORKBOOK = os.path.join(OUTPUT_DIR, f"draft_board_{SEASON}.xlsx")
VALIDATION = os.path.join(OUTPUT_DIR, "validation.xlsx")
WEB_DATA = os.path.join("web", "src", "data", "board.json")


def _clean(value):
    """JSON can't hold NaN/Infinity, and numpy scalars aren't serialisable."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict("records")]


def _sheet(path: str, name: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=name)
    except Exception as exc:
        logger.warning(f"Sheet {name} unavailable in {path}: {exc}")
        return pd.DataFrame()


def build_plans(plan_df: pd.DataFrame) -> dict:
    plans: dict[int, list[dict]] = {}
    if plan_df.empty:
        return plans
    for slot in sorted(plan_df["Slot"].unique()):
        sub = plan_df[plan_df["Slot"] == slot]
        rows = []
        for rnd in sorted(sub["Round"].unique()):
            block = sub[sub["Round"] == rnd]
            primary = block[block["Choice"] == "PRIMARY"]
            if primary.empty:
                continue
            p = primary.iloc[0]
            alts = block[block["Choice"] != "PRIMARY"].head(2)
            rows.append({
                "round": int(rnd),
                "pick": int(p["Pick"]),
                "player": p["Player"],
                "team": p["Team"],
                "pos": p["Pos"],
                "tier": int(p["Tier"]),
                "adp": _clean(p["ADP"]),
                "pAvail": _clean(p["P(available)"]),
                "proj": _clean(p["ProjPts"]),
                "vorp": _clean(p["VORP"]),
                "ceiling": _clean(p["Ceiling"]),
                "floor": _clean(p["Floor"]),
                "pElite": _clean(p["P(elite)"]),
                "pBust": _clean(p["P(bust)"]),
                "injury": p["Injury"] if isinstance(p["Injury"], str) else "",
                "alts": [
                    {"player": a["Player"], "pos": a["Pos"], "adp": _clean(a["ADP"]),
                     "pAvail": _clean(a["P(available)"])}
                    for _, a in alts.iterrows()
                ],
            })
        plans[int(slot)] = rows
    return plans


def main() -> None:
    board = _sheet(WORKBOOK, "Overall")
    payload = {
        "season": SEASON,
        "league": {
            "teams": LEAGUE_TEAMS,
            "rounds": DRAFT_ROUNDS,
            "starters": STARTERS,
            "flexPositions": FLEX_POSITIONS,
            "benchSlots": BENCH_SLOTS,
            "positionLimits": POSITION_LIMITS,
            "earliestRound": {
                "QB": QB_EARLIEST_ROUND, "TE": TE_EARLIEST_ROUND,
                "K": K_EARLIEST_ROUND, "DEF": DEF_EARLIEST_ROUND,
            },
            "adpNoiseSd": ADP_NOISE_SD,
        },
        "board": _records(board),
        "targets": _records(_sheet(WORKBOOK, "Targets")),
        "fades": _records(_sheet(WORKBOOK, "Fades")),
        "injury": _records(_sheet(WORKBOOK, "InjuryRisk")),
        "runs": _records(_sheet(WORKBOOK, "PositionRuns")),
        "naive": _records(_sheet(WORKBOOK, "NaiveVsAdjusted")),
        "plans": build_plans(_sheet(WORKBOOK, "DraftPlan")),
        "validation": {
            "vsExperts": _records(_sheet(VALIDATION, "vs_Experts")),
            "backtest": _records(_sheet(VALIDATION, "Backtest_Scores")),
        },
    }

    os.makedirs(os.path.dirname(WEB_DATA), exist_ok=True)
    with open(WEB_DATA, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    size_kb = os.path.getsize(WEB_DATA) // 1024
    logger.info(f"Wrote {WEB_DATA} ({size_kb} KB, {len(payload['board'])} players)")


if __name__ == "__main__":
    main()
