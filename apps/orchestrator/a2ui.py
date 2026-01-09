from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

Json = Dict[str, Any]


def now_iso() -> str:
    # Local time ISO, second precision (demo)
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_message_id() -> str:
    return str(uuid.uuid4())


def _ensure_path(obj: Json, path: str) -> Any:
    # Creates nested dicts for all but last segment. Returns parent.
    if not path.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {path}")
    parts = [p for p in path.split("/") if p]
    cur: Any = obj
    for seg in parts[:-1]:
        if isinstance(cur, dict):
            if seg not in cur or not isinstance(cur[seg], dict):
                cur[seg] = {}
            cur = cur[seg]
        else:
            raise ValueError(f"Cannot traverse non-dict at segment '{seg}' for path '{path}'")
    return cur, (parts[-1] if parts else "")


def apply_patches(model: Json, patches: List[Json]) -> Json:
    # Minimal JSON Patch subset for demo: add/replace at JSON pointer
    for p in patches:
        op = p.get("op")
        path = p.get("path")
        value = p.get("value")
        if op not in ("add", "replace"):
            continue
        if not isinstance(path, str):
            continue
        parent, last = _ensure_path(model, path)
        if last == "":
            # replace whole model
            if isinstance(value, dict):
                model.clear()
                model.update(value)
            continue
        if isinstance(parent, dict):
            parent[last] = value
    return model


def surface_open(surface_id: str, title: str, data_model: Optional[Json] = None) -> Json:
    return {
        "kind": "surface/open",
        "surfaceId": surface_id,
        "title": title,
        "dataModel": data_model or {},
    }


def data_model_update(surface_id: str, patches: List[Json]) -> Json:
    return {
        "kind": "dataModelUpdate",
        "surfaceId": surface_id,
        "patches": patches,
    }


@dataclass
class SessionState:
    session_id: str
    queue: "asyncio.Queue[Json]" = field(default_factory=asyncio.Queue)
    models: Dict[str, Json] = field(default_factory=dict)

    def get_model(self, surface_id: str) -> Json:
        if surface_id not in self.models:
            self.models[surface_id] = {}
        return self.models[surface_id]


class SessionHub:
    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> SessionState:
        async with self._lock:
            sid = str(uuid.uuid4())
            s = SessionState(session_id=sid)
            self._sessions[sid] = s
            return s

    async def get(self, sid: str) -> Optional[SessionState]:
        async with self._lock:
            return self._sessions.get(sid)

    async def drop(self, sid: str) -> None:
        async with self._lock:
            self._sessions.pop(sid, None)

    async def push(self, sid: str, msg: Json) -> None:
        s = await self.get(sid)
        if not s:
            return
        await s.queue.put(msg)

    async def push_update_and_apply(self, sid: str, surface_id: str, patches: List[Json]) -> None:
        s = await self.get(sid)
        if not s:
            return
        model = s.get_model(surface_id)
        apply_patches(model, patches)
        await s.queue.put(data_model_update(surface_id, patches))
