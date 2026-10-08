# Backend delivery plan

The supplied frontend/backend document is an API specification, not an instruction to execute examples or implement frontend behavior. The user's six-part order governs delivery. Part 1 is Homepage/Common; Part 2 is Workflow 1 (Contract / Case Review).

## 1. Homepage/Common workflow — complete for the local single-host delivery

Build authentication/tenant isolation, standard envelopes, upload allocation/integrity/completion, durable encrypted documents and spans, processing jobs, source viewer, SSE/replay/cancellation, document library and homepage summary. Prove isolation and failure paths using integration tests before workflow modules depend on it.

Implemented: live document frontend; expiring/revocable server-resolved sessions and tenant isolation; encrypted resources/uploads/audit; bounded integrity-checked upload; durable SQLite queue with owner locking and restart recovery; cancellable parser subprocess; TXT, text/scanned/mixed PDF, DOCX and image processing; explicit partial/OCR warnings; structure-aware exact source spans; tenant-scoped extraction deduplication; sparse BM25 and dense LSA search with metadata filters; pagination/source viewing; SSE replay/heartbeat; cancellation/retry; retention/deletion cascades; offline backup/restore/key rotation; integration tests and CI configuration.

Deployment and downstream boundaries:

- Internet deployment needs organizational identity-provider configuration, reverse-proxy HTTPS, managed secrets/storage permissions and backup retention. Local expiring sessions, revocation, rate limits and same-origin frontend behavior are implemented.
- This embedded deployment intentionally enforces a single application process per storage directory. Distributed queue throughput is a separate deployment choice; local work is durable and resumes after interruption.
- OCR is approximate and warns on every recognized page. DOCX unsupported body-external content is explicitly disclosed. Source processing never claims perfect transcription.
- Dense retrieval is a local LSA baseline. Pretrained legal embeddings/reranking and entailment verification are tuned with the legal workflow modules, rather than presented as existing legal intelligence.
- Citation schemas and exact-span validation are shared now; generated report/schema gates and generated-output deletion references are added in each downstream module.

Ready means the local source is parsed and indexed. It does not assert legal validity, OCR perfection or generated-claim verification. Homepage now reports review and Legal Drafting available, with research/chat unavailable until implemented. Acceptance evidence is recorded in `docs/part-1-acceptance.md`.

## 2. Workflow 1 — Contract / Case Review — local LLM pipeline delivered

Implemented: durable jobs/recovery/cancellation, ready-source authorization, focus/options validation, exact quoted facts, potential payment/notice conflicts, missing-material findings, priority report, uploaded authority metadata/date limitations, immutable reruns/versions and JSON/DOCX/PDF exports. Source verification fails closed on unsupported factual text. Separate model slots, local topic-classifier training and opt-in labeled review dataset export are implemented. Updated to a local LLM pipeline: direct arbitrary contract/case upload, parser/OCR, all-source reading, facts/allegation distinctions, chronology, within/across-document conflicts, gaps, evidence, server-resolved exact citations and a separate interpretation-check pass. Independent review LLM configuration and consented SFT export are implemented. Domain-specific fine-tuning and external authority acquisition/currency certification remain future work. See llm-review.md.

## 3. Workflow 2 — Legal Drafting — implemented; live pipeline smoke test passed

Implemented template requirements/state machine, blocking gaps, acknowledged placeholders, grounded generation, optimistic editing, re-verification, versioned exports and consented SFT collection. Governing authorities currently come from the tenant library, not an external legal database. See legal-drafting.md. Gate: no invented facts, stale-write conflicts, visible provenance and unverified export restriction.

## 4. Workflow 3 — Legal Research

Implement query coverage, primary-authority retrieval/ranking, treatment/currency warnings, memo synthesis, conflicting authorities, separate fact/law citations, refine/search-log/export. Gate: exact supporting spans and unknown-treatment warnings.

## 5. Workflow 4 — RAG Chat

Implement conversations, immutable per-turn document scope, idempotent messages, provisional streaming/canonical verified replacement, evidence-aware abstention, summaries, retry and branch provenance. Gate: interruption/replay, mid-chat uploads, cancelled output and insufficient evidence.

## 6. Novelty workflow — last

No novelty behavior is specified. Define it with the user after the four workflows; reuse shared provenance/jobs and add a namespace/profile without breaking v1 contracts.

## Cross-part release gate

Use the contract's common fixtures: conflicting contracts, scanned annexure, missing termination schedule, statute, conflicting judgments and deliberately unsupported generated fact. Every final factual claim must resolve to an exact stored source span. Legal source acquisition/model choices require a separate implementation decision; never substitute invented authorities.


## 2026-10-08 screenshot integration update

Legal Research backend and local preview are now implemented. See [screenshot field mapping and current limitations](research-and-screenshot-integration.md) and [corpus / training preparation](corpus-and-training.md). Earlier statements marking the research API as planned are superseded by this update; external legal databases, citator analysis and large-corpus infrastructure remain unfinished.
