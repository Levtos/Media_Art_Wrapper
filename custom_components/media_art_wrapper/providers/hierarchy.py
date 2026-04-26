"""§2.3 Artwork-hierarchy dispatcher.

Implements the LASTENHEFT §2.3 priority table by classifying the active
context (which source/sensor combination is producing media right now)
and delegating to the matching provider chain. The §2.3 prio 1
native-artwork pass-through is handled by the caller (CoverCoordinator)
before this module is invoked.

Also implements the §2.4 badge overlay: when a non-game primary cover
is shown while a Discord game-context is active, the SteamGridDB /logos/
endpoint supplies a transparent PNG that is composited over the cover.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from ..const import (
    CATEGORY_ADULT,
    CONF_STEAMGRIDDB_API_KEY,
    SCENARIO_ATV_NO_TITLE,
    SCENARIO_ATV_TITLE,
    SCENARIO_FALLBACK,
    SCENARIO_GAME,
    SCENARIO_STASH,
    SCENARIO_TV_IN_LIST,
    SCENARIO_TV_OUT_OF_LIST,
    channel_in_epg_list,
)
from ..helpers import FALLBACK_IMAGE, service_logo
from . import build_provider_instances, get_providers, resolve_cover
from .base import ArtworkProvider, ArtworkQuery, ArtworkResult
from .steamgriddb import SteamGridDBProvider

_LOGGER = logging.getLogger(__name__)

_TRUE_STATES = {"on", "true", "1", "playing", "active"}
_DISCORD_OFF_STATES = {"0", "off", "none", "unknown", "unavailable", ""}

# §2.4 — badge sized to 22% of cover width, anchored bottom-right.
_BADGE_RATIO = 0.22
_BADGE_MARGIN_RATIO = 0.02
_GIF_CT = "image/gif"


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
    options: dict[str, Any] | None = None,
) -> ScenarioContext:
    """Classify which §2.3 priority applies for the current context.

    Detection order mirrors the §2.3 table; the first matching scenario wins.
    Native-artwork pass-through (§2.3 prio 1) is the caller's responsibility.

    *options* provides access to the user-configured EPG channel list (§5.1)
    so the TV-in-list / TV-out-of-list branch respects per-entry overrides.
    """
    tv_input = (tv_input_state or "").strip().lower()
    stash_raw = (stash_active_state or "").strip().lower()
    opts = options or {}

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
        in_list = channel_in_epg_list(channel_name, opts)
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
# §2.4 Badge overlay
# ---------------------------------------------------------------------------

def detect_badge_game(
    discord_state: str | None,
    discord_attrs: dict[str, Any] | None = None,
) -> str | None:
    """Return a SteamGridDB-lookup-able game title for the §2.4 badge, or None.

    Title source order:
      1. discord_attrs["game_title"] / ["game"]
      2. discord_state if it is a non-empty, non-numeric string

    A purely numeric Discord sensor state (e.g. ``2`` from §7.1's
    discord_active_game_atomic) carries no title and yields None — the
    caller cannot look up "Overwatch" from "2" without additional config.
    """
    attrs = discord_attrs or {}
    for key in ("game_title", "game"):
        v = attrs.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()

    state = (discord_state or "").strip()
    if not state or state.lower() in _DISCORD_OFF_STATES:
        return None
    if state.replace(".", "").replace("-", "").isdigit():
        return None
    return state


def _compose_badge(
    primary_bytes: bytes,
    primary_ct: str,
    badge_bytes: bytes,
) -> tuple[bytes, str] | None:
    """Composite *badge* over *primary* per §2.4 (22% width, bottom-right).

    Returns ``(png_bytes, "image/png")`` on success, or None when
    composition is intentionally skipped: animated GIF primary (§2.4 row
    4 — the GIF plays full-frame as the cover), Pillow unavailable, or
    decode failure.
    """
    if (primary_ct or "").lower() == _GIF_CT:
        return None
    try:
        from PIL import Image
    except ImportError:
        _LOGGER.debug("§2.4 badge: Pillow not available, skipping composition")
        return None

    try:
        primary = Image.open(BytesIO(primary_bytes)).convert("RGBA")
        badge = Image.open(BytesIO(badge_bytes)).convert("RGBA")
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("§2.4 badge: decode failed: %s", err)
        return None

    if badge.width <= 0 or primary.width <= 0:
        return None

    target_w = max(1, int(primary.width * _BADGE_RATIO))
    scale = target_w / badge.width
    target_h = max(1, int(badge.height * scale))
    badge_resized = badge.resize((target_w, target_h), Image.LANCZOS)

    margin = max(1, int(primary.width * _BADGE_MARGIN_RATIO))
    x = primary.width - target_w - margin
    y = primary.height - target_h - margin
    primary.paste(badge_resized, (x, y), badge_resized)

    out = BytesIO()
    primary.save(out, format="PNG")
    return out.getvalue(), "image/png"


async def fetch_badge_image(
    session,
    options: dict[str, Any],
    game_title: str,
) -> bytes | None:
    """Download a transparent SGDB logo PNG for *game_title*, or None."""
    api_key = options.get(CONF_STEAMGRIDDB_API_KEY, "")
    if not api_key:
        return None
    provider = SteamGridDBProvider(api_key)
    if not provider.is_available():
        return None
    result = await provider.fetch_logo(session, game_title)
    if result is None or not result.image:
        return None
    return result.image


async def maybe_apply_badge_bytes(
    session,
    options: dict[str, Any],
    primary_bytes: bytes | None,
    primary_ct: str,
    game_title: str | None,
) -> tuple[bytes, str] | None:
    """Apply a §2.4 badge overlay to raw image bytes when possible.

    Returns the composited ``(bytes, content_type)`` tuple, or None when
    no badge is applied (no game title, no SGDB key, no logo found,
    primary is GIF, Pillow missing). Caller falls back to the original.
    """
    if not primary_bytes or not game_title:
        return None
    badge_bytes = await fetch_badge_image(session, options, game_title)
    if not badge_bytes:
        return None
    return _compose_badge(primary_bytes, primary_ct, badge_bytes)


async def _maybe_apply_badge_to_result(
    session,
    options: dict[str, Any],
    result: ArtworkResult,
    game_title: str,
) -> ArtworkResult:
    """Wrap maybe_apply_badge_bytes for an ArtworkResult; returns the
    badged result, or the original when no badge was applied."""
    if not result.image:
        return result
    composed = await maybe_apply_badge_bytes(
        session, options, result.image, result.content_type, game_title
    )
    if composed is None:
        return result
    new_bytes, new_ct = composed
    return ArtworkResult(
        provider_name=f"{result.provider_name}+badge",
        image_url=result.image_url,
        confidence=result.confidence,
        image=new_bytes,
        content_type=new_ct,
    )


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
    badge_game_title: str | None = None,
) -> ArtworkResult | None:
    """Run the §2.3 provider chain matching *scenario*.

    Returns an ArtworkResult (possibly with confidence=0 for the §2.3 prio 8
    placeholder), or ``None`` only when SCENARIO_FALLBACK runs the legacy
    category chain and that chain returns nothing — preserves backward-compat
    behaviour where the caller decides what to do with an empty result.

    When *badge_game_title* is set, the §2.4 badge overlay is composited
    over the primary cover unless the primary IS the game (SCENARIO_GAME)
    or the primary is an animated GIF.
    """
    s = scenario.scenario
    _LOGGER.debug(
        "§2.3 dispatcher: scenario=%s app_name=%r badge=%r",
        s, app_name, badge_game_title,
    )

    if s == SCENARIO_ATV_NO_TITLE:
        # §2.3 prio 2 — App-Logo
        result = _service_logo_result(app_name) or _placeholder_result()
    elif s == SCENARIO_ATV_TITLE:
        # §2.3 prio 3 — TMDb / iTunes Content-Lookup
        primary = await resolve_cover(
            session, query, _chain(["tmdb", "itunes"], options), options=options
        )
        result = primary or _service_logo_result(app_name) or _placeholder_result()
    elif s == SCENARIO_GAME:
        # §2.3 prio 4 — IGDB → SteamGridDB (Steam Store as no-key fallback)
        primary = await resolve_cover(
            session,
            query,
            _chain(["igdb", "steamgriddb", "steam"], options),
            options=options,
        )
        result = primary or _service_logo_result(app_name) or _placeholder_result()
    elif s == SCENARIO_STASH:
        # §2.3 prio 5 — Stash → StashDB → PornDB → AEBN
        # TODO Schritt 7 (§3.2 / §6): provider classes not yet wired;
        # get_providers(CATEGORY_ADULT, ...) currently returns [].
        adult = get_providers(CATEGORY_ADULT, options)
        primary = None
        if adult:
            primary = await resolve_cover(session, query, adult, options=options)
        result = primary or _service_logo_result(app_name) or _placeholder_result()
    elif s == SCENARIO_TV_IN_LIST:
        # §2.3 prio 6 — EPG-Lookup → Programmtitel → Cover (TVMaze / TMDb)
        primary = await resolve_cover(
            session,
            query,
            _chain(["tvmaze", "tmdb", "fanart"], options),
            options=options,
        )
        result = (
            primary
            or _channel_icon_result(query.channel_icon)
            or _service_logo_result(query.channel_name)
            or _placeholder_result()
        )
    elif s == SCENARIO_TV_OUT_OF_LIST:
        # §2.3 prio 7 — Sender-Logo direkt
        result = (
            _service_logo_result(query.channel_name)
            or _channel_icon_result(query.channel_icon)
            or _service_logo_result(app_name)
            or _placeholder_result()
        )
    else:
        # SCENARIO_FALLBACK — legacy behaviour: run configured category chain.
        # Returning None preserves the existing CoverCoordinator semantics
        # (image entity then renders configured fallback_mode).
        result = await resolve_cover(
            session, query, get_providers(fallback_category, options), options=options
        )

    if result is None:
        return None

    # §2.4 — apply badge overlay when a Discord game-context is active and
    # the primary cover is not itself a game (would be redundant).
    if badge_game_title and s != SCENARIO_GAME:
        result = await _maybe_apply_badge_to_result(
            session, options, result, badge_game_title
        )

    return result
