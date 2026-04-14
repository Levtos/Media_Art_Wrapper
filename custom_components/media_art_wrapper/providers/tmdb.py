"""The Movie Database (TMDb) provider — streaming films and series."""
from __future__ import annotations

import logging
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/multi"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
_JSON_KW = {"content_type": None}


class TMDbProvider(ArtworkProvider):
    """TMDb /search/multi — movies and TV series."""

    categories = frozenset({"streaming", "auto"})

    def __init__(self, api_key: str) -> None:
        self._api_key = (api_key or "").strip()

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            # For episodes try series title as fallback
            title = (query.series_title or "").strip()
        if not title:
            return None

        try:
            async with session.get(
                TMDB_SEARCH_URL,
                params={"api_key": self._api_key, "query": title, "page": 1},
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                payload: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("TMDb search failed for %r: %s", title, err)
            return None

        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or not results:
            return None

        # Prefer: exact media_type match for episode content → tv, else movie
        preferred_type = "tv" if query.content_type in ("episode", "tv_episode") else None

        best: dict[str, Any] | None = None
        for item in results:
            if not isinstance(item, dict):
                continue
            if preferred_type and item.get("media_type") == preferred_type:
                best = item
                break
        if best is None:
            # Accept first result regardless of type
            best = next((r for r in results if isinstance(r, dict) and r.get("poster_path")), None)
        if best is None:
            return None

        poster_path = best.get("poster_path")
        if not isinstance(poster_path, str) or not poster_path:
            return None

        # Pick image size closest to requested dimensions
        size = "w500" if max(query.artwork_width, query.artwork_height) <= 600 else "original"
        url = f"https://image.tmdb.org/t/p/{size}{poster_path}"
        try:
            async with session.get(url, timeout=10) as resp:
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "image/jpeg")
                image = await resp.read()
        except Exception as err:
            _LOGGER.debug("TMDb image fetch failed: %s", err)
            return None

        if not image:
            return None

        return ArtworkResult(
            provider_name="tmdb",
            image_url=url,
            confidence=0.9,
            image=image,
            content_type=ct,
        )
