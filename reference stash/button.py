"""Admin action buttons for Stash Player."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLIENT_KEY, CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME, DOMAIN
from . import StashClient


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: StashClient = hass.data[DOMAIN][entry.entry_id][CLIENT_KEY]
    async_add_entities([
        StashScanLibraryButton(client, entry),
        StashCleanLibraryButton(client, entry),
        StashGenerateMetadataButton(client, entry),
        StashAutoTagButton(client, entry),
        StashIdentifyScenesButton(client, entry),
    ])


class _BaseStashButton(ButtonEntity):
    """Base button with shared device info."""

    _attr_has_entity_name = True

    def __init__(self, client: StashClient, entry: ConfigEntry) -> None:
        self._client = client
        player_name = entry.options.get(CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=player_name,
            manufacturer="Stash",
        )


class StashScanLibraryButton(_BaseStashButton):
    def __init__(self, client, entry):
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_scan_library"
        self._attr_name = "Scan Library"
        self._attr_icon = "mdi:database-search"

    async def async_press(self) -> None:
        await self._client.metadata_scan()


class StashCleanLibraryButton(_BaseStashButton):
    def __init__(self, client, entry):
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_clean_library"
        self._attr_name = "Clean Library"
        self._attr_icon = "mdi:broom"

    async def async_press(self) -> None:
        await self._client.metadata_clean()


class StashGenerateMetadataButton(_BaseStashButton):
    def __init__(self, client, entry):
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_generate_metadata"
        self._attr_name = "Generate Metadata"
        self._attr_icon = "mdi:auto-fix"

    async def async_press(self) -> None:
        await self._client.metadata_generate()


class StashAutoTagButton(_BaseStashButton):
    def __init__(self, client, entry):
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_auto_tag"
        self._attr_name = "Auto Tag"
        self._attr_icon = "mdi:tag-multiple"

    async def async_press(self) -> None:
        await self._client.metadata_auto_tag()


class StashIdentifyScenesButton(_BaseStashButton):
    def __init__(self, client, entry):
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_identify_scenes"
        self._attr_name = "Identify Scenes"
        self._attr_icon = "mdi:magnify-scan"

    async def async_press(self) -> None:
        await self._client.metadata_identify()
