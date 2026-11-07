-- flstudio_bridge.py - FL Studio MIDI-scripting queue bridge (template)
--
-- Install: copy into FL Studio's controller script folder
--   %USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\daw_mcp\
--   (create folder; place this file as device_daw_mcp.py)
-- Select it in Options -> MIDI settings -> Controller type.
--
-- The script polls QUEUE_DIR (set below) every OnIdle; server side must configure
-- the same path as "bridge_queue". Actions: get_state / set_track / set_send /
-- add_marker / set_eq / set_comp (best-effort via plugins params).
--
-- NOTE: FL's MIDI scripting API differs across versions; this is a starting
-- template - verify function names against your FL Studio version's
-- "MIDI Scripting API" documentation. The mock bridge in daw_mcp/bridge.py is
-- the tested reference for the protocol.

import json
import os
import time

QUEUE_DIR = r"C:/daw_mcp_queue"
POLL_EVERY = 0.5
_last_poll = 0.0


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


def _pending_ids():
    idx = _read_json(os.path.join(QUEUE_DIR, "index.json")) or []
    return idx if isinstance(idx, list) else []


def _track_by_name(name):
    try:
        count = mixer.trackCount()
    except Exception:
        count = 0
    for i in range(count):
        try:
            if mixer.getTrackName(i) == name:
                return i
        except Exception:
            continue
    return None


def _plugin_of_track(index):
    try:
        plugs = plugins.getTrackPlugins(index)
        return plugs[0] if plugs else None
    except Exception:
        return None


def _set_fx_params(track_index, wanted):
    """wanted: {match: value} applied to the first plugin whose param name matches."""
    p = _plugin_of_track(track_index)
    if p is None:
        return False
    try:
        count = plugins.getParamCount(p)
    except Exception:
        return False
    applied = 0
    for i in range(count):
        try:
            name = (plugins.getParamName(i, p) or "").lower()
        except Exception:
            continue
        for match, (lo, hi, value) in wanted.items():
            if match in name:
                try:
                    norm = (value - lo) / (hi - lo) if hi != lo else 0.5
                    plugins.setParamValue(max(0.0, min(1.0, norm)), i, p)
                    applied += 1
                except Exception:
                    pass
    return applied > 0


def _handle(action, params):
    if action == "get_state":
        try:
            tempo = transport.getTempo()
        except Exception:
            tempo = 120.0
        tracks = []
        for i in range(mixer.trackCount()):
            try:
                tracks.append({
                    "index": i,
                    "name": mixer.getTrackName(i),
                    "volume": mixer.getTrackVolume(i),
                    "pan": mixer.getTrackPan(i),
                    "muted": bool(mixer.isTrackMuted(i)) if hasattr(mixer, "isTrackMuted") else None,
                })
            except Exception:
                continue
        return {"format": "flstudio", "tempo": tempo, "tracks": tracks, "markers": []}
    if action == "set_track":
        idx = _track_by_name(params.get("track", ""))
        if idx is None:
            raise RuntimeError("track not found: " + str(params.get("track")))
        if "volume_db" in params and params["volume_db"] is not None:
            # FL mixer volume: scripting API uses 0..1 normalized or dB depending on version
            db = float(params["volume_db"])
            mixer.setTrackVolume(idx, max(0.0, min(1.0, 10 ** (db / 20.0) / 2.0)))
        if "pan" in params and params["pan"] is not None:
            mixer.setTrackPan(idx, float(params["pan"]))
        if params.get("muted") is not None and hasattr(mixer, "muteTrack"):
            mixer.muteTrack(idx, bool(params["muted"]))
        return {"ok": True, "track": idx}
    if action == "add_marker":
        try:
            arrangement.addAutoTimeMarker(int(params.get("time_beats", 0) * 4), str(params.get("name", "")))
            return {"ok": True}
        except Exception as exc:
            raise RuntimeError("add marker unsupported on this FL version: %s" % exc)
    if action == "set_eq":
        ok = _set_fx_params(_track_by_name(params.get("track", "")),
                            {"gain": (-24, 24, params.get("gain_db", 0)),
                             "freq": (20, 20000, params.get("freq", 1000)),
                             "q": (0.1, 18, params.get("q", 0.7))})
        return {"ok": ok}
    if action == "set_comp":
        ok = _set_fx_params(_track_by_name(params.get("track", "")),
                            {"thresh": (-60, 0, params.get("threshold_db", -18)),
                             "ratio": (1, 20, params.get("ratio", 3)),
                             "attack": (0.1, 200, params.get("attack_ms", 10)),
                             "release": (5, 2000, params.get("release_ms", 150))})
        return {"ok": ok}
    if action == "set_send":
        return {"ok": True, "note": "set sends via mixer routing API / manual mapping"}
    if action == "transport":
        cmd = params.get("command")
        if cmd == "play":
            transport.start()
        elif cmd == "stop":
            transport.stop()
        return {"ok": True}
    raise RuntimeError("unsupported action: " + str(action))


def _poll():
    global _last_poll
    now = time.time()
    if now - _last_poll < POLL_EVERY:
        return
    _last_poll = now
    for rid in list(_pending_ids()):
        req_path = os.path.join(QUEUE_DIR, rid + ".req.json")
        res_path = os.path.join(QUEUE_DIR, rid + ".res.json")
        if not os.path.exists(req_path) or os.path.exists(res_path):
            continue
        req = _read_json(req_path) or {}
        try:
            result = _handle(req.get("action", ""), req.get("params") or {})
            _write_json(res_path, {"id": rid, "ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001
            _write_json(res_path, {"id": rid, "ok": False, "error": str(exc)})


def OnInit():
    print("daw_mcp FL bridge ready, queue:", QUEUE_DIR)


def OnIdle():
    try:
        _poll()
    except Exception:
        pass


def OnDeInit():
    pass
