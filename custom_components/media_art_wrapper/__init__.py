from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ARTWORK_HEIGHT,
    CONF_ARTWORK_SIZE,
    CONF_ARTWORK_WIDTH,
    CONF_PROVIDERS,
    CONF_SOURCE_ENTITY_ID,
    DEFAULT_ARTWORK_HEIGHT,
    DEFAULT_ARTWORK_SIZE,
    DEFAULT_ARTWORK_WIDTH,
    DEFAULT_PROVIDERS,
    DOMAIN,
    PLATFORMS,
)
from .cover_resolver import async_resolve_cover
from .models import TrackQuery

_LOGGER = logging.getLogger(__name__)

# Detects station-ident metadata: no artist AND title contains " - " which
# radio stations use for "STATIONNAME - SLOGAN" (e.g. "WDR 2 - Für den Westen").
# Real track titles without an artist field rarely contain " - ".
_RE_STATION_IDENT = re.compile(r".+\s+-\s+.+")

_RE_CLEAN = re.compile(
    r"""
       \s*
       (
           \([^)]*(?:Remix|Edit|Mix)[^)]*\) |
           \[[^\]]*(?:Remix|Edit|Mix)[^\]]*\] |
           -\s*.*(?:Remix|Edit|Mix).* |
           \(?\s*\d+[_:]\d+\s*\)?
       )
    """,
    re.I | re.X,
)
_BAD = {"", "none", "null", "unknown", "n/a", "-"}


@dataclass(slots=True)
class CoverData:
    source_entity_id: str
    track_key: str | None
    artist: str | None
    title: str | None
    album: str | None
    provider: str | None
    artwork_url: str | None
    content_type: str
    image: bytes | None
    last_updated: datetime | None


def _raw_text(value: str | None) -> str | None:
    """Normalize whitespace only – keeps remix/edit/mix annotations intact."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s{2,}", " ", value).strip()
    if normalized.lower() in _BAD:
        return None
    return normalized or None


def _clean_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s{2,}", " ", _RE_CLEAN.sub("", value)).strip()
    if cleaned.lower() in _BAD:
        return None
    return cleaned or None


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _build_track_key(artist: str | None, title: str | None, album: str | None) -> str | None:
    if not artist and not title:
        return None
    parts = [
        _norm(artist) if artist else "",
        _norm(title) if title else "",
        _norm(album) if album else "",
    ]
    return "|".join(parts)


class CoverCoordinator(DataUpdateCoordinator[CoverData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.source_entity_id: str = entry.data[CONF_SOURCE_ENTITY_ID]
        self.providers: list[str] = []
        self.artwork_size: int = DEFAULT_ARTWORK_SIZE
        self.artwork_width: int = DEFAULT_ARTWORK_WIDTH
        self.artwork_height: int = DEFAULT_ARTWORK_HEIGHT

        self._session = aiohttp_client.async_get_clientsession(hass)
        self._unsub_state_change: Any | None = None
        self._lock = asyncio.Lock()

        self._update_from_entry(entry)

        self._artist: str | None = None
        self._title: str | None = None
        self._raw_title: str | None = None
        self._album: str | None = None
        self._track_key: str | None = None
        self._last_cover: CoverData | None = None
        self._last_error: str | None = None

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"{DOMAIN}:{self.source_entity_id}",
            update_method=self._async_update_data,
            update_interval=None,  # event-driven
        )

    def _update_from_entry(self, entry: ConfigEntry) -> None:
        providers = entry.options.get(CONF_PROVIDERS, entry.data.get(CONF_PROVIDERS, DEFAULT_PROVIDERS))
        self.providers = list(providers) if isinstance(providers, list) else list(DEFAULT_PROVIDERS)

        artwork_width = entry.options.get(
            CONF_ARTWORK_WIDTH,
            entry.data.get(CONF_ARTWORK_WIDTH, entry.data.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_WIDTH)),
        )
        artwork_height = entry.options.get(
            CONF_ARTWORK_HEIGHT,
            entry.data.get(CONF_ARTWORK_HEIGHT, entry.data.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_HEIGHT)),
        )

        self.artwork_width = int(artwork_width)
        self.artwork_height = int(artwork_height)
        self.artwork_size = max(self.artwork_width, self.artwork_height)

    async def async_start(self) -> None:
        """Start listening to media_player state changes and do initial refresh."""
        if self._unsub_state_change is not None:
            return

        self._unsub_state_change = async_track_state_change_event(
            self.hass,
            [self.source_entity_id],
            self._handle_state_change,
        )

        state = self.hass.states.get(self.source_entity_id)
        changed = self._set_track_from_state(state)
        if changed or state is not None:
            await self.async_request_refresh()

    async def async_stop(self) -> None:
        """Stop listeners."""
        if self._unsub_state_change is not None:
            self._unsub_state_change()
            self._unsub_state_change = None

    @callback
    def _handle_state_change(self, event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return

        changed = self._set_track_from_state(new_state)
        if not changed:
            return

        self.hass.async_create_task(self.async_request_refresh())

    def _set_track_from_state(self, state: State | None) -> bool:
        if state is None or state.state in {"unavailable", "unknown"}:
            return False

        attrs = state.attributes or {}
        raw_title = _raw_text(attrs.get("media_title"))
        artist = _clean_text(attrs.get("media_artist"))
        title = _clean_text(attrs.get("media_title"))
        album = _clean_text(attrs.get("media_album_name"))

        # Heuristic: no artist AND title looks like "STATIONNAME - SLOGAN"
        # (e.g. "WDR 2 - Für den Westen"). Treat as no usable track info so
        # the last successful cover is kept instead of triggering a new search.
        if not artist and title and _RE_STATION_IDENT.match(title):
            _LOGGER.debug("Skipping station-ident title %r (no artist)", title)
            return False

        # Use raw title in the key so "Song (Remix)" and "Song" are treated as
        # distinct tracks and each triggers its own cover fetch.
        new_key = _build_track_key(artist, raw_title, album)
        if new_key == self._track_key:
            return False

        self._artist = artist
        self._title = title
        self._raw_title = raw_title
        self._album = album
        self._track_key = new_key
        return True

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _fallback_data(
        self,
        *,
        track_key: str | None,
        artist: str | None,
        title: str | None,
        album: str | None,
    ) -> CoverData:
        if self._last_cover is not None:
            return self._last_cover
        return CoverData(
            source_entity_id=self.source_entity_id,
            track_key=track_key,
            artist=artist,
            title=title,
            album=album,
            provider=None,
            artwork_url=None,
            content_type="image/jpeg",
            image=None,
            last_updated=None,
        )

    async def _async_update_data(self) -> CoverData:
        """Fetch and cache cover data for current track."""
        async with self._lock:
            track_key = self._track_key
            artist = self._artist
            title = self._title
            album = self._album

            if not track_key or (not artist and not title):
                return self._fallback_data(track_key=None, artist=artist, title=title, album=album)

            try:
                raw_title = self._raw_title
                query = TrackQuery(
                    artist=artist,
                    title=title,
                    album=album,
                    artwork_width=self.artwork_width,
                    artwork_height=self.artwork_height,
                    # Pass raw title so the resolver can try it first (e.g. "Song (Remix)")
                    # before falling back to the cleaned title ("Song").
                    original_title=raw_title if raw_title != title else None,
                )
                resolved = await async_resolve_cover(
                    session=self._session,
                    query=query,
                    providers=self.providers,
                )
            except Exception as err:  # noqa: BLE001
                self._last_error = str(err)
                _LOGGER.warning(
                    "Cover resolution failed for %s (%s - %s): %s",
                    self.source_entity_id,
                    artist,
                    title,
                    err,
                )
                return self._fallback_data(track_key=track_key, artist=artist, title=title, album=album)

            if resolved is None:
                return self._fallback_data(track_key=track_key, artist=artist, title=title, album=album)

            self._last_error = None
            data = CoverData(
                source_entity_id=self.source_entity_id,
                track_key=track_key,
                artist=artist,
                title=title,
                album=album,
                provider=resolved.provider,
                artwork_url=resolved.artwork_url,
                content_type=resolved.content_type,
                image=resolved.image,
                last_updated=dt_util.utcnow(),
            )
            self._last_cover = data
            return data


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries to the current schema version.

    Each block handles exactly one version step so the chain is fully additive:
    future migrations just append another ``if current_version < N`` block.

    Version history
    ---------------
    1  – initial release; artwork stored as a single ``artwork_size`` value.
    2  – ``artwork_size`` replaced by separate ``artwork_width`` / ``artwork_height``.
    """
    current_version: int = entry.version
    _LOGGER.debug("Migrating config entry %s from version %s", entry.entry_id, current_version)

    new_data = dict(entry.data)
    new_options = dict(entry.options)

    if current_version < 2:
        # Split the legacy unified ``artwork_size`` field into the two separate
        # dimension fields.  Applies to both ``data`` and ``options`` so that
        # entries whose options were written by the old flow are also cleaned up.
        for store in (new_data, new_options):
            if CONF_ARTWORK_SIZE in store:
                size = int(store.pop(CONF_ARTWORK_SIZE))
                store.setdefault(CONF_ARTWORK_WIDTH, size)
                store.setdefault(CONF_ARTWORK_HEIGHT, size)
        current_version = 2
        _LOGGER.info(
            "Migrated config entry %s: v1 → v2 (artwork_size → artwork_width/artwork_height)",
            entry.entry_id,
        )

    hass.config_entries.async_update_entry(
        entry, data=new_data, options=new_options, version=current_version
    )
    _LOGGER.debug("Config entry %s successfully migrated to version %s", entry.entry_id, current_version)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = CoverCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: CoverCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return unload_ok
