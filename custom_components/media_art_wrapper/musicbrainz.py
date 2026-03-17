from __future__ import annotations

import logging
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .models import ResolvedCover, TrackQuery

_LOGGER = logging.getLogger(__name__)

MB_SEARCH_URL = "https://musicbrainz.org/ws/2/recording"
CAA_FRONT_URL = "https://coverartarchive.org/release/{release_id}/front-500"
_JSON_KW = {"content_type": None}


async def async_musicbrainz_resolve(*, session, query: TrackQuery) -> ResolvedCover | None:
    if not (query.artist or query.title):
        return None

    fragments: list[str] = []
    if query.title:
        fragments.append(f'recording:"{query.title}"')
    if query.artist:
        fragments.append(f'artist:"{query.artist}"')
    mb_query = " AND ".join(fragments)

    params = {
        "query": mb_query,
        "fmt": "json",
        "limit": "5",
    }

    headers = {
        # MusicBrainz asks for a descriptive User-Agent
        "User-Agent": "media-art-wrapper-ha/1.0.0 (+https://github.com/Levtos/Media_Art_Wrapper)",
    }

    try:
        async with session.get(MB_SEARCH_URL, params=params, headers=headers, timeout=10) as resp:
            resp.raise_for_status()
            payload = await resp.json(**_JSON_KW)
    except Exception as err:
        raise HomeAssistantError(f"MusicBrainz search failed: {err}") from err

    recordings = payload.get("recordings") if isinstance(payload, dict) else None
    if not isinstance(recordings, list) or not recordings:
        return None

    release_id: str | None = None
    for rec in recordings:
        if not isinstance(rec, dict):
            continue
        releases = rec.get("releases")
        if not isinstance(releases, list):
            continue
        for rel in releases:
            if not isinstance(rel, dict):
                continue
            rel_id = rel.get("id")
            if isinstance(rel_id, str) and rel_id:
                release_id = rel_id
                break
        if release_id:
            break

    if not release_id:
        return None

    artwork_url = CAA_FRONT_URL.format(release_id=release_id)

    try:
        async with session.get(artwork_url, timeout=10) as img_resp:
            if img_resp.status >= 400:
                return None
            content_type = img_resp.headers.get("Content-Type", "image/jpeg")
            image = await img_resp.read()
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("MusicBrainz artwork fetch failed for %s: %s", artwork_url, err)
        return None

    if not image:
        return None

    return ResolvedCover(
        provider="musicbrainz",
        artwork_url=artwork_url,
        content_type=content_type,
        image=image,
    )
