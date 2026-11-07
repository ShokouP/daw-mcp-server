"""Render adapters: real DAW command line (configurable) or deterministic mock render.

Mock render is used for CI / training without a DAW installed: it synthesizes a
stereo WAV whose per-track amplitude/pan follow project volume/pan values, so
patch->render->analyze loops are exercisable end-to-end.
"""
from __future__ import annotations

import hashlib
import math
import subprocess
from pathlib import Path

import numpy as np

from . import dawproject, rpp
from .metrics import write_wav


def read_project_summary(path: str | Path) -> dict:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".dawproject", ".zip"):
        return dawproject.parse_dawproject(path)
    return rpp.parse_rpp(path)


def mock_render(project_path: str | Path, out_wav: str | Path, duration: float = 2.0) -> dict:
    project = read_project_summary(project_path)
    tracks = project.get("tracks") or []
    sr = 44100
    n = int(duration * sr)
    t = np.arange(n, dtype=np.float32) / sr
    mix = np.zeros((n, 2), dtype=np.float32)
    for i, tr in enumerate(tracks):
        name = str(tr.get("name", f"track{i}"))
        if tr.get("muted") or (tr.get("volume") == 0):
            continue
        vol = tr.get("volume_db")
        if vol is None:
            vol = 0.0
        amp = min(10.0 ** (float(vol) / 20.0), 2.0) * 0.15
        seed = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)
        freq = 110.0 * (2.0 ** ((seed % 24) / 12.0))
        pan = float(tr.get("pan") or 0.0)
        left = amp * (1.0 - max(0.0, pan) * 0.7)
        right = amp * (1.0 + min(0.0, pan) * 0.7)
        sig = np.sin(2 * np.pi * freq * t) * 0.6 + 0.2 * np.sin(2 * np.pi * freq * 2 * t)
        mix[:, 0] += sig * left
        mix[:, 1] += sig * right
    # tempo pulse accents to make patch differences measurable
    tempo = float(project.get("tempo") or 120.0)
    beat = 60.0 / tempo
    pulse = (np.sin(2 * np.pi * (1.0 / beat) * (t % (duration + 1.0))) > 0.9).astype(np.float32)
    mix *= (0.9 + 0.1 * pulse)[:, None]
    write_wav(out_wav, mix, sr)
    return {"engine": "mock", "out": str(out_wav), "duration": duration,
            "project": {"format": project.get("format"), "tracks": len(tracks), "tempo": tempo}}


def command_render(project_path: str | Path, out_wav: str | Path, render_cmd: str,
                   timeout: int = 600) -> dict:
    """Run a configured render command.

    Template vars: {project}, {out}. Example (REAPER):
      "reaper -renderproject {project}"
    Note: REAPER renders to the path configured in the project; some setups use
    a companion ReaScript. Use the queue bridge for exact output control.
    """
    cmd = render_cmd.replace("{project}", str(project_path)).replace("{out}", str(out_wav))
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    ok = res.returncode == 0 and Path(out_wav).exists()
    return {"engine": "command", "cmd": cmd, "returncode": res.returncode,
            "ok": ok, "stdout": res.stdout[-2000:], "stderr": res.stderr[-2000:],
            "out": str(out_wav)}


def render(project_path: str | Path, out_wav: str | Path, render_cmd: str = "",
           duration: float = 2.0) -> dict:
    if render_cmd:
        return command_render(project_path, out_wav, render_cmd)
    return mock_render(project_path, out_wav, duration=duration)
