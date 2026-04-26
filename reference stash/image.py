"""Image entity for Stash scene cover art."""

from __future__ import annotations

import io
import logging
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_API_KEY,
    CONF_NSFW_MODE,
    CONF_PLAYER_NAME,
    COORDINATOR_KEY,
    DEFAULT_NSFW_MODE,
    DEFAULT_PLAYER_NAME,
    DOMAIN,
    NSFW_BLUR,
    NSFW_HIDDEN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]
    async_add_entities([
        StashCoverImage(entry, coordinator, 0, hass),
        StashCoverImage(entry, coordinator, 1, hass),
    ])


class StashCoverImage(CoordinatorEntity, ImageEntity):
    """Screenshot image for a Stash playback slot."""

    def __init__(self, entry: ConfigEntry, coordinator, index: int, hass: HomeAssistant) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._entry = entry
        self._index = index
        self._last_screenshot_url: str | None = None
        self._last_scene_id: str | None = None
        self._last_streaming: bool = False
        player_name = entry.options.get(CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME)
        slot = index + 1
        self._attr_unique_id = f"{entry.entry_id}_cover_{slot}"
        self._attr_name = f"{player_name} Cover {slot}"
        self._attr_content_type = "image/jpeg"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=player_name,
            manufacturer="Stash",
        )
        self._attr_image_last_updated: datetime | None = None

    @property
    def _scene(self) -> dict:
        scenes = (self.coordinator.data or {}).get("scenes", [])
        return scenes[self._index] if self._index < len(scenes) else {}

    @property
    def _is_streaming(self) -> bool:
        scene = self._scene
        if not scene:
            return False
        if scene.get("_is_streaming"):
            return True
        sid = scene.get("id")
        active = (self.coordinator.data or {}).get("active_scene_ids", set())
        return bool(sid) and str(sid) in active

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    def _handle_coordinator_update(self) -> None:
        scene_id = self._scene.get("id") if self._scene else None
        is_streaming_now = self._is_streaming
        # Bump the timestamp whenever the scene or streaming-state changes.
        # image_last_updated drives HA's cache-busting token in entity_picture
        # URLs, so the browser only refetches the cover on real transitions.
        if (
            scene_id != self._last_scene_id
            or is_streaming_now != self._last_streaming
        ):
            self._last_scene_id = scene_id
            self._last_streaming = is_streaming_now
            self._attr_image_last_updated = (
                dt_util.utcnow() if is_streaming_now else None
            )
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        if not self._is_streaming:
            _LOGGER.debug("stash cover %s: skip (not streaming)", self._attr_unique_id)
            return None

        scene = self._scene
        screenshot_url = (scene.get("paths") or {}).get("screenshot")
        if not screenshot_url:
            _LOGGER.debug(
                "stash cover %s: no screenshot URL in scene", self._attr_unique_id
            )
            return None

        nsfw_mode = self._entry.options.get(CONF_NSFW_MODE, DEFAULT_NSFW_MODE)
        if nsfw_mode == NSFW_HIDDEN:
            return None

        session = aiohttp_client.async_get_clientsession(self.hass)
        api_key = self._entry.data.get(CONF_API_KEY, "")
        headers = {"ApiKey": api_key} if api_key else {}
        try:
            async with session.get(screenshot_url, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.read()
        except Exception as err:
            _LOGGER.warning(
                "Stash cover fetch failed for %s: %s", screenshot_url, err
            )
            return None

        self._last_screenshot_url = screenshot_url
        _LOGGER.debug(
            "stash cover %s: fetched %d bytes from %s (nsfw=%s)",
            self._attr_unique_id, len(data), screenshot_url, nsfw_mode,
        )

        if nsfw_mode == NSFW_BLUR:
            try:
                return await self._blur_image(data)
            except Exception:  # noqa: BLE001
                return data
        return data

    async def _blur_image(self, data: bytes) -> bytes:
        try:
            from PIL import Image, ImageFilter
            img = Image.open(io.BytesIO(data))
            blurred = img.filter(ImageFilter.GaussianBlur(radius=30))
            out = io.BytesIO()
            if img.mode in ("RGBA", "P"):
                blurred = blurred.convert("RGB")
            blurred.save(out, format="JPEG", quality=85)
            return out.getvalue()
        except ImportError:
            return data
        except Exception:  # noqa: BLE001
            return data
