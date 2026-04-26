"""IGDB (Twitch) provider — game cover art."""
from __future__ import annotations

import logging
import time
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult
from .game_db import get_title, touch_title, update_title

_LOGGER = logging.getLogger(__name__)

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_GAMES_URL = "https://api.igdb.com/v4/games"
IGDB_COVERS_URL = "https://api.igdb.com/v4/covers"
_JSON_KW = {"content_type": None}

# Access token is cached across requests for its lifetime
_token_cache: dict[str, Any] = {}  # {client_id: {"token": str, "expires_at": float}}


async def _get_access_token(session, client_id: str, client_secret: str) -> str | None:
    """Return a cached or freshly-acquired Twitch OAuth2 access token."""
    cached = _token_cache.get(client_id)
    if cached and time.time() < cached["expires_at"] - 60:
        return cached["token"]

    try:
        async with session.post(
            TWITCH_TOKEN_URL,
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=10,
        ) as resp:
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("IGDB token request failed: %s", err)
        return None

    token = data.get("access_token")
    expires_in = int(data.get("expires_in", 3600))
    if not isinstance(token, str):
        return None

    _token_cache[client_id] = {"token": token, "expires_at": time.time() + expires_in}
    return token


class IGDBProvider(ArtworkProvider):
    """IGDB game cover art via Twitch Developer credentials."""

    categories = frozenset({"gaming", "auto"})

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()

    def is_available(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        db_entry = touch_title(title)
        if db_entry.get("lookup_failed"):
            return None
        cached_cover = db_entry.get("cover_url")
        if isinstance(cached_cover, str) and cached_cover:
            return ArtworkResult(provider_name="igdb", image_url=cached_cover, confidence=0.95)

        token = await _get_access_token(session, self._client_id, self._client_secret)
        if not token:
            return None

        headers = {
            "Client-ID": self._client_id,
            "Authorization": f"Bearer {token}",
        }

        # Search for the game
        search_body = f'search "{title}"; fields id,name,cover; limit 5;'
        try:
            async with session.post(
                IGDB_GAMES_URL,
                headers=headers,
                data=search_body,
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                games: list[dict[str, Any]] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("IGDB game search failed for %r: %s", title, err)
            update_title(title, lookup_failed=True)
            return None

        if not isinstance(games, list) or not games:
            update_title(title, lookup_failed=True)
            return None

        # Pick the first game that has a cover ID
        cover_id: int | None = None
        for game in games:
            if not isinstance(game, dict):
                continue
            cid = game.get("cover")
            if isinstance(cid, int):
                cover_id = cid
                break

        if cover_id is None:
            update_title(title, lookup_failed=True)
            return None

        # Fetch cover URL
        cover_body = f"fields image_id; where id = {cover_id};"
        try:
            async with session.post(
                IGDB_COVERS_URL,
                headers=headers,
                data=cover_body,
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                covers: list[dict[str, Any]] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("IGDB cover fetch failed: %s", err)
            update_title(title, lookup_failed=True)
            return None

        if not isinstance(covers, list) or not covers:
            update_title(title, lookup_failed=True)
            return None

        image_id = covers[0].get("image_id") if isinstance(covers[0], dict) else None
        if not isinstance(image_id, str):
            update_title(title, lookup_failed=True)
            return None

        # Request highest available quality for preset >=2K
        size = "t_1080p" if max(query.artwork_width, query.artwork_height) >= 1600 else "t_cover_big"
        url = f"https://images.igdb.com/igdb/image/upload/{size}/{image_id}.jpg"

        try:
            async with session.get(url, timeout=10) as resp:
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "image/jpeg")
                image = await resp.read()
        except Exception as err:
            _LOGGER.debug("IGDB image download failed: %s", err)
            update_title(title, lookup_failed=True)
            return None

        if not image:
            update_title(title, lookup_failed=True)
            return None

        update_title(title, igdb_id=cover_id, cover_url=url, lookup_failed=False)
        return ArtworkResult(
            provider_name="igdb",
            image_url=url,
            confidence=0.95,
            image=image,
            content_type=ct,
        )
