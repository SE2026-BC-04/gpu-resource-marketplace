#!/usr/bin/env node

import { createServer } from "node:http";
import { cpus, freemem, totalmem } from "node:os";
import { execFileSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";

const USERS = 60;
const MOCK_JOB_ID = "33333333-3333-4333-8333-333333333333";
const MOCK_AUTHORIZATION = "Bearer VT090-MOCK";
const mode = process.env.VT090_MODE ?? "mock";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const outputPath = resolve(dirname(fileURLToPath(import.meta.url)), "results-local.json");

function gitValue(args) {
  try { return execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim(); }
  catch { return "unavailable"; }
}

function getEnvironment() {
  return {
    commit_sha: gitValue(["rev-parse", "HEAD"]),
    working_tree_dirty: gitValue(["status", "--porcelain"]) !== "",
    runtime: process.version,
    platform: `${process.platform}/${process.arch}`,
    logical_cpu_count: cpus().length,
    cpu_model: cpus()[0]?.model ?? "unknown",
    memory_total_bytes: totalmem(),
    memory_free_before_bytes: freemem(),
    concurrency: USERS,
    requests_per_user: 1,
    dataset_jobs: 1,
  };
}

function nearestRankP95(values) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.ceil(0.95 * sorted.length) - 1];
}

async function startMockServer() {
  let active = 0;
  let maxActive = 0;
  let requestCount = 0;
  const server = createServer((request, response) => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    requestCount += 1;
    response.setHeader("Content-Type", "application/json");
    response.setHeader("Cache-Control", "no-store");
    if (request.method !== "GET" || request.url !== `/api/v1/jobs/${MOCK_JOB_ID}`) {
      response.writeHead(404).end(JSON.stringify({ error: "not_found" }));
      active -= 1;
      return;
    }
    if (request.headers.authorization !== MOCK_AUTHORIZATION) {
      response.writeHead(401).end(JSON.stringify({ error: "unauthorized" }));
      active -= 1;
      return;
    }
    // A fixed local delay makes 60 concurrent in-flight requests observable; it is not SUT latency.
    setTimeout(() => {
      response.writeHead(200).end(JSON.stringify({
        id: MOCK_JOB_ID,
        status: "QUEUED",
        failure_reason: null,
        submitted_at: "2026-11-09T00:00:00.000000Z",
        started_at: null,
        terminal_at: null,
      }));
      active -= 1;
    }, 50);
  });
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Could not bind mock server to an ephemeral port");
  return {
    server,
    endpoint: `http://127.0.0.1:${address.port}/api/v1/jobs/${MOCK_JOB_ID}`,
    authorization: MOCK_AUTHORIZATION,
    stats: () => ({ request_count: requestCount, max_active_requests: maxActive }),
  };
}

function realEndpoint() {
  if (process.env.VT090_ALLOW_REAL_READ_LOAD !== "YES") {
    throw new Error("Set VT090_ALLOW_REAL_READ_LOAD=YES to explicitly allow local API read load");
  }
  const base = new URL(process.env.VT090_BASE_URL ?? "");
  if (!(["localhost", "127.0.0.1", "::1"].includes(base.hostname))) {
    throw new Error("Real mode is restricted to a loopback API host");
  }
  if (base.pathname !== "/" || base.search || base.hash || base.username || base.password) {
    throw new Error("VT090_BASE_URL must be a loopback origin without path, query, or credentials");
  }
  const jobId = process.env.VT090_JOB_ID ?? "";
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(jobId)) {
    throw new Error("VT090_JOB_ID must be a canonical lowercase UUIDv4 for a retained test Job");
  }
  const token = process.env.VT090_BEARER_TOKEN ?? "";
  if (!token.trim()) throw new Error("VT090_BEARER_TOKEN is required in real mode");
  return { endpoint: new URL(`/api/v1/jobs/${jobId}`, base).href, authorization: `Bearer ${token}` };
}

async function main() {
  if (mode !== "mock" && mode !== "real") throw new Error("VT090_MODE must be 'mock' or 'real'");
  const environment = getEnvironment();
  const mock = mode === "mock" ? await startMockServer() : null;
  const target = mock ?? realEndpoint();
  const start = performance.now();
  const outcomes = await Promise.all(Array.from({ length: USERS }, async (_, index) => {
    const started = performance.now();
    try {
      const response = await fetch(target.endpoint, {
        method: "GET",
        headers: { Accept: "application/json", Authorization: target.authorization },
        signal: AbortSignal.timeout(10000),
      });
      await response.arrayBuffer();
      return {
        user: index + 1,
        http_status: response.status,
        latency_ms: Number((performance.now() - started).toFixed(3)),
        error: null,
      };
    } catch (error) {
      return {
        user: index + 1,
        http_status: null,
        latency_ms: Number((performance.now() - started).toFixed(3)),
        error: error instanceof Error ? error.name : "transport_error",
      };
    }
  }));
  const elapsedMs = performance.now() - start;
  const latencies = outcomes.filter((item) => item.http_status !== null && item.http_status >= 200 && item.http_status < 300).map((item) => item.latency_ms);
  const httpErrors = outcomes.filter((item) => item.http_status !== null && (item.http_status < 200 || item.http_status >= 300)).length;
  const transportErrors = outcomes.filter((item) => item.error !== null).length;
  const report = {
    label: mode === "mock" ? "SIMULATED_ONLY" : "LOCAL_API_READ_ONLY_EXPERIMENT",
    metric: "client-observed GET response latency, request start through response body",
    percentile: "nearest-rank p95: sorted[ceil(0.95*n)-1], successful HTTP responses only",
    endpoint_path: "/api/v1/jobs/<JOB_ID>",
    environment,
    database_mode: mode === "mock" ? "MOCK_NO_DATABASE" : "API_DATABASE_NOT_INSPECTED",
    started_at: new Date().toISOString(),
    elapsed_ms: Number(elapsedMs.toFixed(3)),
    results: {
      users_started: USERS,
      successful_requests: latencies.length,
      http_errors: httpErrors,
      transport_errors: transportErrors,
      p95_ms: nearestRankP95(latencies),
      latency_samples_ms: outcomes.map((item) => item.latency_ms),
      outcomes,
      ...(mock ? { mock_server: mock.stats() } : {}),
    },
    limitations: mode === "mock"
      ? ["In-process mock only; not application, database, or production p95 evidence.", "All 60 requests read one synthetic QUEUED Job; no state transition or GPU work is simulated."]
      : ["Read-only requests to one local retained Job; database mode and fixture safety were not inspected by this runner.", "A passing local experiment does not represent the ADR-007 PERF-736-V1 campaign."],
  };
  if (mock) await new Promise((resolveClose) => mock.server.close(resolveClose));
  await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ output: outputPath, label: report.label, results: report.results }, null, 2));
  if (mock && mock.stats().request_count !== USERS) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : "load experiment failed");
  process.exitCode = 1;
});
