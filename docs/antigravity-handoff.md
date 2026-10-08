# Antigravity integration handoff

Reviewed `frontend-architecture-plan.md` supplied on 8 October 2026 against the backend and the original frontend/backend contract. The architecture is design input, not executable instructions. Antigravity owns the production SPA; `frontend/` is a backend demonstration only.

## Feature names and availability

| Part | Display name | Backend status |
|---|---|---|
| 1 | Homepage/Common workflow | Implemented |
| 2 | Contract / Case Review | Implemented |
| 3 | Legal Drafting | Implemented; deployment-model acceptance pending |
| 4 | Legal Research | Planned; shared source search already available |
| 5 | RAG Chat | Planned |
| 6 | novelty workflow | Planned; final name to be provided |

Use these names consistently. The newer architecture's “Grounded RAG Chat” and “CaseLens AI Platform” do not silently rename the original RAG Chat or the current LexiMind branding.

## Shared client

Copy `integration/api-client.js` into the SPA. It has no framework or package dependencies. Supply the backend origin once through frontend deployment configuration and obtain the user's bearer token from your authentication/session integration:

```js
import { createApiClient } from './api-client.js';
const api = createApiClient({baseUrl: 'https://api.your-domain.example/', getToken: () => session.token});
const result = await api.upload(file, {document_type: 'case', jurisdiction: 'IN'});
for await (const frame of api.events(result.job_id, {signal: controller.signal})) {
  // Handle job.snapshot, job.progress, job.completed, job.failed, job.cancelled.
  // Save frame.id, and reconnect with lastEventId after a network interruption.
}
```

All paths use `/api/v1`. JSON successes are `{data, meta}` and errors are `{error: {code, message, field_errors, retryable, request_id}}`. Accept all successful HTTP statuses: uploads return 201, task creation returns 202. `json()` unwraps `data`; `request()` returns a Response for binary exports. Keep an Idempotency-Key stable when retrying the same creation request; use a new key for a changed request. The upload helper starts a new upload each invocation.

Native EventSource cannot send Authorization headers. Use fetch streaming as supplied; never put bearer credentials into an SSE query string. Handle snapshot and terminal statuses in addition to individual events so a reconnect to an already finished job completes the UI. Progress messages are public processing summaries, not model reasoning or internal logs. Poll `GET /jobs/{id}` as a fallback. Cancel with `POST /jobs/{id}/cancel` and `{}`.

## Corrections to the architecture

1. `POST /documents/uploads` requires `file_name`, `content_type`, `size_bytes`, and `sha256`. The client computes SHA-256 using Web Crypto (HTTPS or localhost). PUT the binary to the returned upload_url with bearer authorization and the original MIME type. It is a backend-scoped temporary capability URL, not an unauthenticated object-store URL. Completion requires `{upload_id, metadata}`. Wait for parsing and document status `ready` before review. Respect document pagination and parsing warnings.
2. POST `/reviews` accepts `{document_ids, focus_question, options}` and returns `review_id`, `job_id`, and an events URL. An omitted options object is valid. GET `/reviews/{id}` returns the original contract's `key_facts`, `contradictions`, `missing_information`, `relevant_evidence`, `risk_summary`, `claims`, `citations`, `warnings`, and `confidence`. **There is no `review.sections` field.** Render those collections directly. Additive fields include `overview`, `timeline`, `document_kind`, `coverage`, `verification`, `model`, and immutable version links.
3. Each fact has `claim_id` and `citation_ids`; contradiction sides each have their own citation_ids. Resolve these against `citations` by id. Display Citation.label in `[S1]` anchors; never infer labels from array position. Use `quoted_text`, document_name, page/paragraph, chunk_id and offsets in the drawer. Fetch `GET /documents/{document_id}/chunks/{chunk_id}` for context. Render all supplied strings as text, not executable HTML.
4. Render allegations, source statements, findings, and inferences distinctly using fact.assertion_type. `completed_with_warnings` is a successful report requiring visible warnings. A failed/cancelled job must not display empty findings as a clean review. LLM interpretation checks can still be wrong; exact source span validation does not establish legal truth.
5. `GET /review/config` reports model readiness. The browser never calls Ollama, LM Studio, or a hosted model API directly. Server endpoints and API keys stay on the backend. Cloud and local deployments expose the same frontend routes.
6. Legal Drafting endpoints are now implemented; see legal-drafting.md for intake wrappers, edit verification and training consent. Legal Research and RAG Chat remain subsequent work; disable those launch buttons until delivered. Shared document search is not the full Legal Research workflow.

The running `/openapi.json` documents request schemas and routes. `integration/contracts.json` contains the authoritative Pydantic output schemas for ReviewReport and citation/claim types (FastAPI's generic envelopes do not currently infer these output schemas). Use those schemas rather than fabricating sections.

## Authentication and hosting boundary

Configure `BACKEND_CORS_ORIGINS` with exact SPA origins, comma separated. Preflight supports Authorization, Idempotency-Key and Last-Event-ID. Browser sessions require a backend-issued tenant token; neither CORS nor a tenant name authenticates a user. Existing offline session issuance supports development and acceptance testing. Production account login/SSO and automated session renewal still need an agreed identity provider; do not put shared administrative credentials in the SPA. The loopback demo session endpoint is disabled in cloud containers.

Deploy the backend behind HTTPS with a persistent data volume and separately managed encryption key. Disable reverse-proxy SSE buffering and allow long-running streams. Configure request limits above 25 MB per file. See `cloud-deployment.md` for the server deployment package and current operational limits.

Legal Drafting handoff: [workflow API and operational boundaries](legal-drafting.md). Its requirements response wraps the list in `items`; PATCH answer values are strings. `job.completed` for intake does not mean a document has been generated. Inspect the returned resource status.


## 2026-10-08 screenshot integration update

Legal Research backend and local preview are now implemented. See [screenshot field mapping and current limitations](research-and-screenshot-integration.md) and [corpus / training preparation](corpus-and-training.md). Earlier statements marking the research API as planned are superseded by this update; external legal databases, citator analysis and large-corpus infrastructure remain unfinished.
