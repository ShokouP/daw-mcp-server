"""Queue bridge protocol between the MCP server and a live DAW adapter.

Protocol
--------
server -> DAW:   <queue>/<id>.req.json   {"id", "action", "params", "created_at"}
DAW -> server:   <queue>/<id>.res.json   {"id", "ok", "result" | "error"}
pending index:   <queue>/index.json      ["<id>", ...]  (read by ReaScript/FL adapters,
                                           since those runtimes cannot list directories easily)

Adapters poll the queue directory (REAPER ReaScript / FL Studio MIDI-script
Python), execute the action via the DAW's scripting API, then write the result.

A MockBridge is included for tests/CI (deterministic in-memory project state).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


class BridgeError(RuntimeError):
    pass


class QueueBridge:
    def __init__(self, queue_dir: str | Path, timeout: float = 15.0, adapters: list[str] | None = None):
        self.queue = Path(queue_dir)
        self.queue.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.adapters = adapters or ["reaper", "flstudio"]
        if not (self.queue / "index.json").exists():
            self._write_index([])

    # -- index helpers ------------------------------------------------------
    def _read_index(self) -> list[str]:
        try:
            data = json.loads((self.queue / "index.json").read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write_index(self, ids: list[str]) -> None:
        (self.queue / "index.json").write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")

    def _index_add(self, rid: str) -> None:
        ids = self._read_index()
        if rid not in ids:
            ids.append(rid)
            self._write_index(ids)

    def _index_remove(self, rid: str) -> None:
        ids = [i for i in self._read_index() if i != rid]
        self._write_index(ids)

    # -- protocol -----------------------------------------------------------
    def _write_req(self, action: str, params: dict) -> Path:
        rid = uuid.uuid4().hex[:12]
        req = self.queue / f"{rid}.req.json"
        req.write_text(json.dumps({
            "id": rid, "action": action, "params": params,
            "created_at": time.time(),
            "adapters": self.adapters,
        }, ensure_ascii=False), encoding="utf-8")
        self._index_add(rid)
        return req

    def call(self, action: str, params: dict | None = None) -> dict:
        req = self._write_req(action, params or {})
        rid = req.name.split(".")[0]
        res_path = self.queue / f"{rid}.res.json"
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if res_path.exists():
                data = json.loads(res_path.read_text(encoding="utf-8"))
                req.unlink(missing_ok=True)
                res_path.unlink(missing_ok=True)
                self._index_remove(rid)
                if not data.get("ok", False):
                    raise BridgeError(data.get("error", "adapter error"))
                return data.get("result", {})
            time.sleep(0.1)
        req.unlink(missing_ok=True)
        self._index_remove(rid)
        raise BridgeError(
            f"bridge timeout: no adapter responded to '{action}' within {self.timeout}s. "
            "Load adapters/reaper_bridge.lua in REAPER or adapters/flstudio_bridge.py in FL Studio, "
            "and make sure the server's bridge_queue matches QUEUE_DIR in the adapter.")


class MockBridge:
    """In-memory DAW emulator used by tests and GPU-less CI."""

    def __init__(self, tracks: list[dict] | None = None):
        self.state = {"format": "mock-bridge", "tracks": tracks or [], "markers": []}
        self.log: list[dict] = []

    def call(self, action: str, params: dict | None = None) -> dict:
        params = params or {}
        self.log.append({"action": action, "params": params})
        tracks = self.state["tracks"]
        if action == "get_state":
            return {"project": self.state}
        if action == "set_track":
            name = params.get("track")
            for t in tracks:
                if t.get("name") == name:
                    for k in ("volume_db", "pan", "muted"):
                        if k in params:
                            t[k] = params[k]
                    return {"ok": True, "track": t}
            raise BridgeError(f"track not found: {name}")
        if action == "add_marker":
            self.state["markers"].append({"name": params.get("name", ""),
                                          "time_beats": params.get("time_beats", 0)})
            return {"ok": True, "markers": len(self.state["markers"])}
        if action == "set_send":
            return {"ok": True, "note": "mock recorded send", "params": params}
        if action == "render":
            from .render import mock_render
            project = params.get("project")
            if not project:
                raise BridgeError("render params require 'project' path")
            return mock_render(project, params.get("out", "mock_render.wav"),
                               duration=params.get("duration", 2.0))
        raise BridgeError(f"mock bridge does not support action: {action}")
