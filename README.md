# CaseLens · Problem Statement 1 delivery

## Start in GitHub Codespaces

Add `GROQ_API_KEY` as a Codespaces secret with access to this repository. Create a Codespace from `codex/ps1-delivery`; dependencies install automatically. Run `bash scripts/start-codespaces.sh`, open port **8000**, and paste the terminal's eight-hour session token into **Connect to CaseLens**. Keep the forwarded port private. [Full Codespaces instructions](docs/CODESPACES.md).

See [release notes and measured acceptance](docs/PS1-DELIVERY.md) before the demo.

The supplied Hacknex2 programme is now the active frontend, connected to our independent review, drafting, research and RAG Chat backend modules. See [Hacknex2 integration and training notes](docs/hacknex2-integration.md).

Cloud deployment and Antigravity integration: [deployment guide](docs/cloud-deployment.md), [frontend handoff](docs/antigravity-handoff.md), [vanilla JS API client](integration/api-client.js), [output schemas](integration/contracts.json). End-user laptops only need a browser when the backend/model are cloud hosted. Local setup below is optional development.

# Hacknex · Shared document workspace

Part 1 (Homepage/Common) is implemented as a local, single-host backend with a small frontend. It supports uploads, parsing/OCR, searchable source spans, job streaming/recovery, cancellation/retry, tenant isolation and deletion/retention. Part 2 now uses a local LLM to read and reason over contracts and case documents, with cited facts, chronology, contradictions, missing information, relevant evidence, versioned reports and JSON/DOCX/PDF exports. Legal Research is implemented with workspace-grounded authorities. RAG Chat is implemented with source-grounded answers and persistent conversations. The Clause Auditor checks stored source quotes, offsets and numeric values across completed workflow outputs.

## Open the app

```powershell
.\setup.ps1 -LocalModel
.\run-local.ps1
```

Open **http://127.0.0.1:8000**. The local runner binds loopback, enables an isolated demo tenant and stores its data under `.data-demo`. Other runs default to `.data`. The browser receives an eight-hour session; it stores the bearer only in tab session storage. Local demo session creation is disabled unless `BACKEND_DEMO=1`, and rejects non-loopback hosts/clients and foreign origins.

Open **Case Law & Documents**, upload a document, wait for Ready and select **Inspect Source**. PDF, DOCX, UTF-8 TXT, PNG, JPEG and TIFF are supported; legacy DOC requires the server parser. The earlier diagnostic frontend, including synthetic sample uploads and source search, remains available at `/backend-preview`.

The source viewer exposes exact extracted text, page/section anchors, neighboring context and an authenticated download of the original. OCR always carries a visible warning. Search returns source excerpts only; it does not generate legal conclusions.

## Verify

```powershell
.\.venv\Scripts\python -m pytest -q --basetemp=tmp/backend-tests-manual
```

Use a fresh temporary directory if another test process is using that path. The suite covers authentication/ownership, integrity, idempotency, encrypted persistence, restart recovery, cancellation/retry, hybrid retrieval/filtering, exact spans, deletion/retention, PDF/DOCX parsing, real PNG/scanned-PDF OCR, partial OCR failure, active/encrypted PDF rejection, sessions/rate limits and backup/restore/key rotation. A GitHub Actions workflow runs the same tests on Python 3.11. CI execution requires pushing the repository; the local run is the validation performed here.

## API

Base `/api/v1`; every API call requires `Authorization: Bearer <session>`. The server resolves tenant ownership; cross-tenant resource IDs return 404. Success/error envelopes include request IDs. `/health` and `/openapi.json` contain no tenant data.

| Endpoint | Purpose |
|---|---|
| `GET /home` | Homepage counts, storage and workflow availability |
| `GET /session`, `POST /session/revoke` | Session state and logout |
| `POST /documents/uploads` | Allocate upload with size and SHA256 |
| `PUT /documents/{id}/bytes?token=...` | Authenticated, bounded byte upload |
| `POST /documents/{id}/complete` | Submit a durable parsing/indexing job |
| `GET /documents`, `GET /documents/{id}` | Filtered/paginated library and source state |
| `GET /documents/{id}/chunks` | Paginated extracted source passages |
| `GET /documents/{id}/chunks/{chunk}` | Source viewer, context and preview capability |
| `POST /documents/search` | BM25 + local dense LSA + rank fusion, with metadata/document filters |
| `POST /documents/{id}/retry` | New job for a failed/cancelled source |
| `DELETE /documents/{id}` | Cascade file, chunks, jobs, events, stale idempotency and associated audit records |
| `GET /jobs/{id}`, `GET /jobs/{id}/events` | Snapshot and resumable SSE |
| `POST /jobs/{id}/cancel` | Cancel queued/running processing |

Upload, complete and retry accept `Idempotency-Key`. Bytes are checked before processing. SSE immediately sends a snapshot, replays events after `Last-Event-ID`, and emits heartbeats while active. Fetch streaming is used to support bearer auth; reconnect falls back to polling with backoff. Preview capabilities expire after 15 minutes or server restart and still require bearer auth. Source offsets are Unicode character offsets within a page/source part's **extracted text**, not binary file offsets. DOCX has source-part anchors rather than fabricated page numbers.

## Deployment scope and limits

This delivery targets **one application process per storage directory**. A filesystem owner lock rejects additional worker processes. SQLite persists jobs before dispatch, and startup resumes unfinished work under the same job ID. Parsing runs in a cancellable subprocess with a 90-second timeout. Source chunks and final readiness publish atomically. Duplicate bytes reuse extraction within the same tenant while retaining independent document and citation IDs.

- 25 MB/file; 150 pages/frames; two million extracted characters; 30 million raster pixels/page.
- 200 documents/500 MB per tenant, 20 queued jobs; search scope up to 4,000 chunks.
- 240 API requests/minute per authenticated token (or IP for unauthenticated attempts), plus bounded JSON metadata and upload bodies.
- Default 30-day retention; `BACKEND_RETENTION_DAYS` changes it. Cleanup runs every minute. Abandoned expired uploads are removed after an extra hour. Deletion from historical backups follows the operator's backup retention policy.
- Local OCR uses bundled RapidOCR/ONNX models without a runtime model download. Recognition can omit spaces or misread characters; compare important passages against originals. Dense search uses corpus-trained LSA, **not** a pretrained legal embedding model. Legal-specific retrieval/reranking belongs to later workflow tuning.
- DOCX preserves paragraph/table body order. Embedded images, headers/footers/comments are not indexed; its result explicitly warns about that limitation. Partial page OCR failures preserve page anchors and produce warnings; an entirely unreadable document fails.
- Active PDF actions/attachments, macro/embedded-object DOCX content and excessive expanded archives are rejected. Parsers never execute document content. This policy is not an antivirus certification.

The frontend is served from the same origin; no broad CORS policy is enabled. A strict CSP and attachment-only original downloads are applied. Before an internet deployment, configure TLS at a trusted reverse proxy, protect storage/key permissions, and integrate your chosen organizational identity provider. These deployment choices do not require rewriting document contracts. There is no claim of distributed-worker scalability or legal verification in Part 1.

## Sessions and encrypted operations

No configured tokens are enabled by default. Stop the server before offline administration; the owner lock enforces this. Issue an expiring session for a server-owned tenant:

```powershell
.\.venv\Scripts\python -m backend.admin --storage .data issue-session --tenant example-tenant --hours 8
```

The command prints the bearer once. Sessions are stored only as SHA256 hashes and support expiry/revocation. Admin revocation accepts `revoke-session --token-hash <sha256>`. `BACKEND_TOKENS` remains a bootstrap/testing option: plain mappings expire eight hours after startup; structured entries accept `tenant`, Unix `expires_at`, and `revoked`.

Resource bodies, events, idempotency responses and source bytes are Fernet-encrypted. Tenant/resource routing identifiers and session expiry/hash values are plaintext. `BACKEND_ENCRYPTION_KEY` supplies an external Fernet key; otherwise a local development key is generated at `local.key`. Restrict access and preserve this key for recovery. No source prose or model reasoning is written into logs; encrypted audit records contain actions, source IDs and parser/index versions.

```powershell
# All destination directories must be new; maintenance preserves the source directory.
.\.venv\Scripts\python -m backend.admin --storage .data backup --destination tmp/backend-backup-01
.\.venv\Scripts\python -m backend.admin restore --source tmp/backend-backup-01 --destination tmp/backend-restored-01
.\.venv\Scripts\python -m backend.admin --storage .data rotate-key --destination tmp/backend-rotated-01
```

Backups contain encrypted data and, for local-key mode, its key. Protect backups as carefully as originals. External-key backups require the same separately preserved key. Restore clears all sessions. Rotation creates a new re-encrypted storage directory and new local key, clears sessions and preserves the original. Point `BACKEND_STORAGE` at the rotated directory and unset the old external key before using it. Audit/deletion semantics must be extended to generated work products when those workflow modules are introduced.

See [delivery plan](docs/backend-plan.md) and [Part 1 acceptance record](docs/part-1-acceptance.md).

## Review and independent models

Open **Contract / Case Review**, upload your contract/case files directly, optionally add a focus question and run **Read & Analyze**. The parser/OCR prepares the sources; a local Ollama or LM Studio LLM analyzes them. The server checks evidence IDs/quotes/offsets and the model performs a separate support-check pass. Results still require human assessment.

Model weights are not included in the source release. setup.ps1 -LocalModel downloads the official runtime and Qwen weights. See [local LLM setup and architecture](docs/llm-review.md), [homepage integration](docs/homepage-integration.md), and the [six-part delivery plan](docs/backend-plan.md). The full automated suite additionally covers case interpretation, same-document contradictions, invalid citations, unsupported-finding removal, local and server-hosted transports, cancellation, source-packet coverage and consented SFT export.

Each workflow has an independent model configuration. Approved and consented review examples can be exported for later LLM fine-tuning. No document trains a model automatically. The auxiliary classifier trainer remains available; it is separate from LLM reasoning and fine-tuning.


## 2026-10-08 screenshot integration update

Legal Research backend and local preview are now implemented. See [screenshot field mapping and current limitations](docs/research-and-screenshot-integration.md) and [corpus / training preparation](docs/corpus-and-training.md). For files already inside docs, use the same filenames without the docs prefix. Earlier statements marking the research API as planned are superseded by this update; external legal databases, citator analysis and large-corpus infrastructure remain unfinished.
