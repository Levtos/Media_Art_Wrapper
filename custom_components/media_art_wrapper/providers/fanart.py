"""Fanart.tv provider — TV show and music artist artwork."""
from __future__ import annotations

import logging
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

TVMAZE_SEARCH_URL = "https://api.tvmaze.com/search/shows"
FANART_TV_URL = "https://webservice.fanart.tv/v3/tv/{tvdb_id}"
FANART_MUSIC_URL = "https://webservice.fanart.tv/v3/music/{mbid}"
MUSICBRAINZ_ARTIST_URL = "https://musicbrainz.org/ws/2/artist"
_JSON_KW = {"content_type": None}
_UA = "media-art-wrapper-ha/3.0 (+https://github.com/Levtos/Media_Art_Wrapper)"

# Art type preference order for TV: hdtvlogo > clearlogo > tvposter > tvthumb
_TV_ART_KEYS = ("hdtvlogo", "clearlogo", "tvposter", "tvthumb", "showbackground")
# Art type preference order for music: artistthumb > artistbackground
_MUSIC_ART_KEYS = ("artistthumb", "artistbackground", "albumcover")


def _pick_best(images: list[dict[str, Any]]) -> str | None:
    """Return the URL of the highest-liked image from a fanart.tv image list."""
    if not images:
        return None
    best = max(
        (img for img in images if isinstance(img, dict) and img.get("url")),
        key=lambda x: int(x.get("likes", 0)),
        default=None,
    )
    url = best.get("url") if best else None
    return str(url) if isinstance(url, str) and url else None


class FanartTvProvider(ArtworkProvider):
    """Fanart.tv — high-quality TV show logos/posters and music artist images."""

    categories = frozenset({"streaming", "tv", "music", "auto"})

    def __init__(self, api_key: str) -> None:
        self._api_key = (api_key or "").strip()

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        if query.category in ("music",):
            return await self._fetch_music(session, query)
        return await self._fetch_tv(session, query)

    # ------------------------------------------------------------------
    async def _fetch_tv(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        """Fetch TV show poster/logo via TVMaze TVDB ID → Fanart.tv."""
        title = (query.title or query.series_title or "").strip()
        if not title:
            return None

        # Step 1: Resolve TVDB ID from TVMaze (no key required)
        tvdb_id = await self._tvmaze_tvdb_id(session, title)
        if not tvdb_id:
            return None

        # Step 2: Fetch fanart.tv TV metadata
        url = FANART_TV_URL.format(tvdb_id=tvdb_id)
        try:
            async with session.get(
                url,
                params={"api_key": self._api_key},
                timeout=10,
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("Fanart.tv TV fetch failed for TVDB=%s: %s", tvdb_id, err)
            return None

        if not isinstance(data, dict):
            return None

        # Try art types in preference order
        art_url: str | None = None
        for key in _TV_ART_KEYS:
            images = data.get(key)
            if isinstance(images, list):
                art_url = _pick_best(images)
                if art_url:
                    break

        if not art_url:
            return None

        return await self._download(session, art_url, "fanart_tv")

    # ------------------------------------------------------------------
    async def _fetch_music(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        """Fetch music artist image via MusicBrainz MBID → Fanart.tv."""
        artist = (query.artist or "").strip()
        if not artist:
            return None

        mbid = await self._musicbrainz_artist_mbid(session, artist)
        if not mbid:
            return None

        url = FANART_MUSIC_URL.format(mbid=mbid)
        try:
            async with session.get(
                url,
                params={"api_key": self._api_key},
                timeout=10,
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("Fanart.tv music fetch failed for MBID=%s: %s", mbid, err)
            return None

        if not isinstance(data, dict):
            return None

        art_url: str | None = None
        for key in _MUSIC_ART_KEYS:
            images = data.get(key)
            if isinstance(images, list):
                art_url = _pick_best(images)
                if art_url:
                    break

        if not art_url:
            return None

        return await self._download(session, art_url, "fanart_tv_music")

    # ------------------------------------------------------------------
    async def _tvmaze_tvdb_id(self, session, title: str) -> str | None:
        """Search TVMaze for a show and return its TheTVDB external ID."""
        try:
            async with session.get(
                TVMAZE_SEARCH_URL,
                params={"q": title},
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                results: list[dict[str, Any]] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("TVMaze search failed for %r: %s", title, err)
            return None

        if not isinstance(results, list) or not results:
            return None

        for entry in results:
            if not isinstance(entry, dict):
                continue
            show = entry.get("show")
            if not isinstance(show, dict):
                continue
            externals = show.get("externals") or {}
            tvdb = externals.get("thetvdb")
            if tvdb:
                return str(tvdb)

        return None

    async def _musicbrainz_artist_mbid(self, session, artist: str) -> str | None:
        """Return MusicBrainz artist MBID for the given artist name."""
        try:
            async with session.get(
                MUSICBRAINZ_ARTIST_URL,
                params={"query": f'artist:"{artist}"', "fmt": "json", "limit": "1"},
                headers={"User-Agent": _UA},
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                payload: dict[str, Any] = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("MusicBrainz artist lookup failed for %r: %s", artist, err)
            return None

        artists = payload.get("artists") if isinstance(payload, dict) else None
        if not isinstance(artists, list) or not artists:
            return None
        first = artists[0]
        if not isinstance(first, dict):
            return None
        return first.get("id")

    async def _download(
        self, session, url: str, provider_name: str
    ) -> ArtworkResult | None:
        try:
            async with session.get(url, timeout=10) as resp:
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "image/jpeg")
                image = await resp.read()
        except Exception as err:
            _LOGGER.debug("Fanart.tv image download failed (%s): %s", url, err)
            return None

        if not image:
            return None

        return ArtworkResult(
            provider_name=provider_name,
            image_url=url,
            confidence=0.88,
            image=image,
            content_type=ct,
        )
