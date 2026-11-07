"""Minimal DAWproject (.dawproject ZIP + project.xml) reader.

DAWproject is an open, MIT-licensed format supported by Bitwig / Studio One /
Cubase / (via converters) REAPER. This module provides read-only summaries and
best-effort track volume/pan extraction for verification.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def _text(elem, tag_end: str) -> str | None:
    for child in elem:
        if child.tag.split("}")[-1].endswith(tag_end) and child.text:
            return child.text.strip()
    return None


def _attr_or_child(elem, name: str):
    if name in elem.attrib:
        return elem.attrib[name]
    for child in elem:
        if child.tag.split("}")[-1].lower() == name.lower():
            return child.text.strip() if child.text else None
    return None


def parse_dawproject(path: str | Path) -> dict:
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith("project.xml")]
            if not xml_names:
                raise ValueError("dawproject: no project.xml inside archive")
            xml = zf.read(xml_names[0])
    else:
        xml = path.read_bytes()
    root = ET.fromstring(xml)
    tracks = []
    markers = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag in ("Track", "MasterTrack", "EffectTrack"):
            name = _text(elem, "Name") or _attr_or_child(elem, "name") or tag
            vol = _attr_or_child(elem, "volume")
            pan = _attr_or_child(elem, "pan")
            tracks.append({
                "name": name,
                "type": tag,
                "volume": _to_float(vol),
                "pan": _to_float(pan),
                "volume_db": _to_db(vol),
            })
        elif tag in ("Marker", "CueMarker", "ArrangementMarker"):
            markers.append({"name": _text(elem, "Name") or "", "time": _to_float(_attr_or_child(elem, "time"))})
    tempo = None
    for elem in root.iter():
        if elem.tag.split("}")[-1] == "Tempo":
            val = _to_float(_attr_or_child(elem, "value"))
            if val:
                tempo = val
                break
    return {"format": "dawproject", "path": str(path), "tempo": tempo,
            "tracks": tracks, "markers": markers,
            "note": "read-only summary; use a live-DAW bridge or converter for edits"}


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_db(v) -> float | None:
    f = _to_float(v)
    if f is None or f <= 0:
        return None
    import math
    return round(20.0 * math.log10(f), 3)
