"""Reproducible micro-benchmark of scrypt password verification cost (PR #18, finding P2).

Not collected by pytest. Run from the repository root:

    uv run --project backend --locked python backend/tests/bench_identity_password_cost.py

It measures single-verification latency and throughput at several concurrency levels on the
current machine. It is NOT a 736-VU load test and says nothing about the login share of the
ADR-007 mix; that measurement remains NOT_RUN.
"""

from concurrent.futures import ThreadPoolExecutor
import os
import platform
import statistics
import sys
import time

from gpu_marketplace.identity.passwords import DEFAULT_PROFILE, ScryptPasswordHasher, ScryptProfile

PROFILES = [ScryptProfile(n=2**15, r=8, p=1), DEFAULT_PROFILE]
SAMPLES = 10
CONCURRENCY = [1, 2, 4]
BATCH = 12


def peak_memory_mib() -> float | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize / 2**20
        return None
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / 2**20 if sys.platform == "darwin" else peak / 2**10
    except ImportError:
        return None


def main() -> None:
    print(f"python={platform.python_version()} os={platform.platform()} cpus={os.cpu_count()}")
    for profile in PROFILES:
        hasher = ScryptPasswordHasher(profile=profile, max_concurrent=max(CONCURRENCY), acquire_timeout_seconds=60)
        encoded = hasher.hash_password("benchmark-password")
        latencies = []
        for _ in range(SAMPLES):
            start = time.perf_counter()
            assert hasher.verify_password("benchmark-password", encoded)
            latencies.append((time.perf_counter() - start) * 1000)
        latencies.sort()
        p95 = latencies[min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))]
        print(
            f"profile n={profile.n} r={profile.r} p={profile.p} memory_per_verify={profile.memory_bytes / 2**20:.0f} MiB "
            f"| single verify ms: median={statistics.median(latencies):.0f} p95={p95:.0f} max={latencies[-1]:.0f}"
        )
        for workers in CONCURRENCY:
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(lambda _: hasher.verify_password("benchmark-password", encoded), range(BATCH)))
            elapsed = time.perf_counter() - start
            assert all(results)
            print(f"    concurrency={workers}: {BATCH} verifies in {elapsed:.2f} s -> {BATCH / elapsed:.1f} verifies/s")
    peak = peak_memory_mib()
    print(f"process peak memory: {peak:.0f} MiB" if peak is not None else "process peak memory: not measured")


if __name__ == "__main__":
    main()
