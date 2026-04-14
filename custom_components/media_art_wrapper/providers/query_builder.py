"""Category-specific query construction.

build_query() is the single entry point: given raw HA state attributes and
the configured category, it returns an ArtworkQuery ready for the providers.
"""
from __future__ import annotations

import re
from typing import Any

from .base import ArtworkQuery

# ---------------------------------------------------------------------------
# Text helpers (mirrors __init__.py but kept local to avoid circular imports)
# ---------------------------------------------------------------------------

_RE_CLEAN = re.compile(
    r"""
       \s*
       (
           \([^)]*(?:Remix|Edit|Mix)[^)]*\) |
           \[[^\]]*(?:Remix|Edit|Mix)[^\]]*\] |
           -\s*.*(?:Remix|Edit|Mix).* |
           \(?\s*\d+[_:]\d+\s*\)?
       )
    """,
    re.I | re.X,
)
_RE_SPACES = re.compile(r"\s{2,}")
_BAD = {"", "none", "null", "unknown", "n/a", "-"}

# Platform suffixes to strip from gaming titles
_RE_PLATFORM_SUFFIX = re.compile(
    r"\s*[-–|]\s*(?:PS\s*[2345]|PlayStation\s*[2345]?|Xbox(?:\s*One|\s*Series\s*[XS])?|"
    r"PC|Nintendo\s*Switch|Switch|Steam|Epic)\s*$",
    re.IGNORECASE,
)

# Broadcast-quality / regional suffixes for TV channel names
_RE_CHANNEL_SUFFIX = re.compile(
    r"\s+\b(hd|sd|uhd|4k|hbbtv)\b.*$",
    re.IGNORECASE,
)


def _raw(value: Any) -> str | None:
    """Normalise whitespace only – keeps remix/edit annotations."""
    if not isinstance(value, str):
        return None
    s = _RE_SPACES.sub(" ", value).strip()
    return s if s.lower() not in _BAD else None


def _clean(value: Any) -> str | None:
    """Strip remix/edit annotations and normalise whitespace."""
    if not isinstance(value, str):
        return None
    s = _RE_SPACES.sub(" ", _RE_CLEAN.sub("", value)).strip()
    return s if s.lower() not in _BAD else None


def _strip_platform(title: str) -> str:
    return _RE_PLATFORM_SUFFIX.sub("", title).strip()


def _strip_channel(name: str) -> str:
    return _RE_CHANNEL_SUFFIX.sub("", name).strip()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_query(
    state_attrs: dict[str, Any],
    category: str,
    artwork_width: int = 600,
    artwork_height: int = 600,
) -> ArtworkQuery:
    """Build an ArtworkQuery from HA media_player state attributes.

    Category-specific transformations are applied before the query is returned:

    - music  : Strip remix/edit annotations from both title slots; pass artist.
    - streaming: Artist irrelevant; use series_title for episodes if title absent.
    - gaming : Strip platform suffixes from title; artist irrelevant.
    - tv     : Channel-name suffix stripped; app_name used as fallback title.
    - auto   : Minimal transformation; let each provider decide what to use.
    """
    raw_title = _raw(state_attrs.get("media_title"))
    clean_title = _clean(state_attrs.get("media_title"))
    artist = _clean(state_attrs.get("media_artist"))
    album = _clean(state_attrs.get("media_album_name"))
    content_type = state_attrs.get("media_content_type")
    app_name = _raw(state_attrs.get("app_name"))
    series_title = _clean(state_attrs.get("media_series_title"))

    title = clean_title
    original = raw_title if (raw_title and raw_title != clean_title) else None

    if category == "music":
        # Keep remix/edit in original_title so providers can find remix-specific
        # covers, but also try cleaned title as fallback.
        pass  # already handled by raw vs. clean split above

    elif category == "streaming":
        artist = None  # not relevant for films/series
        # For episodes, use series title as the primary search target
        if content_type == "episode" and series_title:
            if not title:
                title = series_title
            # Always expose series_title so providers can use it

    elif category == "gaming":
        artist = None
        if title:
            title = _strip_platform(title)
        if original:
            original = _strip_platform(original)

    elif category == "tv":
        # Use app_name as channel-name hint when title is absent
        if not title and app_name:
            title = app_name
        # Strip broadcast-quality suffix (HD/SD) for cleaner matching
        if title:
            title = _strip_channel(title)

    # For "auto": pass everything through and let providers decide

    return ArtworkQuery(
        title=title,
        original_title=original,
        artist=artist,
        album=album,
        content_type=content_type,
        app_name=app_name,
        category=category,
        artwork_width=artwork_width,
        artwork_height=artwork_height,
        series_title=series_title,
    )
