"""Battle.net / Blizzard Games provider for Media Art Wrapper.

Matches known Blizzard game titles (Overwatch, Hearthstone, World of Warcraft,
Diablo, StarCraft, …) and resolves artwork from the official Blizzard game
page's og:image meta tag.  No API key is required.

Results are cached for CACHE_TTL seconds to avoid hammering the Blizzard
websites.  The cache is per game page URL and is shared across all requests
within the same HA process.
"""
from __future__ import annotations

import logging
import re
import time
from typing import NamedTuple

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

CACHE_TTL = 3600  # 1 hour

# Matches both attribute orderings of <meta property="og:image" content="…">
_RE_OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class _GameEntry(NamedTuple):
    display_name: str
    page_url: str


# Map of normalised game name → (display name, Blizzard page URL).
_BLIZZARD_GAMES: dict[str, _GameEntry] = {
    # Overwatch
    "overwatch": _GameEntry("Overwatch 2", "https://overwatch.blizzard.com/en-us/"),
    "overwatch 2": _GameEntry("Overwatch 2", "https://overwatch.blizzard.com/en-us/"),
    # Hearthstone
    "hearthstone": _GameEntry("Hearthstone", "https://hearthstone.blizzard.com/en-us/"),
    # World of Warcraft
    "world of warcraft": _GameEntry("World of Warcraft", "https://worldofwarcraft.blizzard.com/en-us/"),
    "wow": _GameEntry("World of Warcraft", "https://worldofwarcraft.blizzard.com/en-us/"),
    "world of warcraft classic": _GameEntry("WoW Classic", "https://worldofwarcraft.blizzard.com/en-us/"),
    "wow classic": _GameEntry("WoW Classic", "https://worldofwarcraft.blizzard.com/en-us/"),
    # Diablo
    "diablo iv": _GameEntry("Diablo IV", "https://diablo4.blizzard.com/en-us/"),
    "diablo 4": _GameEntry("Diablo IV", "https://diablo4.blizzard.com/en-us/"),
    "diablo immortal": _GameEntry("Diablo Immortal", "https://diabloimmortal.blizzard.com/en-us/"),
    "diablo iii": _GameEntry("Diablo III", "https://diablo3.blizzard.com/en-us/"),
    "diablo 3": _GameEntry("Diablo III", "https://diablo3.blizzard.com/en-us/"),
    "diablo": _GameEntry("Diablo IV", "https://diablo4.blizzard.com/en-us/"),
    # StarCraft
    "starcraft ii": _GameEntry("StarCraft II", "https://starcraft2.blizzard.com/en-us/"),
    "starcraft 2": _GameEntry("StarCraft II", "https://starcraft2.blizzard.com/en-us/"),
    "starcraft": _GameEntry("StarCraft", "https://starcraft.blizzard.com/en-us/"),
    # Heroes of the Storm
    "heroes of the storm": _GameEntry("Heroes of the Storm", "https://heroesofthestorm.blizzard.com/en-us/"),
    "hots": _GameEntry("Heroes of the Storm", "https://heroesofthestorm.blizzard.com/en-us/"),
    # Warcraft III
    "warcraft iii": _GameEntry("Warcraft III", "https://warcraft3.blizzard.com/en-us/"),
    "warcraft 3": _GameEntry("Warcraft III", "https://warcraft3.blizzard.com/en-us/"),
}

# module-level image URL cache: page_url → (image_url, fetched_at_monotonic)
_IMAGE_URL_CACHE: dict[str, tuple[str, float]] = {}


def _normalize(s: str) -> str:
    return _RE_NON_ALNUM.sub(" ", s.lower()).strip()


def _match_game(title: str | None) -> _GameEntry | None:
    """Return the best-matching Blizzard game entry for *title*, or None."""
    if not title:
        return None
    norm = _normalize(title)

    # Exact lookup first
    entry = _BLIZZARD_GAMES.get(norm)
    if entry:
        return entry

    # Longest substring match (e.g. "Overwatch 2 – Season 14" → "overwatch 2")
    best_key: str | None = None
    best_len = 0
    for key in _BLIZZARD_GAMES:
        if key in norm and len(key) > best_len:
            best_key = key
            best_len = len(key)

    if best_key:
        return _BLIZZARD_GAMES[best_key]

    return None


async def _fetch_og_image(session, page_url: str) -> str | None:
    """Fetch *page_url* and return the og:image URL, using a module-level cache."""
    now = time.monotonic()
    cached = _IMAGE_URL_CACHE.get(page_url)
    if cached and now - cached[1] < CACHE_TTL:
        _LOGGER.debug("Battle.net og:image cache hit for %s", page_url)
        return cached[0]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; media-art-wrapper-ha/3.0; "
            "+https://github.com/Levtos/Media_Art_Wrapper)"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with session.get(page_url, headers=headers, timeout=15, allow_redirects=True) as resp:
            if resp.status != 200:
                _LOGGER.debug("Battle.net page %s returned HTTP %s", page_url, resp.status)
                return None
            html = await resp.text(encoding="utf-8", errors="ignore")
    except Exception as err:
        _LOGGER.debug("Battle.net page fetch failed for %s: %s", page_url, err)
        return None

    m = _RE_OG_IMAGE.search(html)
    if not m:
        _LOGGER.debug("No og:image found on %s", page_url)
        return None

    image_url = (m.group(1) or m.group(2) or "").strip()
    if not image_url:
        return None

    _IMAGE_URL_CACHE[page_url] = (image_url, now)
    return image_url


class BattleNetProvider(ArtworkProvider):
    """Battle.net / Blizzard Games — artwork from official Blizzard game pages.

    Requires no API key.  Supports Overwatch, Hearthstone, World of Warcraft,
    Diablo, StarCraft, Heroes of the Storm, and Warcraft III.
    """

    categories = frozenset({"gaming", "auto"})

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        entry = _match_game(query.title)
        if entry is None:
            return None

        _LOGGER.debug(
            "Battle.net matched game=%r page=%s (query title=%r)",
            entry.display_name,
            entry.page_url,
            query.title,
        )

        image_url = await _fetch_og_image(session, entry.page_url)
        if not image_url:
            _LOGGER.debug("Battle.net: no og:image resolved for %r", entry.display_name)
            return None

        try:
            async with session.get(image_url, timeout=15) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                image = await resp.read()
        except Exception as err:
            _LOGGER.debug("Battle.net artwork download failed for %r: %s", entry.display_name, err)
            return None

        if not image:
            return None

        return ArtworkResult(
            provider_name="battlenet",
            image_url=image_url,
            confidence=0.95,
            image=image,
            content_type=content_type,
        )
