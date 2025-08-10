from fetch import get_player_table
from scoring import compute_fantasy_points
from optimizer import optimize_lineup
import pandas as pd
from logger import logger


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
    for week in range(1, 19):
        logger.info(f"Fetching week {week} data...")
        weekly_df = get_player_table(season=2024, week=week)
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
    return df


def main():
    logger.info("Aggregating 2024 season stats from Sleeper API...")
    df = aggregate_season_stats()
    logger.info(f"Aggregated stats for {len(df)} players.")

    df["fantasy_points"] = compute_fantasy_points(df)
    show_top_players_by_position(df, top_n=30)

    lineup = optimize_lineup(df)
    logger.info("Your optimal lineup for the 2024 season:")
    logger.info(
        "\n"
        + lineup[["slot", "player", "team", "pos", "fantasy_points"]]
        .reset_index(drop=True)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
