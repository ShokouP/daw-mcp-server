"""DAW metrics: WAV analysis for training/inference verification (numpy + stdlib)."""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


def read_wav(path: str | Path) -> tuple[np.ndarray, int, int]:
    """Read PCM WAV -> (samples[n, ch] float32 in [-1,1], sample_rate, channels)."""
    with wave.open(str(path), "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if sw == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width: {sw}")
    if nch > 1:
        data = data.reshape(-1, nch)
    else:
        data = data.reshape(-1, 1)
    return data, sr, nch


def write_wav(path: str | Path, data: np.ndarray, sr: int) -> None:
    """Write float[-1,1] array [n, ch] as 16-bit PCM WAV."""
    data = np.clip(np.asarray(data, dtype=np.float32), -1.0, 1.0)
    if data.ndim == 1:
        data = data[:, None]
    pcm = (data * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(data.shape[1])
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _db(x: float) -> float:
    return 20.0 * math.log10(max(x, 1e-12))


def _k_weight_mono(x: np.ndarray, sr: int) -> np.ndarray:
    """Approximate K-weighting (high-pass + high-shelf) using simple IIR filters."""
    # high-pass ~60 Hz (one-pole)
    hp = np.empty_like(x)
    alpha = math.exp(-2.0 * math.pi * 60.0 / sr)
    prev_x = 0.0
    prev_y = 0.0
    for i, v in enumerate(x):
        y = alpha * (prev_y + v - prev_x)
        hp[i] = y
        prev_x, prev_y = v, y
    # high-shelf +4 dB above ~1.5 kHz (one-pole shelf)
    a = math.exp(-2.0 * math.pi * 1500.0 / sr)
    g = 10.0 ** (4.0 / 20.0)
    lp = np.empty_like(hp)
    prev = 0.0
    for i, v in enumerate(hp):
        prev = a * prev + (1.0 - a) * v
        lp[i] = prev
    return hp + (g - 1.0) * lp


def _spectrum(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    n = min(len(x), sr * 30)
    mono = x[:n].mean(axis=1) if x.ndim > 1 else x[:n]
    if len(mono) < 1024:
        mono = np.pad(mono, (0, 1024 - len(mono)))
    win = np.hanning(len(mono))
    spec = np.abs(np.fft.rfft(mono * win)) + 1e-12
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    return freqs, spec


def analyze_wav(path: str | Path) -> dict:
    data, sr, nch = read_wav(path)
    x = data.astype(np.float32)
    duration = len(x) / sr
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    crest = _db(peak) - _db(rms)

    # approximate integrated loudness from K-weighted mean square
    mono = x.mean(axis=1) if nch > 1 else x[:, 0]
    kw = _k_weight_mono(mono.astype(np.float64), sr)
    ms = float(np.mean(kw ** 2)) if kw.size else 0.0
    lufs = -0.691 + 10.0 * math.log10(max(ms, 1e-12))

    # LRA approximation: 3s windows, 75% overlap
    win = int(3.0 * sr)
    step = max(1, win // 4)
    st = []
    if len(mono) >= win:
        for start in range(0, len(mono) - win + 1, step):
            seg = _k_weight_mono(mono[start:start + win].astype(np.float64), sr)
            m = float(np.mean(seg ** 2))
            st.append(-0.691 + 10.0 * math.log10(max(m, 1e-12)))
    lra = float(np.percentile(st, 95) - np.percentile(st, 10)) if st else 0.0

    freqs, spec = _spectrum(x, sr)
    centroid = float((freqs * spec).sum() / spec.sum())
    bands = {
        "low_20_250": float(spec[(freqs >= 20) & (freqs < 250)].sum() / spec.sum()),
        "mid_250_4k": float(spec[(freqs >= 250) & (freqs < 4000)].sum() / spec.sum()),
        "high_4k_20k": float(spec[(freqs >= 4000) & (freqs <= 20000)].sum() / spec.sum()),
    }
    # stereo
    if nch >= 2:
        mid = (x[:, 0] + x[:, 1]) / 2.0
        side = (x[:, 0] - x[:, 1]) / 2.0
        side_ratio = float(np.sqrt(np.mean(side ** 2)) / max(1e-9, np.sqrt(np.mean(mid ** 2))))
        corr = float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) if len(x) > 1 else 1.0
    else:
        side_ratio = 0.0
        corr = 1.0

    return {
        "path": str(path),
        "sample_rate": sr,
        "channels": nch,
        "duration_seconds": round(duration, 3),
        "peak_dbfs": round(_db(peak), 2),
        "rms_dbfs": round(_db(rms), 2),
        "crest_factor_db": round(crest, 2),
        "lufs_integrated_approx": round(lufs, 2),
        "lra_approx": round(lra, 2),
        "spectral_centroid_hz": round(centroid, 1),
        "band_energy_ratio": {k: round(v, 4) for k, v in bands.items()},
        "stereo_side_mid_ratio": round(side_ratio, 4),
        "stereo_correlation": round(corr, 4),
        "clipped": bool(peak >= 0.999),
    }


def diff_metrics(a: dict, b: dict) -> dict:
    keys = ["peak_dbfs", "rms_dbfs", "crest_factor_db", "lufs_integrated_approx",
            "spectral_centroid_hz", "stereo_side_mid_ratio", "stereo_correlation"]
    out = {}
    for k in keys:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            out[k] = round(float(vb) - float(va), 3)
    for band in ("low_20_250", "mid_250_4k", "high_4k_20k"):
        va = a.get("band_energy_ratio", {}).get(band)
        vb = b.get("band_energy_ratio", {}).get(band)
        if va is not None and vb is not None:
            out[f"band_{band}"] = round(float(vb) - float(va), 4)
    return out
