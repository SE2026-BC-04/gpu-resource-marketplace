# BT3 VT-089 — AI Usage Log

- **Assistant/tool:** Codex coding agent; exact model build identifier unavailable.
- **Input:** user-provided BT3 VT-089 assignment, repository instructions, and the linked TV1 `DEC-VT089-L2-01` / TV2 `ACK_WITH_ACTIONS` comments.
- **AI-assisted output used:** repository exploration, change-record and API-contract drafting, test matrix, backend/frontend implementation suggestions, load-harness draft, evidence summaries, and report prose.
- **Human responsibility:** the student remains responsible for all submitted source, tests, interpretation and claims. No assistant output is an owner ACK, human approval, or runtime result.
- **Review example 1:** an AI-assisted cursor regression initially used a test key with an extra hyphen. The signature check failed; the test was corrected to the exact public baseline fixture key and rerun.
- **Review example 2:** an early PostgreSQL test fixture had inconsistent role/client identity data. Manual review found and corrected the fixture before final focused test evidence.
- **Adversarial check:** a detached temporary mutant removed the role/scope guard. Three cross-role test assertions failed as expected. The mutant commit was not pushed; the submitted implementation retains the guard.
- **Limitations:** local focused and frontend tests are reported separately from skipped PostgreSQL/E2E tests, unavailable coverage tooling, unrun load test, and pending exact-HEAD human reviews. See [README](README.md) and [evidence/coverage-risk-review.md](evidence/coverage-risk-review.md).
