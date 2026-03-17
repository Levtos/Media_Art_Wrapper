from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

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
    PROVIDER_BATTLENET,
    PROVIDER_ITUNES,
    PROVIDER_MUSICBRAINZ,
    PROVIDER_STEAM,
    PROVIDER_TV,
)

# Internal form-field names for the priority slots (UI only, not persisted)
_SLOT_KEYS = ["provider_1", "provider_2", "provider_3", "provider_4", "provider_5"]

# Sentinel value for an empty / disabled slot
_NONE = ""

# Options list shared by all slot selectors.
# The first entry is the "disabled" placeholder; the rest are the real providers.
_PROVIDER_OPTIONS_WITH_NONE = [
    {"value": _NONE, "label": "—"},
    {"value": PROVIDER_ITUNES, "label": "iTunes (Apple Search API)"},
    {"value": PROVIDER_MUSICBRAINZ, "label": "MusicBrainz + Cover Art Archive"},
    {"value": PROVIDER_TV, "label": "TV (iTunes TV + TVMaze + Wikipedia-Senderlogos)"},
    {"value": PROVIDER_BATTLENET, "label": "Battle.net (Overwatch, WoW, Hearthstone, …)"},
    {"value": PROVIDER_STEAM, "label": "Steam (alle Steam-Spiele, z. B. Civilization VII)"},
]

_SLOT_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=_PROVIDER_OPTIONS_WITH_NONE,
        multiple=False,
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


def _providers_to_slots(providers: list[str]) -> dict[str, str]:
    """Convert an ordered providers list to the numbered slot form values."""
    slots: dict[str, str] = {}
    for i, key in enumerate(_SLOT_KEYS):
        slots[key] = providers[i] if i < len(providers) else _NONE
    return slots


def _slots_to_providers(form_data: dict[str, Any]) -> list[str]:
    """Convert numbered slot form values back to an ordered providers list.

    Duplicates and empty slots are silently dropped so callers always receive a
    clean, deduplicated list.
    """
    seen: set[str] = set()
    result: list[str] = []
    for key in _SLOT_KEYS:
        val = str(form_data.get(key, _NONE)).strip()
        if val and val not in seen:
            seen.add(val)
            result.append(val)
    return result or list(DEFAULT_PROVIDERS)


def _slot_schema(
    source_entity_id: str | None,
    slots: dict[str, str],
    artwork_width: int,
    artwork_height: int,
    *,
    include_source: bool,
) -> vol.Schema:
    fields: dict[Any, Any] = {}

    if include_source:
        fields[vol.Required(CONF_SOURCE_ENTITY_ID, default=source_entity_id)] = (
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=False)
            )
        )

    for key in _SLOT_KEYS:
        fields[vol.Optional(key, default=slots.get(key, _NONE))] = _SLOT_SELECTOR

    fields[vol.Optional(CONF_ARTWORK_WIDTH, default=artwork_width)] = vol.Coerce(int)
    fields[vol.Optional(CONF_ARTWORK_HEIGHT, default=artwork_height)] = vol.Coerce(int)

    return vol.Schema(fields)


async def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state and "friendly_name" in state.attributes:
        return str(state.attributes["friendly_name"])
    return entity_id


class MediaCoverArtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            source_entity_id = user_input[CONF_SOURCE_ENTITY_ID]
            await self.async_set_unique_id(source_entity_id)
            self._abort_if_unique_id_configured()

            title = await _friendly_name(self.hass, source_entity_id)

            data = {
                CONF_SOURCE_ENTITY_ID: source_entity_id,
                CONF_PROVIDERS: _slots_to_providers(user_input),
                CONF_ARTWORK_WIDTH: int(user_input.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH)),
                CONF_ARTWORK_HEIGHT: int(user_input.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT)),
            }
            return self.async_create_entry(title=title, data=data)

        schema = _slot_schema(
            source_entity_id=None,
            slots=_providers_to_slots(list(DEFAULT_PROVIDERS)),
            artwork_width=DEFAULT_ARTWORK_WIDTH,
            artwork_height=DEFAULT_ARTWORK_HEIGHT,
            include_source=True,
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return MediaCoverArtOptionsFlow(config_entry)


class MediaCoverArtOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {
                CONF_PROVIDERS: _slots_to_providers(user_input),
                CONF_ARTWORK_WIDTH: int(user_input.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH)),
                CONF_ARTWORK_HEIGHT: int(user_input.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT)),
            }
            return self.async_create_entry(title="", data=data)

        current_providers: list[str] = self.config_entry.options.get(
            CONF_PROVIDERS,
            self.config_entry.data.get(CONF_PROVIDERS, list(DEFAULT_PROVIDERS)),
        )
        artwork_width: int = self.config_entry.options.get(
            CONF_ARTWORK_WIDTH,
            self.config_entry.data.get(
                CONF_ARTWORK_WIDTH,
                self.config_entry.data.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_WIDTH),
            ),
        )
        artwork_height: int = self.config_entry.options.get(
            CONF_ARTWORK_HEIGHT,
            self.config_entry.data.get(
                CONF_ARTWORK_HEIGHT,
                self.config_entry.data.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_HEIGHT),
            ),
        )

        schema = _slot_schema(
            source_entity_id=None,
            slots=_providers_to_slots(current_providers),
            artwork_width=artwork_width,
            artwork_height=artwork_height,
            include_source=False,
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
