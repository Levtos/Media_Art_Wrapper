from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

TVMAZE_SCHEDULE_URL = "https://api.tvmaze.com/schedule"
_JSON_KW = {"content_type": None}

# Date-keyed cache: only the last 2 calendar days are kept.
_schedule_cache: dict[str, list[dict[str, Any]]] = {}

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_SPACES = re.compile(r"\s+")


def _normalize(s: str) -> str:
    s = s.strip().lower()
    s = _RE_NON_ALNUM.sub(" ", s)
    return _RE_SPACES.sub(" ", s).strip()


async def _fetch_schedule(session, date_str: str) -> list[dict[str, Any]]:
    """Return (and cache) the TVMaze Germany schedule for *date_str* (YYYY-MM-DD)."""
    if date_str in _schedule_cache:
        return _schedule_cache[date_str]

    params = {"country": "DE", "date": date_str}
    try:
        async with session.get(TVMAZE_SCHEDULE_URL, params=params, timeout=15) as resp:
            resp.raise_for_status()
            payload = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("TVMaze schedule fetch failed (date=%s): %s", date_str, err)
        return []

    if not isinstance(payload, list):
        return []

    _schedule_cache[date_str] = payload

    # Evict old entries – keep only today and yesterday.
    for old_key in [k for k in _schedule_cache if k < date_str]:
        del _schedule_cache[old_key]

    _LOGGER.debug("TVMaze schedule: cached %d entries for %s", len(payload), date_str)
    return payload


def _network_name(episode: dict[str, Any]) -> str:
    """Extract the network / web-channel name from a TVMaze schedule entry."""
    show = episode.get("show") or {}
    network = show.get("network") or {}
    web_channel = show.get("webChannel") or {}
    return str(network.get("name") or web_channel.get("name") or "")


def _channel_matches(episode: dict[str, Any], channel_tokens: list[str]) -> bool:
    """Return True if every channel token appears in the episode's network name."""
    net = _normalize(_network_name(episode))
    if not net:
        return False
    return all(tok in net for tok in channel_tokens if len(tok) >= 2)


def _is_airing_now(episode: dict[str, Any], now: datetime) -> bool:
    """Return True if the episode is currently on air."""
    airstamp = episode.get("airstamp")
    runtime = episode.get("runtime") or 30
    if not airstamp:
        return False
    try:
        start = datetime.fromisoformat(airstamp)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return start <= now <= start + timedelta(minutes=runtime)


def _image_url(episode: dict[str, Any]) -> str | None:
    """Return the best available image URL for an episode (prefer episode over show)."""
    for source in (episode.get("image"), (episode.get("show") or {}).get("image")):
        if isinstance(source, dict):
            url = source.get("original") or source.get("medium")
            if isinstance(url, str) and url:
                return url
    return None


async def async_get_current_program(
    session,
    channel_name: str,
) -> dict[str, Any] | None:
    """Return metadata for the program currently airing on *channel_name*.

    Uses the TVMaze Germany schedule (free, no API key).  The channel name is
    matched against TVMaze network names via token overlap, so fuzzy variants
    like 'WDR', 'WDR HD', 'wdr fernsehen' all resolve correctly.

    Returns a dict with:
        title     – episode/programme title (may be empty string)
        show_name – series/show name
        image_url – URL of the best available image, or None
    or None if nothing could be found.
    """
    channel_tokens = _normalize(channel_name).split()
    if not channel_tokens:
        return None

    now = datetime.now(tz=timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # Late-night shows may have started yesterday.
    for fetch_date in (date_str, (now - timedelta(days=1)).strftime("%Y-%m-%d")):
        schedule = await _fetch_schedule(session, fetch_date)
        for episode in schedule:
            if not isinstance(episode, dict):
                continue
            if not _channel_matches(episode, channel_tokens):
                continue
            if not _is_airing_now(episode, now):
                continue

            show = episode.get("show") or {}
            result = {
                "title": str(episode.get("name") or ""),
                "show_name": str(show.get("name") or ""),
                "image_url": _image_url(episode),
            }
            _LOGGER.debug(
                "EPG match: channel=%r → show=%r episode=%r",
                channel_name, result["show_name"], result["title"],
            )
            return result

    _LOGGER.debug("EPG: no current program found for channel=%r", channel_name)
    return None
