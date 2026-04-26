"""StashDB provider (GraphQL)."""
from __future__ import annotations

import logging
from typing import Any

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)

STASHDB_GRAPHQL_URL = "https://stashdb.org/graphql"
_JSON_KW = {"content_type": None}

# Ported query strings (including SCENE_BY_ID as requested by LASTENHEFT §6.3)
FIND_SCENES_QUERY = """
query FindScenes($query: String!) {
  queryScenes(input: { q: $query, per_page: 6 }) {
    scenes {
      id
      title
      paths {
        screenshot
      }
      performers {
        name
        image_path
      }
      studio {
        name
        image_path
      }
    }
  }
}
"""

SCENE_BY_ID_QUERY = """
query SceneById($id: ID!) {
  findScene(id: $id) {
    id
    title
    paths {
      screenshot
    }
    performers {
      name
      image_path
    }
    studio {
      name
      image_path
    }
  }
}
"""


def _pick_image(scene: dict[str, Any]) -> str | None:
    paths = scene.get("paths") if isinstance(scene, dict) else None
    if isinstance(paths, dict):
        screenshot = paths.get("screenshot")
        if isinstance(screenshot, str) and screenshot:
            return screenshot

    for performer in scene.get("performers") or []:
        if not isinstance(performer, dict):
            continue
        img = performer.get("image_path")
        if isinstance(img, str) and img:
            return img

    studio = scene.get("studio") if isinstance(scene.get("studio"), dict) else None
    if studio:
        img = studio.get("image_path")
        if isinstance(img, str) and img:
            return img
    return None


class StashDBProvider(ArtworkProvider):
    """StashDB provider with title-based scene lookup."""

    categories = frozenset({"adult"})

    def __init__(self, api_key: str = "") -> None:
        self._api_key = (api_key or "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["ApiKey"] = self._api_key
        return headers

    async def _graphql(self, session, query: str, variables: dict[str, Any]) -> dict[str, Any] | None:
        try:
            async with session.post(
                STASHDB_GRAPHQL_URL,
                json={"query": query, "variables": variables},
                headers=self._headers(),
                timeout=10,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(**_JSON_KW)
        except Exception as err:
            _LOGGER.debug("StashDB GraphQL request failed: %s", err)
            return None

        if not isinstance(payload, dict) or payload.get("errors"):
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        data = await self._graphql(session, FIND_SCENES_QUERY, {"query": title})
        if not data:
            return None

        scenes = ((data.get("queryScenes") or {}).get("scenes") or [])
        if not isinstance(scenes, list) or not scenes:
            return None

        first = scenes[0] if isinstance(scenes[0], dict) else None
        if not first:
            return None

        scene_id = first.get("id")
        if not scene_id:
            return None

        # Explicitly call SCENE_BY_ID_QUERY as requested in §6.3.
        detail = await self._graphql(session, SCENE_BY_ID_QUERY, {"id": str(scene_id)})
        scene = (detail or {}).get("findScene") if isinstance(detail, dict) else None
        if not isinstance(scene, dict):
            scene = first

        image_url = _pick_image(scene)
        if not image_url:
            return None

        return ArtworkResult(provider_name="stashdb", image_url=image_url, confidence=0.91)
