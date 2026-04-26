"""Persistent game metadata database (LASTENHEFT §4.2-§4.4).

Async-first per HA's event-loop discipline: the in-memory mutex is an
``asyncio.Lock`` and the JSON-file read/write is dispatched off-loop
via ``loop.run_in_executor`` so a slow disk does not block the event
loop. All public read/write helpers are coroutines.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

GAME_DB_PATH = Path("/config/custom_components/smart_player/game_db.json")
_KEY_RE = re.compile(r"[^a-z0-9]+")
_LOCK = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def key_for_title(title: str) -> str:
    return _KEY_RE.sub("_", title.strip().lower()).strip("_") or "unknown"


def _default_entry(title: str) -> dict[str, Any]:
    return {
        "canonical_title": title,
        "sgdb_id": None,
        "igdb_id": None,
        "logo_url": None,
        "logo_override_url": None,
        "logo_cached_path": None,
        "cover_cached_path": None,
        "cover_url": None,
        "last_seen": _now_iso(),
        "play_count": 0,
        "lookup_failed": False,
    }


def _load_sync() -> dict[str, dict[str, Any]]:
    if not GAME_DB_PATH.exists():
        return {}
    try:
        payload = json.loads(GAME_DB_PATH.read_text(encoding="utf-8"))
    except Exception as err:
        _LOGGER.debug("game_db load failed: %s", err)
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_sync(data: dict[str, dict[str, Any]]) -> None:
    GAME_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    GAME_DB_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


async def _aio_load() -> dict[str, dict[str, Any]]:
    return await asyncio.get_running_loop().run_in_executor(None, _load_sync)


async def _aio_save(data: dict[str, dict[str, Any]]) -> None:
    await asyncio.get_running_loop().run_in_executor(None, _save_sync, data)


async def touch_title(title: str) -> dict[str, Any]:
    key = key_for_title(title)
    async with _LOCK:
        db = await _aio_load()
        entry = db.get(key)
        if not isinstance(entry, dict):
            entry = _default_entry(title)
        entry["canonical_title"] = str(entry.get("canonical_title") or title)
        entry["last_seen"] = _now_iso()
        entry["play_count"] = int(entry.get("play_count") or 0) + 1
        db[key] = entry
        await _aio_save(db)
        return dict(entry)


async def update_title(title: str, **fields: Any) -> dict[str, Any]:
    key = key_for_title(title)
    async with _LOCK:
        db = await _aio_load()
        entry = db.get(key)
        if not isinstance(entry, dict):
            entry = _default_entry(title)
        for k, v in fields.items():
            entry[k] = v
        entry["last_seen"] = _now_iso()
        db[key] = entry
        await _aio_save(db)
        return dict(entry)


async def get_title(title: str) -> dict[str, Any] | None:
    key = key_for_title(title)
    async with _LOCK:
        db = await _aio_load()
        entry = db.get(key)
        return dict(entry) if isinstance(entry, dict) else None
