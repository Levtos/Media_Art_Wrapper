"""MusicBrainz + Cover Art Archive provider."""
from __future__ import annotations

import logging

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

MB_SEARCH_URL = "https://musicbrainz.org/ws/2/recording"
CAA_FRONT_URL = "https://coverartarchive.org/release/{release_id}/front-500"
_JSON_KW = {"content_type": None}
_UA = "media-art-wrapper-ha/3.0 (+https://github.com/Levtos/Media_Art_Wrapper)"


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
        if not isinstance(recordings, list):
            return None

        release_id: str | None = None
        for rec in recordings:
            if not isinstance(rec, dict):
                continue
            for rel in rec.get("releases") or []:
                rid = rel.get("id") if isinstance(rel, dict) else None
                if isinstance(rid, str) and rid:
                    release_id = rid
                    break
            if release_id:
                break

        if not release_id:
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
            confidence=0.85,
            image=image,
            content_type=ct,
        )
