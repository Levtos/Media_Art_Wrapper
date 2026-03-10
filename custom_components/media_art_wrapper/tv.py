from __future__ import annotations

import logging
import re
from typing import Any

from .models import ResolvedCover, TrackQuery

_LOGGER = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
TVMAZE_SEARCH_URL = "https://api.tvmaze.com/search/shows"
WIKIPEDIA_API_URL = "https://{lang}.wikipedia.org/w/api.php"

_JSON_KW = {"content_type": None}

# Strips broadcast-technical and regional suffixes from channel names.
# Examples:
#   "WDR HD Wuppertal" → "WDR"
#   "Das Erste HD"     → "Das Erste"
#   "ZDF neo"          → "ZDF neo"   (kept – "neo" is part of the brand)
_RE_CHANNEL_SUFFIX = re.compile(
    r"\s+\b(hd|sd|uhd|4k|hbbtv)\b.*$",
    re.IGNORECASE,
)

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_SPACES = re.compile(r"\s+")


def _clean(s: str) -> str:
    s = s.strip().lower()
    s = _RE_NON_ALNUM.sub(" ", s)
    return _RE_SPACES.sub(" ", s).strip()


def _strip_channel_suffix(name: str) -> str:
    """Remove broadcast-technical and regional suffixes from a channel name."""
    return _RE_CHANNEL_SUFFIX.sub("", name).strip()


def _names_overlap(a: str, b: str) -> bool:
    """Return True if cleaned versions of a and b share a substring match."""
    ca, cb = _clean(a), _clean(b)
    return bool(ca and cb and (ca in cb or cb in ca))


# ---------------------------------------------------------------------------
# Sub-searches
# ---------------------------------------------------------------------------

async def _fetch_image(session, url: str) -> tuple[bytes, str] | None:
    try:
        async with session.get(url, timeout=10) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            image = await resp.read()
        return (image, content_type) if image else None
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Image fetch failed (%s): %s", url, err)
        return None


async def _itunes_tv(session, term: str, match_name: str) -> str | None:
    """Search iTunes for TV shows / movies and return the artwork URL of the
    best matching result, or None."""
    params = {
        "term": term,
        "entity": "tvShow,movie",
        "media": "video",
        "limit": "5",
    }
    try:
        async with session.get(ITUNES_SEARCH_URL, params=params, timeout=10) as resp:
            resp.raise_for_status()
            payload = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("iTunes TV search failed: %s", err)
        return None

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None

    for item in results:
        if not isinstance(item, dict):
            continue
        result_name = str(item.get("trackName") or item.get("collectionName") or "")
        if not _names_overlap(match_name, result_name):
            continue
        artwork = (
            item.get("artworkUrl100")
            or item.get("artworkUrl60")
            or item.get("artworkUrl30")
        )
        if isinstance(artwork, str) and artwork:
            return artwork
    return None


async def _tvmaze(session, term: str) -> str | None:
    """Search TVMaze for a show and return its image URL, or None."""
    params = {"q": term}
    try:
        async with session.get(TVMAZE_SEARCH_URL, params=params, timeout=10) as resp:
            resp.raise_for_status()
            results = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("TVMaze search failed: %s", err)
        return None

    if not isinstance(results, list) or not results:
        return None

    best = results[0]
    if not isinstance(best, dict):
        return None
    show = best.get("show")
    if not isinstance(show, dict):
        return None

    # Require a reasonable name match so we don't return unrelated shows.
    show_name = str(show.get("name") or "")
    if not _names_overlap(term, show_name):
        return None

    image_data = show.get("image")
    if not isinstance(image_data, dict):
        return None
    url = image_data.get("original") or image_data.get("medium")
    return str(url) if isinstance(url, str) and url else None


_COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"

# Filenames containing any of these words are very unlikely to be logos.
_LOGO_EXCLUDE = {"karte", "map", "germany", "deutschland", "studio", "gebäude",
                 "building", "headquarters", "sitz", "standort", "portrait",
                 "foto", "photo", "bild", "picture"}

# Extra weight when the filename contains these words.
_LOGO_BOOST = {"logo", "dachmarke", "wortmarke", "signet", "icon", "emblem"}


def _score_image_file(filename: str, channel_tokens: list[str]) -> int:
    """Score a Wikipedia image filename for how likely it is to be a channel logo.

    Returns a negative value for files that should be excluded entirely.
    """
    fn = filename.lower()
    # Strip namespace prefix ("File:" / "Datei:")
    fn = re.sub(r"^(file|datei):", "", fn).strip()

    # Hard exclusions
    if any(excl in fn for excl in _LOGO_EXCLUDE):
        return -1

    score = 0
    if any(boost in fn for boost in _LOGO_BOOST):
        score += 3
    if any(tok in fn for tok in channel_tokens if len(tok) >= 2):
        score += 2
    # SVG files are almost always vector logos; PNGs/JPGs less reliably so.
    if fn.endswith(".svg"):
        score += 1

    return score


async def _resolve_commons_url(session, file_title: str, thumb_width: int) -> str | None:
    """Return a rasterised thumbnail URL for a Wikimedia Commons file title."""
    params = {
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": str(thumb_width),
        "format": "json",
    }
    try:
        async with session.get(_COMMONS_API_URL, params=params, timeout=10) as resp:
            resp.raise_for_status()
            payload = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("Commons imageinfo failed for %r: %s", file_title, err)
        return None

    pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        for info in page.get("imageinfo") or []:
            url = info.get("thumburl") or info.get("url")
            if isinstance(url, str) and url:
                return url
    return None


async def _wikipedia_logo(session, title: str, thumb_width: int = 600) -> str | None:
    """Find the best logo image for a TV channel via Wikipedia.

    Strategy:
      1. Fetch all images listed on the Wikipedia article (prop=images).
      2. Score each filename – prefer files whose name contains 'logo',
         the channel name tokens, or is an SVG; exclude maps/photos.
      3. Resolve the winning file's thumbnail URL via the Commons API.

    Tries German Wikipedia first (better for German broadcasters), then English.
    """
    channel_tokens = _clean(title).split()

    for lang in ("de", "en"):
        api_url = WIKIPEDIA_API_URL.format(lang=lang)
        params = {
            "action": "query",
            "titles": title,
            "prop": "images",
            "imlimit": "30",
            "format": "json",
            "redirects": 1,
        }
        try:
            async with session.get(api_url, params=params, timeout=10) as resp:
                resp.raise_for_status()
                payload = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("Wikipedia (%s) images lookup failed for %r: %s", lang, title, err)
            continue

        pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
        image_titles: list[str] = []
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            for img in page.get("images") or []:
                t = img.get("title")
                if isinstance(t, str) and t:
                    image_titles.append(t)

        if not image_titles:
            continue

        # Pick the best-scoring candidate.
        best_score = 0
        best_file: str | None = None
        for img_title in image_titles:
            score = _score_image_file(img_title, channel_tokens)
            if score > best_score:
                best_score = score
                best_file = img_title

        if not best_file:
            _LOGGER.debug("Wikipedia (%s): no suitable logo image found for %r", lang, title)
            continue

        _LOGGER.debug("Wikipedia (%s): best logo candidate %r (score=%d)", lang, best_file, best_score)
        url = await _resolve_commons_url(session, best_file, thumb_width)
        if url:
            return url

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def async_tv_resolve(*, session, query: TrackQuery) -> ResolvedCover | None:
    """Resolve artwork for TV content.

    Search order:
      1. iTunes TV (tvShow + movie entity) – matches show/movie names.
      2. TVMaze – TV shows, freely accessible without API key.
      3. Wikipedia thumbnail – used as a last resort for channel logos
         (e.g. "WDR HD Wuppertal" → strip suffix → look up "WDR").
    """
    title = (query.title or "").strip()
    artist = (query.artist or "").strip()
    search_term = " ".join(filter(None, [title, artist]))

    if not search_term:
        return None

    artwork_url: str | None = None
    provider_name: str | None = None

    # 1. iTunes TV ----------------------------------------------------------
    artwork_url = await _itunes_tv(session, search_term, match_name=title or artist)
    if artwork_url:
        # Scale up the iTunes thumbnail to the requested size.
        target = max(100, int(max(query.artwork_width, query.artwork_height)))
        artwork_url = re.sub(
            r"/(\d{2,4})x(\d{2,4})bb\.(jpg|png)$",
            f"/{target}x{target}bb.jpg",
            artwork_url,
            flags=re.IGNORECASE,
        )
        provider_name = "tv_itunes"

    # 2. TVMaze -------------------------------------------------------------
    if not artwork_url:
        artwork_url = await _tvmaze(session, title or search_term)
        if artwork_url:
            provider_name = "tv_tvmaze"

    # 3. Wikipedia channel logo --------------------------------------------
    if not artwork_url and title:
        # Try progressively shorter/cleaned variants of the channel name.
        candidates: list[str] = []
        stripped = _strip_channel_suffix(title)
        if stripped and stripped != title:
            candidates.append(stripped)
        candidates.append(title)

        thumb_width = max(100, int(max(query.artwork_width, query.artwork_height)))
        for candidate in candidates:
            artwork_url = await _wikipedia_logo(session, candidate, thumb_width=thumb_width)
            if artwork_url:
                provider_name = "tv_wikipedia"
                break

    if not artwork_url or not provider_name:
        return None

    result = await _fetch_image(session, artwork_url)
    if not result:
        return None

    image, content_type = result
    _LOGGER.debug("TV provider=%r resolved artwork for %r", provider_name, search_term)
    return ResolvedCover(
        provider=provider_name,
        artwork_url=artwork_url,
        content_type=content_type,
        image=image,
    )
