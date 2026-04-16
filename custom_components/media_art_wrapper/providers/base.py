"""Abstract base classes and data models for MAW artwork providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class ArtworkQuery:
    """All information available for an artwork lookup."""

    title: str | None
    artist: str | None = None
    album: str | None = None
    content_type: str | None = None   # media_content_type HA attribute
    app_name: str | None = None       # app_name HA attribute
    category: str = "auto"
    artwork_width: int = 600
    artwork_height: int = 600
    # Raw title before remix/edit stripping (e.g. "Song (Remix)" vs "Song")
    original_title: str | None = None
    # Series title for episode content
    series_title: str | None = None
    title_candidates: list[str] = field(default_factory=list)
    subtitle_hint: str = ""
    channel_icon: str = ""      # og:image or EPG-supplied channel logo URL
    channel_name: str = ""      # raw channel name from app_name / EPG


@dataclass(slots=True)
class ArtworkResult:
    """Successful artwork lookup result."""

    provider_name: str
    image_url: str | None             # Public CDN URL if available
    confidence: float = 1.0           # 0.0–1.0; first-match wins, but stored for diagnostics
    image: bytes | None = None        # Fetched image bytes
    content_type: str = "image/jpeg"


class ArtworkProvider(ABC):
    """Abstract base class for all artwork providers.

    Subclasses declare which categories they serve via the ``categories``
    class attribute and implement ``fetch()``.
    """

    # frozenset of category strings this provider handles.
    # Always include "auto" if the provider should be tried for the catch-all category.
    categories: frozenset[str] = frozenset({"auto"})

    def is_available(self) -> bool:
        """Return True when all required API credentials are configured.

        Override this in providers that require API keys.  The coordinator
        will skip providers where is_available() returns False.
        """
        return True

    @abstractmethod
    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        """Fetch artwork for *query* using *session* (aiohttp ClientSession).

        Return an ArtworkResult on success, or None if no artwork was found.
        Raise an exception only for unexpected errors (network failures, etc.);
        a "no results" outcome should return None silently.
        """
