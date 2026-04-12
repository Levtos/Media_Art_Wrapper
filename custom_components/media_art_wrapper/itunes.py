from __future__ import annotations

import re
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .models import ResolvedCover, TrackQuery

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
_JSON_KW = {"content_type": None}
_RE_ARTWORK_SIZE = re.compile(r"/(\d{2,4})x(\d{2,4})bb\.(jpg|png)$", re.IGNORECASE)

# Pre-compiled patterns for _clean() – avoids recompilation on every call.
_RE_PAREN_FEAT = re.compile(r"\((feat\.|featuring|ft\.|remix|edit|mix).*?\)", re.IGNORECASE)
_RE_BRACKET_FEAT = re.compile(r"\[(feat\.|featuring|ft\.|remix|edit|mix).*?\]", re.IGNORECASE)
# Strips bare "feat." / "featuring" / "ft." that radio stations embed directly
# in the artist string without surrounding brackets, e.g.
# "Armand Van Helden feat. Mark Knight & D.Ramirez" → "Armand Van Helden"
_RE_BARE_FEAT = re.compile(r"\s+(?:feat\.|featuring|ft\.)\s+.*$", re.IGNORECASE)
_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_SPACES = re.compile(r"\s+")


def _search_term(s: str) -> str:
    """Prepare a string as an iTunes API search term.

    Strips feat./remix annotations (bracketed and bare) and collapses
    whitespace. Non-ASCII characters (Ø, ü, é, …) are intentionally
    preserved so that artist names like 'BRØMANCE' reach the API intact.
    """
    s = s.strip()
    s = _RE_BARE_FEAT.sub("", s)
    s = _RE_PAREN_FEAT.sub("", s)
    s = _RE_BRACKET_FEAT.sub("", s)
    s = _RE_SPACES.sub(" ", s)
    return s.strip()


def _clean(s: str) -> str:
    """Aggressively normalise a string for fuzzy score comparison only.

    Strips all non-alphanumeric characters so that special chars, punctuation
    and different encodings do not prevent a match in _score_result().
    Do NOT use this for building API search terms – use _search_term() instead.
    """
    s = s.strip().lower()
    s = _RE_BARE_FEAT.sub("", s)
    s = _RE_PAREN_FEAT.sub("", s)
    s = _RE_BRACKET_FEAT.sub("", s)
    s = _RE_NON_ALNUM.sub(" ", s)
    s = _RE_SPACES.sub(" ", s)
    return s.strip()


def _score_result(query: TrackQuery, item: dict[str, Any]) -> int:
    q_artist = _clean(query.artist or "")
    q_title = _clean(query.title or "")
    q_album = _clean(query.album or "")

    r_artist = _clean(str(item.get("artistName", "")))
    r_title = _clean(str(item.get("trackName", "")))
    r_album = _clean(str(item.get("collectionName", "")))

    score = 0
    if q_title and r_title:
        if q_title == r_title:
            score += 16
        elif q_title in r_title or r_title in q_title:
            score += 7
        else:
            score -= 8

    if q_artist and r_artist:
        if q_artist == r_artist:
            score += 14
        elif q_artist in r_artist or r_artist in q_artist:
            score += 5
        else:
            score -= 6

    if q_album and r_album:
        if q_album == r_album:
            score += 6
        elif q_album in r_album or r_album in q_album:
            score += 3

    if "single" in r_album:
        score += 3

    if str(item.get("wrapperType", "")).lower() == "track":
        score += 1

    return score


def _upscale_artwork(url: str, size: int) -> str:
    m = _RE_ARTWORK_SIZE.search(url)
    if not m:
        return url
    ext = m.group(3)
    return _RE_ARTWORK_SIZE.sub(f"/{size}x{size}bb.{ext}", url)


async def _search_itunes(session, term: str) -> list[dict[str, Any]]:
    params = {
        "term": term,
        "entity": "song",
        "media": "music",
        "limit": "15",
    }
    async with session.get(ITUNES_SEARCH_URL, params=params, timeout=10) as resp:
        resp.raise_for_status()
        payload = await resp.json(**_JSON_KW)
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


async def async_itunes_resolve(*, session, query: TrackQuery) -> ResolvedCover | None:
    if not (query.artist or query.title):
        return None

    terms: list[str] = []
    term1 = " ".join([p for p in [_search_term(query.artist or ""), _search_term(query.title or "")] if p])
    if term1:
        terms.append(term1)
    term2 = " ".join([p for p in [_search_term(query.title or ""), _search_term(query.artist or "")] if p])
    if term2 and term2 != term1:
        terms.append(term2)
    if query.title:
        terms.append(f"{_search_term(query.artist or '')} {_search_term(query.title or '')} single".strip())

    try:
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for term in terms:
            for item in await _search_itunes(session, term):
                item_id = str(item.get("trackId") or item.get("collectionId") or id(item))
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                results.append(item)
    except Exception as err:
        raise HomeAssistantError(f"iTunes search failed: {err}") from err

    if not results:
        return None

    best: dict[str, Any] | None = None
    best_score = -999
    for item in results:
        score = _score_result(query, item)
        if score > best_score:
            best_score = score
            best = item

    # When both artist and title are known, require a stronger match so that
    # a correct title with a completely wrong artist cannot slip through.
    # A title-only exact match scores 16 − 6 (artist penalty) = 10, which
    # is enough to pass the old threshold of 10 — raising to 12 closes that
    # gap without affecting genuine matches (those score 21+).
    if query.artist and query.title:
        minimum_score = 12
    elif query.title:
        minimum_score = 10
    else:
        minimum_score = 4
    if not best or best_score < minimum_score:
        return None

    artwork = best.get("artworkUrl100") or best.get("artworkUrl60") or best.get("artworkUrl30")
    if not isinstance(artwork, str) or not artwork:
        return None

    target_size = max(100, int(max(query.artwork_width, query.artwork_height)))
    artwork_url = _upscale_artwork(artwork, target_size)

    try:
        async with session.get(artwork_url, timeout=10) as img_resp:
            img_resp.raise_for_status()
            content_type = img_resp.headers.get("Content-Type", "image/jpeg")
            image = await img_resp.read()
    except Exception as err:
        raise HomeAssistantError(f"iTunes artwork fetch failed: {err}") from err

    if not image:
        return None

    return ResolvedCover(
        provider="itunes",
        artwork_url=artwork_url,
        content_type=content_type,
        image=image,
    )
