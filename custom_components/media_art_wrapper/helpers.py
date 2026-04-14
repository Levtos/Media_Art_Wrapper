from __future__ import annotations

import base64
import os

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
# Keys are lowercased for case-insensitive matching.
_SERVICE_LOGO_MAP: dict[str, str] = {
    # Music streaming
    "apple music":      "apple_music",
    "spotify":          "spotify",
    "tidal":            "tidal",
    "youtube music":    "youtube_music",
    "amazon music":     "amazon_music",
    "deezer":           "deezer",
    "soundcloud":       "soundcloud",
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
    "hulu":             "hulu",
    "peacock":          "peacock",
    "paramount+":       "paramount_plus",
    "youtube":          "youtube",
    "youtube tv":       "youtube_tv",
    "twitch":           "twitch",
    # Gaming platforms
    "playstation":      "playstation",
    "xbox":             "xbox",
    "steam":            "steam",
    "epic games":       "epic_games",
    "epic":             "epic_games",
    "gog":              "gog",
    # Podcasts / radio
    "pocket casts":     "pocket_casts",
    "overcast":         "overcast",
    "castro":           "castro",
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
