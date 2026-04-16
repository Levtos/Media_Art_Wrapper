"""providers/ — artwork provider registry and resolution pipeline.

Public API
----------
get_providers(category, options) -> list[ArtworkProvider]
    Build an ordered list of ArtworkProvider instances for the given category
    and config entry options dict.  Providers whose credentials are missing
    are silently omitted via is_available().

resolve_cover(session, query, providers) -> ArtworkResult | None
    Try each provider in order; return the first successful ArtworkResult.
"""
from __future__ import annotations

import logging
from typing import Any

from ..const import (
    CATEGORY_AUTO,
    CATEGORY_GAMING,
    CATEGORY_MUSIC,
    CATEGORY_PROVIDERS,
    CATEGORY_STREAMING,
    CATEGORY_TV,
    CONF_FANART_API_KEY,
    CONF_IGDB_CLIENT_ID,
    CONF_IGDB_CLIENT_SECRET,
    CONF_STEAMGRIDDB_API_KEY,
    CONF_TMDB_API_KEY,
)
from .base import ArtworkProvider, ArtworkQuery, ArtworkResult
from .battlenet import BattleNetProvider
from .fanart import FanartTvProvider
from .igdb import IGDBProvider
from .itunes import ITunesProvider
from .musicbrainz import MusicBrainzProvider
from .steamgriddb import SteamGridDBProvider, SteamProvider
from .tmdb import TMDbProvider
from .tvmaze import TVMazeProvider

__all__ = [
    "ArtworkProvider",
    "ArtworkQuery",
    "ArtworkResult",
    "get_providers",
    "resolve_cover",
]

_LOGGER = logging.getLogger(__name__)


def get_providers(
    category: str,
    options: dict[str, Any],
) -> list[ArtworkProvider]:
    """Return an ordered list of available providers for *category*.

    Providers that require credentials are instantiated with the values from
    *options*; those whose ``is_available()`` returns False are excluded.

    The order follows ``CATEGORY_PROVIDERS[category]``.
    """
    wanted: list[str] = CATEGORY_PROVIDERS.get(category, CATEGORY_PROVIDERS[CATEGORY_AUTO])

    # Build all provider instances (keyed by provider name)
    all_instances: dict[str, ArtworkProvider] = {
        "itunes": ITunesProvider(),
        "musicbrainz": MusicBrainzProvider(),
        "tmdb": TMDbProvider(options.get(CONF_TMDB_API_KEY, "")),
        "igdb": IGDBProvider(
            options.get(CONF_IGDB_CLIENT_ID, ""),
            options.get(CONF_IGDB_CLIENT_SECRET, ""),
        ),
        "steamgriddb": SteamGridDBProvider(options.get(CONF_STEAMGRIDDB_API_KEY, "")),
        "steam": SteamProvider(),
        "battlenet": BattleNetProvider(),
        "tvmaze": TVMazeProvider(),
        "fanart": FanartTvProvider(options.get(CONF_FANART_API_KEY, "")),
    }

    result: list[ArtworkProvider] = []
    for name in wanted:
        provider = all_instances.get(name)
        if provider is None:
            _LOGGER.debug("Unknown provider %r skipped", name)
            continue
        if not provider.is_available():
            _LOGGER.debug("Provider %r not available (missing credentials)", name)
            continue
        result.append(provider)

    return result


async def resolve_cover(
    session,
    query: ArtworkQuery,
    providers: list[ArtworkProvider],
) -> ArtworkResult | None:
    """Try each provider in order; return the first successful ArtworkResult.

    Providers are tried in the order supplied by *providers*.  If a provider
    raises an unexpected exception it is logged and skipped so that the next
    provider can be tried.
    """
    for provider in providers:
        try:
            result = await provider.fetch(session, query)
        except Exception as err:
            _LOGGER.debug(
                "Provider %s raised an exception: %s",
                type(provider).__name__,
                err,
            )
            continue

        if result is not None:
            _LOGGER.debug(
                "Artwork resolved by %r (url=%s, confidence=%.2f)",
                result.provider_name,
                result.image_url,
                result.confidence,
            )
            return result

    _LOGGER.debug("No provider returned artwork for query: title=%r artist=%r", query.title, query.artist)
    return None
