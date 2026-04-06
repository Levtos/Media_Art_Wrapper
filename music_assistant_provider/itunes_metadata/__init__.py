"""iTunes Metadata Provider for Music Assistant.

Fetches cover art from the Apple iTunes Search API (no API key required).
Primary use-case: fill in missing artwork for radio streams / ICY metadata
where none of the other metadata providers find a match.

To install into Music Assistant, copy the ``itunes_metadata/`` folder into
the ``music_assistant/providers/`` directory of the music-assistant/server
repository and restart the MA server.  The provider will then appear under
Settings → Providers → Metadata and can be enabled from there.
"""
from __future__ import annotations

import re
from typing import Any

import aiohttp

from music_assistant_models.config_entries import ConfigEntry, ProviderConfig
from music_assistant_models.enums import ImageType, ProviderFeature
from music_assistant_models.media_items import (
    Album,
    Artist,
    MediaItemImage,
    MediaItemMetadata,
    Track,
)
from music_assistant_models.provider import ProviderManifest

from music_assistant.models.metadata_provider import MetadataProvider
from music_assistant.models.provider import MusicAssistant, ProviderInstanceType

# ---------------------------------------------------------------------------
# Provider feature declaration
# ---------------------------------------------------------------------------

SUPPORTED_FEATURES: set[ProviderFeature] = {
    ProviderFeature.ARTIST_METADATA,
    ProviderFeature.ALBUM_METADATA,
    ProviderFeature.TRACK_METADATA,
}

# ---------------------------------------------------------------------------
# Module-level setup hooks (required by MA's provider loader)
# ---------------------------------------------------------------------------

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"

# Matches the iTunes CDN size suffix, e.g. "/100x100bb.jpg"
_RE_ARTWORK_SIZE = re.compile(r"/(\d{2,4})x(\d{2,4})bb\.(jpg|png)$", re.IGNORECASE)

# Strips "feat.", "remix", "edit", "mix" annotations from title/artist strings
# before sending them to the iTunes API so we get broader matches.
_RE_PAREN_FEAT = re.compile(r"\((feat\.|featuring|remix|edit|mix).*?\)", re.IGNORECASE)
_RE_BRACKET_FEAT = re.compile(r"\[(feat\.|featuring|remix|edit|mix).*?\]", re.IGNORECASE)
_RE_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")
_RE_SPACES = re.compile(r"\s+")

# Cache artwork lookups for 30 days (iTunes CDN URLs are long-lived).
_CACHE_TTL = 86400 * 30

# Minimum relevance score – below this threshold results are discarded.
_MIN_SCORE_WITH_TITLE = 10
_MIN_SCORE_WITHOUT_TITLE = 4

# Resolution used when requesting artwork from the CDN.
_ARTWORK_SIZE = 600


async def setup(
    mass: MusicAssistant,
    manifest: ProviderManifest,
    config: ProviderConfig,
) -> ProviderInstanceType:
    """Initialise and return a provider instance."""
    return ItunesMetadataProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,
    action: str | None = None,
    values: dict[str, Any] | None = None,
) -> tuple[ConfigEntry, ...]:
    """No user-configurable settings needed (iTunes API is public)."""
    return ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean(s: str) -> str:
    """Normalise a string for fuzzy matching against iTunes results."""
    s = s.strip().lower()
    s = _RE_PAREN_FEAT.sub("", s)
    s = _RE_BRACKET_FEAT.sub("", s)
    s = _RE_NON_ALNUM.sub(" ", s)
    s = _RE_SPACES.sub(" ", s)
    return s.strip()


def _upscale_artwork(url: str, size: int = _ARTWORK_SIZE) -> str:
    """Replace the iTunes CDN size token with the requested resolution."""
    m = _RE_ARTWORK_SIZE.search(url)
    if not m:
        return url
    ext = m.group(3)
    return _RE_ARTWORK_SIZE.sub(f"/{size}x{size}bb.{ext}", url)


def _score_result(q_artist: str, q_title: str, item: dict[str, Any]) -> int:
    """Return a relevance score for an iTunes result dict."""
    r_artist = _clean(str(item.get("artistName", "")))
    r_title = _clean(str(item.get("trackName", item.get("collectionName", ""))))

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

    # Singles tend to be more specific matches than multi-track albums.
    if "single" in str(item.get("collectionName", "")).lower():
        score += 3

    return score


# ---------------------------------------------------------------------------
# Provider implementation
# ---------------------------------------------------------------------------


class ItunesMetadataProvider(MetadataProvider):
    """Metadata provider that resolves cover art via the iTunes Search API.

    The iTunes Search API is completely free and does not require an API key.
    It is particularly effective for current/popular tracks and therefore
    complements the existing MusicBrainz / TheAudioDB providers well for
    radio streams where exact album metadata is often absent.
    """

    async def handle_async_init(self) -> None:
        """Attach the shared MA cache."""
        self.cache = self.mass.cache

    # ------------------------------------------------------------------
    # MetadataProvider interface
    # ------------------------------------------------------------------

    async def get_track_metadata(self, track: Track) -> MediaItemMetadata | None:
        """Return cover art for a track (primary use-case: radio ICY metadata)."""
        artist = track.artists[0].name if track.artists else ""
        artwork_url = await self._find_artwork(
            artist=artist, title=track.name, entity="song"
        )
        if not artwork_url:
            return None
        return _metadata_with_thumb(artwork_url, self.domain)

    async def get_album_metadata(self, album: Album) -> MediaItemMetadata | None:
        """Return cover art for an album."""
        artist = album.artists[0].name if album.artists else ""
        artwork_url = await self._find_artwork(
            artist=artist, title=album.name, entity="album"
        )
        if not artwork_url:
            return None
        return _metadata_with_thumb(artwork_url, self.domain)

    async def get_artist_metadata(self, artist: Artist) -> MediaItemMetadata | None:
        """iTunes does not provide artist images – return None."""
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _find_artwork(
        self,
        *,
        artist: str,
        title: str,
        entity: str,
    ) -> str | None:
        """Query iTunes and return the best-matching artwork URL, or None.

        Results are cached for ``_CACHE_TTL`` seconds so repeated lookups
        for the same track (e.g. a radio station playing the same song again)
        do not generate extra API traffic.
        """
        cache_key = f"itunes_artwork_{entity}_{_clean(artist)}_{_clean(title)}"
        cached: str | None = await self.cache.get(cache_key)
        if cached is not None:
            return cached or None  # empty string means "previously not found"

        url = await self._query_itunes(artist=artist, title=title, entity=entity)

        # Store result (even a "not found" empty string) to avoid re-querying.
        await self.cache.set(cache_key, url or "", expiration=_CACHE_TTL)
        return url

    async def _query_itunes(
        self,
        *,
        artist: str,
        title: str,
        entity: str,
    ) -> str | None:
        q_artist = _clean(artist)
        q_title = _clean(title)
        term = f"{q_artist} {q_title}".strip()
        if not term:
            return None

        params: dict[str, str] = {
            "term": term,
            "entity": entity,
            "media": "music",
            "limit": "15",
        }
        try:
            async with self.mass.http_session.get(
                ITUNES_SEARCH_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                payload: dict[str, Any] = await resp.json(content_type=None)
        except Exception as err:  # noqa: BLE001
            self.logger.debug(
                "iTunes search failed for artist=%r title=%r: %s", artist, title, err
            )
            return None

        results = payload.get("results") if isinstance(payload, dict) else []
        if not isinstance(results, list) or not results:
            return None

        best = max(results, key=lambda item: _score_result(q_artist, q_title, item))
        score = _score_result(q_artist, q_title, best)
        min_score = _MIN_SCORE_WITH_TITLE if q_title else _MIN_SCORE_WITHOUT_TITLE
        if score < min_score:
            self.logger.debug(
                "iTunes: no confident match for artist=%r title=%r (best score %d < %d)",
                artist,
                title,
                score,
                min_score,
            )
            return None

        raw_url = (
            best.get("artworkUrl100")
            or best.get("artworkUrl60")
            or best.get("artworkUrl30")
        )
        if not isinstance(raw_url, str):
            return None

        return _upscale_artwork(raw_url, _ARTWORK_SIZE)


def _metadata_with_thumb(artwork_url: str, provider_domain: str) -> MediaItemMetadata:
    """Wrap an artwork URL in a MediaItemMetadata with a single THUMB image."""
    return MediaItemMetadata(
        images=[
            MediaItemImage(
                type=ImageType.THUMB,
                path=artwork_url,
                provider=provider_domain,
                remotely_accessible=True,
            )
        ]
    )
