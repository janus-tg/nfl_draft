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

    # Bench: simple diversification heuristic - pick best remaining by cycling positions
    bench_candidates = df[
        (~df["player_id"].isin(used_ids)) & (df["pos"].isin(["QB", "RB", "WR", "TE"]))
    ]
    bench = []
    pos_cycle = ["RB", "WR", "QB", "TE"]
    for _ in range(5):
        for p in pos_cycle:
            if len(bench) >= 5:
                break
            cand = bench_candidates[
                (bench_candidates["pos"] == p)
                & (
                    ~bench_candidates["player_id"].isin(
                        {*used_ids, *[r for r in bench]}
                    )
                )
            ].head(1)
            if not cand.empty:
                bench.append(cand.iloc[0]["player_id"])
        if len(bench) >= 5:
            break
    # Fallback if still short
    if len(bench) < 5:
        extra = (
            bench_candidates[~bench_candidates["player_id"].isin(bench)]
            .head(5 - len(bench))["player_id"]
            .tolist()
        )
        bench.extend(extra)
    lineup["BN"] = bench_candidates[bench_candidates["player_id"].isin(bench)]

    parts = [
        ("QB", lineup["QB"]),
        ("RB", lineup["RB"]),
        ("WR", lineup["WR"]),
        ("TE", lineup["TE"]),
        ("FLEX", lineup["FLEX"]),
        ("K", lineup["K"]),
        ("DEF", lineup["DEF"]),
        ("BN", lineup["BN"]),
    ]
    labeled = []
    for slot_name, df_part in parts:
        if df_part.empty:
            continue
        block = df_part.copy()
        block["slot"] = [slot_name] * len(block)
        labeled.append(block)
    final = pd.concat(labeled)
    return final
