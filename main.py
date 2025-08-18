from fetch import get_player_table
from scoring import compute_fantasy_points
from optimizer import optimize_lineup
import pandas as pd
from logger import logger
from config import (
    POSITIONS,
    LEAGUE_TEAMS,
    TIER_DROP,
    DRAFT_ROUNDS,
    DRAFT_SLOT_R1,
    DRAFT_SLOT_R2,
    DRAFT_SNAKE,
    QB_TE_EARLIEST_ROUND,
    K_DEF_EARLIEST_ROUND,
    PRIORITY_STARTERS,
)
import os


def show_top_players_by_position(df, top_n=30):
    for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
        logger.info(f"Top {top_n} {pos}s:")
        pos_df = df[df["pos"] == pos].sort_values("fantasy_points", ascending=False)
        logger.info(
            "\n"
            + pos_df[["player", "team", "fantasy_points"]]
            .head(top_n)
            .to_string(index=False)
        )


def aggregate_season_stats():
    # Aggregate stats for all 18 weeks
    season_stats = {}
    weekly_points = []  # collect per-week fantasy points for risk/streaming
    for week in range(1, 19):
        logger.info(f"Fetching week {week} data...")
        weekly_df = get_player_table(season=2024, week=week)
        # compute week fantasy points for risk and streaming
        weekly_df = weekly_df.copy()
        weekly_df["fantasy_points"] = compute_fantasy_points(weekly_df)
        weekly_df["week"] = week
        weekly_points.append(
            weekly_df[["player_id", "fantasy_points", "pos", "player", "team", "week"]]
        )
        for _, row in weekly_df.iterrows():
            pid = row["player_id"]
            if pid not in season_stats:
                season_stats[pid] = row.copy()
                # Zero out all stat columns except id/name/team/pos
                for col in weekly_df.columns:
                    if col not in ("player_id", "player", "team", "pos"):
                        season_stats[pid][col] = row[col]
            else:
                for col in weekly_df.columns:
                    if col not in ("player_id", "player", "team", "pos"):
                        season_stats[pid][col] += row[col]
    df = pd.DataFrame(list(season_stats.values()))
    weekly = (
        pd.concat(weekly_points, ignore_index=True)
        if weekly_points
        else pd.DataFrame(
            columns=["player_id", "fantasy_points", "pos", "player", "team", "week"]
        )
    )
    return df, weekly


def log_player_stats(df: pd.DataFrame, query: str | None = None) -> None:
    """Log which stats are available for a player (non-zero fields).

    If no query is provided, the top overall player by fantasy_points is used.
    """
    if "fantasy_points" not in df.columns:
        df = df.assign(fantasy_points=0.0)
    if query:
        m = (df["player"].str.contains(query, case=False, na=False)) | (
            df["player_id"] == query
        )
        candidates = df[m].copy()
        if candidates.empty:
            logger.info(f"No matches found for '{query}'.")
            return
        player_row = candidates.sort_values("fantasy_points", ascending=False).iloc[0]
    else:
        player_row = df.sort_values("fantasy_points", ascending=False).iloc[0]

    stat_cols = [
        c
        for c in df.columns
        if c not in ("player_id", "player", "team", "pos", "fantasy_points")
    ]
    non_zero = {
        c: float(player_row[c]) for c in stat_cols if float(player_row[c]) != 0.0
    }
    logger.info(
        f"Stats available for {player_row['player']} ({player_row['team']} {player_row['pos']}):"
    )
    if non_zero:
        # Sort by absolute contribution magnitude for readability
        items = sorted(non_zero.items(), key=lambda kv: abs(kv[1]), reverse=True)
        preview = "\n" + pd.DataFrame(items, columns=["stat", "value"]).to_string(
            index=False
        )
        logger.info(preview)
    else:
        logger.info("No non-zero stats found for this player in the aggregated data.")

    # Also list all stat columns available in the dataset (schema view)
    logger.info("All stat fields available in dataset: " + ", ".join(sorted(stat_cols)))


def export_top_players_by_position_to_excel(
    df: pd.DataFrame, top_n: int = 100, path: str = "output/top100_by_position.xlsx"
) -> None:
    """Save top N players per position to separate Excel sheets in one file,
    including all available stat columns for each player.
    """
    try:
        out_dir = os.path.dirname(path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # Determine stat columns present in the dataset (exclude identity + fantasy_points)
        base_cols = {"player_id", "player", "team", "pos", "fantasy_points"}
        stat_cols = [c for c in df.columns if c not in base_cols]
        export_cols = ["player", "team", "pos", "fantasy_points"] + stat_cols

        with pd.ExcelWriter(path) as writer:
            for pos in POSITIONS:
                pos_df = df[df["pos"] == pos].sort_values(
                    "fantasy_points", ascending=False
                )
                pos_df.loc[:, export_cols].head(top_n).to_excel(
                    writer, sheet_name=pos, index=False
                )
            # Coverage sheet: non-zero counts per stat by position
            cov_rows = []
            for pos in POSITIONS:
                pos_df = df[df["pos"] == pos]
                counts = {c: int((pos_df[c] != 0).sum()) for c in stat_cols}
                counts.update({"pos": pos, "players": int(len(pos_df))})
                cov_rows.append(counts)
            coverage_df = pd.DataFrame(cov_rows)
            # Reorder columns for readability
            coverage_cols = ["pos", "players"] + stat_cols
            coverage_df = coverage_df.reindex(columns=coverage_cols)
            coverage_df.to_excel(writer, sheet_name="Coverage", index=False)
        logger.info(f"Saved top {top_n} by position to {path}")
    except Exception as e:
        logger.error(f"Failed to write Excel file: {e}")


def build_and_export_draft_board(
    season_df: pd.DataFrame,
    weekly_df: pd.DataFrame,
    output_path: str = "output/draft_board.xlsx",
    teams: int = LEAGUE_TEAMS,
    tier_drop: float = TIER_DROP,
) -> None:
    """Create a Draft Board workbook with Overall, per-position tiers, risk metrics, and K/DEF streaming plan."""
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Compute replacement baselines per position
        pos_baselines = {}
        board_rows = []
        for pos in POSITIONS:
            pos_df = season_df[season_df["pos"] == pos].copy()
            if pos_df.empty:
                continue
            # Determine replacement index based on league teams and starters per pos
            starters_per_team = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}[
                pos
            ]
            replacement_index = teams * starters_per_team
            pos_df = pos_df.sort_values("fantasy_points", ascending=False)
            baseline = pos_df["fantasy_points"].iloc[
                min(replacement_index, len(pos_df) - 1)
            ]
            pos_baselines[pos] = baseline

        # VORP and ranks
        def vorp_for_row(r):
            return float(r["fantasy_points"]) - float(pos_baselines.get(r["pos"], 0))

        season_df = season_df.copy()
        season_df["VORP"] = season_df.apply(vorp_for_row, axis=1)
        # Position rank by VORP, Overall rank by VORP
        season_df["PosRank"] = (
            season_df.groupby("pos")["VORP"]
            .rank(ascending=False, method="first")
            .astype(int)
        )
        season_df["OverallRank"] = (
            season_df["VORP"].rank(ascending=False, method="first").astype(int)
        )

        # Tiers per position based on drop threshold
        def assign_tiers(pos_df: pd.DataFrame) -> pd.DataFrame:
            pos_df = pos_df.sort_values("VORP", ascending=False).reset_index(drop=True)
            tiers = []
            current_tier = 1
            prev_v = None
            for _, row in pos_df.iterrows():
                v = row["VORP"]
                if prev_v is not None and (prev_v - v) >= tier_drop:
                    current_tier += 1
                tiers.append(current_tier)
                prev_v = v
            pos_df["Tier"] = tiers
            return pos_df

        tiered_parts = []
        for pos in POSITIONS:
            part = season_df[season_df["pos"] == pos].copy()
            if part.empty:
                continue
            tiered_parts.append(assign_tiers(part))
        board = (
            pd.concat(tiered_parts, ignore_index=True)
            if tiered_parts
            else season_df.copy()
        )

        # Risk metrics from weekly projections (stdev, floor, ceiling)
        risk = (
            weekly_df.groupby("player_id")["fantasy_points"]
            .agg(
                [
                    ("Floor20", lambda s: float(s.quantile(0.2)) if len(s) else 0.0),
                    ("Ceil80", lambda s: float(s.quantile(0.8)) if len(s) else 0.0),
                    ("Stdev", lambda s: float(s.std(ddof=0)) if len(s) else 0.0),
                    ("Weeks", "count"),
                ]
            )
            .reset_index()
        )
        board = board.merge(risk, on="player_id", how="left")

        # Final board columns
        cols = [
            "OverallRank",
            "player",
            "team",
            "pos",
            "PosRank",
            "Tier",
            "fantasy_points",
            "VORP",
            "Floor20",
            "Ceil80",
            "Stdev",
            "Weeks",
        ]
        # Add stat columns too for visibility
        stat_cols = [
            c
            for c in season_df.columns
            if c
            not in {
                "player_id",
                "player",
                "team",
                "pos",
                "fantasy_points",
                "VORP",
                "PosRank",
                "OverallRank",
                "Tier",
            }
        ]
        board_out_cols = cols + [
            c for c in stat_cols if c not in {"Floor20", "Ceil80", "Stdev", "Weeks"}
        ]

        # Streaming plan for K and DEF: pick top each week
        streaming_rows = []
        if not weekly_df.empty:
            for pos in ["K", "DEF"]:
                pos_weekly = weekly_df[weekly_df["pos"] == pos]
                if pos_weekly.empty:
                    continue
                top_each_week = (
                    pos_weekly.sort_values(
                        ["week", "fantasy_points"], ascending=[True, False]
                    )
                    .groupby("week")
                    .head(1)
                )
                streaming_rows.append(
                    top_each_week[["week", "player", "team", "pos", "fantasy_points"]]
                )
        streaming_plan = (
            pd.concat(streaming_rows, ignore_index=True)
            if streaming_rows
            else pd.DataFrame(
                columns=["week", "player", "team", "pos", "fantasy_points"]
            )
        )

        # Build snake draft plan honoring your slots and priorities
        def build_draft_plan(board_df: pd.DataFrame) -> pd.DataFrame:
            # Prepare sorted views
            by_overall = board_df.sort_values(["OverallRank"]).reset_index(drop=True)
            pos_lists = {
                p: board_df[board_df["pos"] == p]
                .sort_values(["VORP", "Tier", "PosRank"], ascending=[False, True, True])
                .reset_index(drop=True)
                for p in POSITIONS
            }

            taken: set[str] = set()
            plan_rows = []
            # Starters targets (your team only)
            targets = {"QB": 1, "TE": 1, "K": 1, "DEF": 1, **PRIORITY_STARTERS}
            filled = {k: 0 for k in targets}

            # Determine teams used for simulation: derive from slots if mismatch
            sim_teams = teams
            if DRAFT_SNAKE and (DRAFT_SLOT_R1 + DRAFT_SLOT_R2 - 1) > 1:
                inferred = DRAFT_SLOT_R1 + DRAFT_SLOT_R2 - 1
                if inferred != teams:
                    logger.info(
                        f"Adjusting simulated team count from {teams} to {inferred} to honor pick slots R1={DRAFT_SLOT_R1}, R2={DRAFT_SLOT_R2}."
                    )
                    sim_teams = inferred

            def is_taken(pid) -> bool:
                return pid in taken

            def take_row(row: pd.Series) -> pd.Series | None:
                if row is None:
                    return None
                pid = row["player_id"]
                if pid in taken:
                    return None
                taken.add(pid)
                return row

            def best_available_overall(
                allowed_positions: set[str] | None = None,
            ) -> pd.Series | None:
                for _, r in by_overall.iterrows():
                    if r["player_id"] in taken:
                        continue
                    if allowed_positions and r["pos"] not in allowed_positions:
                        continue
                    return take_row(r)
                return None

            def best_available_by_pos(pos: str) -> pd.Series | None:
                lst = pos_lists.get(pos)
                if lst is None or lst.empty:
                    return None
                for _, r in lst.iterrows():
                    if r["player_id"] not in taken:
                        return take_row(r)
                return None

            def my_pick_for_round(rnd: int) -> pd.Series | None:
                pick = None
                # Fill RB then WR starters first
                if filled.get("RB", 0) < targets.get("RB", 0):
                    pick = best_available_by_pos("RB")
                if pick is None and filled.get("WR", 0) < targets.get("WR", 0):
                    pick = best_available_by_pos("WR")
                # Then QB/TE from allowed round
                if pick is None and rnd >= QB_TE_EARLIEST_ROUND:
                    qb = (
                        best_available_by_pos("QB")
                        if filled.get("QB", 0) < targets.get("QB", 0)
                        else None
                    )
                    te = (
                        best_available_by_pos("TE")
                        if filled.get("TE", 0) < targets.get("TE", 0)
                        else None
                    )
                    if qb is not None and te is not None:
                        pick = qb if qb["VORP"] >= te["VORP"] else te
                        other = te if pick is qb else qb
                        if other is not None:
                            # push back the other by removing from taken (since best_available_by_pos took it)
                            taken.discard(other["player_id"])
                    else:
                        if qb is not None:
                            pick = qb
                        elif te is not None:
                            pick = te
                # K/DEF late
                if pick is None and rnd >= K_DEF_EARLIEST_ROUND:
                    cand_def = best_available_by_pos("DEF")
                    if cand_def is not None:
                        pick = cand_def
                    else:
                        cand_k = best_available_by_pos("K")
                        if cand_k is not None:
                            pick = cand_k
                # Depth WR/RB
                if pick is None:
                    cand_wr = best_available_by_pos("WR")
                    if cand_wr is not None:
                        pick = cand_wr
                    else:
                        cand_rb = best_available_by_pos("RB")
                        if cand_rb is not None:
                            pick = cand_rb
                # Fallback: best overall
                if pick is None:
                    pick = best_available_overall()
                return pick

            def opp_pick_for_round(rnd: int) -> pd.Series | None:
                # Opponents pick by overall, deferring K/DEF early and mildly deferring QB/TE
                allowed: set[str] | None = None
                early_def_positions = {"K", "DEF"}
                early_qb_te = {"QB", "TE"}
                if rnd < K_DEF_EARLIEST_ROUND:
                    allowed = set(POSITIONS) - early_def_positions
                if rnd < QB_TE_EARLIEST_ROUND:
                    allowed = (allowed or set(POSITIONS)) - early_qb_te
                return best_available_overall(allowed)

            # Simulate the snake draft across all rounds
            for rnd in range(1, DRAFT_ROUNDS + 1):
                order = list(range(1, sim_teams + 1))
                if DRAFT_SNAKE and (rnd % 2 == 0):
                    order = list(reversed(order))
                for pick_in_round in order:
                    is_me = (rnd % 2 == 1 and pick_in_round == DRAFT_SLOT_R1) or (
                        rnd % 2 == 0 and pick_in_round == DRAFT_SLOT_R2
                    )
                    if is_me:
                        pick = my_pick_for_round(rnd)
                        if pick is not None:
                            if pick["pos"] in filled:
                                filled[pick["pos"]] += 1
                            plan_rows.append(
                                {
                                    "Round": rnd,
                                    "PickInRound": pick_in_round,
                                    "player": pick["player"],
                                    "team": pick["team"],
                                    "pos": pick["pos"],
                                    "VORP": float(pick["VORP"]),
                                    "Tier": int(pick.get("Tier", 0) or 0),
                                }
                            )
                    else:
                        # Opponent removes a player from the pool
                        _ = opp_pick_for_round(rnd)

            return pd.DataFrame(plan_rows)

        draft_plan = build_draft_plan(board)

        with pd.ExcelWriter(output_path) as writer:
            board.sort_values("OverallRank").loc[:, board_out_cols].to_excel(
                writer, sheet_name="Overall", index=False
            )
            for pos in POSITIONS:
                pos_board = board[board["pos"] == pos].sort_values(["Tier", "PosRank"])
                pos_board.loc[
                    :, [c for c in board_out_cols if c in pos_board.columns]
                ].to_excel(writer, sheet_name=pos, index=False)
            if not draft_plan.empty:
                draft_plan.to_excel(writer, sheet_name="DraftPlan", index=False)
            # Streaming plan
            if not streaming_plan.empty:
                streaming_plan.sort_values(["pos", "week"]).to_excel(
                    writer, sheet_name="Streaming_K_DEF", index=False
                )

        logger.info(f"Draft board exported to {output_path}")
    except Exception as e:
        logger.error(f"Failed to build draft board: {e}")


def main():
    logger.info("Aggregating 2024 season stats from Sleeper API...")
    df, weekly = aggregate_season_stats()
    logger.info(
        f"Aggregated stats for {len(df)} players across {weekly['week'].nunique()} weeks."
    )

    df["fantasy_points"] = compute_fantasy_points(df)
    show_top_players_by_position(df, top_n=30)

    # Export top 100 by position to Excel (separate sheets)
    export_top_players_by_position_to_excel(
        df, top_n=100, path="output/top100_by_position.xlsx"
    )

    lineup = optimize_lineup(df)
    logger.info("Your optimal lineup for the 2024 season:")
    logger.info(
        "\n"
        + lineup[["slot", "player", "team", "pos", "fantasy_points"]]
        .reset_index(drop=True)
        .to_string(index=False)
    )

    # Build and export Draft Board workbook (Overall + per-position + Streaming)
    build_and_export_draft_board(df, weekly, output_path="output/draft_board.xlsx")


if __name__ == "__main__":
    main()
