"""BT3 VT-088 load check: 40 concurrent import tasks, p95 target <= 1.5 s.

Not collected by the normal suite (file name is not ``test_*``). Run explicitly on the
disposable cluster, for example:

    run-db-tests.ps1 -Repo <worktree> backend/tests/bench_bt3_import_load.py -s

Scenario (spec decision 3): one task = one import call with ONE record, 40 tasks released at
the same instant by a barrier, sharing ONE production-profile hasher (``DEFAULT_PROFILE``,
``max_concurrent=4``, 2 s acquire timeout), as one process would. Each task writes through the
PostgreSQL harness writer (owner connection, one transaction per account). Three rounds.

The test asserts the correctness invariant under load (created <=> committed). It does NOT
assert the p95 target; it reports the measured latency so the result can be compared honestly.
Conclusions hold only for this machine and a local cluster.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import threading
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from bt3_account_writer import PostgresAccountWriter
from gpu_marketplace.identity.account_import import FailReason, import_accounts
from gpu_marketplace.identity.passwords import ScryptPasswordHasher

TASKS = 40
ROUNDS = 3
P95_TARGET_SECONDS = 1.5


def p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def run_round(engine: Engine, hasher: ScryptPasswordHasher, round_no: int) -> dict:
    writer = PostgresAccountWriter(engine)
    barrier = threading.Barrier(TASKS)
    durations: list[float] = [0.0] * TASKS
    reports: list = [None] * TASKS

    def task(i: int) -> None:
        batch = [{"login_name": f"load_r{round_no}_{i:02d}", "password": f"load-pass-{round_no}-{i}", "role_code": "CLIENT"}]
        barrier.wait()
        started = time.perf_counter()
        reports[i] = import_accounts(batch, writer, hasher)
        durations[i] = time.perf_counter() - started

    threads = [threading.Thread(target=task, args=(i,)) for i in range(TASKS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    with engine.connect() as connection:
        stored = set(
            connection.execute(
                text("SELECT login_name FROM users WHERE login_name LIKE :prefix"), {"prefix": f"load_r{round_no}_%"}
            ).scalars()
        )
    created = {f"load_r{round_no}_{i:02d}" for i, r in enumerate(reports) if r.created}
    reasons = [f.reason for r in reports for f in r.failed]
    # Invariant under load: created <=> committed, and every task accounted for exactly once.
    assert created == stored
    assert all(len(r.created) + len(r.failed) + len(r.rejected) == 1 for r in reports)
    return {
        "round": round_no,
        "created": len(created),
        "failed_hasher_busy": reasons.count(FailReason.HASHER_BUSY),
        "failed_other": len(reasons) - reasons.count(FailReason.HASHER_BUSY),
        "p50_s": round(statistics.median(durations), 3),
        "p95_s": round(p95(durations), 3),
        "max_s": round(max(durations), 3),
        "p95_created_only_s": round(p95([d for d, r in zip(durations, reports) if r.created]), 3)
        if sum(1 for r in reports if r.created) >= 2
        else None,
    }


def test_bt3_load_40_concurrent_import_tasks(migrated_database_with_teardown: Engine) -> None:
    engine = migrated_database_with_teardown
    hasher = ScryptPasswordHasher()  # production profile and limits, one per process

    single = []
    for i in range(5):
        started = time.perf_counter()
        hasher.hash_password(f"warmup-{i}")
        single.append(time.perf_counter() - started)

    rounds = [run_round(engine, hasher, n) for n in range(1, ROUNDS + 1)]
    result = {
        "scenario": (
            f"{TASKS} concurrent tasks x 1 record, shared ScryptPasswordHasher"
            "(DEFAULT_PROFILE n=2^15 r=8 p=3, max_concurrent=4, timeout=2s)"
        ),
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "cpu_count": os.cpu_count()},
        "single_hash_median_s": round(statistics.median(single), 3),
        "p95_target_s": P95_TARGET_SECONDS,
        "rounds": rounds,
        "target_met_all_rounds": all(r["p95_s"] <= P95_TARGET_SECONDS for r in rounds),
    }
    out = os.environ.get("BT3_LOAD_RESULT")
    if out:
        Path(out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nBT3_LOAD_RESULT " + json.dumps(result, indent=2))
