"""AEBN provider (REST fallback)."""
from __future__ import annotations

import logging
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

AEBN_SEARCH_URL = "https://api.aebn.net/v1/titles"
_JSON_KW = {"content_type": None}


class AEBNProvider(ArtworkProvider):
    categories = frozenset({"adult"})

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        try:
            async with session.get(
                AEBN_SEARCH_URL,
                params={"query": title, "limit": 1},
                timeout=10,
            ) as resp:
                if resp.status != 200:
                    return None
                payload: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("AEBN lookup failed for %r: %s", title, err)
            return None

        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            return None

        first = items[0] if isinstance(items[0], dict) else None
        if not first:
            return None

        image_url = first.get("cover") or first.get("image")
        if not isinstance(image_url, str) or not image_url:
            return None

        return ArtworkResult(provider_name="aebn", image_url=image_url, confidence=0.74)
