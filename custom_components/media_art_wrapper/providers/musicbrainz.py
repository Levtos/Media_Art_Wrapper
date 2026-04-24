"""MusicBrainz + Cover Art Archive provider."""
from __future__ import annotations

import logging
import re
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

MB_SEARCH_URL = "https://musicbrainz.org/ws/2/recording"
CAA_FRONT_URL = "https://coverartarchive.org/release/{release_id}/front-500"
_JSON_KW = {"content_type": None}
_UA = "media-art-wrapper-ha/3.0 (+https://github.com/Levtos/Media_Art_Wrapper)"

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_SPACES = re.compile(r"\s+")


def _clean(s: str) -> str:
    s = _RE_NON_ALNUM.sub(" ", s.lower())
    return _RE_SPACES.sub(" ", s).strip()


def _score_recording(query: ArtworkQuery, rec: dict[str, Any]) -> int:
    """Score a MusicBrainz recording against the query.

    Combines MB's Lucene search score (0-100) with explicit title/artist
    overlap checks so mismatched results are penalised even when MB
    returned them with a high search score.
    """
    mb_score = rec.get("score")
    base = int(mb_score) if isinstance(mb_score, int) else 0

    q_title = _clean(query.title or "")
    q_artist = _clean(query.artist or "")
    r_title = _clean(str(rec.get("title", "")))

    artist_credits = rec.get("artist-credit") or []
    r_artist = ""
    if isinstance(artist_credits, list) and artist_credits:
        first = artist_credits[0]
        if isinstance(first, dict):
            artist = first.get("artist") or {}
            r_artist = _clean(str(artist.get("name", "") if isinstance(artist, dict) else ""))
            if not r_artist:
                r_artist = _clean(str(first.get("name", "")))

    bonus = 0
    if q_title and r_title:
        if q_title == r_title:
            bonus += 20
        elif q_title in r_title or r_title in q_title:
            bonus += 8
        else:
            bonus -= 15
    if q_artist and r_artist:
        if q_artist == r_artist:
            bonus += 15
        elif q_artist in r_artist or r_artist in q_artist:
            bonus += 6
        else:
            bonus -= 10

    return base + bonus


class MusicBrainzProvider(ArtworkProvider):
    """MusicBrainz recording search + Cover Art Archive image fetch."""

    categories = frozenset({"music", "auto"})

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        if not (query.artist or query.title):
            return None

        fragments: list[str] = []
        if query.title:
            fragments.append(f'recording:"{query.title}"')
        if query.artist:
            fragments.append(f'artist:"{query.artist}"')
        mb_query = " AND ".join(fragments)

        try:
            async with session.get(
                MB_SEARCH_URL,
                params={"query": mb_query, "fmt": "json", "limit": "5"},
                headers={"User-Agent": _UA},
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("MusicBrainz search failed: %s", err)
            return None

        recordings = payload.get("recordings") if isinstance(payload, dict) else None
        if not isinstance(recordings, list) or not recordings:
            return None

        # Rank all recordings by match score before settling on a release
        scored = [
            (_score_recording(query, rec), rec)
            for rec in recordings
            if isinstance(rec, dict)
        ]
        scored.sort(key=lambda t: t[0], reverse=True)

        MIN_SCORE = 50  # MB base score ~50+ for plausible matches
        best_score: int | None = None
        release_id: str | None = None
        for score, rec in scored:
            if score < MIN_SCORE:
                break
            for rel in rec.get("releases") or []:
                rid = rel.get("id") if isinstance(rel, dict) else None
                if isinstance(rid, str) and rid:
                    release_id = rid
                    best_score = score
                    break
            if release_id:
                break

        if not release_id or best_score is None:
            return None

        url = CAA_FRONT_URL.format(release_id=release_id)
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status >= 400:
                    return None
                ct = resp.headers.get("Content-Type", "image/jpeg")
                image = await resp.read()
        except Exception as err:
            _LOGGER.debug("Cover Art Archive fetch failed: %s", err)
            return None

        if not image:
            return None

        return ArtworkResult(
            provider_name="musicbrainz",
            image_url=url,
            confidence=min(1.0, best_score / 130),
            image=image,
            content_type=ct,
        )
