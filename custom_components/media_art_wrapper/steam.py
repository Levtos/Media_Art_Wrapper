"""Steam provider for Media Art Wrapper.

Uses Steam's public search-suggest endpoint (no API key required) to find a
game by title, extracts the Steam App ID, and fetches the portrait library
artwork from the Steam CDN.

Image priority (highest-quality portrait format first):
  1. library_600x900_2x.jpg  (1200 × 1800 px)
  2. library_600x900.jpg      (600 × 900 px)
  3. header.jpg               (460 × 215 px, landscape fallback)

App-ID lookups are cached for APPID_CACHE_TTL seconds so that a game
played for hours only triggers one search request per HA session restart.
"""
from __future__ import annotations

import logging
import re
import time

from homeassistant.exceptions import HomeAssistantError

from .models import ResolvedCover, TrackQuery

_LOGGER = logging.getLogger(__name__)

# Steam public search-suggest endpoint (no API key needed)
_STEAM_SUGGEST_URL = "https://store.steampowered.com/search/suggest"

# CDN image URL templates, tried in order until one returns HTTP 200
_STEAM_IMAGE_TEMPLATES = [
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
]

# How long to cache appid lookups (games don't change their App ID)
APPID_CACHE_TTL = 86_400  # 24 hours

# module-level cache: normalised_title → (appid, fetched_at)
_APPID_CACHE: dict[str, tuple[int, float]] = {}

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# Extracts Steam App ID from suggest-response href attributes
_RE_APPID = re.compile(r'href=["\']https?://store\.steampowered\.com/app/(\d+)/', re.IGNORECASE)
# Extracts the human-readable game name shown in suggest results
_RE_MATCH_NAME = re.compile(r'class=["\']match_name["\'][^>]*>([^<]+)<', re.IGNORECASE)


def _normalize(s: str) -> str:
    return _RE_NON_ALNUM.sub(" ", s.lower()).strip()


def _similarity(query_norm: str, result_norm: str) -> float:
    """Word-overlap similarity between two normalised strings (0.0–1.0)."""
    if query_norm == result_norm:
        return 1.0
    if query_norm in result_norm or result_norm in query_norm:
        return 0.8
    q_words = set(query_norm.split())
    r_words = set(result_norm.split())
    if not q_words or not r_words:
        return 0.0
    return len(q_words & r_words) / max(len(q_words), len(r_words))


async def _find_appid(session, title: str) -> int | None:
    """Search Steam for *title* and return the best-matching App ID."""
    norm_title = _normalize(title)

    # Cache hit?
    now = time.monotonic()
    cached = _APPID_CACHE.get(norm_title)
    if cached and now - cached[1] < APPID_CACHE_TTL:
        _LOGGER.debug("Steam appid cache hit: %r → %s", title, cached[0])
        return cached[0]

    params = {
        "term": title,
        "f": "games",
        "cc": "US",
        "l": "english",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; media-art-wrapper-ha/1.0; "
            "+https://github.com/Levtos/Media_Art_Wrapper)"
        ),
    }
    try:
        async with session.get(
            _STEAM_SUGGEST_URL, params=params, headers=headers, timeout=10
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug("Steam suggest returned HTTP %s for %r", resp.status, title)
                return None
            html = await resp.text(encoding="utf-8", errors="ignore")
    except Exception as err:
        _LOGGER.debug("Steam suggest request failed for %r: %s", title, err)
        return None

    appids = _RE_APPID.findall(html)
    names = _RE_MATCH_NAME.findall(html)

    if not appids:
        _LOGGER.debug("Steam suggest returned no results for %r", title)
        return None

    # Pick the result whose name best matches the query
    best_appid: int | None = None
    best_score = -1.0
    for raw_appid, raw_name in zip(appids, names if names else [""] * len(appids)):
        score = _similarity(norm_title, _normalize(raw_name))
        _LOGGER.debug(
            "Steam candidate appid=%s name=%r score=%.2f", raw_appid, raw_name, score
        )
        if score > best_score:
            best_score = score
            best_appid = int(raw_appid)

    if best_appid is None or best_score < 0.3:
        _LOGGER.debug(
            "Steam: no good match for %r (best score=%.2f)", title, best_score
        )
        return None

    _APPID_CACHE[norm_title] = (best_appid, now)
    return best_appid


async def async_steam_resolve(*, session, query: TrackQuery) -> ResolvedCover | None:
    """Resolve cover art for a Steam game.

    Returns a *ResolvedCover* when the query title matches a Steam game and
    artwork can be fetched, otherwise *None*.
    """
    if not query.title:
        return None

    appid = await _find_appid(session, query.title)
    if appid is None:
        return None

    _LOGGER.debug("Steam resolved appid=%s for title=%r", appid, query.title)

    # Try image templates from best to worst quality
    for template in _STEAM_IMAGE_TEMPLATES:
        image_url = template.format(appid=appid)
        try:
            async with session.get(image_url, timeout=10) as img_resp:
                if img_resp.status == 404:
                    continue
                img_resp.raise_for_status()
                content_type = img_resp.headers.get("Content-Type", "image/jpeg")
                image = await img_resp.read()
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Steam artwork fetch failed: {err}") from err

        if image:
            _LOGGER.debug("Steam: using image %s", image_url)
            return ResolvedCover(
                provider="steam",
                artwork_url=image_url,
                content_type=content_type,
                image=image,
            )

    _LOGGER.debug("Steam: no artwork found for appid=%s", appid)
    return None
