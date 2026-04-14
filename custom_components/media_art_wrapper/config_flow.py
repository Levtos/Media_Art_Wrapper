"""Config flow — 3-step setup for Media Art Wrapper v3."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CATEGORIES,
    CATEGORY_AUTO,
    CATEGORY_GAMING,
    CATEGORY_MUSIC,
    CATEGORY_STREAMING,
    CATEGORY_TV,
    COMBINED_NUM_SOURCE_SLOTS,
    CONF_AUTO_PRIORITY,
    CONF_ARTWORK_HEIGHT,
    CONF_ARTWORK_WIDTH,
    CONF_CATEGORY,
    CONF_COMBINED_AUDIO_SOURCES,
    CONF_COMBINED_NAME,
    CONF_COMBINED_SOURCES,
    CONF_CREATE_COMBINED,
    CONF_DISPLAY_NAME,
    CONF_FALLBACK_CUSTOM_URL,
    CONF_FALLBACK_MODE,
    CONF_FANART_API_KEY,
    CONF_IGDB_CLIENT_ID,
    CONF_IGDB_CLIENT_SECRET,
    CONF_RATIO,
    CONF_SOURCE_ENTITY_ID,
    CONF_STEAMGRIDDB_API_KEY,
    CONF_TMDB_API_KEY,
    CONF_XMLTV_URL,
    DEFAULT_ARTWORK_HEIGHT,
    DEFAULT_ARTWORK_WIDTH,
    DOMAIN,
    FALLBACK_CUSTOM_URL_MODE,
    FALLBACK_PLACEHOLDER,
    FALLBACK_SERVICE_LOGO,
    RATIO_1_1,
    RATIO_4_3,
    RATIO_16_9,
    RATIO_CUSTOM,
    RATIO_DIMENSIONS,
)

# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

_CATEGORY_OPTIONS = [
    {"value": CATEGORY_MUSIC,     "label": "Music"},
    {"value": CATEGORY_STREAMING, "label": "Streaming (films & series)"},
    {"value": CATEGORY_GAMING,    "label": "Gaming"},
    {"value": CATEGORY_TV,        "label": "TV / Live TV"},
    {"value": CATEGORY_AUTO,      "label": "Auto (try all providers)"},
]

_RATIO_OPTIONS = [
    {"value": RATIO_1_1,     "label": "1:1  — 600 × 600 px (music / gaming)"},
    {"value": RATIO_4_3,     "label": "4:3  — 800 × 600 px"},
    {"value": RATIO_16_9,    "label": "16:9 — 960 × 540 px (landscape TV)"},
    {"value": RATIO_CUSTOM,  "label": "Custom …"},
]

_FALLBACK_OPTIONS = [
    {"value": FALLBACK_PLACEHOLDER,    "label": "Placeholder icon"},
    {"value": FALLBACK_SERVICE_LOGO,   "label": "Service logo (auto-detected)"},
    {"value": FALLBACK_CUSTOM_URL_MODE, "label": "Custom URL …"},
]

_COMBINED_SLOT_KEYS = [f"combined_source_{i}" for i in range(1, COMBINED_NUM_SOURCE_SLOTS + 1)]

_ENTITY_SEL = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player", multiple=False)
)
_MULTI_ENTITY_SEL = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player", multiple=True)
)


def _ratio_to_dims(ratio: str, width: int, height: int) -> tuple[int, int]:
    """Return (width, height) from a ratio preset or custom values."""
    if ratio in RATIO_DIMENSIONS:
        return RATIO_DIMENSIONS[ratio]
    return (max(1, width), max(1, height))


def _dims_to_ratio(width: int, height: int) -> str:
    """Return the ratio key that matches (width, height), or RATIO_CUSTOM."""
    for key, dims in RATIO_DIMENSIONS.items():
        if dims == (width, height):
            return key
    return RATIO_CUSTOM


def _combined_slots_to_sources(form_data: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for key in _COMBINED_SLOT_KEYS:
        val = form_data.get(key)
        if val and isinstance(val, str) and val not in seen:
            seen.add(val)
            result.append(val)
    return result


def _combined_sources_to_slots(sources: list[str]) -> dict[str, str]:
    return {
        _COMBINED_SLOT_KEYS[i]: sources[i]
        for i in range(min(len(sources), COMBINED_NUM_SOURCE_SLOTS))
    }


async def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state and "friendly_name" in state.attributes:
        return str(state.attributes["friendly_name"])
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


# ---------------------------------------------------------------------------
# Schema builders
# ---------------------------------------------------------------------------

def _step1_schema(
    source_entity_id: str | None = None,
    display_name: str = "",
    category: str = CATEGORY_AUTO,
    *,
    include_source: bool = True,
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_source:
        kw: dict[str, Any] = {"default": source_entity_id} if source_entity_id else {}
        fields[vol.Required(CONF_SOURCE_ENTITY_ID, **kw)] = _ENTITY_SEL
    fields[vol.Optional(CONF_DISPLAY_NAME, default=display_name)] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    )
    fields[vol.Required(CONF_CATEGORY, default=category)] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=_CATEGORY_OPTIONS,
            multiple=False,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )
    return vol.Schema(fields)


def _step2_schema(
    category: str,
    opts: dict[str, Any],
) -> vol.Schema:
    """Build the artwork + API-keys step schema for the given category."""
    ratio = opts.get(CONF_RATIO, RATIO_1_1)
    width = int(opts.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH))
    height = int(opts.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT))
    fallback_mode = opts.get(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER)
    fallback_url = opts.get(CONF_FALLBACK_CUSTOM_URL, "")

    fields: dict[Any, Any] = {
        vol.Required(CONF_RATIO, default=ratio): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_RATIO_OPTIONS,
                multiple=False,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_ARTWORK_WIDTH, default=width): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(CONF_ARTWORK_HEIGHT, default=height): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required(CONF_FALLBACK_MODE, default=fallback_mode): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_FALLBACK_OPTIONS,
                multiple=False,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_FALLBACK_CUSTOM_URL, default=fallback_url): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        ),
    }

    # Category-specific API key fields
    if category in (CATEGORY_STREAMING, CATEGORY_AUTO):
        fields[vol.Optional(CONF_TMDB_API_KEY, default=opts.get(CONF_TMDB_API_KEY, ""))] = (
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
        )

    if category in (CATEGORY_GAMING, CATEGORY_AUTO):
        fields[vol.Optional(CONF_IGDB_CLIENT_ID, default=opts.get(CONF_IGDB_CLIENT_ID, ""))] = (
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT))
        )
        fields[vol.Optional(CONF_IGDB_CLIENT_SECRET, default=opts.get(CONF_IGDB_CLIENT_SECRET, ""))] = (
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
        )
        fields[vol.Optional(CONF_STEAMGRIDDB_API_KEY, default=opts.get(CONF_STEAMGRIDDB_API_KEY, ""))] = (
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
        )

    if category in (CATEGORY_TV, CATEGORY_AUTO):
        fields[vol.Optional(CONF_FANART_API_KEY, default=opts.get(CONF_FANART_API_KEY, ""))] = (
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
        )
        fields[vol.Optional(CONF_XMLTV_URL, default=opts.get(CONF_XMLTV_URL, ""))] = (
            selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL))
        )

    return vol.Schema(fields)


def _step3_schema(
    opts: dict[str, Any],
    category: str,
) -> vol.Schema:
    create_combined = bool(opts.get(CONF_CREATE_COMBINED, False))
    combined_name = str(opts.get(CONF_COMBINED_NAME, "")).strip()
    combined_sources: list[str] = list(opts.get(CONF_COMBINED_SOURCES, []))
    combined_audio: list[str] = list(opts.get(CONF_COMBINED_AUDIO_SOURCES, []))
    auto_priority = bool(opts.get(CONF_AUTO_PRIORITY, True))

    fields: dict[Any, Any] = {
        vol.Optional(CONF_CREATE_COMBINED, default=create_combined): selector.BooleanSelector(),
        vol.Optional(CONF_COMBINED_NAME, default=combined_name): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_AUTO_PRIORITY, default=auto_priority): selector.BooleanSelector(),
    }

    slot_defaults = _combined_sources_to_slots(combined_sources)
    for key in _COMBINED_SLOT_KEYS:
        existing = slot_defaults.get(key)
        if existing:
            fields[vol.Optional(key, default=existing)] = _ENTITY_SEL
        else:
            fields[vol.Optional(key)] = _ENTITY_SEL

    fields[vol.Optional(CONF_COMBINED_AUDIO_SOURCES, default=combined_audio)] = _MULTI_ENTITY_SEL

    return vol.Schema(fields)


# ---------------------------------------------------------------------------
# Config flow (3-step setup)
# ---------------------------------------------------------------------------

class MediaCoverArtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    def __init__(self) -> None:
        super().__init__()
        self._step1: dict[str, Any] = {}
        self._step2: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            source_entity_id = user_input[CONF_SOURCE_ENTITY_ID]
            await self.async_set_unique_id(source_entity_id)
            self._abort_if_unique_id_configured()

            # Derive display_name from entity state if blank
            display_name = str(user_input.get(CONF_DISPLAY_NAME, "")).strip()
            if not display_name:
                display_name = await _friendly_name(self.hass, source_entity_id)

            self._step1 = {
                CONF_SOURCE_ENTITY_ID: source_entity_id,
                CONF_DISPLAY_NAME: display_name,
                CONF_CATEGORY: user_input.get(CONF_CATEGORY, CATEGORY_AUTO),
            }
            return await self.async_step_artwork()

        return self.async_show_form(
            step_id="user",
            data_schema=_step1_schema(include_source=True),
        )

    async def async_step_artwork(self, user_input: dict[str, Any] | None = None):
        category = self._step1.get(CONF_CATEGORY, CATEGORY_AUTO)

        if user_input is not None:
            ratio = user_input.get(CONF_RATIO, RATIO_1_1)
            width, height = _ratio_to_dims(
                ratio,
                int(user_input.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH)),
                int(user_input.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT)),
            )
            self._step2 = {
                CONF_RATIO: ratio,
                CONF_ARTWORK_WIDTH: width,
                CONF_ARTWORK_HEIGHT: height,
                CONF_FALLBACK_MODE: user_input.get(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER),
                CONF_FALLBACK_CUSTOM_URL: user_input.get(CONF_FALLBACK_CUSTOM_URL, ""),
                CONF_TMDB_API_KEY: user_input.get(CONF_TMDB_API_KEY, ""),
                CONF_IGDB_CLIENT_ID: user_input.get(CONF_IGDB_CLIENT_ID, ""),
                CONF_IGDB_CLIENT_SECRET: user_input.get(CONF_IGDB_CLIENT_SECRET, ""),
                CONF_STEAMGRIDDB_API_KEY: user_input.get(CONF_STEAMGRIDDB_API_KEY, ""),
                CONF_FANART_API_KEY: user_input.get(CONF_FANART_API_KEY, ""),
                CONF_XMLTV_URL: user_input.get(CONF_XMLTV_URL, ""),
            }
            return await self.async_step_combined()

        return self.async_show_form(
            step_id="artwork",
            data_schema=_step2_schema(category, {}),
        )

    async def async_step_combined(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            create_combined = bool(user_input.get(CONF_CREATE_COMBINED, False))
            combined_name = str(user_input.get(CONF_COMBINED_NAME, "")).strip()

            if create_combined and not combined_name:
                errors[CONF_COMBINED_NAME] = "combined_name_required"

            if not errors:
                data = {CONF_SOURCE_ENTITY_ID: self._step1[CONF_SOURCE_ENTITY_ID]}
                options = {
                    **self._step1,
                    **self._step2,
                    CONF_CREATE_COMBINED: create_combined,
                    CONF_COMBINED_NAME: combined_name,
                    CONF_COMBINED_SOURCES: _combined_slots_to_sources(user_input),
                    CONF_COMBINED_AUDIO_SOURCES: list(user_input.get(CONF_COMBINED_AUDIO_SOURCES) or []),
                    CONF_AUTO_PRIORITY: bool(user_input.get(CONF_AUTO_PRIORITY, True)),
                }
                # Remove source_entity_id from options (it lives only in data)
                options.pop(CONF_SOURCE_ENTITY_ID, None)

                title = self._step1.get(CONF_DISPLAY_NAME) or self._step1[CONF_SOURCE_ENTITY_ID]
                return self.async_create_entry(title=title, data=data, options=options)

        return self.async_show_form(
            step_id="combined",
            data_schema=_step3_schema({}, self._step1.get(CONF_CATEGORY, CATEGORY_AUTO)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return MediaCoverArtOptionsFlow(config_entry)


# ---------------------------------------------------------------------------
# Options flow (mirrors the 3 config steps, minus source_entity_id)
# ---------------------------------------------------------------------------

class MediaCoverArtOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__(config_entry)
        self._step1_opts: dict[str, Any] = {}
        self._artwork_opts: dict[str, Any] = {}

    def _current_opts(self) -> dict[str, Any]:
        opts = dict(self.config_entry.options)
        # Fall back to entry.data for legacy fields
        for key in (CONF_CATEGORY, CONF_DISPLAY_NAME):
            if key not in opts:
                opts[key] = self.config_entry.data.get(key, "")
        return opts

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        opts = self._current_opts()
        category = opts.get(CONF_CATEGORY, CATEGORY_AUTO)
        display_name = str(opts.get(CONF_DISPLAY_NAME, "")).strip()

        if user_input is not None:
            new_category = user_input.get(CONF_CATEGORY, CATEGORY_AUTO)
            new_display_name = str(user_input.get(CONF_DISPLAY_NAME, "")).strip()
            self._step1_opts = {
                CONF_CATEGORY: new_category,
                CONF_DISPLAY_NAME: new_display_name,
            }
            return await self.async_step_artwork()

        return self.async_show_form(
            step_id="init",
            data_schema=_step1_schema(
                display_name=display_name,
                category=category,
                include_source=False,
            ),
        )

    async def async_step_artwork(self, user_input: dict[str, Any] | None = None):
        opts = self._current_opts()
        category = self._step1_opts.get(CONF_CATEGORY, opts.get(CONF_CATEGORY, CATEGORY_AUTO))

        if user_input is not None:
            ratio = user_input.get(CONF_RATIO, RATIO_1_1)
            width, height = _ratio_to_dims(
                ratio,
                int(user_input.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH)),
                int(user_input.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT)),
            )
            self._artwork_opts: dict[str, Any] = {
                CONF_RATIO: ratio,
                CONF_ARTWORK_WIDTH: width,
                CONF_ARTWORK_HEIGHT: height,
                CONF_FALLBACK_MODE: user_input.get(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER),
                CONF_FALLBACK_CUSTOM_URL: user_input.get(CONF_FALLBACK_CUSTOM_URL, ""),
                CONF_TMDB_API_KEY: user_input.get(CONF_TMDB_API_KEY, ""),
                CONF_IGDB_CLIENT_ID: user_input.get(CONF_IGDB_CLIENT_ID, ""),
                CONF_IGDB_CLIENT_SECRET: user_input.get(CONF_IGDB_CLIENT_SECRET, ""),
                CONF_STEAMGRIDDB_API_KEY: user_input.get(CONF_STEAMGRIDDB_API_KEY, ""),
                CONF_FANART_API_KEY: user_input.get(CONF_FANART_API_KEY, ""),
                CONF_XMLTV_URL: user_input.get(CONF_XMLTV_URL, ""),
            }
            return await self.async_step_combined()

        return self.async_show_form(
            step_id="artwork",
            data_schema=_step2_schema(category, opts),
        )

    async def async_step_combined(self, user_input: dict[str, Any] | None = None):
        opts = self._current_opts()
        errors: dict[str, str] = {}

        if user_input is not None:
            create_combined = bool(user_input.get(CONF_CREATE_COMBINED, False))
            combined_name = str(user_input.get(CONF_COMBINED_NAME, "")).strip()

            if create_combined and not combined_name:
                errors[CONF_COMBINED_NAME] = "combined_name_required"

            if not errors:
                new_options = {
                    **self._step1_opts,
                    **self._artwork_opts,
                    CONF_CREATE_COMBINED: create_combined,
                    CONF_COMBINED_NAME: combined_name,
                    CONF_COMBINED_SOURCES: _combined_slots_to_sources(user_input),
                    CONF_COMBINED_AUDIO_SOURCES: list(user_input.get(CONF_COMBINED_AUDIO_SOURCES) or []),
                    CONF_AUTO_PRIORITY: bool(user_input.get(CONF_AUTO_PRIORITY, True)),
                }
                return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="combined",
            data_schema=_step3_schema(opts, self._step1_opts.get(CONF_CATEGORY, opts.get(CONF_CATEGORY, CATEGORY_AUTO))),
            errors=errors,
        )
