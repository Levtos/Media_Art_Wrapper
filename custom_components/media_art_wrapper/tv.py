from __future__ import annotations

import logging
import re
from typing import Any

from .epg import async_get_current_program
from .models import ResolvedCover, TrackQuery

_LOGGER = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
TVMAZE_SEARCH_URL = "https://api.tvmaze.com/search/shows"
WIKIPEDIA_API_URL = "https://{lang}.wikipedia.org/w/api.php"

# Wikipedia list page for European public-broadcasting HD channels.
# Contains a curated logo for every ÖRR/public-TV channel – used as the
# primary logo source before falling back to individual article lookups.
_OERR_LIST_PAGE = "Liste der öffentlich-rechtlichen HD-Programme in Europa"

_JSON_KW = {"content_type": None}

# Module-level cache: stores the image-title list fetched from the ÖRR list
# page so we only hit the API once per HA session.
_oerr_image_cache: list[str] | None = None

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

# Filenames containing any of these words are very unlikely to be the *current* logo.
_LOGO_EXCLUDE = {
    # Geography / maps
    "karte", "map", "germany", "deutschland",
    # Buildings / locations
    "studio", "gebäude", "building", "headquarters", "sitz", "standort",
    # People / photography
    "portrait", "foto", "photo", "bild", "picture",
    # Historical / old versions – e.g. "Alte_ZDF_Logos.svg"
    "alte", "altes", "alter", "alten", "ehemals", "ehemalig", "ehemalige",
    "former", "historical", "history", "old", "variation", "variante",
    "varianten", "uebersicht", "übersicht", "sammlung", "collection",
}

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


async def _fetch_oerr_images(session) -> list[str]:
    """Return (and cache) all image titles from the ÖRR HD list page.

    The list is fetched once per HA session and stored in _oerr_image_cache.
    Every image on that page is a channel logo, so no further exclusion
    filtering is needed when using it as a source.
    """
    global _oerr_image_cache
    if _oerr_image_cache is not None:
        return _oerr_image_cache

    api_url = WIKIPEDIA_API_URL.format(lang="de")
    params = {
        "action": "query",
        "titles": _OERR_LIST_PAGE,
        "prop": "images",
        "imlimit": "500",
        "format": "json",
    }
    try:
        async with session.get(api_url, params=params, timeout=15) as resp:
            resp.raise_for_status()
            payload = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("ÖRR list page fetch failed: %s", err)
        _oerr_image_cache = []
        return []

    pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
    images: list[str] = []
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        for img in page.get("images") or []:
            t = img.get("title")
            if isinstance(t, str) and t:
                images.append(t)

    _oerr_image_cache = images
    _LOGGER.debug("ÖRR list page: cached %d image titles", len(images))
    return images


async def _oerr_list_logo(session, channel_name: str, thumb_width: int) -> str | None:
    """Search the ÖRR HD list page for a logo matching *channel_name*.

    Because every image on that page is already a channel logo, we skip the
    exclusion list and only need a positive token match. The stripped channel
    name (e.g. 'WDR' from 'WDR HD Wuppertal') is matched against image
    filenames; the highest-scoring image is resolved via the Commons API.
    """
    images = await _fetch_oerr_images(session)
    if not images:
        return None

    channel_tokens = _clean(channel_name).split()
    best_score = 0
    best_file: str | None = None

    for img_title in images:
        fn = img_title.lower()
        fn = re.sub(r"^(file|datei):", "", fn).strip()

        score = 0
        # Token match: every channel token found in filename adds points.
        matched = sum(1 for tok in channel_tokens if len(tok) >= 2 and tok in fn)
        if matched == 0:
            continue
        score += matched * 2
        if any(boost in fn for boost in _LOGO_BOOST):
            score += 3
        if fn.endswith(".svg"):
            score += 1

        if score > best_score:
            best_score = score
            best_file = img_title

    if not best_file:
        return None

    _LOGGER.debug("ÖRR list: matched %r (score=%d) for channel %r", best_file, best_score, channel_name)
    return await _resolve_commons_url(session, best_file, thumb_width)


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
      0. EPG (TVMaze DE schedule) – if the title looks like a channel name,
         look up what's currently airing and use that program's artwork.
         If the EPG returns a show title but no image, that title is fed into
         the artwork searches below instead of the raw channel name.
      1. iTunes TV (tvShow + movie entity) – matches show/movie names.
      2. TVMaze show search – TV shows, freely accessible without API key.
      3. Channel logo lookup:
         3a. ÖRR HD list page (curated, Europe-wide public broadcasters).
         3b. Generic Wikipedia article lookup as final fallback.
    """
    title = (query.title or "").strip()
    artist = (query.artist or "").strip()
    search_term = " ".join(filter(None, [title, artist]))

    if not search_term:
        return None

    artwork_url: str | None = None
    provider_name: str | None = None

    # The "effective" search term used for iTunes/TVMaze show searches.
    # May be replaced with the EPG program title when available.
    effective_search = search_term

    # 0. EPG lookup ---------------------------------------------------------
    # Only useful when the title contains a broadcast-technical suffix (HD/SD)
    # or when artist is absent – both are strong indicators of a channel name.
    stripped_title = _strip_channel_suffix(title)
    is_channel_name = stripped_title != title or not artist
    if is_channel_name and title:
        epg = await async_get_current_program(session, stripped_title or title)
        if epg:
            if epg.get("image_url"):
                # Use the programme image directly.
                artwork_url = epg["image_url"]
                provider_name = "tv_epg"
                _LOGGER.debug(
                    "EPG hit: channel=%r → programme=%r image=%r",
                    title, epg.get("show_name") or epg.get("title"), artwork_url,
                )
            elif epg.get("show_name") or epg.get("title"):
                # No image but we have a title – use it for artwork searches.
                effective_search = epg.get("show_name") or epg.get("title") or search_term
                _LOGGER.debug(
                    "EPG title redirect: channel=%r → search=%r",
                    title, effective_search,
                )

    # 1. iTunes TV ----------------------------------------------------------
    if not artwork_url:
        artwork_url = await _itunes_tv(session, effective_search, match_name=effective_search)
        if artwork_url:
            target = max(100, int(max(query.artwork_width, query.artwork_height)))
            artwork_url = re.sub(
                r"/(\d{2,4})x(\d{2,4})bb\.(jpg|png)$",
                f"/{target}x{target}bb.jpg",
                artwork_url,
                flags=re.IGNORECASE,
            )
            provider_name = "tv_itunes"

    # 2. TVMaze show search -------------------------------------------------
    if not artwork_url:
        artwork_url = await _tvmaze(session, effective_search)
        if artwork_url:
            provider_name = "tv_tvmaze"

    # 3. Channel logo lookup -----------------------------------------------
    if not artwork_url and title:
        thumb_width = max(100, int(max(query.artwork_width, query.artwork_height)))
        stripped = _strip_channel_suffix(title)

        # 3a. ÖRR HD list page (curated, Europe-wide public broadcasters).
        #     Try stripped name first (e.g. "WDR"), then full title.
        for candidate in dict.fromkeys(filter(None, [stripped, title])):
            artwork_url = await _oerr_list_logo(session, candidate, thumb_width)
            if artwork_url:
                provider_name = "tv_wikipedia_oerr"
                break

        # 3b. Generic Wikipedia article lookup as final fallback.
        if not artwork_url:
            for candidate in dict.fromkeys(filter(None, [stripped, title])):
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
