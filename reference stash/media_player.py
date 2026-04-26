"""Media player entity for Stash Player.

This entity is intentionally display-only: it shows the title, cover art,
studio and duration of whatever Stash is currently streaming in this slot.
Playback controls are deliberately not exposed, because Home Assistant cannot
actually drive the Stash web player — every "control" would be a lie.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature, MediaType
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_IDLE, STATE_PLAYING
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CLIENT_KEY,
    CONF_PLAYER_NAME,
    COORDINATOR_KEY,
    DEFAULT_PLAYER_NAME,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[COORDINATOR_KEY]
    client = data[CLIENT_KEY]
    async_add_entities([
        StashMediaPlayer(entry, coordinator, client, 0),
        StashMediaPlayer(entry, coordinator, client, 1),
    ])


class StashMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """One playback slot. Displays the currently-streaming scene, or idle."""

    _attr_media_content_type = MediaType.VIDEO
    # Display-only: no controls. Home Assistant happily renders cover + title
    # + duration on a media-control card without any feature flags.
    _attr_supported_features = MediaPlayerEntityFeature(0)

    def __init__(self, entry: ConfigEntry, coordinator, client, index: int) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._client = client
        self._index = index
        self._cover_entity_id: str | None = None
        self._last_scene_id: str | None = None
        self._position_updated_at: datetime | None = None

        player_name = entry.options.get(CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME)
        slot = index + 1
        self._attr_unique_id = f"{entry.entry_id}_player_{slot}"
        self._default_name = f"{player_name} {slot}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=player_name,
            manufacturer="Stash",
        )

    # ── helpers ──────────────────────────────────────────────────────────
    @property
    def _scene(self) -> dict[str, Any]:
        scenes = (self.coordinator.data or {}).get("scenes", [])
        return scenes[self._index] if self._index < len(scenes) else {}

    @property
    def _is_streaming(self) -> bool:
        """True only when this slot holds a currently-streaming scene."""
        scene = self._scene
        if not scene:
            return False
        if scene.get("_is_streaming"):
            return True
        sid = scene.get("id")
        active = (self.coordinator.data or {}).get("active_scene_ids", set())
        return bool(sid) and str(sid) in active

    def _resolve_cover_entity(self) -> str | None:
        if self._cover_entity_id:
            return self._cover_entity_id
        if self.hass is None:
            return None
        slot = self._index + 1
        unique_id = f"{self._entry.entry_id}_cover_{slot}"
        registry = er.async_get(self.hass)
        self._cover_entity_id = registry.async_get_entity_id(
            "image", DOMAIN, unique_id
        )
        return self._cover_entity_id

    # ── identity ─────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        # Keep the slot name stable; title is surfaced via media_title.
        # This avoids renaming the entity in the registry every time a new
        # scene starts playing.
        return self._default_name

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    # ── state & media metadata (all gated on _is_streaming) ──────────────
    @property
    def state(self) -> str:
        return STATE_PLAYING if self._is_streaming else STATE_IDLE

    @property
    def media_title(self) -> str | None:
        if not self._is_streaming:
            return None
        return self._scene.get("title") or None

    @property
    def media_artist(self) -> str | None:
        if not self._is_streaming:
            return None
        performers = self._scene.get("performers") or []
        names = [p.get("name") for p in performers if p.get("name")]
        return ", ".join(names) or None

    @property
    def media_album_name(self) -> str | None:
        if not self._is_streaming:
            return None
        studio = self._scene.get("studio") or {}
        return studio.get("name") or None

    @property
    def media_content_id(self) -> str | None:
        if not self._is_streaming:
            return None
        sid = self._scene.get("id")
        return str(sid) if sid else None

    @property
    def media_duration(self) -> int | None:
        if not self._is_streaming:
            return None
        files = self._scene.get("files") or []
        if not files:
            return None
        duration = files[0].get("duration")
        return int(duration) if duration else None

    @property
    def media_position(self) -> int | None:
        if not self._is_streaming:
            return None
        resume = self._scene.get("resume_time") or 0
        try:
            return int(float(resume))
        except (TypeError, ValueError):
            return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        if not self._is_streaming:
            return None
        return self._position_updated_at

    @property
    def media_image_url(self) -> str | None:
        """Fallback image URL used when the cover entity cannot be resolved."""
        if not self._is_streaming:
            return None
        return (self._scene.get("paths") or {}).get("screenshot")

    @property
    def entity_picture(self) -> str | None:
        if not self._is_streaming:
            return None
        cover = self._resolve_cover_entity()
        if cover and self.hass is not None:
            cover_state = self.hass.states.get(cover)
            if cover_state is not None:
                pic = cover_state.attributes.get("entity_picture")
                if pic:
                    # The image entity's entity_picture already carries the
                    # access-token query string HA uses to bust the browser
                    # cache when the cover changes.
                    return pic
        if cover:
            return f"/api/image_proxy/{cover}"
        # Last resort: serve Stash's own screenshot URL directly so the card
        # still shows something even if the image entity hasn't registered.
        return self.media_image_url

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {
            "active_stream_count": data.get("active_stream_count", 0),
            "is_streaming": self._is_streaming,
        }
        scene = self._scene
        if not scene:
            return attrs

        tags = scene.get("tags") or []
        files = scene.get("files") or []
        studio = scene.get("studio") or {}
        scene_id = scene.get("id")
        rating100 = scene.get("rating100")

        resolution = None
        if files:
            width = files[0].get("width")
            height = files[0].get("height")
            if width and height:
                resolution = f"{width}x{height}"

        attrs.update({
            "stash_scene_id": scene_id,
            "stash_url": (
                f"{self._client.stash_url}/scenes/{scene_id}" if scene_id else None
            ),
            "stash_rating": (rating100 / 20) if rating100 is not None else None,
            "stash_tags": [t.get("name") for t in tags if t.get("name")],
            "stash_studio": studio.get("name") if studio else None,
            "stash_resolution": resolution,
            "stash_play_count": scene.get("play_count"),
            "stash_last_played_at": scene.get("last_played_at"),
        })
        return attrs

    # ── lifecycle ────────────────────────────────────────────────────────
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._resolve_cover_entity()

    def _handle_coordinator_update(self) -> None:
        scene_id = self._scene.get("id") if self._scene else None
        # Only bump position_updated_at when the scene actually changes or
        # when the slot transitions into/out of streaming. Otherwise HA's
        # media card keeps redrawing the progress bar on every poll.
        if scene_id != self._last_scene_id:
            self._last_scene_id = scene_id
            self._position_updated_at = dt_util.utcnow() if self._is_streaming else None
        elif self._is_streaming and self._position_updated_at is None:
            self._position_updated_at = dt_util.utcnow()
        elif not self._is_streaming:
            self._position_updated_at = None
        super()._handle_coordinator_update()
