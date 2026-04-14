from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "media_art_wrapper"

PLATFORMS: list[Platform] = [Platform.IMAGE, Platform.CAMERA, Platform.MEDIA_PLAYER, Platform.SENSOR]

# ---------------------------------------------------------------------------
# Source / display
# ---------------------------------------------------------------------------
CONF_SOURCE_ENTITY_ID = "source_entity_id"
CONF_DISPLAY_NAME = "display_name"
CONF_DELEGATE_ENTITY = "delegate_entity"

# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------
CONF_CATEGORY = "category"

CATEGORY_MUSIC = "music"
CATEGORY_STREAMING = "streaming"
CATEGORY_GAMING = "gaming"
CATEGORY_TV = "tv"
CATEGORY_AUTO = "auto"

CATEGORIES = [CATEGORY_MUSIC, CATEGORY_STREAMING, CATEGORY_GAMING, CATEGORY_TV, CATEGORY_AUTO]

# Category sort priority for Combined Player auto-priority
# Lower number = higher priority (gaming beats streaming beats tv beats music)
CATEGORY_SORT_PRIORITY: dict[str, int] = {
    CATEGORY_GAMING: 1,
    CATEGORY_STREAMING: 2,
    CATEGORY_TV: 3,
    CATEGORY_MUSIC: 4,
    CATEGORY_AUTO: 5,
}

# ---------------------------------------------------------------------------
# Artwork ratio & dimensions
# ---------------------------------------------------------------------------
CONF_RATIO = "ratio"
CONF_ARTWORK_WIDTH = "artwork_width"
CONF_ARTWORK_HEIGHT = "artwork_height"

RATIO_1_1_2000 = "1:1_2000"
RATIO_1_1_3000 = "1:1_3000"
RATIO_4_3_2000 = "4:3_2000"
RATIO_16_9_2000 = "16:9_2000"
RATIO_CUSTOM = "custom"

# (width, height) per preset key
RATIO_DIMENSIONS: dict[str, tuple[int, int]] = {
    RATIO_1_1_2000: (2000, 2000),
    RATIO_1_1_3000: (3000, 3000),
    RATIO_4_3_2000: (1600, 1200),
    RATIO_16_9_2000: (1920, 1080),
}

# Legacy keys retained for migration only
CONF_ARTWORK_SIZE = "artwork_size"

DEFAULT_ARTWORK_WIDTH = 2000
DEFAULT_ARTWORK_HEIGHT = 2000
DEFAULT_ARTWORK_SIZE = 2000
DEFAULT_RATIO = RATIO_1_1_2000

# ---------------------------------------------------------------------------
# Fallback artwork
# ---------------------------------------------------------------------------
CONF_FALLBACK_MODE = "fallback_mode"
CONF_FALLBACK_CUSTOM_URL = "fallback_custom_url"

FALLBACK_PLACEHOLDER = "placeholder"
FALLBACK_SERVICE_LOGO = "service_logo"
FALLBACK_CUSTOM_URL_MODE = "custom_url"

# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
CONF_PROVIDERS = "providers"

PROVIDER_ITUNES = "itunes"
PROVIDER_MUSICBRAINZ = "musicbrainz"
PROVIDER_TMDB = "tmdb"
PROVIDER_IGDB = "igdb"
PROVIDER_STEAMGRIDDB = "steamgriddb"
PROVIDER_STEAM = "steam"          # no-key fallback (Steam Store search)
PROVIDER_TVMAZE = "tvmaze"
PROVIDER_FANART = "fanart"
# Legacy provider keys (kept for migration compatibility)
PROVIDER_TV = "tv"
PROVIDER_BATTLENET = "battlenet"

DEFAULT_PROVIDERS: list[str] = [PROVIDER_ITUNES]

# Category → ordered provider list (providers without required keys are skipped)
CATEGORY_PROVIDERS: dict[str, list[str]] = {
    CATEGORY_MUSIC: [PROVIDER_ITUNES, PROVIDER_MUSICBRAINZ],
    CATEGORY_STREAMING: [PROVIDER_TMDB],
    CATEGORY_GAMING: [PROVIDER_IGDB, PROVIDER_STEAMGRIDDB, PROVIDER_STEAM],
    CATEGORY_TV: [PROVIDER_TVMAZE, PROVIDER_FANART],
    CATEGORY_AUTO: [
        PROVIDER_ITUNES,
        PROVIDER_MUSICBRAINZ,
        PROVIDER_TMDB,
        PROVIDER_IGDB,
        PROVIDER_STEAMGRIDDB,
        PROVIDER_STEAM,
        PROVIDER_TVMAZE,
        PROVIDER_FANART,
    ],
}

# Providers available for manual ordering (music + auto categories only)
ORDERABLE_PROVIDERS: dict[str, list[str]] = {
    CATEGORY_MUSIC: [PROVIDER_ITUNES, PROVIDER_MUSICBRAINZ],
    CATEGORY_AUTO: [
        PROVIDER_ITUNES,
        PROVIDER_MUSICBRAINZ,
        PROVIDER_TMDB,
        PROVIDER_IGDB,
        PROVIDER_STEAMGRIDDB,
        PROVIDER_STEAM,
        PROVIDER_TVMAZE,
        PROVIDER_FANART,
    ],
}

# ---------------------------------------------------------------------------
# API keys (always stored in entry.options, never in entry.data)
# ---------------------------------------------------------------------------
CONF_TMDB_API_KEY = "tmdb_api_key"
CONF_IGDB_CLIENT_ID = "igdb_client_id"
CONF_IGDB_CLIENT_SECRET = "igdb_client_secret"
CONF_STEAMGRIDDB_API_KEY = "steamgriddb_api_key"
CONF_FANART_API_KEY = "fanart_api_key"
CONF_XMLTV_URL = "xmltv_url"  # stored but not yet used (EPG v3.1)

# ---------------------------------------------------------------------------
# Combined Player
# ---------------------------------------------------------------------------
CONF_CREATE_COMBINED = "create_combined"
CONF_COMBINED_NAME = "combined_name"
CONF_COMBINED_SOURCES = "combined_sources"
CONF_COMBINED_AUDIO_SOURCES = "combined_audio_sources"
CONF_AUTO_PRIORITY = "auto_priority"
COMBINED_NUM_SOURCE_SLOTS = 8
