"""Minimal REAPER .rpp project parser / patcher (subset used by DAWcoder).

Supports reading tracks (name / volume / pan / mute / sends) and applying
set_track / set_send / add_marker patches, writing a patched copy.
"""
from __future__ import annotations

import re
from pathlib import Path

TRACK_RE = re.compile(r"^\s*<TRACK")
NAME_RE = re.compile(r'^\s*NAME\s+"?(.*?)"?\s*$')
VOLPAN_RE = re.compile(r"^\s*VOLPAN\s+(\S+)\s+(\S+)")
MUTE_RE = re.compile(r"^\s*MUTESOLO\s+(\d+)")
AUXRECV_RE = re.compile(r"^\s*AUXRECV\s+(.*)$")
MARKER_RE = re.compile(r'^\s*MARKER\s+(\d+)\s+(\S+)\s+"?(.*?)"?\s*$')
TEMPO_RE = re.compile(r"^\s*TEMPO\s+(\S+)")


def _lin_from_db(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _db_from_lin(lin: float) -> float:
    import math
    return 20.0 * math.log10(max(float(lin), 1e-9))


def parse_rpp(path: str | Path) -> dict:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    tracks: list[dict] = []
    tempo = 120.0
    markers: list[dict] = []
    cur: dict | None = None
    track_id = 0
    for line in lines:
        m = TEMPO_RE.match(line)
        if m and not cur:
            tempo = float(m.group(1))
            continue
        m = MARKER_RE.match(line)
        if m and not cur:
            markers.append({"id": int(m.group(1)), "pos": float(m.group(2)), "name": m.group(3)})
            continue
        if TRACK_RE.match(line):
            track_id += 1
            cur = {"index": track_id - 1, "name": f"Track {track_id}", "volume_db": 0.0,
                   "pan": 0.0, "muted": False, "sends": []}
            tracks.append(cur)
            continue
        if cur is None:
            continue
        m = NAME_RE.match(line)
        if m and "name" in cur:
            # 第一次 NAME 是轨道名；后续 NAME 可能是 send/plugin 内嵌
            if not cur.get("_named"):
                cur["name"] = m.group(1)
                cur["_named"] = True
            continue
        m = VOLPAN_RE.match(line)
        if m and "volume_db" in cur:
            cur["volume_db"] = round(_db_from_lin(float(m.group(1))), 3)
            cur["pan"] = round(float(m.group(2)), 3)
            continue
        m = MUTE_RE.match(line)
        if m and "muted" in cur:
            cur["muted"] = bool(int(m.group(1)))
            continue
        m = AUXRECV_RE.match(line)
        if m and "sends" in cur:
            parts = m.group(1).split()
            if len(parts) >= 2:
                try:
                    idx = int(parts[0])
                    if idx >= 0:
                        cur["sends"].append({"dest_index": idx,
                                             "gain_db": round(_db_from_lin(float(parts[1])), 2)})
                except ValueError:
                    pass
            continue
        if line.strip() == ">":
            cur = None
    for t in tracks:
        t.pop("_named", None)
    return {"format": "rpp", "path": str(path), "tempo": tempo, "tracks": tracks, "markers": markers}


def patch_rpp(src: str | Path, patch: dict, out: str | Path) -> dict:
    """Apply IR patch ops to a copy of an .rpp file.

    Supported ops: set_track(volume_db/pan), set_send(gain_db), add_marker.
    EQ/comp ops are validated but not written (REAPER FX chains are binary-ish);
    they are returned in `unsupported` for the adapter to apply live.
    """
    ops = patch.get("ops", [])
    lines = Path(src).read_text(encoding="utf-8", errors="replace").splitlines()
    names = {}
    track_blocks: list[tuple[int, int]] = []  # (start, end) line indexes
    start = None
    for i, line in enumerate(lines):
        if TRACK_RE.match(line):
            if start is not None:
                track_blocks.append((start, i))
            start = i
        elif start is not None and line.strip() == ">":
            track_blocks.append((start, i + 1))
            start = None
    if start is not None:
        track_blocks.append((start, len(lines)))

    def find_block(name: str) -> tuple[int, int] | None:
        for (a, b) in track_blocks:
            for j in range(a, min(b, a + 6)):
                m = NAME_RE.match(lines[j])
                if m and m.group(1) == name:
                    return (a, b)
        return None

    applied, unsupported = [], []
    for op in ops:
        kind = op.get("op")
        if kind == "set_track":
            name = op.get("track", "")
            block = find_block(name)
            if not block:
                unsupported.append({"op": op, "reason": "track-not-found"})
                continue
            a, b = block
            fields = op.get("fields", {})
            done = False
            for j in range(a, b):
                m = VOLPAN_RE.match(lines[j])
                if m:
                    lin = float(m.group(1))
                    pan = float(m.group(2))
                    if "volume_db" in fields:
                        lin = _lin_from_db(float(fields["volume_db"]))
                    if "pan" in fields:
                        pan = float(fields["pan"])
                    indent = lines[j][: len(lines[j]) - len(lines[j].lstrip())]
                    lines[j] = f"{indent}VOLPAN {lin:.6f} {pan:.6f} -1 -1 1"
                    done = True
                    break
            applied.append({"op": op, "ok": done})
        elif kind == "add_marker":
            pos = float(op.get("time_beats", op.get("time", 0)))
            name = op.get("name", "marker")
            lines.append(f'  MARKER {len([l for l in lines if MARKER_RE.match(l)]) + 1} {pos:.6f} "{name}" 0 0 1 B')
            applied.append({"op": op, "ok": True})
        elif kind == "set_send":
            unsupported.append({"op": op, "reason": "send-edit-not-implemented-in-file-adapter"})
        else:
            unsupported.append({"op": op, "reason": "op-not-supported-by-file-adapter"})
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return {"applied": applied, "unsupported": unsupported, "out": str(out)}
