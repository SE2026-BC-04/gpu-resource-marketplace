#!/usr/bin/env node

import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const seed = "VT090-2026-11-09-23001940";
const pollingTransitions = {
  QUEUED: ["QUEUED", "RUNNING", "CANCELLED"],
  RUNNING: ["RUNNING", "COMPLETED", "FAILED"],
};
const transientResults = ["TIMEOUT", "HTTP_503"];
const retryablePostResults = ["NETWORK_LOST_AFTER_COMMIT", "503_BEFORE_COMMIT"];
const suites = {
  polling: {
    prior_status: ["QUEUED", "RUNNING"],
    get_result: ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", ...transientResults],
    ui_context: ["SAME_JOB", "SWITCH_JOB", "UNMOUNT", "CHANGE_IDENTITY"],
    execution_target: "frontend/src/ui/jobs/JobsPage.pairwise.test.tsx (one Vitest case per generated row)",
    excluded_case_mapping: "Invalid persisted lifecycle edges map to backend/tests/test_jobs_guard_update.py::test_only_the_four_lifecycle_edges_exist_even_for_the_owner; PostgreSQL guard test is NOT_RUN locally without a verified disposable cluster. Late QUEUED responses after RUNNING are exercised separately as stale-response cases, not valid transitions.",
    exclusionReason(row) {
      if (transientResults.includes(row.get_result)) return null;
      if (pollingTransitions[row.prior_status].includes(row.get_result)) return null;
      return `invalid persisted Job transition ${row.prior_status} -> ${row.get_result}; DB lifecycle guard rejects it`;
    },
  },
  submission_retry: {
    attempt: ["FIRST_SUBMISSION", "SAME_KEY_SAME_BODY", "SAME_KEY_CHANGED_BODY"],
    post_result: ["201_CREATED", "200_REPLAY", "NETWORK_LOST_AFTER_COMMIT", "503_BEFORE_COMMIT", "409_KEY_REUSED"],
    recovery: ["NO_AUTOMATIC_POST", "RETRY_SAME_ATTEMPT", "EDIT_AND_NEW_ATTEMPT"],
    execution_target: "frontend/src/api/jobs.pairwise.test.ts (one API-client case per generated row; mocked HTTP only)",
    exclusionReason(row) {
      if (row.attempt === "FIRST_SUBMISSION" && !["201_CREATED", ...retryablePostResults].includes(row.post_result)) {
        return `a first submission cannot be a replay or same-key conflict (${row.post_result})`;
      }
      if (row.attempt === "SAME_KEY_SAME_BODY" && !["200_REPLAY", ...retryablePostResults].includes(row.post_result)) {
        return `same key/body retry cannot be a changed-body conflict or a second create (${row.post_result})`;
      }
      if (row.attempt === "SAME_KEY_CHANGED_BODY" && row.post_result !== "409_KEY_REUSED") {
        return `changed body with a retained key must return IDEMPOTENCY_KEY_REUSED (${row.post_result})`;
      }
      if (["201_CREATED", "200_REPLAY"].includes(row.post_result) && row.recovery !== "NO_AUTOMATIC_POST") {
        return `a successful response must not trigger a retry or another submit (${row.recovery})`;
      }
      if (retryablePostResults.includes(row.post_result) && row.recovery === "EDIT_AND_NEW_ATTEMPT") {
        return "an uncertain attempt must be reconciled with the same frozen key/body before editing";
      }
      if (row.post_result === "409_KEY_REUSED" && row.recovery === "RETRY_SAME_ATTEMPT") {
        return "a changed-body conflict cannot be retried with the same attempt";
      }
      return null;
    },
  },
};

function enumerateAll(factors, names, index = 0, current = {}) {
  if (index === names.length) return [{ ...current }];
  const name = names[index];
  return factors[name].flatMap((value) => enumerateAll(factors, names, index + 1, { ...current, [name]: value }));
}

function hash(text) {
  let value = 2166136261;
  for (const char of text) value = Math.imul(value ^ char.charCodeAt(0), 16777619) >>> 0;
  return value;
}

function pairKey(leftName, leftValue, rightName, rightValue) {
  return JSON.stringify([leftName, leftValue, rightName, rightValue]);
}

function pairsForRows(rows, factorNames) {
  const pairs = new Set();
  for (const row of rows) {
    for (let left = 0; left < factorNames.length; left += 1) {
      for (let right = left + 1; right < factorNames.length; right += 1) {
        const a = factorNames[left];
        const b = factorNames[right];
        pairs.add(pairKey(a, row[a], b, row[b]));
      }
    }
  }
  return pairs;
}

function generate(name, factors) {
  const factorNames = Object.keys(factors).filter((key) => !["execution_target", "excluded_case_mapping", "exclusionReason"].includes(key));
  const cartesianRows = enumerateAll(factors, factorNames);
  const validRows = cartesianRows.filter((row) => factors.exclusionReason(row) === null);
  const excludedRows = cartesianRows
    .filter((row) => factors.exclusionReason(row) !== null)
    .map((row) => ({ factors: row, reason: factors.exclusionReason(row) }));
  const uncovered = pairsForRows(validRows, factorNames);
  const feasibleFactorPairs = uncovered.size;
  const selected = [];

  while (uncovered.size > 0) {
    const candidates = validRows.map((row) => {
      const rowPairs = pairsForRows([row], factorNames);
      const newPairs = [...rowPairs].filter((pair) => uncovered.has(pair));
      return { row, newPairs, tie: hash(`${seed}:${name}:${JSON.stringify(row)}`) };
    }).filter((candidate) => candidate.newPairs.length > 0)
      .sort((left, right) => right.newPairs.length - left.newPairs.length || left.tie - right.tie);
    const choice = candidates[0];
    if (!choice) throw new Error(`${name}: pairwise generation stalled with ${uncovered.size} uncovered pairs`);
    selected.push(choice.row);
    for (const pair of choice.newPairs) uncovered.delete(pair);
  }

  const selectedPairs = pairsForRows(selected, factorNames);
  const coveredFactorPairs = selectedPairs.size;
  const pairwiseCoveragePercent = feasibleFactorPairs === 0
    ? 100
    : Math.round((coveredFactorPairs / feasibleFactorPairs) * 10000) / 100;
  if (coveredFactorPairs !== feasibleFactorPairs) {
    throw new Error(`${name}: covered ${coveredFactorPairs}/${feasibleFactorPairs} feasible factor pairs`);
  }

  const excludedByReason = Object.groupBy(excludedRows, (row) => row.reason);
  return {
    execution_target: factors.execution_target,
    excluded_case_mapping: factors.excluded_case_mapping ?? null,
    total_cartesian_rows: cartesianRows.length,
    valid_rows: validRows.length,
    excluded_invalid_rows: excludedRows.length,
    excluded_rows: excludedRows,
    pairwise_rows: selected.map((factorsForCase, index) => ({
      id: `${name.toUpperCase()}-${String(index + 1).padStart(2, "0")}`,
      factors: factorsForCase,
    })),
    feasible_factor_pairs: feasibleFactorPairs,
    covered_factor_pairs: coveredFactorPairs,
    pairwise_coverage_percent: pairwiseCoveragePercent,
    excluded_by_reason: Object.fromEntries(Object.entries(excludedByReason).map(([reason, rows]) => [reason, rows.length])),
  };
}

const output = {
  title: "VT-090 deterministic constrained pairwise cases",
  seed,
  algorithm: "greedy maximum uncovered-pair coverage; FNV-1a(seed + row) tie break",
  generated_from: "generate-pairwise.mjs",
  suites: Object.fromEntries(Object.entries(suites).map(([name, factors]) => [name, generate(name, factors)])),
};
const here = dirname(fileURLToPath(import.meta.url));
const outputPath = resolve(here, "pairwise-cases.json");
await writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
console.log(`wrote ${outputPath}`);
for (const [name, suite] of Object.entries(output.suites)) {
  console.log(`${name}: ${suite.pairwise_rows.length} generated rows; ${suite.valid_rows} executable configurations; ${suite.excluded_invalid_rows} excluded; ${suite.covered_factor_pairs}/${suite.feasible_factor_pairs} feasible pairs (${suite.pairwise_coverage_percent}%)`);
}
