"""Category-specific query construction."""
from __future__ import annotations

import re
from typing import Any

from .base import ArtworkQuery

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

_RE_PLATFORM_SUFFIX = re.compile(
    r"\s*[-–|]\s*(?:PS\s*[2345]|PlayStation\s*[2345]?|Xbox(?:\s*One|\s*Series\s*[XS])?|"
    r"PC|Nintendo\s*Switch|Switch|Steam|Epic)\s*$",
    re.IGNORECASE,
)
_RE_CHANNEL_SUFFIX = re.compile(r"\s+\b(hd|sd|uhd|4k|hbbtv)\b.*$", re.IGNORECASE)

TIMESTAMP_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}(\s+\d{2}:\d{2})?\.?$")
UMLAUT_CANDIDATES = [
    ("a", "ä"), ("o", "ö"), ("u", "ü"),
    ("A", "Ä"), ("O", "Ö"), ("U", "Ü"),
    ("ss", "ß"),
]


def is_timestamp(value: str) -> bool:
    return bool(TIMESTAMP_PATTERN.match(value.strip()))


def umlaut_expand(title: str) -> list[str]:
    variants = [title]
    for ascii_char, umlaut in UMLAUT_CANDIDATES:
        if ascii_char in title:
            variant = title.replace(ascii_char, umlaut, 1)
            if variant not in variants:
                variants.append(variant)
    return variants[:4]


def _raw(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    s = _RE_SPACES.sub(" ", value).strip()
    return s if s.lower() not in _BAD else None


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    s = _RE_SPACES.sub(" ", _RE_CLEAN.sub("", value)).strip()
    return s if s.lower() not in _BAD else None


def _strip_platform(title: str) -> str:
    return _RE_PLATFORM_SUFFIX.sub("", title).strip()


def _strip_channel(name: str) -> str:
    return _RE_CHANNEL_SUFFIX.sub("", name).strip()


def build_query(state_attrs: dict[str, Any], category: str, artwork_width: int = 600, artwork_height: int = 600) -> ArtworkQuery:
    raw_title = _raw(state_attrs.get("media_title"))
    clean_title = _clean(state_attrs.get("media_title"))
    artist = _clean(state_attrs.get("media_artist"))
    album = _clean(state_attrs.get("media_album_name"))
    content_type = state_attrs.get("media_content_type")
    app_name = _raw(state_attrs.get("app_name"))
    series_title = _clean(state_attrs.get("media_series_title"))
    sub_title = _clean(state_attrs.get("media_subtitle"))

    title = clean_title
    original = raw_title if (raw_title and raw_title != clean_title) else None
    title_candidates: list[str] = []
    subtitle_hint = ""

    if category == "streaming":
        artist = None
        if content_type == "episode" and series_title and not title:
            title = series_title
    elif category == "gaming":
        artist = None
        if title:
            title = _strip_platform(title)
        if original:
            original = _strip_platform(original)
    elif category == "tv":
        if not title and app_name:
            title = app_name
        if title:
            title = _strip_channel(title)
            title_candidates = umlaut_expand(title)
        if sub_title and not is_timestamp(sub_title):
            subtitle_hint = sub_title

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
        title_candidates=title_candidates,
        subtitle_hint=subtitle_hint,
    )
