"""Smoke tests for daw-mcp-server (no DAW required; mock renderer)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from daw_mcp.tools import Context, dispatch  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_project.rpp"
VALID_PATCH = {"ops": [
    {"op": "set_track", "track": "Bass", "fields": {"volume_db": -6.0}},
    {"op": "set_track", "track": "Vocal", "fields": {"volume_db": -2.0, "pan": 0.1}},
    {"op": "set_eq", "track": "Vocal", "fields": {"band": "high_shelf", "gain_db": 3.0, "freq": 8000, "q": 0.7}},
    {"op": "set_comp", "track": "Bass", "fields": {"threshold_db": -20, "ratio": 4, "attack_ms": 10, "release_ms": 150}},
    {"op": "add_marker", "time_beats": 16, "name": "chorus"},
]}
INVALID_PATCH = {"ops": [{"op": "set_eq", "track": "Vocal", "fields": {"gain_db": 99.0}}]}


def _call(ctx, name, args):
    res = dispatch(ctx, name, args)
    assert res["isError"] is False, res["content"][0]["text"]
    return json.loads(res["content"][0]["text"])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="daw_mcp_test_"))
    ctx = Context({"telemetry_path": str(tmp / "telemetry.jsonl"),
                   "mock_tracks": [{"name": n, "volume_db": 0.0, "pan": 0.0}
                                   for n in ("Drums", "Kick", "Bass", "Vocal", "Reverb Bus")]})

    status = _call(ctx, "daw_status", {})
    assert status["server"] == "daw-mcp-server"
    apis = _call(ctx, "daw_apis", {})
    assert "flstudio" in apis and "reaper" in apis and "dawproject" in apis

    proj = _call(ctx, "project_read", {"path": str(SAMPLE)})
    assert proj["format"] == "rpp"
    assert len(proj["tracks"]) >= 4
    names = [t["name"] for t in proj["tracks"]]
    assert "Bass" in names and "Vocal" in names, names
    bass = [t for t in proj["tracks"] if t["name"] == "Bass"][0]
    assert -6.2 < bass["volume_db"] < -5.8, bass

    v_ok = _call(ctx, "patch_validate", {"patch": VALID_PATCH})
    assert v_ok["valid"] is True, v_ok
    v_bad = _call(ctx, "patch_validate", {"patch": INVALID_PATCH})
    assert v_bad["valid"] is False, v_bad

    out_rpp = tmp / "patched.rpp"
    applied = _call(ctx, "patch_apply", {"path": str(SAMPLE), "patch": VALID_PATCH, "out_path": str(out_rpp)})
    assert any(a["ok"] for a in applied["applied"]), applied
    patched = _call(ctx, "project_read", {"path": str(out_rpp)})
    bass2 = [t for t in patched["tracks"] if t["name"] == "Bass"][0]
    assert abs(bass2["volume_db"] - (-6.0)) < 0.1, bass2

    wav = _call(ctx, "render", {"path": str(SAMPLE), "out": str(tmp / "base.wav")})
    assert wav["engine"] == "mock"
    stats = _call(ctx, "analyze", {"wav": str(tmp / "base.wav")})
    for key in ("peak_dbfs", "rms_dbfs", "lufs_integrated_approx", "spectral_centroid_hz", "stereo_side_mid_ratio"):
        assert key in stats, key

    wav2 = _call(ctx, "render", {"path": str(out_rpp), "out": str(tmp / "patched.wav")})
    cmp_ = _call(ctx, "compare", {"wav_a": str(tmp / "base.wav"), "wav_b": str(tmp / "patched.wav")})
    assert "rms_dbfs" in cmp_["delta"]

    verified = _call(ctx, "verify_patch", {
        "path": str(SAMPLE), "patch": VALID_PATCH,
        "intent": {"rms_dbfs": -modulate(cmp_["delta"].get("rms_dbfs", 0.0))},
        "workdir": str(tmp / "work"),
    })
    assert "score" in verified and 0.0 <= verified["score"] <= 1.0

    state = _call(ctx, "bridge_call", {"action": "get_state", "params": {}})
    assert state["project"]["format"] == "mock-bridge"
    new_state = _call(ctx, "bridge_call", {"action": "set_track",
                                           "params": {"track": "Vocal", "volume_db": -3.0}})
    assert new_state["ok"] is True

    tele = _call(ctx, "telemetry_append", {"record": {"event": "test", "patch": VALID_PATCH}})
    assert tele["appended"] is True and (tmp / "telemetry.jsonl").exists()

    # MCP stdio smoke
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "project_read", "arguments": {"path": str(SAMPLE)}}},
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "daw_mcp.server"],
        input="\n".join(json.dumps(m) for m in msgs) + "\n",
        capture_output=True, text=True, timeout=120, cwd=str(ROOT),
    )
    lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    assert len(lines) == 3, proc.stdout + proc.stderr
    assert lines[0]["result"]["serverInfo"]["name"] == "daw-mcp-server"
    assert len(lines[1]["result"]["tools"]) >= 10
    assert json.loads(lines[2]["result"]["content"][0]["text"])["format"] == "rpp"

    print("ALL TESTS PASSED")
    return 0


def modulate(x: float) -> float:
    # a plausible intent value so verify_patch has a target
    return -2.0 if x == 0 else x


if __name__ == "__main__":
    raise SystemExit(main())
