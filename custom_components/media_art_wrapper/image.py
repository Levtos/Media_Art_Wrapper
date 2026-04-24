from __future__ import annotations

from typing import Any


from homeassistant.components.image import ImageEntity
from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import CoverCoordinator, CoverData
from .const import (
    CONF_COMBINED_AUDIO_SOURCES,
    CONF_COMBINED_NAME,
    CONF_COMBINED_SOURCES,
    CONF_CREATE_COMBINED,
    CONF_CREATE_WRAPPER,
    CONF_FALLBACK_CUSTOM_URL,
    CONF_FALLBACK_MODE,
    DOMAIN,
    FALLBACK_CUSTOM_URL_MODE,
    FALLBACK_SERVICE_LOGO,
)
from .helpers import (
    FALLBACK_IMAGE,
    active_entity_id as _active_entity_id_helper,
    service_logo,
    source_name,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    create_wrapper = bool(entry.options.get(CONF_CREATE_WRAPPER, entry.data.get(CONF_CREATE_WRAPPER, True)))
    entities: list[ImageEntity] = []
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if create_wrapper and isinstance(coordinator, CoverCoordinator):
        entities.append(MediaCoverArtImage(coordinator, entry))

    opts = entry.options
    data = entry.data
    create_combined = bool(opts.get(CONF_CREATE_COMBINED, data.get(CONF_CREATE_COMBINED, False)))
    combined_name = str(opts.get(CONF_COMBINED_NAME, data.get(CONF_COMBINED_NAME, ""))).strip()
    combined_sources: list[str] = list(opts.get(CONF_COMBINED_SOURCES, data.get(CONF_COMBINED_SOURCES, [])))

    if create_combined and combined_name and combined_sources:
        entities.append(CombinedCoverImage(hass, entry, combined_sources, combined_name))

    async_add_entities(entities, update_before_add=False)


class MediaCoverArtImage(CoordinatorEntity[CoverCoordinator], ImageEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:disc"

    def __init__(self, coordinator: CoverCoordinator, entry: ConfigEntry) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        try:
            ImageEntity.__init__(self, coordinator.hass)
        except TypeError:
            try:
                ImageEntity.__init__(self, hass=coordinator.hass)
            except TypeError:
                ImageEntity.__init__(self)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cover"
        self._attr_name = f"Cover {source_name(coordinator.source_entity_id)}"
        self._attr_content_type = "image/jpeg"

    @property
    def image_last_updated(self):
        data: CoverData | None = self.coordinator.data
        return data.last_updated if data else None

    async def async_image(self) -> bytes | None:
        data: CoverData | None = self.coordinator.data
        if data and data.image:
            self._attr_content_type = data.content_type or "image/jpeg"
            return data.image

        # No artwork — apply the configured fallback mode
        opts = self._entry.options
        fallback_mode = opts.get(CONF_FALLBACK_MODE, "placeholder")

        if fallback_mode == FALLBACK_SERVICE_LOGO:
            # Try app_name from the source entity state
            state = self.hass.states.get(self.coordinator.source_entity_id)
            app_name = state.attributes.get("app_name", "") if state else ""
            logo = service_logo(app_name) if app_name else None
            if logo:
                self._attr_content_type = "image/png"
                return logo

        if fallback_mode == FALLBACK_CUSTOM_URL_MODE:
            custom_url = str(opts.get(CONF_FALLBACK_CUSTOM_URL, "")).strip()
            if custom_url.startswith("http"):
                try:
                    session = aiohttp_client.async_get_clientsession(self.hass)
                    async with session.get(custom_url, timeout=10) as resp:
                        if resp.status == 200:
                            ct = resp.headers.get("Content-Type", "image/jpeg")
                            self._attr_content_type = ct.split(";")[0].strip()
                            img = await resp.read()
                            if img:
                                return img
                except Exception:
                    pass

        self._attr_content_type = "image/png"
        return FALLBACK_IMAGE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data: CoverData | None = self.coordinator.data
        base = {
            "source_entity_id": self.coordinator.source_entity_id,
        }
        if not data:
            return base

        return {
            **base,
            "track_key": data.track_key,
            "artist": data.artist,
            "title": data.title,
            "album": data.album,
            "provider": data.provider,
            "artwork_url": data.artwork_url,
            "artwork_width": self.coordinator.artwork_width,
            "artwork_height": self.coordinator.artwork_height,
            "artwork_size": self.coordinator.artwork_size,
        }


# ---------------------------------------------------------------------------
# Combined Cover Image
# ---------------------------------------------------------------------------

class CombinedCoverImage(ImageEntity):
    """Cover-art image entity for the CombinedMediaPlayer.

    Uses the same tier-based priority logic as CombinedMediaPlayer to select
    the active display source, then retrieves image bytes via:
    1. MAW CoverCoordinator cache for that source (no HTTP overhead)
    2. The source entity's async_get_media_image() method
    3. Direct HTTP fetch of entity_picture if it is an absolute URL
    4. Last-known-good bytes (prevents blank cover during transitions)
    5. FALLBACK_IMAGE placeholder
    """

    _attr_has_entity_name = False
    _attr_icon = "mdi:disc"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        sources: list[str],
        name: str,
    ) -> None:
        try:
            ImageEntity.__init__(self, hass)
        except TypeError:
            try:
                ImageEntity.__init__(self, hass=hass)
            except TypeError:
                ImageEntity.__init__(self)
        self.hass = hass
        self._entry = entry
        self._sources = list(sources)
        self._attr_name = f"{name}_cover"
        self._attr_unique_id = f"{entry.entry_id}_combined_cover"
        self._attr_content_type = "image/jpeg"
        self._attr_image_last_updated = dt_util.utcnow()
        self._last_fingerprint: str | None = None
        self._last_image: bytes | None = None
        self._unsub: Any | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub = async_track_state_change_event(
            self.hass, self._sources, self._handle_state_change
        )
        self._refresh_fingerprint()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_state_change(self, event: Any) -> None:
        self._refresh_fingerprint()
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Fingerprint tracking (drives image_last_updated)
    # ------------------------------------------------------------------

    def _active_entity_id(self) -> str | None:
        return _active_entity_id_helper(self.hass, self._sources)

    def _refresh_fingerprint(self) -> None:
        """Bump image_last_updated when the active source's cover art changes."""
        active_id = self._active_entity_id()
        if active_id is None:
            return
        state = self.hass.states.get(active_id)
        if state is None:
            return
        ep = state.attributes.get("entity_picture", "")
        fingerprint = f"{active_id}:{ep}"
        if fingerprint != self._last_fingerprint:
            self._last_fingerprint = fingerprint
            self._attr_image_last_updated = dt_util.utcnow()

    # ------------------------------------------------------------------
    # Image retrieval
    # ------------------------------------------------------------------

    async def async_image(self) -> bytes | None:
        active_id = self._active_entity_id()
        if active_id is None:
            return self._last_image or FALLBACK_IMAGE

        # Strategy 1: Reuse MAW CoverCoordinator image bytes directly
        for coordinator in self.hass.data.get(DOMAIN, {}).values():
            if (
                isinstance(coordinator, CoverCoordinator)
                and coordinator.source_entity_id == active_id
            ):
                data: CoverData | None = coordinator.data
                if data and data.image:
                    self._attr_content_type = data.content_type or "image/jpeg"
                    self._last_image = data.image
                    return data.image
                break  # coordinator found but has no image yet – try other strategies

        # Strategy 2: Delegate to source media player entity's async_get_media_image()
        entity_comp = self.hass.data.get("entity_components", {}).get(MP_DOMAIN)
        if entity_comp is not None:
            source_entity = entity_comp.get_entity(active_id)
            if source_entity is not None:
                try:
                    img, ct = await source_entity.async_get_media_image()
                    if img:
                        self._attr_content_type = ct or "image/jpeg"
                        self._last_image = img
                        return img
                except Exception:
                    pass

        # Strategy 3: Direct HTTP fetch for absolute entity_picture URLs
        state = self.hass.states.get(active_id)
        if state is not None:
            ep: str = state.attributes.get("entity_picture", "")
            if ep.startswith("http"):
                img = await self._fetch_url(ep)
                if img:
                    self._last_image = img
                    return img

        # Strategy 4: Last-known-good cover (no blank during transitions)
        return self._last_image or FALLBACK_IMAGE

    async def _fetch_url(self, url: str) -> bytes | None:
        """Fetch image bytes from an absolute HTTP(S) URL."""
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.get(url, timeout=aiohttp_client.aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    ct = resp.headers.get("Content-Type", "image/jpeg")
                    self._attr_content_type = ct.split(";")[0].strip()
                    return await resp.read()
        except Exception:
            pass
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "active_source": self._active_entity_id(),
            "sources": self._sources,
        }
