"""Training-data generation loop: sample patches -> verify via MCP tools -> log.

Run from repo root:  python examples/training_loop.py
Works without any DAW (mock renderer). Replace Context(config) with a config
that has a real render_cmd / bridge_queue for production runs.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from daw_mcp.tools import Context, dispatch  # noqa: E402

BASE = ROOT / "examples" / "sample_project.rpp"
TRACKS = ["Bass", "Vocal", "Drums"]


def sample_patch(rng: random.Random) -> dict:
    ops = []
    for track in rng.sample(TRACKS, k=rng.randint(1, 2)):
        ops.append({"op": "set_track", "track": track,
                    "fields": {"volume_db": round(rng.uniform(-12, 3), 1),
                               "pan": round(rng.uniform(-0.6, 0.6), 2)}})
    if rng.random() < 0.6:
        ops.append({"op": "set_eq", "track": rng.choice(TRACKS),
                    "fields": {"band": rng.choice(["high_shelf", "low_shelf", "bell"]),
                               "gain_db": round(rng.uniform(-6, 6), 1),
                               "freq": rng.choice([120, 400, 2500, 8000]),
                               "q": round(rng.uniform(0.3, 2.0), 2)}})
    if rng.random() < 0.5:
        ops.append({"op": "set_comp", "track": "Bass",
                    "fields": {"threshold_db": round(rng.uniform(-30, -10), 1),
                               "ratio": round(rng.uniform(2, 8), 1),
                               "attack_ms": 10.0, "release_ms": 150.0}})
    if rng.random() < 0.5:
        ops.append({"op": "add_marker", "time_beats": rng.choice([8, 16, 24, 32]),
                    "name": rng.choice(["verse", "chorus", "bridge"])})
    return {"ops": ops}


def verify(ctx, patch: dict, intent: dict, workdir: str) -> dict:
    res = dispatch(ctx, "verify_patch", {"path": str(BASE), "patch": patch,
                                        "intent": intent, "min_score": 0.0,
                                        "workdir": workdir})
    return json.loads(res["content"][0]["text"])


def main() -> int:
    tmp = Path("daw_mcp_work") / "training_loop"
    tmp.mkdir(parents=True, exist_ok=True)
    ctx = Context({"telemetry_path": str(tmp / "telemetry.jsonl"),
                   "mock_tracks": [{"name": n, "volume_db": 0.0, "pan": 0.0} for n in TRACKS]})
    rng = random.Random(20261107)
    strong = 0
    for i in range(30):
        patch = sample_patch(rng)
        # 1) free-form intent (random target): reward signal for "does this patch
        #    move the rendered metrics toward the requested direction"
        random_intent = {"rms_dbfs": round(rng.uniform(-3, 3), 2)}
        first = verify(ctx, patch, random_intent, str(tmp / f"case_{i:03d}_a"))
        # 2) teacher-consistent intent: target = measured delta, so a correct patch
        #    (and a correct verifier) should score ~1.0
        second = verify(ctx, patch, first["delta"], str(tmp / f"case_{i:03d}_b"))
        if second["score"] >= 0.99:
            strong += 1
        dispatch(ctx, "telemetry_append", {"record": {
            "case": i, "patch": patch,
            "score_random_intent": first["score"], "score_teacher_intent": second["score"],
            "delta": first["delta"], "manifest": str(BASE)}})
        if i < 2:
            print(f"case {i}: random_score={first['score']} teacher_score={second['score']}")
    print(f"generated 30 cases, self-consistent passes={strong}, telemetry={ctx.telemetry_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
