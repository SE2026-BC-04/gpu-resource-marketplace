# TV4-P2D-14 — Signer readiness and planned rotation test design

**Status:** Ready for cross-owner review as a test plan. `P2D-RACE-07` and `P2D-DRT-12` are BLOCKED pending the approved readiness and allocation ports and guarded PostgreSQL. The direction is D-18/E-C3 + G1. No new TTL, provisioning or incident policy is selected.

## Fixture and controls

Seed Worker A with K1 as the sole active public key, two QUEUED Jobs on an ACTIVE Listing, and enough GPUs for the FIFO head. Seed an independent Worker B and eligible Listing as a progress control. Use TV3/TV5's synthetic signer fixture and TV1's actual readiness adapter when available. Save Worker/key IDs and a trusted DB-clock reading without logging proof bytes, private keys or tokens. Build matching readiness outside the UoW; compare expiry against the DB clock after locks. Run a positive control with fresh K1 before testing rejection or rotation.

For blocked cases read a fresh committed snapshot after the port returns. Require exact Job IDs/statuses and queue order, unchanged Listing counter, no new Allocation/Attempt/Outbox for the blocked Job, and no reassignment to a later Job of Worker A. Worker B may progress. When testing the Manager precheck, separately assert that it makes no allocation-port call. When testing the transactional fence, require that the real port entered and returned `Blocked(SIGNER_NOT_READY)` without business writes.

## Deterministic cases

| Case | Barrier or input | Required observation |
|---|---|---|
| Rotation wins Worker advisory lock | Native provisioning transaction acquires exclusive first and commits registration of K2. Observe allocation waiting for the shared lock, then release. | Recheck sees K1 and K2 active. New reservations are blocked while existing RUNNING work can finish. |
| Allocation wins Worker advisory lock | Allocation holds shared and reaches the locked head. Verify K2 registration waits for exclusive, then let allocation commit. | Exactly one legal reservation and one Attempt under K1. K2 registration then quiesces A. Activation refuses while that Attempt is RUNNING. |
| Activation after drain | Finish all RUNNING attempts through the approved path, provision/shadow-check K2 as specified by owners, then take exclusive for activation. | Activation leaves K2 as the sole active key. Previously committed K1 receipts remain eligible for historical verification. Fresh K2 proof allows the true FIFO head. |
| Stale K1 after K2 activation | Capture otherwise fresh K1 readiness before rotation. Send it to the locked allocation port after K2 becomes sole active. | No reservation, no head bypass and Manager drops the affected readiness cache entry on the port result. |
| Locked readiness edges | With one active key, separately vary proof Worker ID, key ID, fingerprint and expiry. Test expiry one microsecond before DB time, exactly equal, and one microsecond after with all other inputs valid. With zero active keys, also exercise the locked port. | Wrong identity, zero active keys, expired and equal-expiry all block. The strictly future valid proof is a separate positive control. |
| Rollback during planned rotation | After two-key quiesce, simulate K2 readiness/startup failure. Observe a still-queued candidate while restoration is incomplete. | The two-key fence remains while K1 is unusable. Restore usable K1 before removing the second-key fence under the authorized procedure. Require fresh K1 proof before admitting new work. |

Use separate committed sessions, bounded gates, and observation of the actual blocked backend. For each contested case run both legal commit orders and record the active-key set and matching Allocation/Attempt/Outbox graph. Keep the signer protocol and private material outside the DB transaction. A cold Simulator restart inside a still-valid proof TTL remains the documented residual case `P2C-SIGN-07`; the tests above do not use restart as proof of invalidation.

Sources: Phase 2D §7.4/§7.5; `D-IF-07`; Phase 2C §6.6.5; Phase 2B `B-IF-06` and `P2B-DRT-24..29`.
