"""SteamGridDB + Steam Store provider — game cover art."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

SGDB_SEARCH_URL = "https://www.steamgriddb.com/api/v2/search/autocomplete/{term}"
SGDB_GRIDS_URL = "https://www.steamgriddb.com/api/v2/grids/game/{game_id}"
_JSON_KW = {"content_type": None}

# Steam public search-suggest endpoint (no API key needed)
_STEAM_SUGGEST_URL = "https://store.steampowered.com/search/suggest"

# Steam CDN image templates, tried in order (best quality first)
_STEAM_IMAGE_TEMPLATES = [
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
]

# App-ID cache: normalised_title → (appid, fetched_at)
_APPID_CACHE: dict[str, tuple[int, float]] = {}
_APPID_CACHE_TTL = 86_400  # 24 hours

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_APPID = re.compile(
    r'href=["\']https?://store\.steampowered\.com/app/(\d+)/', re.IGNORECASE
)
_RE_MATCH_NAME = re.compile(
    r'class=["\']match_name["\'][^>]*>([^<]+)<', re.IGNORECASE
)


def _normalize(s: str) -> str:
    return _RE_NON_ALNUM.sub(" ", s.lower()).strip()


def _similarity(query_norm: str, result_norm: str) -> float:
    if query_norm == result_norm:
        return 1.0
    if query_norm in result_norm or result_norm in query_norm:
        return 0.8
    q_words = set(query_norm.split())
    r_words = set(result_norm.split())
    if not q_words or not r_words:
        return 0.0
    return len(q_words & r_words) / max(len(q_words), len(r_words))


async def _steam_find_appid(session, title: str) -> int | None:
    """Search Steam Store suggest for title, return best-matching App ID."""
    norm_title = _normalize(title)
    now = time.monotonic()
    cached = _APPID_CACHE.get(norm_title)
    if cached and now - cached[1] < _APPID_CACHE_TTL:
        return cached[0]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; media-art-wrapper-ha/3.0; "
            "+https://github.com/Levtos/Media_Art_Wrapper)"
        ),
    }
    try:
        async with session.get(
            _STEAM_SUGGEST_URL,
            params={"term": title, "f": "games", "cc": "US", "l": "english"},
            headers=headers,
            timeout=10,
        ) as resp:
            if resp.status != 200:
                return None
            html = await resp.text(encoding="utf-8", errors="ignore")
    except Exception as err:
        _LOGGER.debug("Steam suggest failed for %r: %s", title, err)
        return None

    appids = _RE_APPID.findall(html)
    names = _RE_MATCH_NAME.findall(html)
    if not appids:
        return None

    best_appid: int | None = None
    best_score = -1.0
    for raw_appid, raw_name in zip(appids, names if names else [""] * len(appids)):
        score = _similarity(norm_title, _normalize(raw_name))
        if score > best_score:
            best_score = score
            best_appid = int(raw_appid)

    if best_appid is None or best_score < 0.3:
        return None

    _APPID_CACHE[norm_title] = (best_appid, now)
    return best_appid


class SteamProvider(ArtworkProvider):
    """Steam Store — no API key required, portrait library art."""

    categories = frozenset({"gaming", "auto"})

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        appid = await _steam_find_appid(session, title)
        if appid is None:
            return None

        for template in _STEAM_IMAGE_TEMPLATES:
            url = template.format(appid=appid)
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    ct = resp.headers.get("Content-Type", "image/jpeg")
                    image = await resp.read()
            except Exception as err:
                _LOGGER.debug("Steam image fetch failed (%s): %s", url, err)
                continue

            if image:
                return ArtworkResult(
                    provider_name="steam",
                    image_url=url,
                    confidence=0.85,
                    image=image,
                    content_type=ct,
                )

        return None


class SteamGridDBProvider(ArtworkProvider):
    """SteamGridDB — high-quality community game art (API key required)."""

    categories = frozenset({"gaming", "auto"})

    def __init__(self, api_key: str) -> None:
        self._api_key = (api_key or "").strip()

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        headers = {"Authorization": f"Bearer {self._api_key}"}

        # Search for the game by title
        search_url = SGDB_SEARCH_URL.format(term=title)
        try:
            async with session.get(search_url, headers=headers, timeout=10) as resp:
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("SteamGridDB search failed for %r: %s", title, err)
            return None

        if not isinstance(data, dict) or not data.get("success"):
            return None

        results: list[dict[str, Any]] = data.get("data") or []
        if not isinstance(results, list) or not results:
            return None

        # Find best-matching game by name similarity
        best_game: dict[str, Any] | None = None
        best_score = -1.0
        norm_title = _normalize(title)
        for game in results:
            if not isinstance(game, dict):
                continue
            gname = _normalize(str(game.get("name") or ""))
            score = _similarity(norm_title, gname)
            if score > best_score:
                best_score = score
                best_game = game

        if best_game is None or best_score < 0.3:
            return None

        game_id = best_game.get("id")
        if not isinstance(game_id, int):
            return None

        grids_url = SGDB_GRIDS_URL.format(game_id=game_id)
        # Portrait library-art dimensions first, retry without filter if empty.
        try:
            async with session.get(
                grids_url,
                headers=headers,
                params={"limit": "1", "dimensions": "600x900,660x930"},
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                grids_data: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("SteamGridDB grids fetch failed: %s", err)
            return None

        grids = (
            grids_data.get("data")
            if isinstance(grids_data, dict) and grids_data.get("success")
            else None
        )
        if not grids:
            try:
                async with session.get(
                    grids_url,
                    headers=headers,
                    params={"limit": "1"},
                    timeout=10,
                ) as resp:
                    resp.raise_for_status()
                    grids_data = await resp.json(**_JSON_KW)
            except Exception as err:
                _LOGGER.debug("SteamGridDB grids retry failed: %s", err)
                return None

        grids = grids_data.get("data") or []
        if not isinstance(grids, list) or not grids:
            return None

        first = grids[0]
        if not isinstance(first, dict):
            return None

        url = first.get("url")
        if not isinstance(url, str) or not url:
            return None

        try:
            async with session.get(url, timeout=10) as resp:
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "image/png")
                image = await resp.read()
        except Exception as err:
            _LOGGER.debug("SteamGridDB image download failed: %s", err)
            return None

        if not image:
            return None

        return ArtworkResult(
            provider_name="steamgriddb",
            image_url=url,
            confidence=0.92,
            image=image,
            content_type=ct,
        )
