"""Sleeper API access layer with on-disk caching.

Three sources feed the model:
  * projections  -- forward-looking 2026 weekly expectations
  * stats        -- ACTUAL weekly results from prior seasons (durability + real
                    volatility; the projection stream cannot supply either)
  * players      -- metadata: injury designation, age, depth chart, market rank
"""

import json
import os
import time
from functools import lru_cache

import requests

from logger import logger

PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
PROJECTIONS_URL = "https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}"
STATS_URL = "https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
# Player metadata carries live injury news, so it must not go stale on us.
PLAYERS_CACHE_TTL = 6 * 3600


def _cache_path(name: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{name}.json")


def _get_json(url: str, retries: int = 3, backoff: float = 1.5):
    attempt = 0
    while True:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            attempt += 1
            if attempt > retries:
                logger.error(f"HTTP failed after {retries} retries: {url} -> {exc}")
                raise
            sleep_s = backoff ** attempt
            logger.warning(f"HTTP error {url}: {exc}. Retry {attempt}/{retries} in {sleep_s:.1f}s")
            time.sleep(sleep_s)


def _cached_get(url: str, cache_name: str, ttl: float | None = None):
    path = _cache_path(cache_name)
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if ttl is None or age < ttl:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                logger.warning(f"Cache unreadable, refetching: {path}")
    data = _get_json(url)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except Exception as exc:
        logger.warning(f"Could not write cache {path}: {exc}")
    return data


@lru_cache(maxsize=1)
def get_players() -> dict:
    """Player metadata keyed by Sleeper player_id."""
    logger.info("Fetching Sleeper player metadata ...")
    return _cached_get(PLAYERS_URL, "players_nfl", ttl=PLAYERS_CACHE_TTL) or {}


@lru_cache(maxsize=None)
def get_projections(season: int, week: int) -> dict:
    return _cached_get(
        PROJECTIONS_URL.format(season=season, week=week), f"proj_{season}_{week}"
    ) or {}


@lru_cache(maxsize=None)
def get_actual_stats(season: int, week: int) -> dict:
    """Real results. Past seasons are immutable, so they cache forever."""
    return _cached_get(
        STATS_URL.format(season=season, week=week), f"stats_{season}_{week}"
    ) or {}


def get_season_projections(season: int, weeks: int = 18) -> dict[int, dict]:
    out = {}
    for week in range(1, weeks + 1):
        logger.info(f"Projections {season} week {week}")
        out[week] = get_projections(season, week)
    return out


def get_season_actuals(season: int, weeks: int = 18) -> dict[int, dict]:
    out = {}
    for week in range(1, weeks + 1):
        logger.info(f"Actuals {season} week {week}")
        out[week] = get_actual_stats(season, week)
    return out
