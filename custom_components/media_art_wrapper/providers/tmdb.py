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

    categories = frozenset({"streaming", "tv", "auto"})

    def __init__(self, api_key: str) -> None:
        self._api_key = (api_key or "").strip()

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        candidates = [c for c in (query.title_candidates or []) if isinstance(c, str) and c.strip()]
        if not candidates:
            title = (query.title or "").strip() or (query.series_title or "").strip()
            candidates = [title] if title else []
        if not candidates:
            return None

        results = None
        for candidate in candidates:
            try:
                async with session.get(
                    TMDB_SEARCH_URL,
                    params={"api_key": self._api_key, "query": candidate, "page": 1},
                    timeout=10,
                ) as resp:
                    resp.raise_for_status()
                    payload: dict[str, Any] = await resp.json(**_JSON_KW)
            except Exception as err:
                _LOGGER.debug("TMDb search failed for %r: %s", candidate, err)
                continue
            results = payload.get("results") if isinstance(payload, dict) else None
            if isinstance(results, list) and results:
                break
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

        # Episode title search: when subtitle_hint set, try episode still_path
        subtitle = (query.subtitle_hint or "").strip()
        if subtitle and best.get("media_type") == "tv":
            tv_id = best.get("id")
            episode_img = await self._find_episode_still(session, tv_id, subtitle) if tv_id else None
            if episode_img:
                url = episode_img
                try:
                    async with session.get(url, timeout=10) as resp:
                        resp.raise_for_status()
                        ct = resp.headers.get("Content-Type", "image/jpeg")
                        image = await resp.read()
                except Exception as err:
                    _LOGGER.debug("TMDb episode still fetch failed: %s", err)
                    image = None
                if image:
                    return ArtworkResult(
                        provider_name="tmdb_episode",
                        image_url=url,
                        confidence=0.88,
                        image=image,
                        content_type=ct,
                    )

        poster_path = best.get("poster_path")
        if not isinstance(poster_path, str) or not poster_path:
            return None

        size = "original"
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

    async def _find_episode_still(
        self, session, tv_id: int, subtitle: str
    ) -> str | None:
        """Search the last 2 seasons of tv_id for an episode matching subtitle."""
        seasons_url = f"https://api.themoviedb.org/3/tv/{tv_id}"
        try:
            async with session.get(
                seasons_url,
                params={"api_key": self._api_key},
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                show_data: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception:
            return None

        seasons = show_data.get("seasons") or []
        season_numbers = [
            s["season_number"]
            for s in seasons
            if isinstance(s, dict) and s.get("season_number", 0) > 0
        ]
        # Check last 2 seasons only
        for season_num in sorted(season_numbers)[-2:]:
            season_url = f"https://api.themoviedb.org/3/tv/{tv_id}/season/{season_num}"
            try:
                async with session.get(
                    season_url,
                    params={"api_key": self._api_key},
                    timeout=10,
                ) as resp:
                    resp.raise_for_status()
                    season_data: dict[str, Any] = await resp.json(**_JSON_KW)
            except Exception:
                continue

            for ep in season_data.get("episodes") or []:
                if not isinstance(ep, dict):
                    continue
                ep_name = str(ep.get("name") or "")
                if ep_name.lower() == subtitle.lower():
                    still = ep.get("still_path")
                    if isinstance(still, str) and still:
                        return f"https://image.tmdb.org/t/p/original{still}"

        return None
