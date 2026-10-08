# Part 1 acceptance record

Scope: Homepage/Common document workflow, local single-host deployment. This does not include Contract Review or any legal generation.

Validation: **30 tests passed** on Python 3.11 (Windows), using `python -m pytest -q --basetemp=tmp/backend-tests-verified`. Dependency consistency (`pip check`) passed. Browser checks confirmed sample uploads, a file-picker upload with duplicate-source handling, source search, exact source viewing and visible OCR warnings. The app is served at `http://127.0.0.1:8000` by `run-local.ps1`.

| Capability | Evidence |
|---|---|
| Server-resolved tenants and unavailable cross-tenant IDs | API integration tests for documents, jobs, SSE, search, deletion and source access |
| SHA256/size validation and idempotency | Correct/wrong/truncated/oversized bytes, create/complete/retry replay and conflicts |
| Encrypted durable sources and source spans | Stored ciphertext check, exact offset/quote tests and restart recovery |
| PDF/DOCX/TXT/image parsing | Real DOCX tables, text/mixed PDFs, real PNG and scanned-PDF OCR |
| Partial processing is visible | Mixed-page OCR failure preserves usable page and warning; all-unreadable input fails |
| Local hybrid retrieval | BM25 and dense LSA scores, exact citation source, jurisdiction/document filters and tenant isolation |
| Durable processing | Queued work survives restart, same job completes; cancellation and new retry job verified |
| SSE resilience | Immediate snapshot, ordered persisted IDs, Last-Event-ID replay, invalid cursor validation and terminal delivery |
| Retention/deletion | Document/chunk/job/event/blob/idempotency/associated-audit cascade and retention-expiry tests |
| Sessions/security boundaries | Expiry, revocation, throttling, loopback-only demo and foreign-origin rejection |
| Operational recovery | Encrypted backup/restore and new-directory key rotation; restored sessions cleared |
| Small frontend | Browser-confirmed sample uploads, live readiness, exact search passage, scanned-source OCR warning and library |

The test command and deployment/format limitations are in README.md. The common typed evidence gate rejects dangling citations and unsupported final claims and verifies quotes/offsets against stored source text. Exact matching alone is not semantic/legal verification; that work remains in the later workflow pipelines.

The browser test uses synthetic sources only. Its demo library is intentionally left populated so the user can inspect the backend. CI configuration is supplied; no CI run or public deployment is claimed.
