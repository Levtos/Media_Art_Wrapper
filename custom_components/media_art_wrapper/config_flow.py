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
    PROVIDER_ITUNES,
    PROVIDER_MUSICBRAINZ,
    PROVIDER_TV,
)

PROVIDER_OPTIONS = [
    {"value": PROVIDER_ITUNES, "label": "iTunes (Apple Search API)"},
    {"value": PROVIDER_MUSICBRAINZ, "label": "MusicBrainz + Cover Art Archive"},
    {"value": PROVIDER_TV, "label": "TV (iTunes TV + TVMaze + Wikipedia-Senderlogos)"},
]


def _data_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_SOURCE_ENTITY_ID, default=defaults.get(CONF_SOURCE_ENTITY_ID)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=False)
            ),
            vol.Optional(CONF_PROVIDERS, default=defaults.get(CONF_PROVIDERS, DEFAULT_PROVIDERS)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=PROVIDER_OPTIONS,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_ARTWORK_WIDTH,
                default=defaults.get(CONF_ARTWORK_WIDTH, defaults.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_WIDTH)),
            ): vol.Coerce(int),
            vol.Optional(
                CONF_ARTWORK_HEIGHT,
                default=defaults.get(CONF_ARTWORK_HEIGHT, defaults.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_HEIGHT)),
            ): vol.Coerce(int),
        }
    )


async def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state and "friendly_name" in state.attributes:
        return str(state.attributes["friendly_name"])
    return entity_id


class MediaCoverArtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            source_entity_id = user_input[CONF_SOURCE_ENTITY_ID]
            await self.async_set_unique_id(source_entity_id)
            self._abort_if_unique_id_configured()

            title = await _friendly_name(self.hass, source_entity_id)

            data = {
                CONF_SOURCE_ENTITY_ID: source_entity_id,
                CONF_PROVIDERS: user_input.get(CONF_PROVIDERS, DEFAULT_PROVIDERS),
                CONF_ARTWORK_WIDTH: int(user_input.get(CONF_ARTWORK_WIDTH, user_input.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_WIDTH))),
                CONF_ARTWORK_HEIGHT: int(user_input.get(CONF_ARTWORK_HEIGHT, user_input.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_HEIGHT))),
            }
            return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema(),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return MediaCoverArtOptionsFlow(config_entry)


class MediaCoverArtOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = {
            CONF_SOURCE_ENTITY_ID: self.config_entry.data.get(CONF_SOURCE_ENTITY_ID),
            CONF_PROVIDERS: self.config_entry.options.get(
                CONF_PROVIDERS,
                self.config_entry.data.get(CONF_PROVIDERS, DEFAULT_PROVIDERS),
            ),
            CONF_ARTWORK_WIDTH: self.config_entry.options.get(
                CONF_ARTWORK_WIDTH,
                self.config_entry.data.get(CONF_ARTWORK_WIDTH, self.config_entry.data.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_WIDTH)),
            ),
            CONF_ARTWORK_HEIGHT: self.config_entry.options.get(
                CONF_ARTWORK_HEIGHT,
                self.config_entry.data.get(CONF_ARTWORK_HEIGHT, self.config_entry.data.get(CONF_ARTWORK_SIZE, DEFAULT_ARTWORK_HEIGHT)),
            ),
        }

        # Options allow changing providers/size; source entity stays fixed per unique_id
        schema = vol.Schema(
            {
                vol.Optional(CONF_PROVIDERS, default=defaults[CONF_PROVIDERS]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=PROVIDER_OPTIONS,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_ARTWORK_WIDTH, default=defaults[CONF_ARTWORK_WIDTH]): vol.Coerce(int),
                vol.Optional(CONF_ARTWORK_HEIGHT, default=defaults[CONF_ARTWORK_HEIGHT]): vol.Coerce(int),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
