#!/usr/bin/env python3
"""Opt-in 120-VU HTTP harness for a disposable VT-089 environment.

Bearer tokens are read only from VT089_BEARER_TOKENS_JSON and are never printed.
This script does not create data or change database state; prepare representative
fixtures through the repository's disposable-database runbook before using it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from collections import Counter
from urllib.parse import urlencode
from uuid import UUID

import httpx


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one observation")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


async def run(args: argparse.Namespace) -> dict[str, object]:
    try:
        listing_id = UUID(args.listing_id)
    except ValueError as exc:
        raise SystemExit("listing_id must be a canonical lowercase UUIDv4") from exc
    if listing_id.version != 4 or str(listing_id) != args.listing_id:
        raise SystemExit("listing_id must be a canonical lowercase UUIDv4")
    raw_tokens = os.environ.get("VT089_BEARER_TOKENS_JSON", "")
    try:
        tokens = json.loads(raw_tokens)
    except json.JSONDecodeError as exc:
        raise SystemExit("VT089_BEARER_TOKENS_JSON must be a JSON array of Bearer tokens") from exc
    if not isinstance(tokens, list) or not tokens or not all(
        isinstance(token, str) and token for token in tokens
    ):
        raise SystemExit("VT089_BEARER_TOKENS_JSON must contain one or more non-empty tokens")
    if (
        args.account_count < 1
        or args.vus < 1
        or args.requests_per_vu < 1
        or args.warmup_requests < 0
        or args.timeout_seconds <= 0
    ):
        raise SystemExit("counts must be positive (warmup may be zero) and timeout must be positive")

    query = urlencode({"scope": "mine", "listing_id": args.listing_id, "limit": "20"})
    url = f"{args.base_url.rstrip('/')}/api/v1/jobs?{query}"
    latencies: list[float] = []
    statuses: Counter[str] = Counter()
    warmup_statuses: Counter[str] = Counter()
    in_flight = 0
    max_in_flight = 0
    ready = asyncio.Event()

    limits = httpx.Limits(max_connections=args.vus, max_keepalive_connections=args.vus)
    timeout = httpx.Timeout(args.timeout_seconds)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, trust_env=False) as client:
        async def get_one(token: str, *, measure: bool) -> None:
            nonlocal in_flight, max_in_flight
            headers = {"Authorization": f"Bearer {token}"}
            started = time.monotonic()
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            try:
                response = await client.get(url, headers=headers)
                (statuses if measure else warmup_statuses)[str(response.status_code)] += 1
                if measure:
                    latencies.append(time.monotonic() - started)
            except httpx.HTTPError as exc:
                (statuses if measure else warmup_statuses)[
                    f"ERROR:{type(exc).__name__}"
                ] += 1
                if measure:
                    latencies.append(time.monotonic() - started)
            finally:
                in_flight -= 1

        for index in range(args.warmup_requests):
            await get_one(tokens[index % len(tokens)], measure=False)

        async def virtual_user(index: int) -> None:
            await ready.wait()
            token = tokens[index % len(tokens)]
            for _ in range(args.requests_per_vu):
                await get_one(token, measure=True)

        tasks = [asyncio.create_task(virtual_user(index)) for index in range(args.vus)]
        await asyncio.sleep(0)
        measured_started = time.monotonic()
        ready.set()
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - measured_started

    total = len(latencies)
    successful = statuses.get("200", 0)
    failures = total - successful
    return {
        "route": "GET /api/v1/jobs",
        "query": {"scope": "mine", "listing_id": args.listing_id, "limit": 20},
        "virtual_users": args.vus,
        "requests_per_virtual_user": args.requests_per_vu,
        "account_count_reported_by_operator": args.account_count,
        "token_count": len(tokens),
        "warmup_requests": args.warmup_requests,
        "warmup_status_counts": dict(warmup_statuses),
        "measurement_requests": total,
        "observed_max_in_flight_client_requests": max_in_flight,
        "elapsed_seconds": elapsed,
        "throughput_requests_per_second": total / elapsed if elapsed else 0.0,
        "http_status_counts": dict(statuses),
        "error_rate": failures / total if total else 1.0,
        "latency_percentile_method": "nearest-rank; includes HTTP and transport failures",
        "latency_seconds": {
            "p50": percentile_nearest_rank(latencies, 0.50),
            "p95": percentile_nearest_rank(latencies, 0.95),
            "p99": percentile_nearest_rank(latencies, 0.99),
        },
        "acceptance_p95_seconds": 3.5,
        "acceptance_pass": failures == 0 and percentile_nearest_rank(latencies, 0.95) <= 3.5,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--listing-id", required=True)
    parser.add_argument("--account-count", type=int, required=True)
    parser.add_argument("--vus", type=int, default=120)
    parser.add_argument("--requests-per-vu", type=int, default=10)
    parser.add_argument("--warmup-requests", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
