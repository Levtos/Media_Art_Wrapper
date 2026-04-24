"""TVMaze + EPG + Wikipedia provider — TV channel/show artwork."""
from __future__ import annotations

import logging
import re
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult
from .epg_base import _episode_image_url, get_schedule_program

_LOGGER = logging.getLogger(__name__)

TVMAZE_SEARCH_URL = "https://api.tvmaze.com/search/shows"
TVMAZE_EPISODES_BY_DATE_URL = "https://api.tvmaze.com/shows/{show_id}/episodesbydate"
WIKIPEDIA_API_URL = "https://{lang}.wikipedia.org/w/api.php"
_COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"

# ÖRR curated HD channel list page (German public broadcasters)
_OERR_LIST_PAGE = "Liste der öffentlich-rechtlichen HD-Programme in Europa"

_JSON_KW = {"content_type": None}

# Module-level caches
_oerr_image_cache: list[str] | None = None
# Search result cache keyed by query term — prevents duplicate API calls when
# both _tvmaze_show_id and _tvmaze_show_image are invoked for the same term.
_show_search_cache: dict[str, list[Any]] = {}
_SHOW_SEARCH_CACHE_MAX = 128

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_SPACES = re.compile(r"\s+")

# Filenames containing these words are unlikely to be the *current* logo.
_LOGO_EXCLUDE = {
    "karte", "map", "germany", "deutschland",
    "studio", "gebäude", "building", "headquarters", "sitz", "standort",
    "portrait", "foto", "photo", "bild", "picture",
    "alte", "altes", "alter", "alten", "ehemals", "ehemalig", "ehemalige",
    "former", "historical", "history", "old", "variation", "variante",
    "varianten", "uebersicht", "übersicht", "sammlung", "collection",
}
_LOGO_BOOST = {"logo", "dachmarke", "wortmarke", "signet", "icon", "emblem"}


def _clean(s: str) -> str:
    s = s.strip().lower()
    s = _RE_NON_ALNUM.sub(" ", s)
    return _RE_SPACES.sub(" ", s).strip()


def _names_overlap(a: str, b: str) -> bool:
    ca, cb = _clean(a), _clean(b)
    return bool(ca and cb and (ca in cb or cb in ca))


# ---------------------------------------------------------------------------
# TVMaze show search
# ---------------------------------------------------------------------------

async def _tvmaze_search_shows(session, term: str) -> list[Any]:
    """Return the raw TVMaze show-search response for *term*, cached per term."""
    if term in _show_search_cache:
        return _show_search_cache[term]
    try:
        async with session.get(
            TVMAZE_SEARCH_URL, params={"q": term}, timeout=10
        ) as resp:
            resp.raise_for_status()
            results = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("TVMaze show search failed for %r: %s", term, err)
        results = []

    if not isinstance(results, list):
        results = []

    if len(_show_search_cache) >= _SHOW_SEARCH_CACHE_MAX:
        _show_search_cache.pop(next(iter(_show_search_cache)))
    _show_search_cache[term] = results
    return results


async def _tvmaze_show_image(session, term: str) -> str | None:
    results = await _tvmaze_search_shows(session, term)
    if not results:
        return None

    best = results[0]
    if not isinstance(best, dict):
        return None
    show = best.get("show")
    if not isinstance(show, dict):
        return None

    show_name = str(show.get("name") or "")
    if not _names_overlap(term, show_name):
        return None

    image_data = show.get("image")
    if not isinstance(image_data, dict):
        return None
    url = image_data.get("original") or image_data.get("medium")
    return str(url) if isinstance(url, str) and url else None


# ---------------------------------------------------------------------------
# TVMaze episodesbydate helpers
# ---------------------------------------------------------------------------

async def _tvmaze_episode_by_date(
    session, show_id: int, today: str
) -> dict[str, Any] | None:
    """Return the first episode airing on *today* for *show_id*."""
    try:
        async with session.get(
            TVMAZE_EPISODES_BY_DATE_URL.format(show_id=show_id),
            params={"date": today},
            timeout=10,
        ) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            episodes = await resp.json(**_JSON_KW)
    except Exception as err:
        _LOGGER.debug("TVMaze episodesbydate failed for show %s: %s", show_id, err)
        return None

    if not isinstance(episodes, list) or not episodes:
        return None
    return episodes[0] if isinstance(episodes[0], dict) else None


async def _tvmaze_show_id(session, term: str) -> tuple[int | None, str | None]:
    """Return (show_id, show_image_url) for the best-matching TVMaze show."""
    results = await _tvmaze_search_shows(session, term)
    if not results:
        return None, None

    best = results[0]
    if not isinstance(best, dict):
        return None, None
    show = best.get("show")
    if not isinstance(show, dict):
        return None, None

    show_name = str(show.get("name") or "")
    if not _names_overlap(term, show_name):
        return None, None

    show_id = show.get("id")
    image_data = show.get("image")
    show_img = None
    if isinstance(image_data, dict):
        url = image_data.get("original") or image_data.get("medium")
        show_img = str(url) if isinstance(url, str) and url else None

    return (int(show_id) if isinstance(show_id, int) else None), show_img


# ---------------------------------------------------------------------------
# Wikipedia / Wikimedia Commons logo lookup
# ---------------------------------------------------------------------------

def _score_image_file(filename: str, channel_tokens: list[str]) -> int:
    fn = filename.lower()
    fn = re.sub(r"^(file|datei):", "", fn).strip()

    if any(excl in fn for excl in _LOGO_EXCLUDE):
        return -1

    score = 0
    if any(boost in fn for boost in _LOGO_BOOST):
        score += 3
    if any(tok in fn for tok in channel_tokens if len(tok) >= 2):
        score += 2
    if fn.endswith(".svg"):
        score += 1
    return score


async def _resolve_commons_url(session, file_title: str, thumb_width: int) -> str | None:
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
    global _oerr_image_cache
    if _oerr_image_cache is not None:
        return _oerr_image_cache

    api_url = WIKIPEDIA_API_URL.format(lang="de")
    try:
        async with session.get(
            api_url,
            params={
                "action": "query",
                "titles": _OERR_LIST_PAGE,
                "prop": "images",
                "imlimit": "500",
                "format": "json",
            },
            timeout=15,
        ) as resp:
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
    return images


async def _oerr_list_logo(session, channel_name: str, thumb_width: int) -> str | None:
    images = await _fetch_oerr_images(session)
    if not images:
        return None

    channel_tokens = _clean(channel_name).split()
    best_score = 0
    best_file: str | None = None

    for img_title in images:
        fn = img_title.lower()
        fn = re.sub(r"^(file|datei):", "", fn).strip()

        matched = sum(1 for tok in channel_tokens if len(tok) >= 2 and tok in fn)
        if matched == 0:
            continue
        score = matched * 2
        if any(boost in fn for boost in _LOGO_BOOST):
            score += 3
        if fn.endswith(".svg"):
            score += 1

        if score > best_score:
            best_score = score
            best_file = img_title

    if not best_file:
        return None
    return await _resolve_commons_url(session, best_file, thumb_width)


async def _wikipedia_logo(session, title: str, thumb_width: int = 600) -> str | None:
    channel_tokens = _clean(title).split()

    for lang in ("de", "en"):
        api_url = WIKIPEDIA_API_URL.format(lang=lang)
        try:
            async with session.get(
                api_url,
                params={
                    "action": "query",
                    "titles": title,
                    "prop": "images",
                    "imlimit": "30",
                    "format": "json",
                    "redirects": 1,
                },
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("Wikipedia (%s) lookup failed for %r: %s", lang, title, err)
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

        best_score = 0
        best_file: str | None = None
        for img_title in image_titles:
            score = _score_image_file(img_title, channel_tokens)
            if score > best_score:
                best_score = score
                best_file = img_title

        if not best_file:
            continue

        url = await _resolve_commons_url(session, best_file, thumb_width)
        if url:
            return url

    return None


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------

class TVMazeProvider(ArtworkProvider):
    """TV artwork via EPG + TVMaze show search + Wikipedia channel logos.

    Search order:
      1. EPG (TVMaze DE schedule) — if title looks like a channel name,
         find what's currently airing and use that programme's image.
         If EPG returns a title but no image, use it for subsequent searches.
      2. TVMaze show search — free, no API key.
      3. ÖRR HD list page (curated, Europe-wide public broadcasters).
      4. Generic Wikipedia article logo lookup.
    """

    categories = frozenset({"tv", "auto"})

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        thumb_width = max(100, int(max(query.artwork_width, query.artwork_height)))
        effective_search = title
        artwork_url: str | None = None
        provider_name: str | None = None

        # Strip broadcast-technical suffix for channel matching
        from .query_builder import _strip_channel
        stripped_title = _strip_channel(title)

        # 1. EPG lookup -------------------------------------------------------
        # Only when the title has a broadcast suffix (HD/SD) or no artist
        # is set — both are strong signals of a channel name rather than a show.
        is_channel_name = stripped_title != title or not (query.artist or "").strip()
        if is_channel_name and title:
            epg = await get_schedule_program(session, stripped_title or title)
            if epg:
                if epg.image_url:
                    artwork_url = epg.image_url
                    provider_name = "tv_epg"
                    _LOGGER.debug(
                        "EPG hit: channel=%r → programme=%r image=%r",
                        title, epg.show_name or epg.title, artwork_url,
                    )
                elif epg.show_name or epg.title:
                    effective_search = epg.show_name or epg.title or title
                    _LOGGER.debug(
                        "EPG title redirect: channel=%r → search=%r", title, effective_search
                    )

        # 2. TVMaze show search (+ episodesbydate when subtitle_hint available) -
        if not artwork_url:
            subtitle = (query.subtitle_hint or "").strip()
            if subtitle:
                # Try to get episode-specific image via episodesbydate
                from datetime import date as _date
                today_str = _date.today().isoformat()
                show_id, show_img = await _tvmaze_show_id(session, effective_search)
                if show_id is not None:
                    ep = await _tvmaze_episode_by_date(session, show_id, today_str)
                    if ep:
                        ep_img = _episode_image_url(ep)
                        if ep_img:
                            artwork_url = ep_img
                            provider_name = "tv_tvmaze_episode"
                            _LOGGER.debug(
                                "TVMaze episodesbydate hit: show_id=%s today=%s img=%s",
                                show_id, today_str, ep_img,
                            )
                    if not artwork_url and show_img:
                        # Episode found but no image → use show poster
                        artwork_url = show_img
                        provider_name = "tv_tvmaze"
            if not artwork_url:
                artwork_url = await _tvmaze_show_image(session, effective_search)
                if artwork_url:
                    provider_name = "tv_tvmaze"

        # 3. Channel logo lookup ---------------------------------------------
        if not artwork_url and title:
            for candidate in dict.fromkeys(filter(None, [stripped_title, title])):
                artwork_url = await _oerr_list_logo(session, candidate, thumb_width)
                if artwork_url:
                    provider_name = "tv_wikipedia_oerr"
                    break

            if not artwork_url:
                for candidate in dict.fromkeys(filter(None, [stripped_title, title])):
                    artwork_url = await _wikipedia_logo(session, candidate, thumb_width=thumb_width)
                    if artwork_url:
                        provider_name = "tv_wikipedia"
                        break

        if not artwork_url or not provider_name:
            return None

        # Download the resolved image
        try:
            async with session.get(artwork_url, timeout=10) as resp:
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "image/jpeg")
                image = await resp.read()
        except Exception as err:
            _LOGGER.debug("TVMaze provider image download failed (%s): %s", artwork_url, err)
            return None

        if not image:
            return None

        return ArtworkResult(
            provider_name=provider_name,
            image_url=artwork_url,
            confidence=0.80,
            image=image,
            content_type=ct,
        )
