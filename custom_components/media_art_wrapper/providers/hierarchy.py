"""§2.3 Artwork-hierarchy dispatcher.

Implements the LASTENHEFT §2.3 priority table by classifying the active
context (which source/sensor combination is producing media right now)
and delegating to the matching provider chain. The §2.3 prio 1
native-artwork pass-through is handled by the caller (CoverCoordinator)
before this module is invoked.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..const import (
    CATEGORY_ADULT,
    EPG_FULL_LOOKUP_CHANNELS,
    SCENARIO_ATV_NO_TITLE,
    SCENARIO_ATV_TITLE,
    SCENARIO_FALLBACK,
    SCENARIO_GAME,
    SCENARIO_STASH,
    SCENARIO_TV_IN_LIST,
    SCENARIO_TV_OUT_OF_LIST,
)
from ..helpers import FALLBACK_IMAGE, service_logo
from . import build_provider_instances, get_providers, resolve_cover
from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

_TRUE_STATES = {"on", "true", "1", "playing", "active"}


@dataclass(slots=True)
class ScenarioContext:
    """Detected §2.3 scenario plus useful supporting flags."""

    scenario: str
    channel_in_list: bool = False


def detect_scenario(
    *,
    state_attrs: dict[str, Any],
    tv_input_state: str | None,
    discord_game_state: str | None,
    stash_active_state: str | None,
    channel_name: str = "",
) -> ScenarioContext:
    """Classify which §2.3 priority applies for the current context.

    Detection order mirrors the §2.3 table; the first matching scenario wins.
    Native-artwork pass-through (§2.3 prio 1) is the caller's responsibility.
    """
    tv_input = (tv_input_state or "").strip().lower()
    stash_raw = (stash_active_state or "").strip().lower()

    # Prio 5 — Stash
    if stash_raw and stash_raw in _TRUE_STATES:
        return ScenarioContext(SCENARIO_STASH)

    # Prio 2 / 3 — Apple TV
    if tv_input == "atv":
        title = state_attrs.get("media_title")
        if isinstance(title, str) and title.strip():
            return ScenarioContext(SCENARIO_ATV_TITLE)
        return ScenarioContext(SCENARIO_ATV_NO_TITLE)

    # Prio 4 — PS5 / Switch / Discord (game)
    discord_active = False
    if discord_game_state:
        try:
            discord_active = int(float(discord_game_state)) > 0
        except (TypeError, ValueError):
            discord_active = False
    if tv_input in {"ps5", "switch"} or discord_active:
        return ScenarioContext(SCENARIO_GAME)

    # Prio 6 / 7 — TV / Sat
    if tv_input == "live_tv":
        in_list = bool(channel_name and channel_name.strip() in EPG_FULL_LOOKUP_CHANNELS)
        return ScenarioContext(
            SCENARIO_TV_IN_LIST if in_list else SCENARIO_TV_OUT_OF_LIST,
            channel_in_list=in_list,
        )

    return ScenarioContext(SCENARIO_FALLBACK)


# ---------------------------------------------------------------------------
# Result wrappers
# ---------------------------------------------------------------------------

def _service_logo_result(name: str | None) -> ArtworkResult | None:
    """Wrap helpers.service_logo() bytes as an ArtworkResult, or None."""
    if not name:
        return None
    logo = service_logo(name)
    if not logo:
        return None
    return ArtworkResult(
        provider_name="service_logo",
        image_url=None,
        confidence=0.4,
        image=logo,
        content_type="image/png",
    )


def _channel_icon_result(channel_icon: str) -> ArtworkResult | None:
    if not channel_icon:
        return None
    return ArtworkResult(
        provider_name="channel_icon",
        image_url=channel_icon,
        confidence=0.5,
        image=None,
        content_type="image/jpeg",
    )


def _placeholder_result() -> ArtworkResult:
    """§2.3 prio 8 — last-resort placeholder image."""
    return ArtworkResult(
        provider_name="placeholder",
        image_url=None,
        confidence=0.0,
        image=FALLBACK_IMAGE,
        content_type="image/png",
    )


# ---------------------------------------------------------------------------
# Provider-chain helpers
# ---------------------------------------------------------------------------

def _chain(provider_names: list[str], options: dict[str, Any]) -> list[ArtworkProvider]:
    """Build a custom provider chain by name; missing-credential providers are skipped."""
    instances = build_provider_instances(options)
    out: list[ArtworkProvider] = []
    for name in provider_names:
        provider = instances.get(name)
        if provider is None:
            continue
        if not provider.is_available():
            continue
        out.append(provider)
    return out


# ---------------------------------------------------------------------------
# Hierarchy dispatcher
# ---------------------------------------------------------------------------

async def resolve_hierarchy(
    *,
    session,
    scenario: ScenarioContext,
    query: ArtworkQuery,
    options: dict[str, Any],
    app_name: str,
    fallback_category: str,
) -> ArtworkResult | None:
    """Run the §2.3 provider chain matching *scenario*.

    Returns an ArtworkResult (possibly with confidence=0 for the §2.3 prio 8
    placeholder), or ``None`` only when SCENARIO_FALLBACK runs the legacy
    category chain and that chain returns nothing — preserves backward-compat
    behaviour where the caller decides what to do with an empty result.
    """
    s = scenario.scenario
    _LOGGER.debug("§2.3 dispatcher: scenario=%s app_name=%r", s, app_name)

    if s == SCENARIO_ATV_NO_TITLE:
        # §2.3 prio 2 — App-Logo
        return _service_logo_result(app_name) or _placeholder_result()

    if s == SCENARIO_ATV_TITLE:
        # §2.3 prio 3 — TMDb / iTunes Content-Lookup
        result = await resolve_cover(session, query, _chain(["tmdb", "itunes"], options))
        return result or _service_logo_result(app_name) or _placeholder_result()

    if s == SCENARIO_GAME:
        # §2.3 prio 4 — IGDB → SteamGridDB (Steam Store as no-key fallback)
        result = await resolve_cover(
            session, query, _chain(["igdb", "steamgriddb", "steam"], options)
        )
        return result or _service_logo_result(app_name) or _placeholder_result()

    if s == SCENARIO_STASH:
        # §2.3 prio 5 — Stash → StashDB → PornDB → AEBN
        # TODO Schritt 7 (§3.2 / §6): provider classes not yet wired;
        # get_providers(CATEGORY_ADULT, ...) currently returns [].
        adult = get_providers(CATEGORY_ADULT, options)
        if adult:
            result = await resolve_cover(session, query, adult)
            if result is not None:
                return result
        return _service_logo_result(app_name) or _placeholder_result()

    if s == SCENARIO_TV_IN_LIST:
        # §2.3 prio 6 — EPG-Lookup → Programmtitel → Cover (TVMaze / TMDb)
        result = await resolve_cover(
            session, query, _chain(["tvmaze", "tmdb", "fanart"], options)
        )
        return (
            result
            or _channel_icon_result(query.channel_icon)
            or _service_logo_result(query.channel_name)
            or _placeholder_result()
        )

    if s == SCENARIO_TV_OUT_OF_LIST:
        # §2.3 prio 7 — Sender-Logo direkt
        return (
            _service_logo_result(query.channel_name)
            or _channel_icon_result(query.channel_icon)
            or _service_logo_result(app_name)
            or _placeholder_result()
        )

    # SCENARIO_FALLBACK — legacy behaviour: run configured category chain.
    # Returning None preserves the existing CoverCoordinator semantics
    # (image entity then renders configured fallback_mode).
    return await resolve_cover(session, query, get_providers(fallback_category, options))
