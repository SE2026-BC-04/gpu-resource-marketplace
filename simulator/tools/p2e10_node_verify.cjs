#!/usr/bin/env node
"use strict";

// Independent test oracle for the ADR-004 ASCII-only public vector. Signed
// Result V1 values are strings/null only, so JSON.stringify plus UTF-16 key
// sorting is JCS-equivalent for this exact schema/vector (not a general JCS lib).
const crypto = require("node:crypto");

function canonicalize(value) {
  if (value === null || typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) throw new Error("arrays are outside Signed Result V1 payload");
  if (typeof value !== "object") throw new Error("non-string primitive is outside Signed Result V1");
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`)
    .join(",")}}`;
}

const input = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
const canonical = canonicalize(input.payload);
const prefix = Buffer.from("GPU-MARKETPLACE:SIGNED-RESULT:V1\n", "ascii");
const message = Buffer.concat([prefix, Buffer.from(canonical, "utf8")]);
const rawPublicKey = Buffer.from(input.public_key_hex, "hex");
if (rawPublicKey.length !== 32) throw new Error("expected raw Ed25519 public key");
const spkiPrefix = Buffer.from("302a300506032b6570032100", "hex");
const publicKey = crypto.createPublicKey({
  key: Buffer.concat([spkiPrefix, rawPublicKey]),
  format: "der",
  type: "spki",
});
const signature = Buffer.from(input.signature, "base64url");
const valid = crypto.verify(null, message, publicKey, signature);
const tampered = Buffer.from(message);
tampered[tampered.length - 1] ^= 1;
const tamperedValid = crypto.verify(null, tampered, publicKey, signature);
process.stdout.write(JSON.stringify({ canonical, valid, tampered_valid: tamperedValid }));
