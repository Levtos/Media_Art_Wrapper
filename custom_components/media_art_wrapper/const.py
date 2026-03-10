from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "media_art_wrapper"

PLATFORMS: list[Platform] = [Platform.IMAGE, Platform.CAMERA, Platform.MEDIA_PLAYER, Platform.SENSOR]

CONF_SOURCE_ENTITY_ID = "source_entity_id"
CONF_PROVIDERS = "providers"
CONF_ARTWORK_SIZE = "artwork_size"
CONF_ARTWORK_WIDTH = "artwork_width"
CONF_ARTWORK_HEIGHT = "artwork_height"

PROVIDER_ITUNES = "itunes"
PROVIDER_MUSICBRAINZ = "musicbrainz"
PROVIDER_TV = "tv"

DEFAULT_PROVIDERS: list[str] = [PROVIDER_ITUNES]
DEFAULT_ARTWORK_SIZE = 600
DEFAULT_ARTWORK_WIDTH = 600
DEFAULT_ARTWORK_HEIGHT = 600
