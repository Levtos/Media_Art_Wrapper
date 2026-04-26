"""Config flow for Stash Player — connection logic based on Druidblack/stash-home-assistant."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_NSFW_MODE,
    CONF_PLAYER_NAME,
    CONF_POLL_INTERVAL,
    CONF_URL,
    CONF_USE_WEBHOOK,
    CONF_WEBHOOK_PORT,
    DEFAULT_NSFW_MODE,
    DEFAULT_PLAYER_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_USE_WEBHOOK,
    DEFAULT_WEBHOOK_PORT,
    DOMAIN,
    NSFW_BLUR,
    NSFW_FULL,
    NSFW_HIDDEN,
)

_LOGGER = logging.getLogger(__name__)

_NSFW_OPTIONS = [
    {"value": NSFW_BLUR,   "label": "Blurred"},
    {"value": NSFW_HIDDEN, "label": "Hidden"},
    {"value": NSFW_FULL,   "label": "Full quality"},
]


async def _normalize_and_test(hass, raw_url: str, api_key: str) -> str:
    """Normalize URL and verify it reaches a Stash GraphQL endpoint.

    Returns the full /graphql URL on success, raises RuntimeError on failure.
    This approach is adapted from Druidblack/stash-home-assistant.
    """
    url = raw_url.strip()
    if not url:
        raise RuntimeError("Empty URL")

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url

    url = url.rstrip("/")
    graphql_url = url if url.endswith("/graphql") else f"{url}/graphql"

    session = async_get_clientsession(hass)
    headers = {"ApiKey": api_key.strip()} if api_key.strip() else {}
    payload = {"query": "query { version { version } }"}

    async with session.post(graphql_url, json=payload, headers=headers) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"HTTP {resp.status}: {text}")
        data = await resp.json()

    if "errors" in data or "data" not in data:
        raise RuntimeError(f"GraphQL error: {data.get('errors')}")

    return graphql_url


class StashPlayerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Stash Player."""

    VERSION = 2

    def __init__(self) -> None:
        self._connection_data: dict[str, Any] = {}
        self._options_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 1: test connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_url = user_input[CONF_URL]
            api_key = user_input.get(CONF_API_KEY, "")
            try:
                graphql_url = await _normalize_and_test(self.hass, raw_url, api_key)
            except Exception as err:
                _LOGGER.warning("Cannot connect to Stash at %s: %s", raw_url, err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(graphql_url.lower())
                self._abort_if_unique_id_configured()

                parsed = urlparse(graphql_url)
                host = parsed.hostname or graphql_url
                port = parsed.port
                title = f"{DEFAULT_PLAYER_NAME} {host}:{port}" if port else f"{DEFAULT_PLAYER_NAME} {host}"

                self._connection_data = {CONF_URL: graphql_url, CONF_API_KEY: api_key.strip()}
                self._options_data["_title"] = title
                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL): selector.TextSelector(),
                vol.Optional(CONF_API_KEY, default=""): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }),
            errors=errors,
        )

    async def async_step_options(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 2: behavior options."""
        if user_input is not None:
            self._options_data.update(user_input)
            if user_input.get(CONF_USE_WEBHOOK):
                return await self.async_step_webhook()
            return self._create_entry()

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema({
                vol.Optional(CONF_PLAYER_NAME, default=DEFAULT_PLAYER_NAME): selector.TextSelector(),
                vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=2, max=60, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_USE_WEBHOOK, default=DEFAULT_USE_WEBHOOK): selector.BooleanSelector(),
                vol.Optional(CONF_NSFW_MODE, default=DEFAULT_NSFW_MODE): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_NSFW_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
            }),
        )

    async def async_step_webhook(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 3 (optional): webhook port."""
        if user_input is not None:
            self._options_data.update(user_input)
            return self._create_entry()

        return self.async_show_form(
            step_id="webhook",
            data_schema=vol.Schema({
                vol.Optional(CONF_WEBHOOK_PORT, default=DEFAULT_WEBHOOK_PORT): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=65535, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
            }),
        )

    def _create_entry(self) -> FlowResult:
        self._options_data.setdefault(CONF_WEBHOOK_PORT, DEFAULT_WEBHOOK_PORT)
        self._options_data.setdefault(CONF_USE_WEBHOOK, DEFAULT_USE_WEBHOOK)
        title = self._options_data.pop("_title",
                                       self._options_data.get(CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME))
        return self.async_create_entry(title=title, data=self._connection_data, options=self._options_data)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return StashPlayerOptionsFlow(config_entry)


class StashPlayerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._options_data: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._options_data = user_input
            if user_input.get(CONF_USE_WEBHOOK):
                return await self.async_step_webhook()
            self._options_data.setdefault(CONF_WEBHOOK_PORT, DEFAULT_WEBHOOK_PORT)
            return self.async_create_entry(title="", data=self._options_data)

        o = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_PLAYER_NAME, default=o.get(CONF_PLAYER_NAME, DEFAULT_PLAYER_NAME)): selector.TextSelector(),
                vol.Optional(CONF_POLL_INTERVAL, default=o.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=2, max=60, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_USE_WEBHOOK, default=o.get(CONF_USE_WEBHOOK, DEFAULT_USE_WEBHOOK)): selector.BooleanSelector(),
                vol.Optional(CONF_NSFW_MODE, default=o.get(CONF_NSFW_MODE, DEFAULT_NSFW_MODE)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_NSFW_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
            }),
        )

    async def async_step_webhook(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._options_data.update(user_input)
            return self.async_create_entry(title="", data=self._options_data)

        o = self.config_entry.options
        return self.async_show_form(
            step_id="webhook",
            data_schema=vol.Schema({
                vol.Optional(CONF_WEBHOOK_PORT, default=o.get(CONF_WEBHOOK_PORT, DEFAULT_WEBHOOK_PORT)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=65535, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
            }),
        )
