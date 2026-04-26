from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CATEGORY_AUTO,
    CONF_ARTWORK_HEIGHT,
    CONF_ARTWORK_SIZE,
    CONF_ARTWORK_WIDTH,
    CONF_CATEGORY,
    CONF_CREATE_WRAPPER,
    CONF_EPG_FULL_LOOKUP_CHANNELS,
    CONF_EPG_SENSOR,
    CONF_EPG_SENSOR_MAP,
    CONF_FALLBACK_MODE,
    CONF_MAW_SENSOR_DISCORD_GAME,
    CONF_MAW_SENSOR_STASH_ACTIVE,
    CONF_MAW_SENSOR_TV_INPUT,
    CONF_SOURCE_ENTITY_ID,
    COMBINED_NUM_SOURCE_SLOTS,
    DEFAULT_ARTWORK_HEIGHT,
    DEFAULT_ARTWORK_SIZE,
    DEFAULT_ARTWORK_WIDTH,
    DEFAULT_MAW_SENSOR_DISCORD_GAME,
    DEFAULT_MAW_SENSOR_STASH_ACTIVE,
    DEFAULT_MAW_SENSOR_TV_INPUT,
    DEFAULT_EPG_FULL_LOOKUP_CHANNELS,
    DOMAIN,
    FALLBACK_PLACEHOLDER,
    PLATFORMS,
    RATIO_1_1_2000,
    epg_sensor_for_channel,
)
from .providers.epg_base import HaEpgProvider
from .providers.hierarchy import (
    detect_badge_game,
    detect_scenario,
    maybe_apply_badge_bytes,
    resolve_hierarchy,
)
from .providers.query_builder import build_query

_LOGGER = logging.getLogger(__name__)

# Station-ident heuristic: no artist AND title contains " - " (e.g. "WDR 2 - Für den Westen")
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
    category: str = CATEGORY_AUTO


def _raw_text(value: Any) -> str | None:
    """Normalize whitespace only – keeps remix/edit/mix annotations intact."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s{2,}", " ", value).strip()
    if normalized.lower() in _BAD:
        return None
    return normalized or None


def _clean_text(value: Any) -> str | None:
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
        self.category: str = CATEGORY_AUTO
        self.artwork_size: int = DEFAULT_ARTWORK_SIZE
        self.artwork_width: int = DEFAULT_ARTWORK_WIDTH
        self.artwork_height: int = DEFAULT_ARTWORK_HEIGHT

        self._session = aiohttp_client.async_get_clientsession(hass)
        self._unsub_state_change: Any | None = None
        self._lock = asyncio.Lock()

        self._update_from_entry(entry)

        self._state_attrs: dict[str, Any] = {}
        self._artist: str | None = None
        self._title: str | None = None
        self._raw_title: str | None = None
        self._album: str | None = None
        self._track_key: str | None = None
        self._last_cover: CoverData | None = None
        self._last_error: str | None = None
        self._epg_sensor: str | None = None
        self._epg_channel_icon: str | None = None
        self._sensor_tv_input: str = ""
        self._sensor_discord_game: str = ""
        self._sensor_stash_active: str = ""
        self._epg_full_lookup_channels: set[str] = set(DEFAULT_EPG_FULL_LOOKUP_CHANNELS)

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"{DOMAIN}:{self.source_entity_id}",
            update_method=self._async_update_data,
            update_interval=None,  # event-driven
        )

    def _update_from_entry(self, entry: ConfigEntry) -> None:
        opts = entry.options
        data = entry.data

        self.category = str(opts.get(CONF_CATEGORY, data.get(CONF_CATEGORY, CATEGORY_AUTO)))

        artwork_width = opts.get(
            CONF_ARTWORK_WIDTH,
            data.get(CONF_ARTWORK_WIDTH, data.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_WIDTH)),
        )
        artwork_height = opts.get(
            CONF_ARTWORK_HEIGHT,
            data.get(CONF_ARTWORK_HEIGHT, data.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_HEIGHT)),
        )

        self.artwork_width = int(artwork_width)
        self.artwork_height = int(artwork_height)
        self.artwork_size = max(self.artwork_width, self.artwork_height)
        # EPG sensor lookup is done per-call against options now (§5 Teil 2 —
        # per-channel sensor map with single-sensor fallback). The instance
        # attribute is kept only for legacy diagnostics / state-change tracking.
        epg = opts.get(CONF_EPG_SENSOR, data.get(CONF_EPG_SENSOR))
        self._epg_sensor = str(epg).strip() if isinstance(epg, str) and epg else None

        # §7.1 context sensors driving the §2.3 hierarchy detector.
        # Defaults match LASTENHEFT §7.1 so an out-of-the-box setup needs
        # no extra configuration. Empty string disables that branch.
        self._sensor_tv_input = str(
            opts.get(CONF_MAW_SENSOR_TV_INPUT,
                     data.get(CONF_MAW_SENSOR_TV_INPUT, DEFAULT_MAW_SENSOR_TV_INPUT))
        ).strip()
        self._sensor_discord_game = str(
            opts.get(CONF_MAW_SENSOR_DISCORD_GAME,
                     data.get(CONF_MAW_SENSOR_DISCORD_GAME, DEFAULT_MAW_SENSOR_DISCORD_GAME))
        ).strip()
        self._sensor_stash_active = str(
            opts.get(CONF_MAW_SENSOR_STASH_ACTIVE,
                     data.get(CONF_MAW_SENSOR_STASH_ACTIVE, DEFAULT_MAW_SENSOR_STASH_ACTIVE))
        ).strip()
        raw_channels = opts.get(CONF_EPG_FULL_LOOKUP_CHANNELS, data.get(CONF_EPG_FULL_LOOKUP_CHANNELS))
        if isinstance(raw_channels, str):
            parsed = {part.strip() for part in raw_channels.split(",") if part.strip()}
        elif isinstance(raw_channels, (list, tuple, set)):
            parsed = {str(part).strip() for part in raw_channels if str(part).strip()}
        else:
            parsed = set(DEFAULT_EPG_FULL_LOOKUP_CHANNELS)
        self._epg_full_lookup_channels = parsed or set(DEFAULT_EPG_FULL_LOOKUP_CHANNELS)

    def _tracked_entity_ids(self) -> list[str]:
        """Source plus §7.1 context sensors used by the §2.3 detector."""
        ids = [self.source_entity_id]
        for sensor in (
            self._sensor_tv_input,
            self._sensor_discord_game,
            self._sensor_stash_active,
        ):
            if sensor and sensor not in ids:
                ids.append(sensor)
        return ids

    async def async_start(self) -> None:
        """Start listening to media_player state changes and do initial refresh."""
        if self._unsub_state_change is not None:
            return

        self._unsub_state_change = async_track_state_change_event(
            self.hass,
            self._tracked_entity_ids(),
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

        entity_id = event.data.get("entity_id")
        if entity_id != self.source_entity_id:
            # §7.1 context sensor changed — scenario may have changed even
            # though the source track did not. Trigger a refresh either way.
            self.hass.async_create_task(self.async_request_refresh())
            return

        changed = self._set_track_from_state(new_state)
        if not changed:
            return

        self.hass.async_create_task(self.async_request_refresh())

    def _set_track_from_state(self, state: State | None) -> bool:
        if state is None or state.state in {"unavailable", "unknown"}:
            return False

        attrs = dict(state.attributes or {})
        raw_title = _raw_text(attrs.get("media_title"))
        artist = _clean_text(attrs.get("media_artist"))
        title = _clean_text(attrs.get("media_title"))
        album = _clean_text(attrs.get("media_album_name"))

        # Heuristic: no artist AND title looks like "STATIONNAME - SLOGAN".
        if not artist and title and _RE_STATION_IDENT.match(title):
            _LOGGER.debug("Skipping station-ident title %r (no artist)", title)
            return False

        new_key = _build_track_key(artist, raw_title, album)
        if new_key == self._track_key:
            return False

        self._state_attrs = attrs
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
        # Only reuse the last cover when it belongs to the *same* track (e.g. a
        # transient network error while loading the same song/game).  If the
        # track changed and the new lookup simply failed, return an empty
        # CoverData so we never display artwork from a previous unrelated track.
        if (
            self._last_cover is not None
            and track_key is not None
            and self._last_cover.track_key == track_key
        ):
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
            category=self.category,
        )

    def _native_artwork_result(self, state_attrs: dict[str, Any]) -> str | None:
        """§2.3 prio 1 — return the source's own external artwork URL.

        Looks up *both* the live state and the snapshotted attrs because
        Music Assistant updates ``entity_picture`` shortly after a track
        change, while ``_state_attrs`` is captured exactly at track change
        and may still hold the previous (or proxy) URL.

        URL source order:
          1. ``media_image_url`` — most integrations (incl. MA) expose the
             canonical external URL here without HA's proxy rewriting.
          2. ``entity_picture`` — only when it's an absolute http(s) URL.

        Anything starting with ``/`` (e.g. ``/api/media_player_proxy/...``
        or ``entity_picture_local``) is intentionally ignored — it would
        either loop back to HA's own proxy or to this wrapper's served
        image and would never count as native source artwork.
        """
        live = self.hass.states.get(self.source_entity_id)
        live_attrs = dict(live.attributes) if live is not None else {}

        for source_label, attrs in (("live", live_attrs), ("snapshot", state_attrs)):
            for key in ("media_image_url", "entity_picture"):
                value = attrs.get(key)
                if isinstance(value, str) and (
                    value.startswith("http://") or value.startswith("https://")
                ):
                    _LOGGER.debug(
                        "§2.3 prio 1 native artwork: source=%s key=%s url=%s",
                        source_label, key, value,
                    )
                    return value
        return None

    def _sensor_state_str(self, entity_id: str) -> str | None:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        if st is None or st.state in {"unavailable", "unknown"}:
            return None
        return st.state

    def _sensor_attrs(self, entity_id: str) -> dict[str, Any]:
        if not entity_id:
            return {}
        st = self.hass.states.get(entity_id)
        if st is None:
            return {}
        return dict(st.attributes or {})

    async def _fetch_native_image(self, url: str) -> tuple[bytes | None, str]:
        """Best-effort byte download for §2.3 prio 1 native artwork."""
        try:
            async with self._session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None, "image/jpeg"
                ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                return await resp.read(), ct
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Native artwork download failed (%s): %s", url, err)
            return None, "image/jpeg"

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
                state_attrs = dict(self._state_attrs)

                # §2.4 — badge overlay: Discord game-context drives an SGDB
                # logo composited over the primary cover. Detected once per
                # update and reused by both the native pass-through and the
                # hierarchy dispatcher.
                badge_game_title = detect_badge_game(
                    self._sensor_state_str(self._sensor_discord_game),
                    self._sensor_attrs(self._sensor_discord_game),
                )

                # §2.3 prio 1 — native artwork pass-through.
                native_url = self._native_artwork_result(state_attrs)
                if native_url:
                    image, ct = await self._fetch_native_image(native_url)
                    provider_name = "native"
                    if image and badge_game_title:
                        composed = await maybe_apply_badge_bytes(
                            self._session,
                            self.entry.options,
                            image,
                            ct,
                            badge_game_title,
                        )
                        if composed is not None:
                            image, ct = composed
                            provider_name = "native+badge"
                    self._last_error = None
                    data = CoverData(
                        source_entity_id=self.source_entity_id,
                        track_key=track_key,
                        artist=artist,
                        title=title,
                        album=album,
                        provider=provider_name,
                        artwork_url=native_url,
                        content_type=ct,
                        image=image,
                        last_updated=dt_util.utcnow(),
                        category=self.category,
                    )
                    self._last_cover = data
                    return data

                self._epg_channel_icon = None
                if self.category in {"tv", "auto"}:
                    epg_channel_name = str(state_attrs.get("app_name") or "")
                    epg_sensor = epg_sensor_for_channel(
                        self.entry.options, epg_channel_name
                    )
                    if epg_sensor:
                        try:
                            epg = await HaEpgProvider().get_current_program(
                                self.hass, epg_sensor
                            )
                        except Exception:
                            epg = None
                        _LOGGER.debug(
                            "§5 EPG sensor for channel %r → %s (hit=%s)",
                            epg_channel_name, epg_sensor, bool(epg),
                        )
                    else:
                        epg = None
                    if epg and epg.title:
                        state_attrs["media_title"] = epg.title
                        if epg.sub_title:
                            state_attrs["media_subtitle"] = epg.sub_title
                        if epg.channel_icon:
                            self._epg_channel_icon = epg.channel_icon

                query = build_query(
                    state_attrs=state_attrs,
                    category=self.category,
                    artwork_width=self.artwork_width,
                    artwork_height=self.artwork_height,
                    epg_full_lookup_channels=self._epg_full_lookup_channels,
                )

                # §2.3 prios 2-8 — hierarchy dispatch driven by §7.1 sensors.
                scenario = detect_scenario(
                    state_attrs=state_attrs,
                    tv_input_state=self._sensor_state_str(self._sensor_tv_input),
                    discord_game_state=self._sensor_state_str(self._sensor_discord_game),
                    stash_active_state=self._sensor_state_str(self._sensor_stash_active),
                    channel_name=query.channel_name,
                    options=self.entry.options,
                )
                resolved = await resolve_hierarchy(
                    session=self._session,
                    scenario=scenario,
                    query=query,
                    options=self.entry.options,
                    app_name=query.app_name or "",
                    fallback_category=self.category,
                    badge_game_title=badge_game_title,
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
                fallback = self._fallback_data(track_key=track_key, artist=artist, title=title, album=album)
                if self._epg_channel_icon:
                    fallback.artwork_url = self._epg_channel_icon
                return fallback

            self._last_error = None
            data = CoverData(
                source_entity_id=self.source_entity_id,
                track_key=track_key,
                artist=artist,
                title=query.title or title,
                album=album,
                provider=resolved.provider_name,
                artwork_url=resolved.image_url,
                content_type=resolved.content_type,
                image=resolved.image,
                last_updated=dt_util.utcnow(),
                category=self.category,
            )
            self._last_cover = data
            return data


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries to the current schema version.

    Version history
    ---------------
    1  – initial release; artwork stored as a single ``artwork_size`` value.
    2  – ``artwork_size`` replaced by separate ``artwork_width`` / ``artwork_height``.
    3  – Added category, display_name, ratio, fallback_mode, auto_priority;
         providers/ subpackage replaces old flat provider list.
    4  – Renamed ratio presets to width-suffixed form (``1:1_2000`` etc.);
         added ``create_wrapper`` flag for combined-only entries.
    5  – Removed legacy ``delegate_entity`` key; introduced per-slot
         ``combined_delegate_1..N``; backfilled ``epg_sensor`` default.
    6  – Removed remaining ``delegate_entity`` artefacts; added
         ``channel_icon`` and ``channel_name`` defaults on the wrapper.
    7  – §5 Teil 2: introduce ``epg_sensor_map`` (channel_name → sensor)
         for multi-EPG-source setups; legacy single ``epg_sensor`` is
         retained as a catch-all fallback.
    """
    current_version: int = entry.version
    _LOGGER.debug("Migrating config entry %s from version %s", entry.entry_id, current_version)

    new_data = dict(entry.data)
    new_options = dict(entry.options)

    if current_version < 2:
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

    if current_version < 3:
        # Add new v3 fields with sensible defaults
        new_options.setdefault(CONF_CATEGORY, CATEGORY_AUTO)
        new_options.setdefault(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER)

        # Derive display_name from source entity_id if not present
        src = new_data.get(CONF_SOURCE_ENTITY_ID, "")
        derived_name = src.split(".", 1)[-1].replace("_", " ").title() if src else ""
        new_options.setdefault("display_name", derived_name)
        new_options.setdefault("ratio", RATIO_1_1_2000)
        new_options.setdefault("auto_priority", True)

        # Remove legacy flat provider list (providers are now derived from category)
        new_options.pop("providers", None)
        new_data.pop("providers", None)

        current_version = 3
        _LOGGER.info(
            "Migrated config entry %s: v2 → v3 (added category/display_name/ratio/fallback_mode)",
            entry.entry_id,
        )

    if current_version < 4:
        old_ratio = str(new_options.get("ratio", new_data.get("ratio", "")))
        ratio_map = {"1:1": "1:1_2000", "4:3": "4:3_2000", "16:9": "16:9_2000"}
        if old_ratio in ratio_map:
            new_options["ratio"] = ratio_map[old_ratio]
        new_options.setdefault("ratio", "1:1_2000")
        new_options.setdefault(CONF_CREATE_WRAPPER, True)

        current_version = 4
        _LOGGER.info(
            "Migrated config entry %s: v3.0 → v3.1 (delegate_entity + ratio presets)",
            entry.entry_id,
        )

    if current_version < 5:
        # v3.1.1 cleanup
        new_options.pop("delegate_entity", None)
        new_data.pop("delegate_entity", None)
        ratio_map = {"1:1": "1:1_2000", "4:3": "4:3_1600", "16:9": "16:9_1920", "4:3_2000": "4:3_1600", "16:9_2000": "16:9_1920"}
        ratio = str(new_options.get("ratio", ""))
        if ratio in ratio_map:
            new_options["ratio"] = ratio_map[ratio]
        new_options.setdefault("ratio", "1:1_2000")
        new_options.setdefault(CONF_EPG_SENSOR, None)
        for i in range(1, COMBINED_NUM_SOURCE_SLOTS + 1):
            new_options.setdefault(f"combined_delegate_{i}", None)
        current_version = 5

    if current_version < 6:
        # v3.2: remove delegate_entity legacy key; add channel_icon/channel_name defaults
        new_options.pop("delegate_entity", None)
        new_data.pop("delegate_entity", None)
        new_options.setdefault("channel_icon", "")
        new_options.setdefault("channel_name", "")
        current_version = 6
        _LOGGER.info(
            "Migrated config entry %s: v5 → v6 (remove delegate_entity, add channel fields)",
            entry.entry_id,
        )

    if current_version < 7:
        # §5 Teil 2 — introduce per-channel EPG sensor map. The single
        # CONF_EPG_SENSOR remains as catch-all fallback so existing entries
        # keep behaving identically until the user adds per-channel mappings.
        new_options.setdefault("epg_sensor_map", {})
        current_version = 7
        _LOGGER.info(
            "Migrated config entry %s: v6 → v7 (added per-channel epg_sensor_map)",
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
    create_wrapper = bool(entry.options.get(CONF_CREATE_WRAPPER, entry.data.get(CONF_CREATE_WRAPPER, True)))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if create_wrapper:
        coordinator = CoverCoordinator(hass, entry)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await coordinator.async_start()
        platforms = PLATFORMS
    else:
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = None
        platforms = [Platform.MEDIA_PLAYER]

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    create_wrapper = bool(entry.options.get(CONF_CREATE_WRAPPER, entry.data.get(CONF_CREATE_WRAPPER, True)))
    platforms = PLATFORMS if create_wrapper else [Platform.MEDIA_PLAYER]
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if isinstance(coordinator, CoverCoordinator):
            await coordinator.async_stop()
    return unload_ok
