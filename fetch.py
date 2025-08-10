import requests
import pandas as pd
import time
from functools import lru_cache
from logger import logger

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_PROJECTIONS_URL = (
    "https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}"
)


def _get_json(url: str, retries: int = 3, backoff: float = 1.5):
    """GET JSON with simple retry/backoff and basic logging."""
    attempt = 0
    while True:
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            attempt += 1
            if attempt > retries:
                logger.error(
                    f"HTTP request failed after {retries} retries: {url} -> {e}"
                )
                raise
            sleep_s = backoff**attempt
            logger.warning(
                f"HTTP error on {url}: {e}. Retrying {attempt}/{retries} in {sleep_s:.1f}s"
            )
            time.sleep(sleep_s)


@lru_cache(maxsize=1)
def fetch_sleeper_players():
    logger.info("Fetching Sleeper players metadata ...")
    return _get_json(SLEEPER_PLAYERS_URL)


@lru_cache(maxsize=None)
def fetch_sleeper_projections(season=2024, week=1):
    url = SLEEPER_PROJECTIONS_URL.format(season=season, week=week)
    logger.info(f"Fetching Sleeper projections: season={season}, week={week}")
    stats = _get_json(url)
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

        # Kicker derivations (best-effort based on available fields)
        # Makes and attempts per distance bucket
        m_0_19 = row.get("fgm_0_19", 0)
        a_0_19 = row.get("fga_0_19", row.get("fg_att_0_19", 0))
        m_20_29 = row.get("fgm_20_29", 0)
        a_20_29 = row.get("fga_20_29", row.get("fg_att_20_29", 0))
        m_30_39 = row.get("fgm_30_39", 0)
        a_30_39 = row.get("fga_30_39", row.get("fg_att_30_39", 0))
        m_40_49 = row.get("fgm_40_49", 0)
        a_40_49 = row.get("fga_40_49", row.get("fg_att_40_49", 0))
        m_50p = row.get("fgm_50p", row.get("fgm_50_plus", 0))
        a_50p = row.get("fga_50p", row.get("fg_att_50_plus", 0))

        miss_0_19 = max((a_0_19 or 0) - (m_0_19 or 0), 0)
        miss_20_29 = max((a_20_29 or 0) - (m_20_29 or 0), 0)
        miss_30_39 = max((a_30_39 or 0) - (m_30_39 or 0), 0)
        miss_40_49 = max((a_40_49 or 0) - (m_40_49 or 0), 0)
        miss_50p = max((a_50p or 0) - (m_50p or 0), 0)

        # PATs
        xpm = row.get("xpm", row.get("pat_made", 0))
        xpa = row.get("xpa", 0)
        xpmissed = row.get("xpmissed", row.get("pat_miss", 0))
        pat_made = xpm or 0
        pat_miss = (
            xpmissed if xpmissed not in (None, 0) else max((xpa or 0) - (xpm or 0), 0)
        )

        # Field goal yards: use provided value if present, else approximate by bin midpoints
        fg_yds_val = row.get("fg_yds")
        if fg_yds_val in (None, 0):
            fg_yds_val = (
                19 * (m_0_19 or 0)
                + 24 * (m_20_29 or 0)
                + 34 * (m_30_39 or 0)
                + 44 * (m_40_49 or 0)
                + 55 * (m_50p or 0)
            )

        # DST alternative keys (fallbacks if projections use other names)
        sack = row.get("sack", row.get("sacks", 0))
        dst_int = row.get("int", row.get("ints", 0))
        dst_fum_rec = row.get("fum_rec", row.get("fumble_rec", 0))
        dst_td = row.get("td", row.get("def_td", 0))
        dst_safety = row.get("safety", row.get("safeties", 0))
        dst_block_kick = row.get("block_kick", row.get("blk_kick", 0))
        dst_ret_td = row.get("ret_td", row.get("kick_ret_td", 0)) + row.get(
            "punt_ret_td", 0
        )
        dst_pa = row.get("points_allowed", row.get("pts_allow", 99))

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
            "fg_miss_0_19": miss_0_19,
            "fg_miss_20_29": miss_20_29,
            "fg_miss_30_39": miss_30_39,
            "fg_miss_40_49": miss_40_49,
            "fg_miss_50": miss_50p,
            "pat_made": pat_made,
            "pat_miss": pat_miss,
            "fg_yds": fg_yds_val,
            "sack": sack,
            "dst_int": dst_int,
            "dst_fum_rec": dst_fum_rec,
            "dst_td": dst_td,
            "dst_safety": dst_safety,
            "dst_block_kick": dst_block_kick,
            "dst_ret_td": dst_ret_td,
            "dst_pa": dst_pa,
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
