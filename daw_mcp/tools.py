"""Tool registry + dispatch for the DAW MCP server."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import bridge as bridge_mod
from . import metrics as metrics_mod
from . import render as render_mod
from . import rpp
from . import dawproject

# ---------------------------------------------------------------------------
# DAW API survey (also written to docs/DAW-API-SURVEY.md)
# ---------------------------------------------------------------------------
DAW_APIS = {
    "flstudio": {
        "automation": ["MIDI scripting API (Python device scripts in FL's Python)",
                        "Piano roll scripting (.pyscript, flpianoroll module)",
                        "MIDI controller script message API (OnMidiMsg)"],
        "readable": ["transport position/tempo", "mixer track volume/pan/mute/solo",
                     "channel/plugin parameters via plugins.getParamCount/getParamName/getParamValue",
                     "pattern/note data (via piano roll scripting or plugin params)"],
        "writable": ["mixer.setTrackVolume/setTrackPan/setTrackMute", "plugins.setParamValue",
                     "transport", "ui focus", "piano roll notes (script-based)"],
        "limits": ["no official headless CLI", "no official project file API",
                   "scripting runs inside FL; needs a bridge (queue/file/MIDI) for external control"],
        "bridge": "adapters/flstudio_bridge.py (queue-based MIDI-script device)",
    },
    "reaper": {
        "automation": ["ReaScript API (Lua/EEL2/Python) - ~2000 functions",
                        "command line: -new -open -saveas -renderproject -batchconvert -nosplash -close -quit",
                        "Web Remote Control (HTTP)", "OSC control surface"],
        "readable": ["tracks, items, takes, FX chains and all FX parameters",
                     "sends/receives, automation envelopes, markers/regions, tempo map",
                     "project render settings"],
        "writable": ["everything above via ReaScript; render via CLI or ReaScript",
                     "markers, items, MIDI/audio media, FX params, sends, envelopes"],
        "limits": ["ReaScript must run inside REAPER (defer loop) for live control",
                   "render output paths are configured in project/render settings"],
        "bridge": "adapters/reaper_bridge.lua (ReaScript queue bridge) + render_cmd config",
    },
    "dawproject": {
        "automation": ["open ZIP+XML project format (MIT); read/write by converter tools"],
        "readable": ["tracks, clips, channels, devices, automation, transport/markers"],
        "writable": ["whole project via converters (DawVert/ProjectConverter, Bitwig/Studio One/Cubase)"],
        "limits": ["no live DAW control; file-level exchange only"],
        "bridge": "daw_mcp.dawproject (read summary); use live bridges for edits",
    },
    "ardour": {
        "automation": ["Lua scripting API (inside Ardour)", "OSC", "headless CLI (ardour8 -N)"],
        "readable": ["tracks, processors, automation, transport"],
        "writable": ["most session state via Lua/OSC; export via CLI"],
        "limits": ["Lua runs inside Ardour"],
    },
    "ableton-live": {
        "automation": ["Max for Live devices", "Live remote scripts (Python, in-app)"],
        "readable": ["transport, tracks, devices, clips (via M4L/remote scripts)"],
        "writable": ["same via M4L/remote scripts"],
        "limits": ["no official external API/CLI; .als unofficial (gzip XML)"],
    },
    "pro-tools": {
        "automation": ["Pro Tools Scripting SDK (official, Windows/macOS)"],
        "readable/writable": ["session operations, transport, render/bounce via SDK"],
        "limits": ["requires Pro Tools + SDK licensing/toolchain"],
    },
    "bitwig": {
        "automation": ["Java controller API", "DAWproject import/export"],
        "limits": ["controller API runs inside Bitwig"],
    },
    "logic-pro": {
        "automation": ["Scripter MIDI FX (JS)", "AppleScript UI automation"],
        "limits": ["macOS only; no official project API"],
    },
}

PATCH_OP_SCHEMA = {
    "type": "object",
    "properties": {
        "ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": [
                        "set_track", "set_eq", "set_comp", "set_send", "add_marker"]},
                    "track": {"type": "string"},
                    "fields": {"type": "object"},
                    "band": {"type": "string"},
                    "time_beats": {"type": "number"},
                    "name": {"type": "string"},
                    "from_track": {"type": "string"},
                    "to_track": {"type": "string"},
                    "gain_db": {"type": "number"},
                },
                "required": ["op"],
            },
        }
    },
    "required": ["ops"],
}

RANGES = {
    "volume_db": (-60.0, 12.0),
    "pan": (-1.0, 1.0),
    "gain_db": (-60.0, 12.0),
    "threshold_db": (-60.0, 0.0),
    "ratio": (1.0, 20.0),
    "attack_ms": (0.1, 200.0),
    "release_ms": (5.0, 2000.0),
}


def validate_patch(patch: dict) -> dict:
    errors: list[str] = []
    ops = patch.get("ops")
    if not isinstance(ops, list) or not ops:
        return {"valid": False, "errors": ["patch.ops must be a non-empty array"]}
    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind not in ("set_track", "set_eq", "set_comp", "set_send", "add_marker"):
            errors.append(f"ops[{i}]: unknown op {kind!r}")
            continue
        fields = op.get("fields") or {}
        for key, (lo, hi) in RANGES.items():
            if key in fields:
                try:
                    v = float(fields[key])
                except (TypeError, ValueError):
                    errors.append(f"ops[{i}].fields.{key} is not numeric")
                    continue
                if not (lo <= v <= hi):
                    errors.append(f"ops[{i}].fields.{key}={v} out of range [{lo},{hi}]")
        if kind == "set_track" and not op.get("track"):
            errors.append(f"ops[{i}]: set_track requires track")
        if kind in ("set_eq", "set_comp") and not op.get("track"):
            errors.append(f"ops[{i}]: {kind} requires track")
        if kind == "set_send" and not (op.get("from_track") and op.get("to_track")):
            errors.append(f"ops[{i}]: set_send requires from_track/to_track")
    return {"valid": not errors, "errors": errors, "op_count": len(ops)}


# ---------------------------------------------------------------------------
# stateful server context
# ---------------------------------------------------------------------------
class Context:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.mock_bridge = bridge_mod.MockBridge(tracks=self.config.get("mock_tracks"))
        self.queue = None
        queue_dir = self.config.get("bridge_queue")
        if queue_dir:
            self.queue = bridge_mod.QueueBridge(queue_dir, timeout=self.config.get("bridge_timeout", 15.0))

    def bridge(self):
        return self.queue if self.queue is not None else self.mock_bridge

    def telemetry_path(self) -> Path:
        p = Path(self.config.get("telemetry_path", "daw_telemetry.jsonl"))
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def _ok(data: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
            "isError": False}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": f"ERROR: {msg}"}], "isError": True}


def dispatch(ctx: Context, name: str, args: dict) -> dict:
    try:
        if name == "daw_status":
            return _ok({
                "server": "daw-mcp-server",
                "config": {k: v for k, v in ctx.config.items() if k != "telemetry_path"},
                "bridge": "queue" if ctx.queue else "mock",
                "daws": list(DAW_APIS.keys()),
                "tools": [t["name"] for t in TOOLS],
            })
        if name == "daw_apis":
            return _ok(DAW_APIS)
        if name == "project_read":
            path = args["path"]
            suffix = Path(path).suffix.lower()
            summary = (dawproject.parse_dawproject(path) if suffix in (".dawproject", ".zip")
                       else rpp.parse_rpp(path))
            return _ok(summary)
        if name == "patch_validate":
            return _ok(validate_patch(args["patch"]))
        if name == "patch_apply":
            src = args["path"]
            out = args.get("out_path") or str(Path(src).with_name(Path(src).stem + ".patched" + Path(src).suffix))
            res = rpp.patch_rpp(src, args["patch"], out)
            res["validated"] = validate_patch(args["patch"])
            return _ok(res)
        if name == "render":
            out = args.get("out") or str(Path(args["path"]).with_suffix(".wav"))
            res = render_mod.render(args["path"], out,
                                    render_cmd=args.get("render_cmd", ctx.config.get("render_cmd", "")),
                                    duration=float(args.get("duration", 2.0)))
            return _ok(res)
        if name == "analyze":
            return _ok(metrics_mod.analyze_wav(args["wav"]))
        if name == "compare":
            a = metrics_mod.analyze_wav(args["wav_a"])
            b = metrics_mod.analyze_wav(args["wav_b"])
            return _ok({"a": a, "b": b, "delta": metrics_mod.diff_metrics(a, b)})
        if name == "bridge_call":
            res = ctx.bridge().call(args["action"], args.get("params") or {})
            return _ok(res)
        if name == "telemetry_append":
            rec = {"ts": time.time(), **args.get("record", {})}
            with ctx.telemetry_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return _ok({"appended": True, "path": str(ctx.telemetry_path())})
        if name == "verify_patch":
            project = args["path"]
            patch = args["patch"]
            validated = validate_patch(patch)
            if not validated["valid"]:
                return _ok({"pass": False, "validated": validated})
            tmpdir = Path(args.get("workdir") or "daw_mcp_work")
            tmpdir.mkdir(parents=True, exist_ok=True)
            base_wav = tmpdir / "base.wav"
            patched_src = tmpdir / "patched.rpp"
            patched_wav = tmpdir / "patched.wav"
            rpp.patch_rpp(project, patch, patched_src)
            render_cmd = args.get("render_cmd", ctx.config.get("render_cmd", ""))
            render_mod.render(project, base_wav, render_cmd=render_cmd)
            render_mod.render(patched_src, patched_wav, render_cmd=render_cmd)
            a = metrics_mod.analyze_wav(base_wav)
            b = metrics_mod.analyze_wav(patched_wav)
            delta = metrics_mod.diff_metrics(a, b)
            intent = args.get("intent") or {}
            score, checks = _score_intent(delta, intent)
            return _ok({"pass": score >= float(args.get("min_score", 0.0)),
                        "validated": validated, "score": round(score, 4),
                        "checks": checks, "base": a, "patched": b, "delta": delta,
                        "files": {"base_wav": str(base_wav), "patched_wav": str(patched_wav)}})
        return _err(f"unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001
        return _err(f"{type(exc).__name__}: {exc}")


def _score_intent(delta: dict, intent: dict) -> tuple[float, list[dict]]:
    """Cheap deterministic scoring of rendered differences against a target intent."""
    rules = []
    for key, target in intent.items():
        if key not in delta:
            continue
        got = delta[key]
        tgt = float(target)
        if tgt == 0:
            ok = abs(got) < 0.5
        else:
            ok = (got == 0) or (abs(got - tgt) / abs(tgt) < 0.5)
        rules.append({"metric": key, "target": tgt, "got": got, "ok": ok})
    if not rules:
        return 0.0, rules
    return sum(1 for r in rules if r["ok"]) / len(rules), rules


# ---------------------------------------------------------------------------
# MCP tool schemas
# ---------------------------------------------------------------------------
TOOLS = [
    {"name": "daw_status", "description": "Server config, bridge mode and available DAW adapters.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "daw_apis", "description": "Survey of DAW automation APIs/commands (FL Studio, REAPER, DAWproject, Ardour, Ableton, Pro Tools, Bitwig, Logic).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "project_read", "description": "Read a REAPER .rpp or DAWproject file: tracks, volume/pan, sends, markers, tempo.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "patch_validate", "description": "Validate a DAWcoder IR patch (ops schema + parameter ranges).",
     "inputSchema": {"type": "object", "properties": {"patch": PATCH_OP_SCHEMA}, "required": ["patch"]}},
    {"name": "patch_apply", "description": "Apply an IR patch to a copy of an .rpp project file; returns applied/unsupported ops.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "patch": PATCH_OP_SCHEMA, "out_path": {"type": "string"}},
         "required": ["path", "patch"]}},
    {"name": "render", "description": "Render a project to WAV (configured DAW command, or deterministic mock renderer).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "out": {"type": "string"},
         "render_cmd": {"type": "string"}, "duration": {"type": "number"}},
         "required": ["path"]}},
    {"name": "analyze", "description": "Analyze a WAV: peak/RMS/LUFS-approx/LRA/spectral centroid/bands/stereo width.",
     "inputSchema": {"type": "object", "properties": {"wav": {"type": "string"}}, "required": ["wav"]}},
    {"name": "compare", "description": "Compare two WAVs and return metric deltas.",
     "inputSchema": {"type": "object", "properties": {"wav_a": {"type": "string"}, "wav_b": {"type": "string"}},
                     "required": ["wav_a", "wav_b"]}},
    {"name": "bridge_call", "description": "Call a live DAW bridge action (get_state/set_track/set_eq/set_comp/set_send/add_marker/render/transport).",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string"}, "params": {"type": "object"}}, "required": ["action"]}},
    {"name": "verify_patch", "description": "Closed loop: apply patch -> render baseline+patched -> analyze -> score against intent.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "patch": PATCH_OP_SCHEMA,
         "intent": {"type": "object"}, "min_score": {"type": "number"},
         "render_cmd": {"type": "string"}, "workdir": {"type": "string"}},
         "required": ["path", "patch"]}},
    {"name": "telemetry_append", "description": "Append one record to the engineer-edit telemetry JSONL (for training data).",
     "inputSchema": {"type": "object", "properties": {"record": {"type": "object"}}, "required": ["record"]}},
]
