from __future__ import annotations

import logging
from dataclasses import replace
from typing import Iterable

from .const import PROVIDER_ITUNES, PROVIDER_MUSICBRAINZ, PROVIDER_TV
from .itunes import async_itunes_resolve
from .models import ResolvedCover, TrackQuery
from .musicbrainz import async_musicbrainz_resolve
from .tv import async_tv_resolve

_LOGGER = logging.getLogger(__name__)


async def _try_providers(
    *,
    session,
    query: TrackQuery,
    provider_list: list[str],
) -> ResolvedCover | None:
    """Try each provider once with the given query. Returns first match or None."""
    for provider in provider_list:
        try:
            if provider == PROVIDER_ITUNES:
                resolved = await async_itunes_resolve(session=session, query=query)
                if resolved:
                    return resolved
                continue

            if provider == PROVIDER_MUSICBRAINZ:
                resolved = await async_musicbrainz_resolve(session=session, query=query)
                if resolved:
                    return resolved
                continue

            if provider == PROVIDER_TV:
                resolved = await async_tv_resolve(session=session, query=query)
                if resolved:
                    return resolved
                continue

            _LOGGER.debug("Unknown provider '%s' (skipping)", provider)

        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Provider '%s' failed (title=%r): %s", provider, query.title, err)

    return None


async def async_resolve_cover(*, session, query: TrackQuery, providers: Iterable[str]) -> ResolvedCover | None:
    """Resolve cover art with a staged title fallback strategy.

    Stage 1 – original title (e.g. "Song (Remix)"): lets providers find a
              remix-specific cover if one exists.
    Stage 2 – cleaned title (e.g. "Song"): strips remix/edit annotations and
              retries so the original release cover is used as a fallback.
    Stage 3 – swapped artist/title: some radio stations (e.g. ÖRR) transmit
              the artist in the title field and vice versa. If all previous
              stages fail and both fields are set, retry with artist and title
              exchanged.

    Returns the first successful result or None (callers should show the
    default fallback logo in that case).
    """
    provider_list = [p for p in providers if isinstance(p, str)]
    if not provider_list:
        provider_list = [PROVIDER_ITUNES]

    def _title_stages(q: TrackQuery) -> list[str | None]:
        """Return the ordered list of title variants to try for a query."""
        if q.original_title and q.original_title != q.title:
            return [q.original_title, q.title]
        return [q.title]

    async def _try_stages(q: TrackQuery) -> ResolvedCover | None:
        for stage_title in _title_stages(q):
            stage_query = replace(q, title=stage_title, original_title=None) if stage_title != q.title else q
            _LOGGER.debug("Cover search stage title=%r artist=%r", stage_title, q.artist)
            resolved = await _try_providers(session=session, query=stage_query, provider_list=provider_list)
            if resolved:
                return resolved
        return None

    # --- Normal order: artist / title as received ---
    resolved = await _try_stages(query)
    if resolved:
        return resolved

    # --- Swapped order: title field → artist, artist field → title ---
    if query.artist and query.title:
        _LOGGER.debug(
            "No cover found with original order – retrying with swapped artist/title "
            "(artist=%r title=%r → artist=%r title=%r)",
            query.artist, query.title, query.title, query.artist,
        )
        swapped_query = replace(query, artist=query.title, title=query.artist, original_title=None)
        resolved = await _try_stages(swapped_query)
        if resolved:
            return resolved

    _LOGGER.debug("All stages exhausted – no cover found for artist=%r title=%r", query.artist, query.title)
    return None
