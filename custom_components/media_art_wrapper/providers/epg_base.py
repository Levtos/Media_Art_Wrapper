"""EPG helpers — unified path for HA-EPG sensor and TVMaze schedule lookups."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

TVMAZE_SCHEDULE_URL = "https://api.tvmaze.com/schedule"
_JSON_KW = {"content_type": None}

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_SPACES = re.compile(r"\s+")

# Module-level cache: date string → TVMaze schedule list
_schedule_cache: dict[str, list[dict[str, Any]]] = {}


@dataclass(slots=True)
class EPGProgram:
    """Unified EPG programme record returned by any EPG source."""

    title: str
    sub_title: str = ""
    description: str = ""
    channel_name: str = ""
    channel_icon: str | None = None
    show_name: str = ""
    image_url: str | None = None


def _clean(s: str) -> str:
    return _RE_SPACES.sub(" ", _RE_NON_ALNUM.sub(" ", s.lower())).strip()


# ---------------------------------------------------------------------------
# HA-EPG sensor source
# ---------------------------------------------------------------------------

class HaEpgProvider:
    """Reads the current program from a Home Assistant EPG sensor."""

    async def get_current_program(
        self, hass: HomeAssistant, sensor_entity_id: str
    ) -> EPGProgram | None:
        state = hass.states.get(sensor_entity_id)
        if not state:
            return None

        today = state.attributes.get("today", {})
        if not isinstance(today, dict):
            return None
        now = datetime.now(tz=timezone.utc).strftime("%H:%M")

        current: dict[str, Any] | None = None
        for slot_time, program in sorted(today.items()):
            if not isinstance(program, dict):
                continue
            slot_start = str(program.get("start", slot_time))
            slot_end = str(program.get("end", "23:59"))
            if slot_start <= now < slot_end:
                current = program
                break

        if not current:
            return None

        return EPGProgram(
            title=str(current.get("title", "")),
            sub_title=str(current.get("sub_title", "")),
            description=str(current.get("desc", "")),
            channel_name=str(state.attributes.get("channel_display_name", "")),
            channel_icon=state.attributes.get("channel_icon"),
        )


# ---------------------------------------------------------------------------
# TVMaze schedule source
# ---------------------------------------------------------------------------

async def _fetch_schedule(session, date_str: str) -> list[dict[str, Any]]:
    if date_str in _schedule_cache:
        return _schedule_cache[date_str]

    try:
        async with session.get(
            TVMAZE_SCHEDULE_URL,
            params={"country": "DE", "date": date_str},
            timeout=15,
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("TVMaze schedule fetch failed (%s): %s", date_str, err)
        return []

    if not isinstance(payload, list):
        return []

    _schedule_cache[date_str] = payload
    for old_key in [k for k in _schedule_cache if k < date_str]:
        del _schedule_cache[old_key]
    return payload


def _network_name(episode: dict[str, Any]) -> str:
    show = episode.get("show") or {}
    network = show.get("network") or {}
    web_channel = show.get("webChannel") or {}
    return str(network.get("name") or web_channel.get("name") or "")


def _channel_matches(episode: dict[str, Any], channel_tokens: list[str]) -> bool:
    net = _clean(_network_name(episode))
    if not net:
        return False
    return all(tok in net for tok in channel_tokens if len(tok) >= 2)


def _is_airing_now(episode: dict[str, Any], now: datetime) -> bool:
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


def _episode_image_url(episode: dict[str, Any]) -> str | None:
    for source in (episode.get("image"), (episode.get("show") or {}).get("image")):
        if isinstance(source, dict):
            url = source.get("original") or source.get("medium")
            if isinstance(url, str) and url:
                return url
    return None


async def get_schedule_program(
    session, channel_name: str
) -> EPGProgram | None:
    """Return the programme currently airing on *channel_name* via TVMaze schedule."""
    channel_tokens = _clean(channel_name).split()
    if not channel_tokens:
        return None

    now = datetime.now(tz=timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

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
            return EPGProgram(
                title=str(episode.get("name") or ""),
                channel_name=channel_name,
                show_name=str(show.get("name") or ""),
                image_url=_episode_image_url(episode),
            )

    return None
