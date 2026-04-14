"""iTunes Search API provider — music and TV/movie artwork."""
from __future__ import annotations

import re
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
_JSON_KW = {"content_type": None}
_RE_ARTWORK_SIZE = re.compile(r"/(\d{2,4})x(\d{2,4})bb\.(jpg|png)$", re.IGNORECASE)

_RE_PAREN_FEAT = re.compile(r"\((feat\.|featuring|ft\.|remix|edit|mix).*?\)", re.IGNORECASE)
_RE_BRACKET_FEAT = re.compile(r"\[(feat\.|featuring|ft\.|remix|edit|mix).*?\]", re.IGNORECASE)
_RE_BARE_FEAT = re.compile(r"\s+(?:feat\.|featuring|ft\.)\s+.*$", re.IGNORECASE)
_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_SPACES = re.compile(r"\s+")


def _search_term(s: str) -> str:
    s = s.strip()
    s = _RE_BARE_FEAT.sub("", s)
    s = _RE_PAREN_FEAT.sub("", s)
    s = _RE_BRACKET_FEAT.sub("", s)
    return _RE_SPACES.sub(" ", s).strip()


def _clean_score(s: str) -> str:
    s = s.strip().lower()
    s = _RE_BARE_FEAT.sub("", s)
    s = _RE_PAREN_FEAT.sub("", s)
    s = _RE_BRACKET_FEAT.sub("", s)
    s = _RE_NON_ALNUM.sub(" ", s)
    return _RE_SPACES.sub(" ", s).strip()


def _score_music(query: ArtworkQuery, item: dict[str, Any]) -> int:
    q_artist = _clean_score(query.artist or "")
    q_title = _clean_score(query.title or "")
    q_album = _clean_score(query.album or "")
    r_artist = _clean_score(str(item.get("artistName", "")))
    r_title = _clean_score(str(item.get("trackName", "")))
    r_album = _clean_score(str(item.get("collectionName", "")))
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


def _upscale(url: str, size: int) -> str:
    m = _RE_ARTWORK_SIZE.search(url)
    if not m:
        return url
    return _RE_ARTWORK_SIZE.sub(f"/{size}x{size}bb.{m.group(3)}", url)


async def _search(session, term: str, entity: str = "song", media: str = "music") -> list[dict[str, Any]]:
    params = {"term": term, "entity": entity, "media": media, "limit": "15"}
    async with session.get(ITUNES_SEARCH_URL, params=params, timeout=10) as resp:
        resp.raise_for_status()
        payload = await resp.json(**_JSON_KW)
    results = payload.get("results") if isinstance(payload, dict) else None
    return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []


class ITunesProvider(ArtworkProvider):
    """iTunes Search API — music tracks, TV shows, movies."""

    categories = frozenset({"music", "auto"})

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        if not (query.artist or query.title):
            return None

        category = query.category
        if category in ("streaming", "tv"):
            return await self._fetch_video(session, query)
        return await self._fetch_music(session, query)

    # ------------------------------------------------------------------
    async def _fetch_music(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        terms = []
        t1 = " ".join(filter(None, [_search_term(query.artist or ""), _search_term(query.title or "")]))
        if t1:
            terms.append(t1)
        t2 = " ".join(filter(None, [_search_term(query.title or ""), _search_term(query.artist or "")]))
        if t2 and t2 != t1:
            terms.append(t2)
        if query.title:
            single = f"{_search_term(query.artist or '')} {_search_term(query.title)} single".strip()
            terms.append(single)

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for term in terms:
            try:
                for item in await _search(session, term, entity="song", media="music"):
                    iid = str(item.get("trackId") or item.get("collectionId") or id(item))
                    if iid not in seen:
                        seen.add(iid)
                        results.append(item)
            except Exception:
                pass

        if not results:
            return None

        best = max(results, key=lambda r: _score_music(query, r))
        best_score = _score_music(query, best)
        min_score = 12 if (query.artist and query.title) else (10 if query.title else 4)
        if best_score < min_score:
            return None

        artwork = best.get("artworkUrl100") or best.get("artworkUrl60") or best.get("artworkUrl30")
        if not isinstance(artwork, str):
            return None

        target = max(100, int(max(query.artwork_width, query.artwork_height)))
        url = _upscale(artwork, target)
        try:
            async with session.get(url, timeout=10) as r:
                r.raise_for_status()
                ct = r.headers.get("Content-Type", "image/jpeg")
                image = await r.read()
        except Exception:
            return None

        return ArtworkResult(
            provider_name="itunes",
            image_url=url,
            confidence=min(1.0, best_score / 30),
            image=image,
            content_type=ct,
        )

    # ------------------------------------------------------------------
    async def _fetch_video(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        """Fetch TV/movie artwork (used internally by TVMazeProvider cascade)."""
        term = query.title or ""
        if not term:
            return None

        try:
            results = await _search(session, term, entity="tvShow,movie", media="video")
        except Exception:
            return None

        def _name_overlap(a: str, b: str) -> bool:
            ca = _clean_score(a)
            cb = _clean_score(b)
            return bool(ca and cb and (ca in cb or cb in ca))

        for item in results:
            result_name = str(item.get("trackName") or item.get("collectionName") or "")
            if not _name_overlap(term, result_name):
                continue
            artwork = item.get("artworkUrl100") or item.get("artworkUrl60") or item.get("artworkUrl30")
            if not isinstance(artwork, str):
                continue
            target = max(100, int(max(query.artwork_width, query.artwork_height)))
            url = re.sub(
                r"/(\d{2,4})x(\d{2,4})bb\.(jpg|png)$",
                f"/{target}x{target}bb.jpg",
                artwork,
                flags=re.IGNORECASE,
            )
            try:
                async with session.get(url, timeout=10) as r:
                    r.raise_for_status()
                    ct = r.headers.get("Content-Type", "image/jpeg")
                    image = await r.read()
                    if image:
                        return ArtworkResult(
                            provider_name="itunes_tv",
                            image_url=url,
                            confidence=0.7,
                            image=image,
                            content_type=ct,
                        )
            except Exception:
                continue

        return None
