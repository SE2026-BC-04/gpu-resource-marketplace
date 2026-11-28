#!/usr/bin/env node
"use strict";
/*
 * Independent Node.js compatibility oracle for frozen demo-v1-public1.
 * Only the fixed ASCII UUIDv4 / integer domain is supported; this is NOT
 * an arbitrary-value RFC 8785 encoder and is not a runtime service.
 *
 * Usage: node simulator/tools/p2e09_node_oracle.cjs < fixture.json
 * Emits a deterministic JSON trace to stdout, with no secrets or DB access.
 */
const { createHash } = require("node:crypto");
const fs = require("node:fs");

const PREFIX = Buffer.from("GPU-MARKETPLACE:SIM-REFERENCE:PUBLIC-V1\n", "ascii");
const LIMIT32 = 4294967296;
const INPUT_KEYS = [
  "algorithm_version", "duration_seconds", "job_id", "listing_id",
  "requested_gpu_count", "worker_id", "workload_profile"
];
const OUTPUT_KEYS = [
  "duration_seconds", "failure_reason", "job_id", "listing_id", "outcome",
  "requested_gpu_count", "schema_version", "work_units", "workload_profile"
];

function sortedCanonicalBytes(obj, keys) {
  const ordered = {};
  for (const key of keys) ordered[key] = obj[key];
  return Buffer.from(JSON.stringify(ordered), "utf8");
}
function sha256(bytes) {
  return createHash("sha256").update(bytes).digest();
}
function domainHash(domain, counter, canonicalInput) {
  if (!["seed", "outcome", "work_units"].includes(domain)) throw Error("invalid domain");
  const counterBytes = Buffer.alloc(4);
  counterBytes.writeUInt32BE(counter);
  const preimage = Buffer.concat([
    PREFIX, Buffer.from(domain + "\n", "ascii"),
    canonicalInput, Buffer.from("\n", "ascii"), counterBytes
  ]);
  return { preimage, digest: sha256(preimage) };
}
function draw(domain, canonicalInput, range) {
  const limit = Math.floor(LIMIT32 / range) * range;
  const probes = [];
  for (let counter = 0; counter < LIMIT32; counter++) {
    const { preimage, digest } = domainHash(domain, counter, canonicalInput);
    const raw = digest.readUInt32BE(0);
    probes.push({ counter, raw, hash_input_hex: preimage.toString("hex"),
                  hash_hex: digest.toString("hex"), accepted: raw < limit });
    if (raw < limit) return { value: raw % range, probes };
  }
  throw Error("sampling exhausted");
}
function verifyUUIDv4(value) {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
}
function main(input) {
  if (Object.keys(input).sort().join(",") !== [
    "duration_seconds", "job_id", "listing_id", "requested_gpu_count",
    "worker_id", "workload_profile"
  ].join(",")) throw Error("wrong input keys");
  for (const key of ["job_id", "listing_id", "worker_id"]) {
    if (!verifyUUIDv4(input[key])) throw Error("invalid UUIDv4: " + key);
  }
  for (const key of ["requested_gpu_count", "duration_seconds"]) {
    if (!Number.isInteger(input[key]) || input[key] < 1 || input[key] > 2147483647) {
      throw Error("invalid int32: " + key);
    }
  }
  if (input.workload_profile !== "demo-v1") throw Error("invalid profile");

  const canonicalInput = sortedCanonicalBytes(
    { ...input, algorithm_version: "demo-v1-public1" }, INPUT_KEYS
  );
  const seedHash = domainHash("seed", 0, canonicalInput);
  const seed = (seedHash.digest.readBigUInt64BE(0) & 0x7fffffffffffffffn).toString();
  const outcome = draw("outcome", canonicalInput, 100);
  const units = draw("work_units", canonicalInput, 1000000);
  const failure = outcome.value < 80 ? null :
    outcome.value < 90 ? "WORKER_FAULT" : "JOB_FAULT";
  const output = {
    duration_seconds: input.duration_seconds, failure_reason: failure,
    job_id: input.job_id, listing_id: input.listing_id,
    outcome: failure === null ? "SUCCESS" : "FAILED",
    requested_gpu_count: input.requested_gpu_count, schema_version: "demo-v1",
    work_units: units.value, workload_profile: "demo-v1"
  };
  const outputBytes = sortedCanonicalBytes(output, OUTPUT_KEYS);
  return {
    canonical_input_hex: canonicalInput.toString("hex"),
    seed_value: seed,
    seed_hash_input_hex: seedHash.preimage.toString("hex"),
    seed_hash_hex: seedHash.digest.toString("hex"),
    outcome, work_units: units,
    canonical_output_hex: outputBytes.toString("hex"),
    output,
    result_digest: "sha256:" + sha256(outputBytes).toString("hex")
  };
}
const data = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(main(data)) + "\n");
