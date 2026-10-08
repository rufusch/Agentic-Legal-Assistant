# Frontend–Backend Contract for Legal AI Workflows

Version: `1.0-draft`  
API base path: `/api/v1`  
Transport: HTTPS JSON; Server-Sent Events (SSE) for progress and streamed text  
Date/time format: ISO 8601 UTC  
Identifier format: UUID  

## 1. Purpose and ownership split

This contract separates the product into four independently implementable workflow modules:

| Part | Workflow | Frontend owns | Backend owns |
|---|---|---|---|
| 1 | Contract / Case Review | Document selection, focus input, progress, structured report views | Evidence extraction, contradiction/missing-info analysis, risk report, verification |
| 2 | Legal Drafting | Draft setup wizard, missing-info form, editor, warning display | Requirement analysis, legal retrieval, grounded drafting, citation verification |
| 3 | Legal Research | Research form, filters, memo reader, authorities/source explorer | Query decomposition, authority retrieval, synthesis, conflict analysis, verification |
| 4 | RAG Chat | Conversation UI, uploads, source drawer, retry/stop controls | Turn retrieval, grounded streaming response, history summarization, verification |

The shared document and job APIs below are built once and used by all four parts.

## 2. Global rules

### 2.1 Authentication and tenancy

- Every request requires `Authorization: Bearer <token>`.
- Every resource is tenant-scoped on the backend. The frontend must never send or trust a tenant ID.
- The backend must return `404`, not `403`, when a resource exists in another tenant.
- Idempotent create requests accept `Idempotency-Key`.

### 2.2 Standard response envelope

Successful non-streaming responses:

```json
{
  "data": {},
  "meta": {
    "request_id": "uuid",
    "api_version": "v1"
  }
}
```

Errors:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "A human-readable summary.",
    "field_errors": [
      { "field": "focus_question", "message": "Must be 2,000 characters or fewer." }
    ],
    "retryable": false,
    "request_id": "uuid"
  }
}
```

Common status codes: `400` invalid input, `401` unauthenticated, `404` unavailable resource, `409` invalid state/idempotency conflict, `413` upload too large, `422` supported request but insufficient/invalid content, `429` rate limited, `500` internal failure, `503` dependency unavailable.

### 2.3 Shared enums

```ts
type WorkflowType = "review" | "drafting" | "research" | "chat";
type JobStatus =
  | "queued" | "parsing" | "indexing" | "understanding"
  | "retrieving" | "reranking" | "generating" | "verifying"
  | "completed" | "completed_with_warnings" | "failed" | "cancelled";
type ConfidenceLevel = "high" | "medium" | "low" | "unavailable";
type VerificationStatus = "supported" | "partially_supported" | "unsupported" | "contradicted";
type DocumentStatus = "uploading" | "processing" | "ready" | "failed";
```

### 2.4 Evidence and citation model

Every factual output uses the same citation object. UI labels such as `[S1]` are display labels, not database IDs.

```ts
interface Citation {
  id: string;
  label: string;                    // e.g. "S1"
  document_id: string;
  document_name: string;
  chunk_id: string;
  page?: number;
  section?: string;
  paragraph?: number;
  start_offset?: number;
  end_offset?: number;
  quoted_text: string;              // exact supporting span
  source_url?: string;
  jurisdiction?: string;
  court?: string;
  decided_at?: string;
}

interface VerifiedClaim {
  id: string;
  text: string;
  citation_ids: string[];
  verification_status: VerificationStatus;
  confidence: number;               // 0..1
  warning?: string;
}

interface Confidence {
  score: number;                    // 0..1
  level: ConfidenceLevel;
  explanation: string;
}
```

Backend invariants:

- A factual claim is returned as final only when it has at least one valid citation and is `supported` or explicitly marked `partially_supported`.
- Unsupported generated claims are removed from user-facing prose or returned only inside `warnings`.
- Citation IDs referenced in content must exist in the response `citations` array.
- `quoted_text` must be an exact span from the stored source version.
- Contradictory or missing evidence must be stated explicitly; confidence must not hide it.

### 2.5 Shared document API

#### Create an upload

`POST /documents/uploads`

```json
{
  "file_name": "agreement.pdf",
  "content_type": "application/pdf",
  "size_bytes": 184203,
  "sha256": "hex-string"
}
```

Response includes `upload_id`, `document_id`, a short-lived `upload_url`, allowed headers, and `expires_at`. The frontend uploads bytes directly to the returned URL, then calls:

`POST /documents/{document_id}/complete`

```json
{
  "upload_id": "uuid",
  "metadata": {
    "title": "Service Agreement",
    "document_type": "contract",
    "jurisdiction": "IN",
    "document_date": "2026-09-14"
  }
}
```

#### List/select documents

`GET /documents?status=ready&query=&cursor=&limit=25`

#### Document state

`GET /documents/{document_id}`

```json
{
  "data": {
    "id": "uuid",
    "name": "agreement.pdf",
    "status": "ready",
    "media_type": "application/pdf",
    "page_count": 24,
    "ocr_used": false,
    "metadata": {},
    "processing": { "stage": "indexed", "progress": 1 },
    "failure": null,
    "created_at": "2026-10-08T08:00:00Z"
  }
}
```

Supported initial formats: PDF, DOCX, TXT and common scanned-image formats. The backend owns parsing, OCR, structure-aware chunking, metadata extraction, deduplication and hybrid indexing.

#### Source viewer

`GET /documents/{document_id}/chunks/{chunk_id}`

Returns chunk text, neighboring context, page/section anchors and a time-limited document preview URL. The frontend uses this endpoint whenever a citation is opened.

### 2.6 Shared job API and progress stream

All long-running workflows create a job.

- `GET /jobs/{job_id}` — latest snapshot
- `GET /jobs/{job_id}/events` — SSE stream
- `POST /jobs/{job_id}/cancel` — best-effort cancellation

SSE frame:

```text
id: 18
event: job.progress
data: {"job_id":"uuid","status":"retrieving","progress":0.42,"message":"Finding relevant clauses"}
```

Event types:

| Event | Required data |
|---|---|
| `job.snapshot` | Full current job state; sent immediately on connect |
| `job.progress` | `status`, `progress` (0..1), safe user-facing `message` |
| `output.delta` | `target`, `sequence`, `text` for draft/chat streaming |
| `warning.created` | Complete warning object |
| `job.completed` | `result_id`, final status |
| `job.failed` | Safe error code/message and `retryable` |
| `heartbeat` | Server timestamp |

Reconnection: frontend sends `Last-Event-ID`; backend resumes when possible or sends a new `job.snapshot`. The frontend must deduplicate by event ID and `sequence`.

### 2.7 Shared warnings

```ts
interface Warning {
  id: string;
  type: "missing_information" | "contradiction" | "unsupported_claim" |
        "weak_authority" | "ocr_quality" | "partial_processing";
  severity: "info" | "warning" | "critical";
  title: string;
  message: string;
  related_claim_ids?: string[];
  citation_ids?: string[];
  resolvable: boolean;
}
```

## 3. Part 1 — Contract / Case Review

### 3.1 User journey

1. Frontend lets the user select one or more `ready` documents.
2. User optionally supplies a focus question and review settings.
3. Backend runs the shared pipeline with review-specific extraction.
4. Frontend renders the report by section and opens citations in the source viewer.

### 3.2 Create review

`POST /reviews`

```json
{
  "document_ids": ["uuid"],
  "focus_question": "Find contradictions about payment terms and termination.",
  "options": {
    "compare_with_governing_law": true,
    "risk_tolerance": "balanced",
    "jurisdiction": "IN",
    "as_of_date": "2026-10-08"
  }
}
```

Validation: at least one document; all documents must be `ready`; `focus_question` max 2,000 characters. Comparing with law requires jurisdiction or enough source evidence to infer it; an inference must be surfaced for confirmation or warning.

Response: `202 Accepted`

```json
{
  "data": {
    "review_id": "uuid",
    "job_id": "uuid",
    "status": "queued",
    "events_url": "/api/v1/jobs/uuid/events"
  }
}
```

### 3.3 Read review result

`GET /reviews/{review_id}`

```ts
interface ReviewReport {
  id: string;
  status: JobStatus;
  focus_question?: string;
  key_facts: Array<{
    id: string;
    label: string;
    value: string;
    claim_id: string;
    citation_ids: string[];
  }>;
  contradictions: Array<{
    id: string;
    topic: string;
    description: string;
    severity: "low" | "medium" | "high" | "critical";
    sides: Array<{ statement: string; citation_ids: string[] }>;
    legal_effect?: string;
    resolution?: string;
    confidence: Confidence;
  }>;
  missing_information: Array<{
    id: string;
    item: string;
    why_it_matters: string;
    suggested_action?: string;
    severity: "low" | "medium" | "high";
  }>;
  relevant_evidence: Array<{
    id: string;
    title: string;
    summary: string;
    category: "clause" | "fact" | "law" | "precedent";
    citation_ids: string[];
  }>;
  risk_summary: {
    overall: "low" | "medium" | "high" | "critical" | "undetermined";
    rationale: string;
    items: Array<{
      risk: string;
      severity: "low" | "medium" | "high" | "critical";
      likelihood: "unlikely" | "possible" | "likely" | "unknown";
      citation_ids: string[];
    }>;
  };
  claims: VerifiedClaim[];
  citations: Citation[];
  warnings: Warning[];
  confidence: Confidence;
  source_document_ids: string[];
  created_at: string;
}
```

Additional endpoints:

- `POST /reviews/{review_id}/rerun` with changed focus/options; creates a new immutable report version.
- `GET /reviews/{review_id}/versions`.
- `GET /reviews/{review_id}/export?format=pdf|docx|json`.

### 3.4 Acceptance criteria

- Every key fact, contradiction side, evidence item and evidence-based risk links to one or more citations.
- A contradiction must preserve both sides and may not collapse uncertainty into a definitive conclusion.
- Governing-law comparison identifies authority type and effective/as-of date.
- Partial document failures produce `completed_with_warnings`, never silent omission.

## 4. Part 2 — Legal Drafting

### 4.1 User journey and state machine

`setup → checking_requirements → awaiting_information → ready_to_draft → drafting → verifying → completed`

The user can proceed from `awaiting_information` with unanswered non-blocking items. Blocking items prevent generation and explain why.

### 4.2 Start a drafting matter

`POST /drafts`

```json
{
  "document_type": "bail_application",
  "jurisdiction": "IN-MH",
  "court": "High Court of Bombay",
  "instructions": "Prepare an anticipatory bail application.",
  "facts": {
    "applicant_name": "Example Name",
    "case_number": null,
    "allegations": "User-provided facts"
  },
  "supporting_document_ids": ["uuid"],
  "preferences": {
    "language": "en",
    "tone": "formal",
    "include_alternative_clauses": false
  }
}
```

Response returns `draft_id`, `job_id`, and state `checking_requirements`.

### 4.3 Missing-information check

`GET /drafts/{draft_id}/requirements`

```ts
interface DraftRequirement {
  id: string;
  key: string;
  question: string;
  rationale: string;
  required: boolean;
  answer_type: "short_text" | "long_text" | "date" | "number" |
               "boolean" | "single_select" | "multi_select" | "document";
  options?: Array<{ value: string; label: string }>;
  current_answer?: unknown;
  source: "template" | "model_detected" | "jurisdiction_rule";
}
```

Submit answers:

`PATCH /drafts/{draft_id}/requirements`

```json
{
  "answers": [
    { "requirement_id": "uuid", "value": "C.R. No. 123/2026" }
  ]
}
```

Generate:

`POST /drafts/{draft_id}/generate`

```json
{
  "proceed_with_missing_information": true,
  "acknowledged_requirement_ids": ["uuid"]
}
```

Backend returns `409 BLOCKING_INFORMATION_REQUIRED` for unresolved blocking fields. It records explicit placeholders for acknowledged non-blocking gaps rather than inventing values.

### 4.4 Draft result

`GET /drafts/{draft_id}`

```ts
interface LegalDraft {
  id: string;
  status: JobStatus;
  document_type: string;
  title: string;
  sections: Array<{
    id: string;
    heading?: string;
    order: number;
    blocks: Array<{
      id: string;
      kind: "paragraph" | "heading" | "list" | "signature" | "placeholder";
      text: string;
      claim_ids: string[];
      citation_ids: string[];
      editable: boolean;
    }>;
  }>;
  unresolved_placeholders: Array<{
    id: string;
    token: string;                  // e.g. "[DATE OF ARREST]"
    description: string;
    requirement_id?: string;
  }>;
  authorities: Array<{
    name: string;
    citation_ids: string[];
    treatment?: "followed" | "distinguished" | "overruled" | "unknown";
  }>;
  claims: VerifiedClaim[];
  citations: Citation[];
  warnings: Warning[];
  confidence: Confidence;
  version: number;
  created_at: string;
}
```

Editing/version endpoints:

- `PATCH /drafts/{draft_id}/sections/{section_id}` with `{ "text": "...", "base_version": 3 }`.
- `POST /drafts/{draft_id}/verify` re-verifies user-edited content and creates a new version.
- `GET /drafts/{draft_id}/versions`.
- `GET /drafts/{draft_id}/export?format=docx|pdf|txt`.

### 4.5 Acceptance criteria

- Unknown facts appear as visible placeholders, never inferred facts.
- Each factual/legal proposition has citations or a visible verification warning.
- The UI distinguishes user-provided facts, source-supported facts and draft language.
- Export is blocked or watermarked as `UNVERIFIED` when edits have not been re-verified.

## 5. Part 3 — Legal Research

### 5.1 Create research task

`POST /research`

```json
{
  "question": "What precedents govern anticipatory bail under Section 438 in Maharashtra?",
  "context_document_ids": ["uuid"],
  "filters": {
    "jurisdictions": ["IN", "IN-MH"],
    "courts": ["Supreme Court of India", "High Court of Bombay"],
    "date_from": "2015-01-01",
    "date_to": "2026-10-08",
    "source_types": ["statute", "judgment", "secondary"]
  },
  "options": {
    "include_secondary_sources": true,
    "connect_to_case_facts": true,
    "depth": "deep"
  }
}
```

Response: `research_id`, `job_id`, status and events URL.

### 5.2 Research memo result

`GET /research/{research_id}`

```ts
interface ResearchMemo {
  id: string;
  status: JobStatus;
  question: string;
  scope: {
    interpreted_question: string;
    assumptions: string[];
    jurisdictions: string[];
    as_of_date: string;
  };
  sub_queries: Array<{
    id: string;
    question: string;
    status: "completed" | "limited_evidence" | "failed";
  }>;
  executive_summary: { text: string; claim_ids: string[]; citation_ids: string[] };
  legal_framework: Array<{
    heading: string;
    analysis: string;
    claim_ids: string[];
    citation_ids: string[];
  }>;
  key_authorities: Array<{
    id: string;
    case_name: string;
    neutral_citation?: string;
    court: string;
    decided_at?: string;
    proposition: string;
    treatment: "binding" | "persuasive" | "distinguished" |
               "overruled" | "negative_treatment" | "unknown";
    claim_ids: string[];
    citation_ids: string[];
  }>;
  application_to_facts?: Array<{
    issue: string;
    analysis: string;
    fact_citation_ids: string[];
    law_citation_ids: string[];
    confidence: Confidence;
  }>;
  conflicting_authorities: Array<{
    issue: string;
    description: string;
    authority_groups: Array<{
      position: string;
      citation_ids: string[];
    }>;
  }>;
  limitations: string[];
  claims: VerifiedClaim[];
  citations: Citation[];
  warnings: Warning[];
  confidence: Confidence;
  created_at: string;
}
```

Additional endpoints:

- `POST /research/{research_id}/refine` with a follow-up question and optional changed filters; creates a linked memo version.
- `GET /research/{research_id}/search-log` returns safe, user-visible query coverage (not hidden reasoning): sub-query, filters, result count and selected source IDs.
- `GET /research/{research_id}/export?format=pdf|docx|json`.

### 5.3 Authority requirements

- The backend records source type, court, jurisdiction, decision date and available treatment for every authority.
- Primary law is ranked above secondary commentary for legal propositions.
- Secondary sources are labeled and cannot be presented as binding authority.
- If currency or treatment cannot be verified, return `treatment: "unknown"` and a warning.

### 5.4 Acceptance criteria

- Complex questions expose their sub-query coverage to the user.
- Every case proposition links to the precise supporting span, not merely a case landing page.
- Application-to-facts separates fact citations from law citations.
- Conflicting authorities show each position and its sources.

## 6. Part 4 — RAG Chat

### 6.1 Create conversation

`POST /conversations`

```json
{
  "title": "Payment dispute analysis",
  "document_ids": ["uuid"],
  "settings": {
    "jurisdiction": "IN",
    "answer_style": "concise",
    "strict_grounding": true
  }
}
```

Returns `conversation_id`. Documents may be added later:

- `POST /conversations/{conversation_id}/documents` with `{ "document_ids": [...] }`.
- `DELETE /conversations/{conversation_id}/documents/{document_id}` affects future turns only; previous turn provenance remains immutable.

### 6.2 Send a message

`POST /conversations/{conversation_id}/messages`

```json
{
  "content": "When can the supplier terminate?",
  "client_message_id": "uuid",
  "reply_to_message_id": null,
  "document_scope": "conversation",
  "selected_document_ids": []
}
```

Response: `202 Accepted` with `user_message_id`, `assistant_message_id`, `job_id`, and events URL. `client_message_id` makes retries idempotent.

For `document_scope: "selected"`, at least one selected document is required. The backend retrieves using the current message plus an internal conversation summary and relevant recent turns.

### 6.3 Assistant message model

`GET /conversations/{conversation_id}/messages?cursor=&limit=50`

```ts
interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "queued" | "streaming" | "verifying" | "completed" |
          "completed_with_warnings" | "failed" | "cancelled";
  claim_ids: string[];
  citations: Citation[];
  claims: VerifiedClaim[];
  warnings: Warning[];
  confidence?: Confidence;
  answerability?: {
    status: "answerable" | "partially_answerable" | "not_answerable";
    missing_information: string[];
  };
  created_at: string;
}
```

Streaming rules:

- `output.delta` may stream provisional prose.
- The UI displays a `Verifying…` state after the final delta.
- Citations become clickable only after `job.completed`, unless a delta explicitly includes a resolved citation object.
- If verification removes or changes text, `job.completed` includes the canonical final message; frontend replaces the provisional text.
- Stop uses `POST /jobs/{job_id}/cancel` and keeps any response visibly marked `cancelled` and unverified.

### 6.4 Conversation context and branching

- `GET /conversations/{id}` returns settings, active document IDs and summary metadata.
- `POST /conversations/{id}/branch` with `{ "from_message_id": "uuid" }` creates a new conversation preserving provenance up to that turn.
- `POST /messages/{message_id}/retry` creates a new assistant alternative without deleting the original.
- Backend summarization must preserve named parties, dates, holdings, unresolved questions and source references; it must never be used as evidence itself.

### 6.5 Acceptance criteria

- Insufficient evidence produces `not_answerable` or `partially_answerable` plus missing information, not a guessed answer.
- Every completed factual answer includes inline citation labels whose IDs resolve to citation objects.
- Uploading a document mid-chat does not retroactively alter old answers.
- Retry and branch operations keep an auditable relationship to their source message.

## 7. Shared core pipeline contract

Workflow services submit an internal normalized request to the shared pipeline:

```ts
interface CorePipelineRequest {
  workflow: WorkflowType;
  user_query: string;
  document_ids: string[];
  jurisdiction?: string;
  as_of_date: string;
  filters?: Record<string, unknown>;
  retrieval_profile: "review" | "drafting" | "research" | "chat";
  output_schema: string;
  strict_grounding: true;
}
```

The pipeline guarantees these observable stages:

1. Documents are parsed/indexed or rejected before the workflow starts.
2. Intent, entities and legal search variants are recorded for retrieval.
3. Hybrid retrieval applies full-text, dense and metadata filtering.
4. Results are reranked, deduplicated and assembled with provenance.
5. Generation uses only assembled sources.
6. Atomic claims are checked against source spans.
7. Unsupported claims are removed or surfaced as warnings.
8. Final output contains a complete, internally consistent citation list.

Retrieval internals and model reasoning are backend-private. The frontend receives status, coverage, sources and verification outcomes, not hidden prompts or chain-of-thought.

## 8. Frontend implementation rules

- Treat backend resources as immutable snapshots unless an endpoint explicitly supports edits.
- Do not infer completion from `progress === 1`; use the terminal status/event.
- Render low confidence, missing information and contradictions near the affected content.
- Never hide `critical` warnings behind a collapsed panel.
- Preserve citation label-to-ID mapping supplied by the backend.
- Sanitize all generated rich text. Prefer structured blocks over raw HTML.
- Store client draft inputs locally until the create call succeeds; use idempotency keys for retry.
- Poll `GET /jobs/{id}` only when SSE is unavailable, with exponential backoff.

## 9. Backend implementation rules

- Validate ownership and readiness of all supplied document IDs.
- Keep document versions and citation spans immutable for reproducibility.
- Log model/retrieval versions, source IDs, verification results and request IDs for audit, without exposing private reasoning.
- Encrypt stored documents and generated legal work product; use short-lived preview/export URLs.
- Apply retention and deletion policy to documents, derived indexes, reports and audit records.
- Make create/generate/message endpoints idempotent.
- Enforce per-workflow JSON schemas before marking jobs complete.
- Return `completed_with_warnings` whenever usable output exists but evidence or processing is incomplete.

## 10. Suggested delivery split

Each workflow team delivers the vertical slice below. Shared document, source-viewer, job/SSE and citation components should be completed first or mocked against this contract.

| Part | Frontend deliverables | Backend deliverables | Contract tests |
|---|---|---|---|
| Review | Setup + report + source drawer | Review orchestration + report schema | contradiction provenance; partial OCR; rerun versioning |
| Drafting | Wizard + requirements + editor + export | Requirements engine + drafting + reverification | blocking gaps; placeholders; stale-version edit |
| Research | Query/filter form + memo + authority explorer | Decomposition + authority retrieval + memo | conflicting law; treatment unknown; fact/law split |
| Chat | Thread + streaming + uploads + citations | Turn orchestration + context summary + branching | reconnect/dedup; insufficient evidence; mid-chat upload |

## 11. Future workflows (“novelties coming soon”)

New workflows must reuse `Document`, `Citation`, `VerifiedClaim`, `Warning`, `Confidence`, `JobStatus` and SSE event contracts. Add a new workflow namespace and retrieval profile without changing existing enum meanings or response shapes. Breaking changes require `/api/v2`; additive optional fields remain compatible within v1.

## 12. Minimum end-to-end test fixture

All four teams should share one fixture set containing:

- Two contracts with conflicting payment dates.
- One scanned annexure requiring OCR.
- One missing termination schedule.
- One statute and two judgments with conflicting or distinguishable positions.
- One unsupported fact deliberately included in a draft-generation candidate.

The release gate passes only when the unsupported fact is removed/flagged, every surviving factual claim resolves to an exact source span, missing material is visible, and all four workflows recover correctly from an interrupted SSE connection.
