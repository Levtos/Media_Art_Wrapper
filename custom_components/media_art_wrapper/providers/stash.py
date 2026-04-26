"""Stash provider (local GraphQL scene lookup with screenshot priority)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .base import ArtworkProvider, ArtworkQuery, ArtworkResult

_LOGGER = logging.getLogger(__name__)
_JSON_KW = {"content_type": None}

FIND_SCENES_QUERY = """
query FindScenes($query: String!) {
  findScenes(
    scene_filter: { title: { value: $query, modifier: INCLUDES } }
    filter: { per_page: 6 }
  ) {
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

GENERATE_SCREENSHOT_MUTATION = """
mutation GenerateScreenshot($id: ID!) {
  sceneGenerateScreenshot(id: $id)
}
"""


class StashProvider(ArtworkProvider):
    categories = frozenset({"adult"})

    def __init__(self, base_url: str, api_key: str, host_rewrite: str = "") -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = (api_key or "").strip()
        self._host_rewrite = (host_rewrite or "").strip()

    def is_available(self) -> bool:
        return bool(self._base_url)

    def _graphql_url(self) -> str:
        return f"{self._base_url}/graphql"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["ApiKey"] = self._api_key
        return headers

    def _rewrite_url(self, url: str) -> str:
        if not url.startswith("http"):
            return url
        parts = urlsplit(url)
        if not parts.hostname:
            return url
        host = parts.hostname.lower()
        if host not in {"127.0.0.1", "localhost", "host.docker.internal", "stash", "stashapp"}:
            return url
        if not self._host_rewrite:
            return url

        target = self._host_rewrite
        if ":" in target:
            new_host, new_port = target.split(":", 1)
            try:
                port = int(new_port)
            except ValueError:
                port = parts.port
        else:
            new_host, port = target, parts.port

        netloc = f"{new_host}:{port}" if port else new_host
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    def _normalize_screenshot_url(self, screenshot_url: str) -> str:
        """Normalize Stash screenshot URLs for HA-reachable access.

        Stash commonly emits screenshot URLs on localhost:9999. If we know the
        configured base URL, remap those URLs to the same host/port as base_url.
        Then apply optional host rewrite for Docker/loopback environments.
        """
        normalized = screenshot_url
        src = urlsplit(screenshot_url)
        base = urlsplit(self._base_url)
        if (
            src.scheme in {"http", "https"}
            and src.hostname == "localhost"
            and src.port == 9999
            and base.scheme
            and base.hostname
        ):
            target_port = base.port
            if target_port is None:
                target_port = 443 if base.scheme == "https" else 80
            normalized = urlunsplit(
                (
                    base.scheme,
                    f"{base.hostname}:{target_port}",
                    src.path,
                    src.query,
                    src.fragment,
                )
            )
        return self._rewrite_url(normalized)

    async def _post_graphql(self, session, query: str, variables: dict[str, Any]) -> dict[str, Any] | None:
        for attempt in range(2):
            try:
                async with session.post(
                    self._graphql_url(),
                    json={"query": query, "variables": variables},
                    headers=self._headers(),
                    timeout=10,
                ) as resp:
                    resp.raise_for_status()
                    payload = await resp.json(**_JSON_KW)
                if isinstance(payload, dict) and not payload.get("errors"):
                    data = payload.get("data")
                    if isinstance(data, dict):
                        return data
            except Exception as err:
                _LOGGER.debug("Stash GraphQL failed (attempt %s): %s", attempt + 1, err)
            if attempt == 0:
                await asyncio.sleep(0.2)
        return None

    async def _trigger_screenshot_generation(self, session, scene_id: str) -> None:
        try:
            await self._post_graphql(session, GENERATE_SCREENSHOT_MUTATION, {"id": scene_id})
        except Exception as err:
            _LOGGER.debug("Stash screenshot generation call failed: %s", err)

    def _pick_fallback(self, scene: dict[str, Any]) -> str | None:
        for performer in scene.get("performers") or []:
            if isinstance(performer, dict) and isinstance(performer.get("image_path"), str):
                return self._rewrite_url(performer["image_path"])
        studio = scene.get("studio")
        if isinstance(studio, dict) and isinstance(studio.get("image_path"), str):
            return self._rewrite_url(studio["image_path"])
        return None

    async def fetch(self, session, query: ArtworkQuery) -> ArtworkResult | None:
        title = (query.title or "").strip()
        if not title:
            return None

        data = await self._post_graphql(session, FIND_SCENES_QUERY, {"query": title})
        scenes = ((data or {}).get("findScenes") or {}).get("scenes") or []
        if not isinstance(scenes, list) or not scenes:
            return None

        first = scenes[0] if isinstance(scenes[0], dict) else None
        if not first or not first.get("id"):
            return None

        detail = await self._post_graphql(session, SCENE_BY_ID_QUERY, {"id": str(first["id"])})
        scene = (detail or {}).get("findScene") if isinstance(detail, dict) else None
        if not isinstance(scene, dict):
            scene = first

        screenshot = ((scene.get("paths") or {}).get("screenshot") if isinstance(scene.get("paths"), dict) else None)
        if isinstance(screenshot, str) and screenshot:
            return ArtworkResult(
                provider_name="stash",
                image_url=self._normalize_screenshot_url(screenshot),
                confidence=0.97,
            )

        await self._trigger_screenshot_generation(session, str(first["id"]))
        detail = await self._post_graphql(session, SCENE_BY_ID_QUERY, {"id": str(first["id"])})
        generated = (detail or {}).get("findScene") if isinstance(detail, dict) else None
        generated_screenshot = (
            ((generated.get("paths") or {}).get("screenshot"))
            if isinstance(generated, dict) and isinstance(generated.get("paths"), dict)
            else None
        )
        if isinstance(generated_screenshot, str) and generated_screenshot:
            return ArtworkResult(
                provider_name="stash",
                image_url=self._normalize_screenshot_url(generated_screenshot),
                confidence=0.95,
            )

        fallback = self._pick_fallback(scene)
        if fallback:
            return ArtworkResult(provider_name="stash", image_url=fallback, confidence=0.93)
        return None
