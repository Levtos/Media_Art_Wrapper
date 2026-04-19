"""Config flow — 3-step setup for Media Art Wrapper v3.1."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector

from .const import (
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
    CONF_COMBINED_DELEGATE_PREFIX,
    CONF_COMBINED_NAME,
    CONF_COMBINED_SOURCES,
    CONF_CREATE_COMBINED,
    CONF_CREATE_WRAPPER,
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
    CONF_EPG_SENSOR,
    DEFAULT_ARTWORK_HEIGHT,
    DEFAULT_ARTWORK_WIDTH,
    DEFAULT_RATIO,
    DOMAIN,
    FALLBACK_CUSTOM_URL_MODE,
    FALLBACK_PLACEHOLDER,
    FALLBACK_SERVICE_LOGO,
    RATIO_16_9_1920,
    RATIO_1_1_2000,
    RATIO_1_1_3000,
    RATIO_4_3_1600,
    RATIO_CUSTOM,
    RATIO_DIMENSIONS,
)


_CATEGORY_OPTIONS = [
    {"value": CATEGORY_MUSIC, "label": "Music"},
    {"value": CATEGORY_STREAMING, "label": "Streaming (films & series)"},
    {"value": CATEGORY_GAMING, "label": "Gaming"},
    {"value": CATEGORY_TV, "label": "TV / Live TV"},
    {"value": CATEGORY_AUTO, "label": "Auto (try all providers)"},
]

_RATIO_OPTIONS = [
    {"value": RATIO_1_1_2000, "label": "1:1  — 2000 × 2000 px (default)"},
    {"value": RATIO_1_1_3000, "label": "1:1  — 3000 × 3000 px"},
    {"value": RATIO_4_3_1600, "label": "4:3  — 1600 × 1200 px"},
    {"value": RATIO_16_9_1920, "label": "16:9 — 1920 × 1080 px"},
    {"value": RATIO_CUSTOM, "label": "Custom …"},
]

_FALLBACK_OPTIONS = [
    {"value": FALLBACK_PLACEHOLDER, "label": "Placeholder icon"},
    {"value": FALLBACK_SERVICE_LOGO, "label": "Service logo (auto-detected)"},
    {"value": FALLBACK_CUSTOM_URL_MODE, "label": "Custom URL …"},
]

_COMBINED_SLOT_KEYS = [f"combined_source_{i}" for i in range(1, COMBINED_NUM_SOURCE_SLOTS + 1)]
_COMBINED_DELEGATE_KEYS = [f"{CONF_COMBINED_DELEGATE_PREFIX}{i}" for i in range(1, COMBINED_NUM_SOURCE_SLOTS + 1)]
_PREVIEW_KEY = "combined_auto_order_preview"
_NO_MAW_INFO = "combined_no_maw_info"
CONF_ENTITY_KIND = "entity_kind"
ENTITY_KIND_WRAPPER = "wrapper"
ENTITY_KIND_WRAPPER_COMBINED = "wrapper_combined"
ENTITY_KIND_COMBINED_ONLY = "combined_only"

_ENTITY_KIND_OPTIONS = [
    {"value": ENTITY_KIND_WRAPPER, "label": "Nur Media Art Wrapper"},
    {"value": ENTITY_KIND_COMBINED_ONLY, "label": "Nur kombinierter Player"},
    {"value": ENTITY_KIND_WRAPPER_COMBINED, "label": "Media Art Wrapper + kombinierter Player"},
]

_ENTITY_SEL = selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player", multiple=False))
_MULTI_ENTITY_SEL = selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player", multiple=True))


def _ratio_to_dims(ratio: str, width: int, height: int) -> tuple[int, int]:
    if ratio in RATIO_DIMENSIONS:
        return RATIO_DIMENSIONS[ratio]
    return (max(1, width), max(1, height))


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
    return {_COMBINED_SLOT_KEYS[i]: sources[i] for i in range(min(len(sources), COMBINED_NUM_SOURCE_SLOTS))}


async def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state and "friendly_name" in state.attributes:
        return str(state.attributes["friendly_name"])
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


async def _maw_wrapper_entities(hass: HomeAssistant) -> list[str]:
    registry = er.async_get(hass)
    result: list[str] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        for e in er.async_entries_for_config_entry(registry, entry.entry_id):
            if e.domain == "media_player" and e.unique_id.endswith("_cover_player") and e.entity_id:
                result.append(e.entity_id)
    return sorted(dict.fromkeys(result))


def _map_control_target_by_wrapper(hass: HomeAssistant) -> dict[str, str]:
    registry = er.async_get(hass)
    mapping: dict[str, str] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        wrapper_entity_id: str | None = None
        for e in er.async_entries_for_config_entry(registry, entry.entry_id):
            if e.domain == "media_player" and e.unique_id.endswith("_cover_player") and e.entity_id:
                wrapper_entity_id = e.entity_id
                break
        if not wrapper_entity_id:
            continue
        data = entry.data
        source = str(data.get(CONF_SOURCE_ENTITY_ID, ""))
        mapping[wrapper_entity_id] = source
    return mapping


def _step1_schema(source_entity_id: str | None = None, display_name: str = "", category: str = CATEGORY_AUTO, entity_kind: str = ENTITY_KIND_WRAPPER, *, include_source: bool = True) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_source:
        fields[vol.Required(CONF_ENTITY_KIND, default=entity_kind)] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=_ENTITY_KIND_OPTIONS, multiple=False, mode=selector.SelectSelectorMode.DROPDOWN)
        )
        if entity_kind != ENTITY_KIND_COMBINED_ONLY:
            kw: dict[str, Any] = {"default": source_entity_id} if source_entity_id else {}
            fields[vol.Optional(CONF_SOURCE_ENTITY_ID, **kw)] = _ENTITY_SEL
    fields[vol.Optional(CONF_DISPLAY_NAME, default=display_name)] = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT))
    fields[vol.Required(CONF_CATEGORY, default=category)] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=_CATEGORY_OPTIONS, multiple=False, mode=selector.SelectSelectorMode.DROPDOWN)
    )
    return vol.Schema(fields)


def _step2_schema(category: str, opts: dict[str, Any]) -> vol.Schema:
    ratio = opts.get(CONF_RATIO, DEFAULT_RATIO)
    width = int(opts.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH))
    height = int(opts.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT))
    fallback_mode = opts.get(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER)

    fields: dict[Any, Any] = {
        vol.Required(CONF_RATIO, default=ratio): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_RATIO_OPTIONS, multiple=False, mode=selector.SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_FALLBACK_MODE, default=fallback_mode): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_FALLBACK_OPTIONS, multiple=False, mode=selector.SelectSelectorMode.DROPDOWN)
        ),
    }

    if ratio == RATIO_CUSTOM:
        fields[vol.Optional(CONF_ARTWORK_WIDTH, default=width)] = vol.All(vol.Coerce(int), vol.Range(min=1))
        fields[vol.Optional(CONF_ARTWORK_HEIGHT, default=height)] = vol.All(vol.Coerce(int), vol.Range(min=1))

    if fallback_mode == FALLBACK_CUSTOM_URL_MODE:
        fields[vol.Optional(CONF_FALLBACK_CUSTOM_URL, default=opts.get(CONF_FALLBACK_CUSTOM_URL, ""))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        )

    if category in (CATEGORY_STREAMING, CATEGORY_TV, CATEGORY_AUTO):
        fields[vol.Optional(CONF_TMDB_API_KEY, default=opts.get(CONF_TMDB_API_KEY, ""))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    if category in (CATEGORY_GAMING, CATEGORY_AUTO):
        fields[vol.Optional(CONF_IGDB_CLIENT_ID, default=opts.get(CONF_IGDB_CLIENT_ID, ""))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        )
        fields[vol.Optional(CONF_IGDB_CLIENT_SECRET, default=opts.get(CONF_IGDB_CLIENT_SECRET, ""))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        fields[vol.Optional(CONF_STEAMGRIDDB_API_KEY, default=opts.get(CONF_STEAMGRIDDB_API_KEY, ""))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    if category in (CATEGORY_TV, CATEGORY_AUTO):
        fields[vol.Optional(CONF_FANART_API_KEY, default=opts.get(CONF_FANART_API_KEY, ""))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        fields[vol.Optional(CONF_EPG_SENSOR, default=opts.get(CONF_EPG_SENSOR))] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", multiple=False)
        )

    return vol.Schema(fields)


def _step3_schema(opts: dict[str, Any], maw_sources: list[str], control_map: dict[str, str], *, force_combined: bool = False) -> vol.Schema:
    create_combined = True if force_combined else bool(opts.get(CONF_CREATE_COMBINED, False))
    auto_priority = bool(opts.get(CONF_AUTO_PRIORITY, True))
    fields: dict[Any, Any] = {}
    if not force_combined:
        fields[vol.Optional(CONF_CREATE_COMBINED, default=create_combined)] = selector.BooleanSelector()

    if not create_combined:
        return vol.Schema(fields)

    fields[vol.Optional(CONF_COMBINED_NAME, default=str(opts.get(CONF_COMBINED_NAME, "")).strip())] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    )
    fields[vol.Optional(CONF_AUTO_PRIORITY, default=auto_priority)] = selector.BooleanSelector()

    chosen_sources: list[str] = list(opts.get(CONF_COMBINED_SOURCES, []))
    if auto_priority:
        if maw_sources:
            fields[vol.Optional(CONF_COMBINED_SOURCES, default=chosen_sources)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=maw_sources, multiple=True, mode=selector.SelectSelectorMode.LIST)
            )
        else:
            fields[vol.Optional(_NO_MAW_INFO, default="Keine MAW-Instanzen gefunden. Bitte zuerst einzelne Player konfigurieren.")] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            )
    else:
        slot_defaults = _combined_sources_to_slots(chosen_sources)
        if not maw_sources:
            fields[vol.Optional(_NO_MAW_INFO, default="Keine MAW-Instanzen gefunden. Bitte zuerst einzelne Player konfigurieren.")] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            )
        slot_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(options=maw_sources, multiple=False, mode=selector.SelectSelectorMode.DROPDOWN)
        )
        delegate_selector = _ENTITY_SEL
        for idx, key in enumerate(_COMBINED_SLOT_KEYS, start=1):
            existing = slot_defaults.get(key)
            fields[vol.Optional(key, default=existing)] = slot_selector
            delegate_key = f"{CONF_COMBINED_DELEGATE_PREFIX}{idx}"
            fields[vol.Optional(delegate_key, default=opts.get(delegate_key))] = delegate_selector

    default_audio = list(opts.get(CONF_COMBINED_AUDIO_SOURCES, []))
    if not default_audio and chosen_sources:
        default_audio = [control_map[s] for s in chosen_sources if control_map.get(s)]
    fields[vol.Optional(CONF_COMBINED_AUDIO_SOURCES, default=default_audio)] = _MULTI_ENTITY_SEL

    return vol.Schema(fields)

class MediaCoverArtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 6

    def __init__(self) -> None:
        self._step1: dict[str, Any] = {}
        self._step2: dict[str, Any] = {}
        self._step3: dict[str, Any] = {}
        self._step1_draft: dict[str, Any] = {}
        self._entity_kind: str = ENTITY_KIND_WRAPPER

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            draft = {**self._step1_draft, **user_input}
            selected_kind = draft.get(CONF_ENTITY_KIND, ENTITY_KIND_WRAPPER)
            selected_category = draft.get(CONF_CATEGORY, CATEGORY_AUTO)
            if (CONF_ENTITY_KIND in user_input or CONF_CATEGORY in user_input) and (
                selected_kind != self._step1_draft.get(CONF_ENTITY_KIND, ENTITY_KIND_WRAPPER)
                or selected_category != self._step1_draft.get(CONF_CATEGORY, CATEGORY_AUTO)
            ):
                self._step1_draft = draft
                return self.async_show_form(step_id="user", data_schema=_step1_schema(include_source=True, **{k: v for k, v in draft.items() if k in (CONF_SOURCE_ENTITY_ID, CONF_DISPLAY_NAME, CONF_CATEGORY, CONF_ENTITY_KIND)}))

            self._entity_kind = selected_kind
            source_entity_id = draft.get(CONF_SOURCE_ENTITY_ID)

            if self._entity_kind != ENTITY_KIND_COMBINED_ONLY and not source_entity_id:
                errors[CONF_SOURCE_ENTITY_ID] = "source_entity_required"

            if not errors:
                if self._entity_kind != ENTITY_KIND_COMBINED_ONLY and source_entity_id:
                    await self.async_set_unique_id(source_entity_id)
                    self._abort_if_unique_id_configured()

                display_name = str(draft.get(CONF_DISPLAY_NAME, "")).strip()
                if not display_name and source_entity_id:
                    display_name = await _friendly_name(self.hass, source_entity_id)

                self._step1 = {
                    CONF_SOURCE_ENTITY_ID: source_entity_id,
                    CONF_DISPLAY_NAME: display_name,
                    CONF_CATEGORY: selected_category,
                }
                if self._entity_kind == ENTITY_KIND_COMBINED_ONLY:
                    self._step2 = {}
                    self._step3[CONF_CREATE_COMBINED] = True
                    return await self.async_step_combined()
                return await self.async_step_artwork()

            self._step1_draft = draft

        return self.async_show_form(
            step_id="user",
            data_schema=_step1_schema(
                include_source=True,
                source_entity_id=self._step1_draft.get(CONF_SOURCE_ENTITY_ID),
                display_name=str(self._step1_draft.get(CONF_DISPLAY_NAME, "")),
                category=str(self._step1_draft.get(CONF_CATEGORY, CATEGORY_AUTO)),
                entity_kind=self._step1_draft.get(CONF_ENTITY_KIND, self._entity_kind),
            ),
            errors=errors,
        )

    async def async_step_artwork(self, user_input: dict[str, Any] | None = None):
        category = self._step1.get(CONF_CATEGORY, CATEGORY_AUTO)
        if user_input is not None:
            draft = {**self._step2, **user_input}
            prev_ratio = self._step2.get(CONF_RATIO, DEFAULT_RATIO)
            prev_fallback = self._step2.get(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER)
            new_ratio = user_input.get(CONF_RATIO, prev_ratio)
            new_fallback = user_input.get(CONF_FALLBACK_MODE, prev_fallback)
            if (new_ratio == RATIO_CUSTOM) != (prev_ratio == RATIO_CUSTOM) or (new_fallback == FALLBACK_CUSTOM_URL_MODE) != (prev_fallback == FALLBACK_CUSTOM_URL_MODE):
                self._step2 = draft
                return self.async_show_form(step_id="artwork", data_schema=_step2_schema(category, draft))

            ratio = draft.get(CONF_RATIO, DEFAULT_RATIO)
            width, height = _ratio_to_dims(ratio, int(draft.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH)), int(draft.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT)))
            self._step2 = {
                CONF_RATIO: ratio,
                CONF_ARTWORK_WIDTH: width,
                CONF_ARTWORK_HEIGHT: height,
                CONF_FALLBACK_MODE: draft.get(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER),
                CONF_FALLBACK_CUSTOM_URL: draft.get(CONF_FALLBACK_CUSTOM_URL, ""),
                CONF_TMDB_API_KEY: draft.get(CONF_TMDB_API_KEY, ""),
                CONF_IGDB_CLIENT_ID: draft.get(CONF_IGDB_CLIENT_ID, ""),
                CONF_IGDB_CLIENT_SECRET: draft.get(CONF_IGDB_CLIENT_SECRET, ""),
                CONF_STEAMGRIDDB_API_KEY: draft.get(CONF_STEAMGRIDDB_API_KEY, ""),
                CONF_FANART_API_KEY: draft.get(CONF_FANART_API_KEY, ""),
                CONF_EPG_SENSOR: draft.get(CONF_EPG_SENSOR),
            }
            if self._entity_kind == ENTITY_KIND_WRAPPER_COMBINED:
                self._step3[CONF_CREATE_COMBINED] = True
                return await self.async_step_combined()
            data = {CONF_SOURCE_ENTITY_ID: self._step1[CONF_SOURCE_ENTITY_ID]}
            options = {**self._step1, **self._step2, CONF_CREATE_WRAPPER: True, CONF_CREATE_COMBINED: False}
            options.pop(CONF_SOURCE_ENTITY_ID, None)
            title = self._step1.get(CONF_DISPLAY_NAME) or self._step1[CONF_SOURCE_ENTITY_ID]
            return self.async_create_entry(title=title, data=data, options=options)

        return self.async_show_form(step_id="artwork", data_schema=_step2_schema(category, self._step2))

    async def async_step_combined(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        maw_sources = await _maw_wrapper_entities(self.hass)
        control_map = _map_control_target_by_wrapper(self.hass)

        if user_input is not None:
            draft = {**self._step3, **user_input}
            create_combined = bool(draft.get(CONF_CREATE_COMBINED, False))
            if self._entity_kind == ENTITY_KIND_COMBINED_ONLY:
                create_combined = True
            auto_priority = bool(draft.get(CONF_AUTO_PRIORITY, True))
            prev_create = bool(self._step3.get(CONF_CREATE_COMBINED, False))
            prev_auto = bool(self._step3.get(CONF_AUTO_PRIORITY, True))
            new_create = bool(draft.get(CONF_CREATE_COMBINED, False))
            new_auto = bool(draft.get(CONF_AUTO_PRIORITY, True))
            if new_create != prev_create or (new_create and new_auto != prev_auto):
                selected = list(draft.get(CONF_COMBINED_SOURCES, [])) or _combined_slots_to_sources(draft)
                draft[CONF_COMBINED_SOURCES] = selected
                draft[CONF_COMBINED_AUDIO_SOURCES] = [control_map[s] for s in selected if control_map.get(s)]
                self._step3 = draft
                return self.async_show_form(step_id="combined", data_schema=_step3_schema(draft, maw_sources, control_map, force_combined=self._entity_kind == ENTITY_KIND_COMBINED_ONLY))

            combined_name = str(draft.get(CONF_COMBINED_NAME, "")).strip()
            if create_combined and not combined_name:
                errors[CONF_COMBINED_NAME] = "combined_name_required"

            if not errors:
                if auto_priority:
                    combined_sources = list(draft.get(CONF_COMBINED_SOURCES, []))
                else:
                    combined_sources = _combined_slots_to_sources(draft)
                if self._entity_kind == ENTITY_KIND_COMBINED_ONLY:
                    await self.async_set_unique_id(f"combined:{combined_name.lower()}")
                    self._abort_if_unique_id_configured()
                    data: dict[str, Any] = {}
                    title = combined_name
                    create_wrapper = False
                else:
                    data = {CONF_SOURCE_ENTITY_ID: self._step1[CONF_SOURCE_ENTITY_ID]}
                    title = self._step1.get(CONF_DISPLAY_NAME) or self._step1[CONF_SOURCE_ENTITY_ID]
                    create_wrapper = True
                options = {
                    **self._step1,
                    **self._step2,
                    CONF_CREATE_WRAPPER: create_wrapper,
                    CONF_CREATE_COMBINED: create_combined,
                    CONF_COMBINED_NAME: combined_name,
                    CONF_COMBINED_SOURCES: combined_sources,
                    CONF_COMBINED_AUDIO_SOURCES: list(draft.get(CONF_COMBINED_AUDIO_SOURCES) or []),
                    CONF_AUTO_PRIORITY: auto_priority,
                    **{k: draft.get(k) for k in _COMBINED_DELEGATE_KEYS},
                }
                options.pop(CONF_SOURCE_ENTITY_ID, None)
                return self.async_create_entry(title=title, data=data, options=options)
            self._step3 = draft

        return self.async_show_form(step_id="combined", data_schema=_step3_schema(self._step3, maw_sources, control_map, force_combined=self._entity_kind == ENTITY_KIND_COMBINED_ONLY), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return MediaCoverArtOptionsFlow(config_entry)


class MediaCoverArtOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__(config_entry)
        self._step1_opts: dict[str, Any] = {}
        self._artwork_opts: dict[str, Any] = {}
        self._combined_opts: dict[str, Any] = {}

    def _current_opts(self) -> dict[str, Any]:
        opts = dict(self.config_entry.options)
        for key in (CONF_CATEGORY, CONF_DISPLAY_NAME):
            if key not in opts:
                opts[key] = self.config_entry.data.get(key, "")
        return opts

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        opts = self._current_opts()
        if user_input is not None:
            self._step1_opts = {
                CONF_CATEGORY: user_input.get(CONF_CATEGORY, CATEGORY_AUTO),
                CONF_DISPLAY_NAME: str(user_input.get(CONF_DISPLAY_NAME, "")).strip(),
            }
            return await self.async_step_artwork()

        return self.async_show_form(
            step_id="init",
            data_schema=_step1_schema(
                display_name=str(opts.get(CONF_DISPLAY_NAME, "")).strip(),
                category=opts.get(CONF_CATEGORY, CATEGORY_AUTO),
                include_source=False,
            ),
        )

    async def async_step_artwork(self, user_input: dict[str, Any] | None = None):
        opts = self._current_opts()
        category = self._step1_opts.get(CONF_CATEGORY, opts.get(CONF_CATEGORY, CATEGORY_AUTO))
        if user_input is not None:
            draft = {**self._artwork_opts, **user_input}
            prev_ratio = self._artwork_opts.get(CONF_RATIO, opts.get(CONF_RATIO, DEFAULT_RATIO))
            prev_fallback = self._artwork_opts.get(CONF_FALLBACK_MODE, opts.get(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER))
            new_ratio = user_input.get(CONF_RATIO, prev_ratio)
            new_fallback = user_input.get(CONF_FALLBACK_MODE, prev_fallback)
            if (new_ratio == RATIO_CUSTOM) != (prev_ratio == RATIO_CUSTOM) or (new_fallback == FALLBACK_CUSTOM_URL_MODE) != (prev_fallback == FALLBACK_CUSTOM_URL_MODE):
                self._artwork_opts = draft
                return self.async_show_form(step_id="artwork", data_schema=_step2_schema(category, {**opts, **draft}))
            ratio = draft.get(CONF_RATIO, opts.get(CONF_RATIO, DEFAULT_RATIO))
            width, height = _ratio_to_dims(ratio, int(draft.get(CONF_ARTWORK_WIDTH, opts.get(CONF_ARTWORK_WIDTH, DEFAULT_ARTWORK_WIDTH))), int(draft.get(CONF_ARTWORK_HEIGHT, opts.get(CONF_ARTWORK_HEIGHT, DEFAULT_ARTWORK_HEIGHT))))
            self._artwork_opts = {
                CONF_RATIO: ratio,
                CONF_ARTWORK_WIDTH: width,
                CONF_ARTWORK_HEIGHT: height,
                CONF_FALLBACK_MODE: draft.get(CONF_FALLBACK_MODE, FALLBACK_PLACEHOLDER),
                CONF_FALLBACK_CUSTOM_URL: draft.get(CONF_FALLBACK_CUSTOM_URL, ""),
                CONF_TMDB_API_KEY: draft.get(CONF_TMDB_API_KEY, ""),
                CONF_IGDB_CLIENT_ID: draft.get(CONF_IGDB_CLIENT_ID, ""),
                CONF_IGDB_CLIENT_SECRET: draft.get(CONF_IGDB_CLIENT_SECRET, ""),
                CONF_STEAMGRIDDB_API_KEY: draft.get(CONF_STEAMGRIDDB_API_KEY, ""),
                CONF_FANART_API_KEY: draft.get(CONF_FANART_API_KEY, ""),
                CONF_EPG_SENSOR: draft.get(CONF_EPG_SENSOR),
            }
            return await self.async_step_combined()

        return self.async_show_form(step_id="artwork", data_schema=_step2_schema(category, opts))

    async def async_step_combined(self, user_input: dict[str, Any] | None = None):
        opts = self._current_opts()
        merged = {**opts, **self._combined_opts}
        errors: dict[str, str] = {}
        maw_sources = await _maw_wrapper_entities(self.hass)
        control_map = _map_control_target_by_wrapper(self.hass)

        if user_input is not None:
            draft = {**merged, **user_input}
            create_combined = bool(draft.get(CONF_CREATE_COMBINED, False))
            auto_priority = bool(draft.get(CONF_AUTO_PRIORITY, True))
            prev_create = bool(merged.get(CONF_CREATE_COMBINED, False))
            prev_auto = bool(merged.get(CONF_AUTO_PRIORITY, True))
            new_create = bool(draft.get(CONF_CREATE_COMBINED, False))
            new_auto = bool(draft.get(CONF_AUTO_PRIORITY, True))
            if new_create != prev_create or (new_create and new_auto != prev_auto):
                selected = list(draft.get(CONF_COMBINED_SOURCES, [])) or _combined_slots_to_sources(draft)
                draft[CONF_COMBINED_SOURCES] = selected
                draft[CONF_COMBINED_AUDIO_SOURCES] = [control_map[s] for s in selected if control_map.get(s)]
                self._combined_opts = draft
                return self.async_show_form(step_id="combined", data_schema=_step3_schema(draft, maw_sources, control_map))

            combined_name = str(draft.get(CONF_COMBINED_NAME, "")).strip()
            if create_combined and not combined_name:
                errors[CONF_COMBINED_NAME] = "combined_name_required"

            if not errors:
                combined_sources = list(draft.get(CONF_COMBINED_SOURCES, [])) if auto_priority else _combined_slots_to_sources(draft)
                new_options = {
                    **self._step1_opts,
                    **self._artwork_opts,
                    CONF_CREATE_WRAPPER: opts.get(CONF_CREATE_WRAPPER, True),
                    CONF_CREATE_COMBINED: create_combined,
                    CONF_COMBINED_NAME: combined_name,
                    CONF_COMBINED_SOURCES: combined_sources,
                    CONF_COMBINED_AUDIO_SOURCES: list(draft.get(CONF_COMBINED_AUDIO_SOURCES) or []),
                    CONF_AUTO_PRIORITY: auto_priority,
                    **{k: draft.get(k) for k in _COMBINED_DELEGATE_KEYS},
                }
                return self.async_create_entry(title="", data=new_options)
            self._combined_opts = draft

        return self.async_show_form(step_id="combined", data_schema=_step3_schema(merged, maw_sources, control_map), errors=errors)
