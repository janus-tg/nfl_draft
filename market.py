"""FantasyPros expert consensus ranking (ECR): a second opinion on player
value, independent of Sleeper ADP, used by both valuation.py (blended into
the market signal) and validate.py (agreement check).

Shared here so the two don't drift into two different name-matching
implementations of the same idea.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata

import pandas as pd
import requests

from fetch import CACHE_DIR
from logger import logger

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
# Camp injuries and depth-chart battles move ECR through the offseason, but
# not minute to minute -- cache it like player metadata, not like a live feed.
ECR_CACHE_TTL = 6 * 3600


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


def _ecr_cache_path(scoring: str) -> str:
    return os.path.join(CACHE_DIR, f"ecr_{scoring.lower()}.json")


def fetch_expert_consensus(scoring: str = "PPR", use_cache: bool = True) -> pd.DataFrame:
    """FantasyPros Expert Consensus Rankings, from the page's embedded JSON.

    The visible table is rendered client-side, so the table markup is empty on
    fetch; the data lives in a `var ecrData = {...}` blob in the page source.
    Falls back to the on-disk cache (any age) if the live fetch fails, so a
    FantasyPros outage or a page-layout change degrades the market blend to
    ADP-only instead of crashing the whole board build.
    """
    path = _ecr_cache_path(scoring)
    if use_cache and os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < ECR_CACHE_TTL:
            try:
                return pd.DataFrame(json.load(open(path, "r", encoding="utf-8")))
            except Exception:
                logger.warning(f"ECR cache unreadable, refetching: {path}")

    try:
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

        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(df.to_dict("records"), fh)
        except Exception as exc:
            logger.warning(f"Could not write ECR cache {path}: {exc}")
        return df

    except Exception as exc:
        logger.warning(f"FantasyPros ECR fetch failed ({exc}); "
                       f"falling back to any cached copy.")
        if os.path.exists(path):
            try:
                return pd.DataFrame(json.load(open(path, "r", encoding="utf-8")))
            except Exception:
                pass
        raise
