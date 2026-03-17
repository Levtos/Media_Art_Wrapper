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

# ---------------------------------------------------------------------------
# Provider priority slots
# ---------------------------------------------------------------------------

# Internal form-field names for the priority slots (UI only, not persisted)
_SLOT_KEYS = ["provider_1", "provider_2", "provider_3", "provider_4", "provider_5"]

# Sentinel value for an empty / disabled slot
_NONE = ""

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

# ---------------------------------------------------------------------------
# Artwork size presets
# ---------------------------------------------------------------------------

# UI-only field key for the preset selector (not persisted)
_CONF_ARTWORK_PRESET = "artwork_preset"
_PRESET_CUSTOM = "custom"

# Ordered (width, height) for each preset key
_ARTWORK_PRESETS: dict[str, tuple[int, int]] = {
    "300x300": (300, 300),
    "600x600": (600, 600),
    "800x800": (800, 800),
    "1000x1000": (1000, 1000),
    "600x900": (600, 900),
    "1200x1800": (1200, 1800),
}

_PRESET_OPTIONS = [
    {"value": "300x300",    "label": "300 × 300 px"},
    {"value": "600x600",    "label": "600 × 600 px (Standard)"},
    {"value": "800x800",    "label": "800 × 800 px"},
    {"value": "1000x1000",  "label": "1000 × 1000 px"},
    {"value": "600x900",    "label": "600 × 900 px (Hochformat, z. B. Steam)"},
    {"value": "1200x1800",  "label": "1200 × 1800 px (Hochformat HD, Steam 2×)"},
    {"value": _PRESET_CUSTOM, "label": "Benutzerdefiniert …"},
]

_PRESET_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=_PRESET_OPTIONS,
        multiple=False,
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


def _detect_preset(width: int, height: int) -> str:
    """Return the preset key matching (width, height), or _PRESET_CUSTOM."""
    for key, dims in _ARTWORK_PRESETS.items():
        if dims == (width, height):
            return key
    return _PRESET_CUSTOM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _providers_to_slots(providers: list[str]) -> dict[str, str]:
    """Convert an ordered providers list to the numbered slot form values."""
    slots: dict[str, str] = {}
    for i, key in enumerate(_SLOT_KEYS):
        slots[key] = providers[i] if i < len(providers) else _NONE
    return slots


def _slots_to_providers(form_data: dict[str, Any]) -> list[str]:
    """Convert numbered slot form values back to an ordered providers list.

    Duplicates and empty slots are silently dropped.
    """
    seen: set[str] = set()
    result: list[str] = []
    for key in _SLOT_KEYS:
        val = str(form_data.get(key, _NONE)).strip()
        if val and val not in seen:
            seen.add(val)
            result.append(val)
    return result or list(DEFAULT_PROVIDERS)


def _resolve_dimensions(form_data: dict[str, Any]) -> tuple[int, int]:
    """Return (width, height) from form data, honouring the preset selector."""
    preset = str(form_data.get(_CONF_ARTWORK_PRESET, _PRESET_CUSTOM))
    if preset in _ARTWORK_PRESETS:
        return _ARTWORK_PRESETS[preset]
    width = int(form_data.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH))
    height = int(form_data.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT))
    return width, height


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

    fields[vol.Optional(_CONF_ARTWORK_PRESET, default=_detect_preset(artwork_width, artwork_height))] = (
        _PRESET_SELECTOR
    )
    fields[vol.Optional(CONF_ARTWORK_WIDTH, default=artwork_width)] = vol.All(
        vol.Coerce(int), vol.Range(min=1)
    )
    fields[vol.Optional(CONF_ARTWORK_HEIGHT, default=artwork_height)] = vol.All(
        vol.Coerce(int), vol.Range(min=1)
    )

    return vol.Schema(fields)


async def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state and "friendly_name" in state.attributes:
        return str(state.attributes["friendly_name"])
    return entity_id


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------

class MediaCoverArtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            source_entity_id = user_input[CONF_SOURCE_ENTITY_ID]
            await self.async_set_unique_id(source_entity_id)
            self._abort_if_unique_id_configured()

            title = await _friendly_name(self.hass, source_entity_id)
            artwork_width, artwork_height = _resolve_dimensions(user_input)

            data = {
                CONF_SOURCE_ENTITY_ID: source_entity_id,
                CONF_PROVIDERS: _slots_to_providers(user_input),
                CONF_ARTWORK_WIDTH: artwork_width,
                CONF_ARTWORK_HEIGHT: artwork_height,
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
            artwork_width, artwork_height = _resolve_dimensions(user_input)
            data = {
                CONF_PROVIDERS: _slots_to_providers(user_input),
                CONF_ARTWORK_WIDTH: artwork_width,
                CONF_ARTWORK_HEIGHT: artwork_height,
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
