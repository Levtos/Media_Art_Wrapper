"""PornDB provider (REST fallback)."""
from __future__ import annotations

import logging
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

PORNDB_SEARCH_URL = "https://api.porndb.me/scenes/search"
_JSON_KW = {"content_type": None}


class PornDBProvider(ArtworkProvider):
    categories = frozenset({"adult"})

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        try:
            async with session.get(PORNDB_SEARCH_URL, params={"q": title, "limit": 1}, timeout=10) as resp:
                if resp.status != 200:
                    return None
                payload: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("PornDB lookup failed for %r: %s", title, err)
            return None

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            return None

        first = data[0] if isinstance(data[0], dict) else None
        if not first:
            return None

        image_url = first.get("image") or first.get("poster")
        if not isinstance(image_url, str) or not image_url:
            return None

        return ArtworkResult(provider_name="porndb", image_url=image_url, confidence=0.82)
