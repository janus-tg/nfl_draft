from config import LINEUP
import pandas as pd


def optimize_lineup(df: pd.DataFrame):
    df = df.copy()
    df = df.sort_values("fantasy_points", ascending=False)
    lineup = {}
    used_ids = set()

    for pos, count in [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1)]:
        pos_players = df[(df["pos"] == pos) & (~df["player_id"].isin(used_ids))]
        lineup[pos] = pos_players.head(count)
        used_ids.update(lineup[pos]["player_id"])

    flex_pool = df[
        (df["pos"].isin(["RB", "WR", "TE"])) & (~df["player_id"].isin(used_ids))
    ]
    lineup["FLEX"] = flex_pool.head(1)
    used_ids.update(lineup["FLEX"]["player_id"])

    k_players = df[(df["pos"] == "K") & (~df["player_id"].isin(used_ids))]
    lineup["K"] = k_players.head(1)
    used_ids.update(lineup["K"]["player_id"])

    def_players = df[(df["pos"] == "DEF") & (~df["player_id"].isin(used_ids))]
    lineup["DEF"] = def_players.head(1)
    used_ids.update(lineup["DEF"]["player_id"])

    bench_pool = df[
        (~df["player_id"].isin(used_ids)) & (df["pos"].isin(["QB", "RB", "WR", "TE"]))
    ]
    lineup["BN"] = bench_pool.head(5)

    final = pd.concat(
        [
            lineup["QB"],
            lineup["RB"],
            lineup["WR"],
            lineup["TE"],
            lineup["FLEX"],
            lineup["K"],
            lineup["DEF"],
            lineup["BN"],
        ]
    )
    final["slot"] = (
        ["QB"]
        + ["RB"] * 2
        + ["WR"] * 2
        + ["TE"]
        + ["FLEX"]
        + ["K"]
        + ["DEF"]
        + ["BN"] * 5
    )
    return final
