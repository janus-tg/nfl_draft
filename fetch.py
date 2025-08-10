import requests
import pandas as pd

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_PROJECTIONS_URL = (
    "https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}"
)


def fetch_sleeper_players():
    resp = requests.get(SLEEPER_PLAYERS_URL)
    resp.raise_for_status()
    return resp.json()


def fetch_sleeper_projections(season=2024, week=1):
    url = SLEEPER_PROJECTIONS_URL.format(season=season, week=week)
    resp = requests.get(url)
    resp.raise_for_status()
    stats = resp.json()
    df = pd.DataFrame.from_dict(stats, orient="index")
    return df


def get_player_table(season=2024, week=1):
    players = fetch_sleeper_players()
    stats_df = fetch_sleeper_projections(season, week)

    def map_row(row):
        pid = row.name
        info = players.get(pid, {})
        pos = info.get("position")
        if pos is None:
            pos = "UNK"
        else:
            pos = pos.upper()
        team = info.get("team", "")
        player_name = info.get("full_name", info.get("search_last_name", pid))
        return {
            "player_id": pid,
            "player": player_name,
            "team": team,
            "pos": pos,
            "pass_yds": row.get("pass_yd", 0),
            "pass_td": row.get("pass_td", 0),
            "pass_int": row.get("pass_int", 0),
            "rush_yds": row.get("rush_yd", 0),
            "rush_td": row.get("rush_td", 0),
            "rec": row.get("rec", 0),
            "rec_yds": row.get("rec_yd", 0),
            "rec_td": row.get("rec_td", 0),
            "ret_yds": row.get("kr_yd", 0) + row.get("pr_yd", 0),
            "ret_td": row.get("kr_td", 0) + row.get("pr_td", 0),
            "two_pt": row.get("two_pt", 0),
            "fum_lost": row.get("fum_lost", 0),
            "off_fum_td": row.get("off_fum_td", 0),
            "fg_miss_0_19": row.get("fg_miss_0_19", 0),
            "fg_miss_20_29": row.get("fg_miss_20_29", 0),
            "fg_miss_30_39": row.get("fg_miss_30_39", 0),
            "fg_miss_40_49": row.get("fg_miss_40_49", 0),
            "fg_miss_50": row.get("fg_miss_50", 0),
            "pat_made": row.get("pat_made", 0),
            "pat_miss": row.get("pat_miss", 0),
            "fg_yds": row.get("fg_yds", 0),
            "sack": row.get("sack", 0),
            "dst_int": row.get("int", 0),
            "dst_fum_rec": row.get("fum_rec", 0),
            "dst_td": row.get("td", 0),
            "dst_safety": row.get("safety", 0),
            "dst_block_kick": row.get("block_kick", 0),
            "dst_ret_td": row.get("ret_td", 0),
            "dst_pa": row.get("points_allowed", 99),
            "dst_xp_ret": row.get("xp_ret", 0),
        }

    mapped = stats_df.apply(map_row, axis=1)
    df = pd.DataFrame(list(mapped))
    df = df[df["pos"].isin(["QB", "RB", "WR", "TE", "K", "DEF"])]
    df = df[df["team"].notnull() & (df["team"] != "")]
    stat_cols = [
        c for c in df.columns if c not in ("player_id", "player", "team", "pos")
    ]
    df[stat_cols] = df[stat_cols].fillna(0)
    df = df[df[stat_cols].sum(axis=1) > 0]
    return df.reset_index(drop=True)
