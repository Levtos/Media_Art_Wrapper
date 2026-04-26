"""Stash Player integration — based on Druidblack/stash-home-assistant."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVE_SCENE_QUERY,
    CLIENT_KEY,
    CONF_API_KEY,
    CONF_POLL_INTERVAL,
    CONF_URL,
    CONF_USE_WEBHOOK,
    COORDINATOR_KEY,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FRESH_PLAY_THRESHOLD_SECONDS,
    LIBRARY_COORDINATOR_KEY,
    PLATFORMS,
    STREAM_ACTIVITY_GRACE_SECONDS,
    WEBHOOK_VIEW_KEY,
)

_LOGGER = logging.getLogger(__name__)


class StashError(Exception):
    """Base error for Stash API."""


class StashClient:
    """Simple async GraphQL client for Stash."""

    def __init__(self, graphql_url: str, session, api_key: str = "") -> None:
        self._url = graphql_url.rstrip("/")
        self._session = session
        self._api_key = api_key.strip()
        self._base_url = self._url[:-len("/graphql")] if self._url.endswith("/graphql") else self._url

    @property
    def stash_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict:
        return {"ApiKey": self._api_key} if self._api_key else {}

    async def _post(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        async with asyncio.timeout(10):
            async with self._session.post(self._url, json=payload, headers=self._headers()) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise StashError(f"HTTP {resp.status}: {text}")
                data = await resp.json()
        if "errors" in data:
            raise StashError(f"GraphQL errors: {data['errors']}")
        return data

    async def _post_allow_errors(self, query: str) -> dict[str, Any]:
        payload = {"query": query}
        async with asyncio.timeout(10):
            async with self._session.post(self._url, json=payload, headers=self._headers()) as resp:
                if resp.status != 200:
                    raise StashError(f"HTTP {resp.status}")
                return await resp.json()

    async def validate(self) -> None:
        await self._post("query { version { version } }")

    async def get_scenes_count(self) -> int:
        data = await self._post("query { findScenes { count } }")
        return int(data["data"]["findScenes"]["count"])

    async def get_movies_count(self) -> int:
        raw = await self._post_allow_errors("query { findGroups { count } }")
        try:
            return int(raw["data"]["findGroups"]["count"])
        except (KeyError, TypeError, ValueError):
            pass
        raw2 = await self._post_allow_errors("query { findMovies { count } }")
        try:
            return int(raw2["data"]["findMovies"]["count"])
        except (KeyError, TypeError, ValueError):
            return 0

    async def get_performers_count(self) -> int:
        data = await self._post("query { findPerformers { count } }")
        return int(data["data"]["findPerformers"]["count"])

    async def get_studios_count(self) -> int:
        data = await self._post("query { findStudios { count } }")
        return int(data["data"]["findStudios"]["count"])

    async def get_tags_count(self) -> int:
        data = await self._post("query { findTags { count } }")
        return int(data["data"]["findTags"]["count"])

    async def get_images_count(self) -> int:
        data = await self._post("query { findImages { count } }")
        return int(data["data"]["findImages"]["count"])

    async def get_galleries_count(self) -> int:
        data = await self._post("query { findGalleries { count } }")
        return int(data["data"]["findGalleries"]["count"])

    async def get_markers_count(self) -> int:
        data = await self._post("query { findSceneMarkers { count } }")
        return int(data["data"]["findSceneMarkers"]["count"])

    async def get_version(self) -> str | None:
        data = await self._post("query { version { version } }")
        try:
            return str(data["data"]["version"]["version"])
        except (KeyError, TypeError):
            return None

    async def generate_screenshot(self, scene_id: str) -> None:
        await self._post_allow_errors(
            f'mutation {{ sceneGenerateScreenshot(id: "{scene_id}") }}'
        )

    async def save_activity(self, scene_id: str, position: float) -> None:
        await self._post_allow_errors(
            f'mutation {{ sceneSaveActivity(id: "{scene_id}", resume_time: {position}) }}'
        )

    async def metadata_scan(self) -> None:
        await self._post("mutation { metadataScan(input:{}) }")

    async def metadata_clean(self) -> None:
        await self._post('mutation { metadataClean(input: {dryRun: false, paths: ""}) }')

    async def metadata_generate(self) -> None:
        await self._post("mutation { metadataGenerate(input: {}) }")

    async def metadata_auto_tag(self) -> None:
        await self._post("mutation { metadataAutoTag(input: {}) }")

    async def metadata_identify(self) -> None:
        await self._post(
            'mutation { metadataIdentify(input: { sources: [{ source: { stash_box_endpoint: "https://stashdb.org/graphql" } }] }) }'
        )


class StashLibraryCoordinator(DataUpdateCoordinator):
    """Polls library statistics every 5 minutes."""

    def __init__(self, hass: HomeAssistant, client: StashClient) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_library",
                         update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL))
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return {
                "scenes":     await self.client.get_scenes_count(),
                "movies":     await self.client.get_movies_count(),
                "performers": await self.client.get_performers_count(),
                "studios":    await self.client.get_studios_count(),
                "tags":       await self.client.get_tags_count(),
                "images":     await self.client.get_images_count(),
                "galleries":  await self.client.get_galleries_count(),
                "markers":    await self.client.get_markers_count(),
                "version":    await self.client.get_version(),
            }
        except Exception as err:
            raise UpdateFailed(f"Library update failed: {err}") from err


class StashPlaybackCoordinator(DataUpdateCoordinator):
    """Polls Stash for active playback.

    Stash provides no first-class "currently streaming" query. The top-level
    ``sceneStreams`` GraphQL field actually requires a scene id and returns
    the *available* stream URLs for that scene, not a list of live sessions.

    Empirically verified on Stash v0.31.1: ``last_played_at`` is written only
    once at the start of a play session and does NOT advance. ``play_duration``
    and ``resume_time`` however are advanced by the web player's
    ``sceneSaveActivity`` mutation roughly every 10 seconds during playback
    and stop advancing the moment the stream pauses or ends. This makes
    ``play_duration`` the cleanest "is currently playing" signal: monotonically
    increasing, and only while the player is actually pumping frames.

    Detection rule per scene:
      1. Primary — if ``play_duration`` has strictly increased since the last
         poll, the scene is streaming *now*. Keep it marked as streaming for
         ``STREAM_ACTIVITY_GRACE_SECONDS`` after the last observed increase
         so that variable save intervals do not flap the state.
      2. Fallback for first observation (e.g. HA restart mid-stream) — if we
         have no prior signal for this scene but its ``last_played_at`` is
         younger than ``FRESH_PLAY_THRESHOLD_SECONDS``, treat the scene as
         streaming until the next poll provides a real delta.

    Data contract returned to entities:
        {
            "scenes":              list[dict],    # up to 2, currently streaming
            "active_scene_ids":    set[str],
            "is_streaming":        bool,
            "active_stream_count": int,
            "last_played":         dict | None,   # most recent scene, any age
        }

    Each scene dict in "scenes" has ``_is_streaming = True``.
    """

    def __init__(self, hass: HomeAssistant, client: StashClient, poll_interval: int) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN,
                         update_interval=timedelta(seconds=max(2, poll_interval)))
        self.client = client
        # scene_id -> {"play_duration": float, "last_activity_ts": float}
        self._scene_signals: dict[str, dict[str, Any]] = {}

    def _fix_paths(self, scene: dict) -> dict:
        base = self.client.stash_url
        paths = scene.get("paths") or {}
        screenshot = paths.get("screenshot")
        if screenshot:
            paths["screenshot"] = (
                screenshot
                .replace("http://localhost:9999", base)
                .replace("https://localhost:9999", base)
            )
            scene["paths"] = paths
        return scene

    def _prune_stale_signals(self, seen_ids: set[str], now_ts: float) -> None:
        """Drop signal state for scenes we haven't seen in a while."""
        cutoff = STREAM_ACTIVITY_GRACE_SECONDS * 2
        stale = [
            sid for sid, sig in self._scene_signals.items()
            if sid not in seen_ids
            and (now_ts - (sig.get("last_activity_ts") or 0)) > cutoff
        ]
        for sid in stale:
            self._scene_signals.pop(sid, None)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            raw = await self.client._post_allow_errors(ACTIVE_SCENE_QUERY)
            scenes_raw = (
                ((raw.get("data") or {}).get("findScenes") or {}).get("scenes") or []
            )
        except Exception as err:
            raise UpdateFailed(f"Playback update failed: {err}") from err

        now = dt_util.utcnow()
        now_ts = now.timestamp()

        streaming_scenes: list[dict] = []
        active_scene_ids: set[str] = set()
        seen_ids: set[str] = set()

        for raw_scene in scenes_raw:
            sid_val = raw_scene.get("id")
            if sid_val is None:
                continue
            sid = str(sid_val)
            seen_ids.add(sid)

            scene = self._fix_paths(dict(raw_scene))
            try:
                play_duration = float(scene.get("play_duration") or 0)
            except (TypeError, ValueError):
                play_duration = 0.0

            prev = self._scene_signals.get(sid)
            delta_advanced = False
            fresh_first_seen = False

            if prev is None:
                # First observation — fall back to last_played_at recency so
                # we don't show idle for a couple of polls right after HA
                # restarts mid-stream.
                lpa = scene.get("last_played_at")
                if lpa:
                    lp_dt = dt_util.parse_datetime(lpa)
                    if lp_dt is not None:
                        age = (now - lp_dt).total_seconds()
                        if 0 <= age < FRESH_PLAY_THRESHOLD_SECONDS:
                            fresh_first_seen = True
            else:
                prev_duration = float(prev.get("play_duration") or 0)
                if play_duration > prev_duration:
                    delta_advanced = True

            last_activity_ts = (prev or {}).get("last_activity_ts")
            if delta_advanced or fresh_first_seen:
                last_activity_ts = now_ts
                _LOGGER.debug(
                    "stash scene %s active: play_duration=%.1f (delta=%s fresh=%s)",
                    sid, play_duration, delta_advanced, fresh_first_seen,
                )

            self._scene_signals[sid] = {
                "play_duration": play_duration,
                "last_activity_ts": last_activity_ts,
            }

            if (
                last_activity_ts is not None
                and (now_ts - last_activity_ts) < STREAM_ACTIVITY_GRACE_SECONDS
            ):
                scene["_is_streaming"] = True
                streaming_scenes.append(scene)
                active_scene_ids.add(sid)

        self._prune_stale_signals(seen_ids, now_ts)

        # Cap displayed slots at 2; the most recent activity wins naturally
        # because ACTIVE_SCENE_QUERY already sorts by last_played_at DESC.
        streaming_scenes = streaming_scenes[:2]
        active_scene_ids = {str(s["id"]) for s in streaming_scenes if s.get("id")}

        # last_played summary (always the most-recently-played scene, any age)
        last_played_summary: dict | None = None
        if scenes_raw:
            top = self._fix_paths(dict(scenes_raw[0]))
            studio = top.get("studio") or {}
            performers = top.get("performers") or []
            last_played_summary = {
                "id": top.get("id"),
                "title": top.get("title"),
                "last_played_at": top.get("last_played_at"),
                "studio": studio.get("name"),
                "performers": [p.get("name") for p in performers if p.get("name")],
                "screenshot": (top.get("paths") or {}).get("screenshot"),
            }

        return {
            "scenes": streaming_scenes,
            "is_streaming": bool(active_scene_ids),
            "active_scene_ids": active_scene_ids,
            "active_stream_count": len(active_scene_ids),
            "last_played": last_played_summary,
        }


class StashWebhookView(HomeAssistantView):
    """Receive webhook POST from Stash and trigger immediate refresh."""

    requires_auth = False

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.url = f"/api/stash_player/webhook/{entry_id}"
        self.name = f"api:stash_player:webhook:{entry_id}"

    async def post(self, request: web.Request) -> web.Response:
        await request.json(content_type=None)
        data = self.hass.data.get(DOMAIN, {}).get(self.url.rsplit("/", 1)[-1], {})
        coordinator = data.get(COORDINATOR_KEY)
        if coordinator:
            self.hass.async_create_task(coordinator.async_request_refresh())
        return self.json({"ok": True})


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version < 2:
        new_data = dict(entry.data)
        if "stash_url" in new_data and CONF_URL not in new_data:
            new_data[CONF_URL] = new_data.pop("stash_url")
        hass.config_entries.async_update_entry(entry, data=new_data, version=2)
        _LOGGER.info("Migrated Stash Player config entry to version 2")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    graphql_url: str = entry.data[CONF_URL]
    api_key: str = entry.data.get(CONF_API_KEY, "")

    client = StashClient(graphql_url, session, api_key)

    poll_interval = int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
    playback = StashPlaybackCoordinator(hass, client, poll_interval)
    library = StashLibraryCoordinator(hass, client)

    try:
        await playback.async_config_entry_first_refresh()
        await library.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        COORDINATOR_KEY: playback,
        LIBRARY_COORDINATOR_KEY: library,
        CLIENT_KEY: client,
    }

    if entry.options.get(CONF_USE_WEBHOOK, False):
        view = StashWebhookView(hass, entry.entry_id)
        hass.http.register_view(view)
        hass.data[DOMAIN][entry.entry_id][WEBHOOK_VIEW_KEY] = view

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("Stash Player connected to %s", graphql_url)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
