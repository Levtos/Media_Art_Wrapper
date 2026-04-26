"""Binary sensors for Stash Player."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_PLAYER_NAME,
    COORDINATOR_KEY,
    DEFAULT_PLAYER_NAME,
    DOMAIN,
    LIBRARY_COORDINATOR_KEY,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Stash binary sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    library = data[LIBRARY_COORDINATOR_KEY]
    playback = data[COORDINATOR_KEY]
    async_add_entities([
        StashOnlineBinarySensor(library, entry),
        StashStreamActiveBinarySensor(playback, entry),
    ])


class _BaseStashBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        player_name = entry.options.get(CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=player_name,
            manufacturer="Stash",
        )


class StashOnlineBinarySensor(_BaseStashBinarySensor):
    """Binary sensor showing whether Stash is reachable."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_online"
        self._attr_name = "Online"
        self._attr_icon = "mdi:lan-connect"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.last_update_success)


class StashStreamActiveBinarySensor(_BaseStashBinarySensor):
    """Binary sensor that is on while Stash has at least one active stream."""

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_stream_active"
        self._attr_name = "Stream Active"
        self._attr_icon = "mdi:play-circle"

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("is_streaming"))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "active_stream_count": data.get("active_stream_count", 0),
            "active_scene_ids": sorted(data.get("active_scene_ids") or []),
        }
