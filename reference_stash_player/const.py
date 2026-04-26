"""Constants for Stash Player integration."""

from __future__ import annotations

DOMAIN = "stash_player"

CONF_URL = "url"
CONF_API_KEY = "api_key"
CONF_PLAYER_NAME = "player_name"
CONF_POLL_INTERVAL = "poll_interval"
CONF_USE_WEBHOOK = "use_webhook"
CONF_WEBHOOK_PORT = "webhook_port"
CONF_NSFW_MODE = "nsfw_mode"

DEFAULT_PLAYER_NAME = "Stash"
DEFAULT_POLL_INTERVAL = 5
DEFAULT_SCAN_INTERVAL = 300
DEFAULT_USE_WEBHOOK = False
DEFAULT_WEBHOOK_PORT = 8765
DEFAULT_NSFW_MODE = "blur"

# Stash exposes no GraphQL query for "what is playing right now". The only
# reliable signal is that the web player periodically calls sceneSaveActivity,
# which advances last_played_at, resume_time, and eventually play_count. We
# detect active playback by polling the most-recently-played scenes and
# watching those three fields for changes across polls.
#
# STREAM_ACTIVITY_GRACE_SECONDS — how long after the last observed signal
#   change we still consider the scene "streaming". Must be > the interval at
#   which Stash's frontend calls sceneSaveActivity (typically 5-10s) plus the
#   HA poll interval, so a single missed signal does not kick us to idle.
#
# FRESH_PLAY_THRESHOLD_SECONDS — on first observation of a scene (e.g. HA
#   restart) treat it as streaming if last_played_at is younger than this.
STREAM_ACTIVITY_GRACE_SECONDS = 60
FRESH_PLAY_THRESHOLD_SECONDS = 30

NSFW_BLUR = "blur"
NSFW_HIDDEN = "hidden"
NSFW_FULL = "full"

COORDINATOR_KEY = "coordinator"
LIBRARY_COORDINATOR_KEY = "library_coordinator"
CLIENT_KEY = "client"
WEBHOOK_VIEW_KEY = "webhook_view"

PLATFORMS = ["media_player", "image", "sensor", "button", "binary_sensor"]

# ── GraphQL queries (playback) ────────────────────────────────────────────────

ACTIVE_SCENE_QUERY = """
query ActiveScene {
  findScenes(
    scene_filter: {
      last_played_at: { modifier: NOT_NULL, value: "" }
    }
    filter: { per_page: 2, sort: "last_played_at", direction: DESC }
  ) {
    scenes {
      id
      title
      rating100
      play_count
      play_duration
      resume_time
      last_played_at
      paths {
        screenshot
      }
      performers { name }
      tags { name }
      studio { name }
      files {
        duration
        size
        width
        height
      }
    }
  }
}
"""

PLAYING_STATE_QUERY = """
query PlayingState {
  sceneStreams {
    url
    mime_type
  }
}
"""

SCENE_BY_ID_QUERY = """
query SceneById($id: ID!) {
  findScene(id: $id) {
    id
    title
    rating100
    play_count
    resume_time
    last_played_at
    paths {
      screenshot
    }
    performers { name }
    tags { name }
    studio { name }
    files {
      duration
      size
      width
      height
    }
  }
}
"""

GENERATE_SCREENSHOT_MUTATION = """
mutation GenerateScreenshot($id: ID!) {
  sceneGenerateScreenshot(id: $id)
}
"""

SAVE_ACTIVITY_MUTATION = """
mutation SaveScene($id: ID!, $pos: Float!) {
  sceneSaveActivity(id: $id, resume_time: $pos)
}
"""
