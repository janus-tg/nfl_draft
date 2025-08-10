from fetch import get_player_table
from scoring import compute_fantasy_points
from optimizer import optimize_lineup


def show_top_players_by_position(df, top_n=30):
    for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
        print(f"\nTop {top_n} {pos}s:")
        pos_df = df[df["pos"] == pos].sort_values("fantasy_points", ascending=False)
        print(
            pos_df[["player", "team", "fantasy_points"]]
            .head(top_n)
            .to_string(index=False)
        )


def main():
    print("Fetching player projections from Sleeper API...")
    df = get_player_table(season=2024, week=1)
    print(f"Fetched {len(df)} players.")

    df["fantasy_points"] = compute_fantasy_points(df)
    show_top_players_by_position(df, top_n=30)

    lineup = optimize_lineup(df)
    print("\nYour optimal lineup:")
    print(
        lineup[["slot", "player", "team", "pos", "fantasy_points"]]
        .reset_index(drop=True)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
