#!/usr/bin/env node

import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const seed = "VT090-2026-11-09-23001940";
const suites = {
  polling: {
    known_status: ["QUEUED", "RUNNING"],
    get_result: ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "HTTP_503"],
    ui_context: ["SAME_JOB", "SWITCH_JOB", "UNMOUNT", "CHANGE_IDENTITY"],
    valid: () => true,
  },
  submission_retry: {
    attempt: ["FIRST_SUBMISSION", "SAME_KEY_SAME_BODY", "SAME_KEY_CHANGED_BODY"],
    post_result: ["201_CREATED", "200_REPLAY", "NETWORK_LOST_AFTER_COMMIT", "503_BEFORE_COMMIT", "409_KEY_REUSED"],
    recovery: ["NO_AUTOMATIC_POST", "RETRY_SAME_ATTEMPT", "EDIT_AND_NEW_ATTEMPT"],
    valid(row) {
      if (row.attempt === "FIRST_SUBMISSION" && ["200_REPLAY", "409_KEY_REUSED"].includes(row.post_result)) return false;
      if (row.attempt === "SAME_KEY_SAME_BODY" && row.post_result === "409_KEY_REUSED") return false;
      if (row.attempt === "SAME_KEY_CHANGED_BODY" && row.post_result !== "409_KEY_REUSED") return false;
      if (row.post_result === "409_KEY_REUSED" && row.recovery !== "NO_AUTOMATIC_POST" && row.recovery !== "EDIT_AND_NEW_ATTEMPT") return false;
      return true;
    },
  },
};

function enumerate(factors, names, index = 0, current = {}) {
  if (index === names.length) return factors.valid(current) ? [{ ...current }] : [];
  const name = names[index];
  return factors[name].flatMap((value) => enumerate(factors, names, index + 1, { ...current, [name]: value }));
}

function hash(text) {
  let value = 2166136261;
  for (const char of text) value = Math.imul(value ^ char.charCodeAt(0), 16777619) >>> 0;
  return value;
}

function pairKey(leftName, leftValue, rightName, rightValue) {
  return JSON.stringify([leftName, leftValue, rightName, rightValue]);
}

function generate(name, factors) {
  const factorNames = Object.keys(factors).filter((key) => key !== "valid");
  const validRows = enumerate(factors, factorNames);
  const totalRows = factorNames.reduce((count, factor) => count * factors[factor].length, 1);
  const uncovered = new Set();
  for (let left = 0; left < factorNames.length; left += 1) {
    for (let right = left + 1; right < factorNames.length; right += 1) {
      const a = factorNames[left];
      const b = factorNames[right];
      for (const row of validRows) uncovered.add(pairKey(a, row[a], b, row[b]));
    }
  }

  const selected = [];
  while (uncovered.size > 0) {
    const candidates = validRows.map((row) => {
      const covers = [];
      for (let left = 0; left < factorNames.length; left += 1) {
        for (let right = left + 1; right < factorNames.length; right += 1) {
          covers.push(pairKey(factorNames[left], row[factorNames[left]], factorNames[right], row[factorNames[right]]));
        }
      }
      const newPairs = covers.filter((pair) => uncovered.has(pair));
      return { row, newPairs, tie: hash(`${seed}:${name}:${JSON.stringify(row)}`) };
    }).filter((candidate) => candidate.newPairs.length > 0)
      .sort((left, right) => right.newPairs.length - left.newPairs.length || left.tie - right.tie);
    const choice = candidates[0];
    if (!choice) throw new Error(`${name}: pairwise generation stalled with ${uncovered.size} uncovered pairs`);
    selected.push(choice.row);
    for (const pair of choice.newPairs) uncovered.delete(pair);
  }

  const feasibleFactorPairs = [...new Set(validRows.flatMap((row) => {
    const pairs = [];
    for (let left = 0; left < factorNames.length; left += 1) {
      for (let right = left + 1; right < factorNames.length; right += 1) {
        pairs.push(pairKey(factorNames[left], row[factorNames[left]], factorNames[right], row[factorNames[right]]));
      }
    }
    return pairs;
  }))].length;
  return {
    total_cartesian_rows: totalRows,
    valid_rows: validRows.length,
    excluded_invalid_rows: totalRows - validRows.length,
    pairwise_rows: selected.map((factorsForCase, index) => ({ id: `${name.toUpperCase()}-${String(index + 1).padStart(2, "0")}`, factors: factorsForCase })),
    feasible_factor_pairs: feasibleFactorPairs,
    covered_factor_pairs: feasibleFactorPairs,
    pairwise_coverage_percent: 100,
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
  console.log(`${name}: ${suite.pairwise_rows.length} rows; ${suite.feasible_factor_pairs} feasible pairs; coverage 100%`);
}
