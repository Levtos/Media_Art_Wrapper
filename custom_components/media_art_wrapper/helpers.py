from __future__ import annotations

import base64
import os

from homeassistant.components.media_player import MediaPlayerState
from homeassistant.core import HomeAssistant

# Shared fallback image (small PNG placeholder shown when no cover is available).
# Used by both the Image and Camera entities to avoid duplicating the binary blob.
FALLBACK_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAABQUlEQVR42u3cMRGAMAAEwVeSGglowAqKcBY3QQAVM+l+izPAb8NAkvN6lnqLhwCABwGAABAAAkAACAABIAAEgAAQAAJAAAgAASAABIAAEAACQAAIAAEgAASAABAAAkAACAABIAAEgAAQAAJAAAgAASAABIAAEAACQAAIAAEgAASAABAAO1vz/h0ApcM3QYjhuyHE+N0IYvhuCDF+N4IYvxsBAAAYvxlBjN+NAAAAjN+MAAAAjN+MAAAAAAAAAADaABxjfAIAAAAAAAAAAAAAwFsAAAAAAAAAAAAAga+BAAAAgT+CAAAAAn8FQ+BcAAAAQOBsoNPBALgfAAA3hADgjiAA3BIGgAAQAAJAAAgAASAABIAAEAACQAAIAAEgAASAABAAAkAACAABIAAEgAAQAAJAAAgAASAABIAAEAACQNt6Adpn9COM5b1AAAAAAElFTkSuQmCC"
)

# ---------------------------------------------------------------------------
# Service logo mapping
# ---------------------------------------------------------------------------

# Base directory where service logo PNGs are stored
_LOGO_DIR = os.path.join(os.path.dirname(__file__), "icons", "services")

# app_name / category keyword → PNG filename stem (without extension)
# Keys are lowercased for case-insensitive matching. All listed stems must
# correspond to an existing PNG under icons/services/ — see LASTENHEFT §8.2.
_SERVICE_LOGO_MAP: dict[str, str] = {
    # Music streaming
    "apple music":      "apple_music",
    "spotify":          "spotify",
    "tidal":            "tidal",
    "youtube music":    "youtube_music",
    "amazon music":     "amazon_music",
    # Video streaming
    "netflix":          "netflix",
    "disney+":          "disney_plus",
    "disney plus":      "disney_plus",
    "apple tv+":        "apple_tv_plus",
    "apple tv plus":    "apple_tv_plus",
    "amazon prime":     "amazon_prime",
    "prime video":      "amazon_prime",
    "hbo max":          "hbo_max",
    "max":              "hbo_max",
    # Gaming platforms
    "playstation":      "playstation",
    "xbox":             "xbox",
    "steam":            "steam",
    "epic games":       "epic_games",
    "epic":             "epic_games",
}


def service_logo(app_name: str) -> bytes | None:
    """Return PNG bytes for a known streaming service, or None.

    *app_name* is matched case-insensitively against ``_SERVICE_LOGO_MAP``.
    Returns ``None`` when the service is unknown or the logo file is missing.
    """
    key = (app_name or "").strip().lower()
    stem = _SERVICE_LOGO_MAP.get(key)
    if not stem:
        return None
    path = os.path.join(_LOGO_DIR, f"{stem}.png")
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def source_name(source_entity_id: str) -> str:
    """Return a human-readable name derived from a media_player entity id."""
    object_id = source_entity_id.split(".", 1)[-1]
    return object_id.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Shared source-priority helpers (used by CombinedMediaPlayer and CombinedCoverImage)
# ---------------------------------------------------------------------------

TIER1_STATES: frozenset[MediaPlayerState] = frozenset(
    {MediaPlayerState.PLAYING, MediaPlayerState.BUFFERING}
)
TIER2_STATES: frozenset[MediaPlayerState] = frozenset(
    {MediaPlayerState.PAUSED, MediaPlayerState.IDLE}
)
TIER3_STATES: frozenset[MediaPlayerState] = frozenset({MediaPlayerState.ON})

_PRIORITY_TIERS: tuple[frozenset[MediaPlayerState], ...] = (
    TIER1_STATES,
    TIER2_STATES,
    TIER3_STATES,
)


def safe_media_player_state(raw: str) -> MediaPlayerState | None:
    """Parse a raw state string into a MediaPlayerState, or return None on failure."""
    try:
        return MediaPlayerState(raw)
    except ValueError:
        return None


def active_entity_id(hass: HomeAssistant, sources: list[str]) -> str | None:
    """Return the entity_id of the highest-priority active display source."""
    for tier in _PRIORITY_TIERS:
        for sid in sources:
            state = hass.states.get(sid)
            if state is None:
                continue
            s = safe_media_player_state(state.state)
            if s is not None and s in tier:
                return sid
    return None
