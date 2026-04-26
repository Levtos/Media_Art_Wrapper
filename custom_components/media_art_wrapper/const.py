from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "media_art_wrapper"

PLATFORMS: list[Platform] = [Platform.IMAGE, Platform.CAMERA, Platform.MEDIA_PLAYER, Platform.SENSOR]

# ---------------------------------------------------------------------------
# Source / display
# ---------------------------------------------------------------------------
CONF_SOURCE_ENTITY_ID = "source_entity_id"
CONF_DISPLAY_NAME = "display_name"
CONF_DELEGATE_ENTITY = "delegate_entity"  # legacy key (migrated away in v3.1.1)

# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------
CONF_CATEGORY = "category"

CATEGORY_MUSIC = "music"
CATEGORY_STREAMING = "streaming"
CATEGORY_GAMING = "gaming"
CATEGORY_TV = "tv"
CATEGORY_AUTO = "auto"
CATEGORY_ADULT = "adult"

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
RATIO_4_3_1600 = "4:3_1600"
RATIO_16_9_1920 = "16:9_1920"
RATIO_CUSTOM = "custom"

# (width, height) per preset key
RATIO_DIMENSIONS: dict[str, tuple[int, int]] = {
    RATIO_1_1_2000: (2000, 2000),
    RATIO_1_1_3000: (3000, 3000),
    RATIO_4_3_1600: (1600, 1200),
    RATIO_16_9_1920: (1920, 1080),
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
# Adult content providers — wired in by Schritt 7 (§3.2 / §6).
PROVIDER_STASH = "stash"
PROVIDER_STASHDB = "stashdb"
PROVIDER_PORNDB = "porndb"
PROVIDER_AEBN = "aebn"
# Legacy provider keys (kept for migration compatibility)
PROVIDER_TV = "tv"

DEFAULT_PROVIDERS: list[str] = [PROVIDER_ITUNES]

# Category → ordered provider list (providers without required keys are skipped)
CATEGORY_PROVIDERS: dict[str, list[str]] = {
    CATEGORY_MUSIC: [PROVIDER_ITUNES, PROVIDER_MUSICBRAINZ],
    CATEGORY_STREAMING: [PROVIDER_TMDB],
    CATEGORY_GAMING: [PROVIDER_IGDB, PROVIDER_STEAMGRIDDB, PROVIDER_STEAM],
    CATEGORY_TV: [PROVIDER_TVMAZE, PROVIDER_TMDB, PROVIDER_FANART],
    # §6.4 Stash priority — provider classes wired in Schritt 7/10
    CATEGORY_ADULT: [PROVIDER_STASH, PROVIDER_STASHDB, PROVIDER_PORNDB, PROVIDER_AEBN],
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
CONF_STASH_URL = "stash_url"
CONF_STASH_API_KEY = "stash_api_key"
CONF_STASH_HOST_REWRITE = "stash_host_rewrite"
CONF_STASHDB_API_KEY = "stashdb_api_key"
# §3.2 / §6.4 — adult-content API keys for the §6.4 prio 3/4 providers.
# Both endpoints are reachable without a key for basic search but keys
# are required for higher-quality / non-rate-limited responses; providers
# attach Bearer auth when set, otherwise hit the public endpoint and may
# still degrade to None.
CONF_PORNDB_API_KEY = "porndb_api_key"
CONF_AEBN_API_KEY = "aebn_api_key"
CONF_XMLTV_URL = "xmltv_url"  # Reserved for EPG v3.2 — not yet implemented; kept in storage only
CONF_EPG_SENSOR = "epg_sensor"
# §5 Teil 2 — per-channel EPG sensor map. dict[channel_name, sensor_entity_id],
# case-insensitive key match. CONF_EPG_SENSOR remains as the catch-all
# fallback when no per-channel entry hits.
CONF_EPG_SENSOR_MAP = "epg_sensor_map"


def epg_sensor_for_channel(options: dict, channel_name: str | None) -> str | None:
    """Return the EPG sensor entity_id to query for *channel_name*.

    Lookup order:
      1. options[CONF_EPG_SENSOR_MAP][channel_name] — case-insensitive match.
      2. options[CONF_EPG_SENSOR] — single catch-all fallback.
      3. None — caller skips EPG enrichment.
    """
    raw_map = options.get(CONF_EPG_SENSOR_MAP)
    if isinstance(raw_map, dict) and channel_name:
        ch_lower = channel_name.strip().lower()
        if ch_lower:
            for key, sensor in raw_map.items():
                if (
                    isinstance(key, str)
                    and key.strip().lower() == ch_lower
                    and isinstance(sensor, str)
                    and sensor.strip()
                ):
                    return sensor.strip()
    fallback = options.get(CONF_EPG_SENSOR)
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return None

# ---------------------------------------------------------------------------
# §2.3 Artwork-hierarchy detector sensors (per §7.1)
# ---------------------------------------------------------------------------
# Drive scenario detection in the MAW coordinator. Defaults match LASTENHEFT
# §7.1 so an out-of-the-box setup needs no extra configuration.
CONF_MAW_SENSOR_TV_INPUT = "maw_sensor_tv_input"
CONF_MAW_SENSOR_DISCORD_GAME = "maw_sensor_discord_game"
CONF_MAW_SENSOR_STASH_ACTIVE = "maw_sensor_stash_active"

DEFAULT_MAW_SENSOR_TV_INPUT = "sensor.tv_active_input"
DEFAULT_MAW_SENSOR_DISCORD_GAME = "sensor.discord_active_game_atomic"
# §7.2 — sensor planned but does not exist yet; default to empty so the
# detector silently skips the Stash branch until the user wires one in.
DEFAULT_MAW_SENSOR_STASH_ACTIVE = ""

# §2.3 scenario classifier values (returned by hierarchy.detect_scenario).
SCENARIO_NATIVE = "native"
SCENARIO_ATV_NO_TITLE = "atv_no_title"
SCENARIO_ATV_TITLE = "atv_title"
SCENARIO_GAME = "game"
SCENARIO_STASH = "stash"
SCENARIO_TV_IN_LIST = "tv_in_list"
SCENARIO_TV_OUT_OF_LIST = "tv_out_of_list"
SCENARIO_FALLBACK = "fallback"

# ---------------------------------------------------------------------------
# Combined Player
# ---------------------------------------------------------------------------
CONF_CREATE_WRAPPER = "create_wrapper"
CONF_CREATE_COMBINED = "create_combined"
CONF_COMBINED_NAME = "combined_name"
CONF_COMBINED_SOURCES = "combined_sources"
CONF_COMBINED_AUDIO_SOURCES = "combined_audio_sources"
CONF_AUTO_PRIORITY = "auto_priority"
COMBINED_NUM_SOURCE_SLOTS = 8
CONF_COMBINED_DELEGATE_PREFIX = "combined_delegate_"

# Per-slot role tag for §2.2 scenario-based priority resolution.
# Slot index 1..COMBINED_NUM_SOURCE_SLOTS; values must be one of CMP_ROLES.
CONF_COMBINED_ROLE_PREFIX = "combined_role_"

CMP_ROLE_ATV = "atv"
CMP_ROLE_HOMEPODS = "homepods"
CMP_ROLE_PS5 = "ps5"
CMP_ROLE_STASH = "stash"
CMP_ROLE_OTHER = "other"

CMP_ROLES: list[str] = [
    CMP_ROLE_ATV,
    CMP_ROLE_HOMEPODS,
    CMP_ROLE_PS5,
    CMP_ROLE_STASH,
    CMP_ROLE_OTHER,
]

# Context sensor ids used by §2.2 priority resolver. Defaults match §7.1
# (already-existing sensors in the user's HA setup); override-capable.
CONF_CMP_SENSOR_PS5_CONTEXT = "cmp_sensor_ps5_context"
CONF_CMP_SENSOR_HOMEPODS_MUSIC = "cmp_sensor_homepods_music"
CONF_CMP_SENSOR_HOMEPODS_ACTIVE = "cmp_sensor_homepods_active"

DEFAULT_CMP_SENSOR_PS5_CONTEXT = "binary_sensor.ps5_context_active_combined"
DEFAULT_CMP_SENSOR_HOMEPODS_MUSIC = "binary_sensor.homepods_music_active"
DEFAULT_CMP_SENSOR_HOMEPODS_ACTIVE = "binary_sensor.homepods_active_atomic"

# ---------------------------------------------------------------------------
# EPG — Channel classification
# ---------------------------------------------------------------------------
CONF_EPG_FULL_LOOKUP_CHANNELS = "epg_full_lookup_channels"

# Channels in this set trigger full API lookups (TVMaze + TMDb episode search).
# All other channels (private/commercial) receive channel_icon directly.
# Stored as the LASTENHEFT default; users can override via OptionsFlow.
DEFAULT_EPG_FULL_LOOKUP_CHANNELS: tuple[str, ...] = (
    # ARD Familie
    "Das Erste", "ARD", "ARD HD", "Das Erste HD", "tagesschau24", "ONE", "ARD alpha",
    # ZDF Familie
    "ZDF", "ZDF HD", "ZDFinfo", "ZDFneo", "ZDF Krimi", "3sat",
    # WDR
    "WDR", "WDR HD", "WDR Fernsehen",
    # Weitere ÖR
    "arte", "arte HD",
    "NDR", "MDR", "SWR", "BR", "HR", "RBB",
    "Phoenix", "KiKA",
)

# Backwards-compat alias for code that still imports the legacy frozenset.
# Read from options first via epg_full_lookup_channels(); this constant only
# represents the LASTENHEFT default.
EPG_FULL_LOOKUP_CHANNELS: frozenset[str] = frozenset(DEFAULT_EPG_FULL_LOOKUP_CHANNELS)


def epg_full_lookup_channels(options: dict) -> frozenset[str]:
    """Return the user-configured (or default) EPG full-lookup channel set,
    normalised to lowercase for case-insensitive matching."""
    raw = options.get(CONF_EPG_FULL_LOOKUP_CHANNELS)
    if isinstance(raw, (list, tuple, set, frozenset)) and raw:
        return frozenset(str(c).strip().lower() for c in raw if str(c).strip())
    return frozenset(c.lower() for c in DEFAULT_EPG_FULL_LOOKUP_CHANNELS)


def channel_in_epg_list(channel_name: str, options: dict) -> bool:
    """Case-insensitive membership test for the EPG full-lookup channel list."""
    if not channel_name:
        return False
    return channel_name.strip().lower() in epg_full_lookup_channels(options)
