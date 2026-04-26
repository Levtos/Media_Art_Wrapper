"""PornDB provider (REST, §6.4 prio 3).

The public ``/scenes/search`` endpoint accepts an optional Bearer token.
With a key, results are richer and rate-limits relax; without a key
the same query path is tried but may return nothing — graceful None
either way.
"""
from __future__ import annotations

import logging
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

PORNDB_SEARCH_URL = "https://api.porndb.me/scenes/search"
_JSON_KW = {"content_type": None}


class PornDBProvider(ArtworkProvider):
    categories = frozenset({"adult"})

    def __init__(self, api_key: str = "") -> None:
        self._api_key = (api_key or "").strip()

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            # TODO: most newer PornDB deployments require a Bearer token;
            # without one the public endpoint may return 401/empty. Caller
            # treats that as a graceful miss and falls through to AEBN.
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        try:
            async with session.get(
                PORNDB_SEARCH_URL,
                params={"q": title, "limit": 1},
                headers=self._headers(),
                timeout=10,
            ) as resp:
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
