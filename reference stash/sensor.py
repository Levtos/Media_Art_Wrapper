"""Library statistics sensors for Stash Player."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PLAYER_NAME,
    COORDINATOR_KEY,
    DEFAULT_PLAYER_NAME,
    DOMAIN,
    LIBRARY_COORDINATOR_KEY,
)
from . import StashLibraryCoordinator, StashPlaybackCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up library + playback sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    library: StashLibraryCoordinator = data[LIBRARY_COORDINATOR_KEY]
    playback: StashPlaybackCoordinator = data[COORDINATOR_KEY]
    async_add_entities([
        StashScenesSensor(library, entry),
        StashMoviesSensor(library, entry),
        StashPerformersSensor(library, entry),
        StashStudiosSensor(library, entry),
        StashTagsSensor(library, entry),
        StashImagesSensor(library, entry),
        StashGalleriesSensor(library, entry),
        StashMarkersSensor(library, entry),
        StashVersionSensor(library, entry),
        StashActiveStreamCountSensor(playback, entry),
        StashLastPlayedTitleSensor(playback, entry),
        StashLastPlayedAtSensor(playback, entry),
    ])


class _BaseStashSensor(CoordinatorEntity, SensorEntity):
    """Base class for Stash library sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: StashLibraryCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        player_name = entry.options.get(CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=player_name,
            manufacturer="Stash",
        )


class StashScenesSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_scenes_count"
        self._attr_name = "Scenes"
        self._attr_icon = "mdi:filmstrip"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("scenes")


class StashMoviesSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_movies_count"
        self._attr_name = "Movies"
        self._attr_icon = "mdi:movie-open-outline"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("movies")


class StashPerformersSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_performers_count"
        self._attr_name = "Performers"
        self._attr_icon = "mdi:account-multiple"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("performers")


class StashStudiosSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_studios_count"
        self._attr_name = "Studios"
        self._attr_icon = "mdi:office-building"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("studios")


class StashTagsSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_tags_count"
        self._attr_name = "Tags"
        self._attr_icon = "mdi:tag-multiple"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("tags")


class StashImagesSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_images_count"
        self._attr_name = "Images"
        self._attr_icon = "mdi:image-multiple-outline"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("images")


class StashGalleriesSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_galleries_count"
        self._attr_name = "Galleries"
        self._attr_icon = "mdi:image-album"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("galleries")


class StashMarkersSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_markers_count"
        self._attr_name = "Markers"
        self._attr_icon = "mdi:bookmark-multiple-outline"
        self._attr_native_unit_of_measurement = "items"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("markers")


class StashVersionSensor(_BaseStashSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_version"
        self._attr_name = "Version"
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("version")


# ── Playback-coordinator sensors ─────────────────────────────────────────────

class _BasePlaybackSensor(CoordinatorEntity, SensorEntity):
    """Base class for sensors that read from the playback coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: StashPlaybackCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        player_name = entry.options.get(CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=player_name,
            manufacturer="Stash",
        )


class StashActiveStreamCountSensor(_BasePlaybackSensor):
    """Number of streams Stash is currently serving."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_active_streams"
        self._attr_name = "Active Streams"
        self._attr_icon = "mdi:play-network"
        self._attr_native_unit_of_measurement = "streams"

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("active_stream_count", 0) or 0)


class StashLastPlayedTitleSensor(_BasePlaybackSensor):
    """Title of the most recently played scene (regardless of current state)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_played_title"
        self._attr_name = "Last Played"
        self._attr_icon = "mdi:history"

    @property
    def native_value(self) -> str | None:
        lp = (self.coordinator.data or {}).get("last_played") or {}
        return lp.get("title") or None

    @property
    def extra_state_attributes(self) -> dict:
        lp = (self.coordinator.data or {}).get("last_played") or {}
        return {
            "stash_scene_id": lp.get("id"),
            "studio": lp.get("studio"),
            "performers": lp.get("performers") or [],
            "last_played_at": lp.get("last_played_at"),
            "screenshot": lp.get("screenshot"),
        }


class StashLastPlayedAtSensor(_BasePlaybackSensor):
    """Timestamp of the most recent playback."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_played_at"
        self._attr_name = "Last Played At"
        self._attr_icon = "mdi:clock-outline"

    @property
    def native_value(self) -> datetime | None:
        lp = (self.coordinator.data or {}).get("last_played") or {}
        raw = lp.get("last_played_at")
        if not raw:
            return None
        parsed = dt_util.parse_datetime(raw)
        if parsed is None:
            return None
        # Home Assistant requires timezone-aware datetimes for TIMESTAMP
        # device class. Stash already returns ISO-8601 with offset, but guard
        # against a naive value just in case.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        return parsed
