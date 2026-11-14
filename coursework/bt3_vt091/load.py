"""150 simultaneous asyncio tasks, three runs/profile; in-memory, not HTTP load."""

import asyncio
import json
import math
import platform
import random
import time

from drafts import DraftStore, StaleDraft


async def run_profile(profile: str, run: int) -> dict:
    store = DraftStore()
    release, all_ready = asyncio.Event(), asyncio.Event()
    ready = 0
    released_at = 0.0
    revisions = list(range(1, 151))
    random.Random(23001954 + run).shuffle(revisions)

    async def worker(revision):
        nonlocal ready
        ready += 1
        if ready == 150:
            all_ready.set()
        await release.wait()
        status = "saved"
        try:
            key = str(revision) if profile == "150-independent-drafts" else "shared"
            fields = {"gpu_model": str(revision), "vram_gb": "", "total_gpu_count": "", "mock_price_per_hour": ""}
            await store.save("synthetic-worker", key, revision, fields)
        except StaleDraft:
            status = "stale_rejected"
        except Exception as exc:
            status = "unexpected:" + type(exc).__name__
        return {"revision": revision, "status": status, "latency_ms": (time.perf_counter() - released_at) * 1000}

    tasks = [asyncio.create_task(worker(revision)) for revision in revisions]
    await asyncio.wait_for(all_ready.wait(), 10)
    released_at = time.perf_counter()
    release.set()
    samples = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    elapsed = time.perf_counter() - released_at
    latencies = sorted(sample["latency_ms"] for sample in samples)
    if profile == "150-independent-drafts":
        invariant = all([(await store.get("synthetic-worker", str(r))).revision == r for r in revisions])
        invariant = invariant and all([(await store.get("synthetic-worker", str(r))).fields()["gpu_model"] == str(r) for r in revisions])
    else:
        saved = await store.get("synthetic-worker", "shared")
        invariant = saved.revision == 150 and saved.fields()["gpu_model"] == "150"
    unexpected = sum(sample["status"].startswith("unexpected:") for sample in samples)
    p95 = latencies[math.ceil(0.95 * len(samples)) - 1]
    return {
        "profile": profile, "run": run, "seed": 23001954 + run,
        "tasks_waiting_before_release": ready, "completed": len(samples),
        "saved": sum(s["status"] == "saved" for s in samples),
        "stale_rejected": sum(s["status"] == "stale_rejected" for s in samples),
        "unexpected_errors": unexpected, "invariant_pass": invariant,
        "elapsed_seconds": elapsed, "p95_ms": p95, "max_ms": max(latencies),
        "p95_target_ms": 4000, "pass": invariant and unexpected == 0 and p95 <= 4000,
        "samples": samples,
    }


async def main():
    runs = []
    for profile in ["150-independent-drafts", "150-saves-one-draft"]:
        for run in range(1, 4):
            runs.append(await run_profile(profile, run))
    result = {
        "environment": {"python": platform.python_version(), "os": platform.platform(), "processor": platform.processor()},
        "clock": "perf_counter; latency includes scheduling from common gate release until completion",
        "percentile": "nearest-rank ceil(0.95*n), all completed requests including stale rejections",
        "scope": "single-process in-memory asyncio harness, no TCP/HTTP/DB/browser; not 150 real users",
        "runs": runs, "pass": all(r["pass"] for r in runs),
    }
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
