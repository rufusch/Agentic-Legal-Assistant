# Legal AI Frontend Implementation Plan (6 Parts)

Based on **`frontend-backend-contract_24.md`** (API base path `/api/v1`), the frontend is divided into 6 vertical milestones:

---

## 🏛️ Part 1: Homepage / Common Workflow (Active Focus)
*The shared foundation that all four legal workflows and the novelty workflow rely upon.*
- **Global App Shell & Navigation**:
  - Executive legal dark/light theme (navy, deep slate, gold accents, crisp typography).
  - Primary navigation with matter overview, workflow tabs, active job monitoring indicator, and tenant security status.
- **Shared Document Management (`/documents`)**:
  - Document library with filter (`status=ready`, search query, type).
  - Two-step upload wizard: `POST /documents/uploads` (file name, type, SHA256) -> direct payload upload -> `POST /documents/{id}/complete` with legal metadata (title, jurisdiction, document type, date).
  - Real-time document parsing/indexing simulation with OCR badges.
- **Shared Job & SSE Streaming System (`/jobs`)**:
  - Event stream listener with reconnect handling, `Last-Event-ID`, sequence deduplication, heartbeat monitoring, and cancellation control (`POST /jobs/{id}/cancel`).
  - Stage progress tracker (`queued` → `parsing` → `indexing` → `understanding` → `retrieving` → `reranking` → `generating` → `verifying` → `completed`).
- **Universal Source Drawer / Citation Viewer**:
  - Interactive right-side slide-over drawer triggered by clicking any citation badge (e.g., `[S1]`, `[S2]`).
  - Queries `GET /documents/{document_id}/chunks/{chunk_id}` to render exact highlighted `quoted_text`, neighboring context, page/section anchors, and document preview.
- **Shared Legal Primitives**:
  - `VerifiedClaim` badge and popup inspector (supported, partially supported, contradicted).
  - `Confidence` meter (score 0..1, explanation popover).
  - `Warning` banners with rule enforcement (critical warnings never collapsed).
- **Section 12 Test Fixtures**:
  - Preloaded initial legal bundle (Conflicting payment terms contracts, scanned annexure, CrPC/BNSS statutes & precedents).

---

## 📑 Part 2: Workflow 1 — Contract / Case Review
- Document multi-selection picker (filtered to `ready` documents).
- Review setup form: Focus question (max 2,000 chars), risk tolerance slider, governing law comparison toggle with jurisdiction specification.
- Structured Review Report reader (`GET /reviews/{id}`):
  - **Key Facts**: Table with verified claim IDs and source citations.
  - **Contradictions**: Dual-sided side-by-side card preserving both positions without collapsing uncertainty, severity tags, and legal effect notes.
  - **Missing Information**: Highlighted cards with "why it matters" and recommended actions.
  - **Risk Summary**: Overall risk dial + granular risk items with likelihood and citation links.
  - **Relevant Evidence Explorer**: Filter by clause, fact, law, precedent.
- Version history (`GET /reviews/{id}/versions`) and Rerun trigger (`POST /reviews/{id}/rerun`).
- Multi-format Export modal (PDF, DOCX, JSON).

---

## ✍️ Part 3: Workflow 2 — Legal Drafting
- Matter setup wizard (`POST /drafts`): document type (e.g., bail application, commercial agreement), jurisdiction, court, facts, preferences.
- Missing Information Engine:
  - Requirements list (`GET /drafts/{id}/requirements`) with blocking vs non-blocking indicators.
  - Inline input fields for short text, date, select, documents.
  - Acknowledgment modal for non-blocking gaps before triggering generation (`POST /drafts/{id}/generate`).
- Structured Legal Editor (`GET /drafts/{id}`):
  - Structured section and block renderer with paragraph, heading, signature, and explicit `[UNRESOLVED_PLACEHOLDER]` tokens.
  - Inline claim citations and warnings.
  - Inline editing with version tracking (`base_version` concurrency control).
  - Re-verification action (`POST /drafts/{id}/verify`) & unverified export watermarking.

---

## 🔍 Part 4: Workflow 3 — Legal Research
- Research query builder (`POST /research`): legal question, context documents, court/jurisdiction filters, date ranges, depth selector.
- Search execution & Sub-query coverage visualizer: safe sub-query breakdown (`completed`, `limited_evidence`, `failed`).
- Comprehensive Research Memo Reader (`GET /research/{id}`):
  - Executive summary with claims and citations.
  - Legal framework hierarchy with statutory and case interpretations.
  - Key Authorities table with treatment tags (`binding`, `persuasive`, `distinguished`, `overruled`, `unknown`).
  - Application to Facts: distinct separation of fact citations from law citations.
  - Conflicting Authorities comparison matrix.
- Query refinement (`POST /research/{id}/refine`) and Search Log inspection (`GET /research/{id}/search-log`).

---

## 💬 Part 5: Workflow 4 — RAG Chat
- Conversation workspace (`POST /conversations`): topic title, active documents scope, strict grounding switch.
- Streaming turn experience:
  - Streaming prose (`output.delta`) with visible `Verifying...` transitional phase.
  - Citation tags `[S1]` enabled only after verification completes or delta resolves.
  - Stop button (`POST /jobs/{id}/cancel`) visibly marking cancelled turns.
- Answerability analyzer: clear callouts for `not_answerable` and `partially_answerable` states with missing evidence list.
- Provenance controls: Conversation branching (`POST /conversations/{id}/branch`) and Turn retry (`POST /messages/{id}/retry`).
- Mid-chat document upload without corrupting past turn provenance.

---

## ⚡ Part 6: Novelty Workflow — Regulatory & Cross-Jurisdictional Cross-Auditing
- Cross-regulatory Compliance & Multi-Jurisdictional Sanctions / Clause Comparator.
- Fully reuses Section 11 core contracts: `Document`, `Citation`, `VerifiedClaim`, `Warning`, `Confidence`, and SSE job pipeline.
- Matrix comparison of clauses across multi-state or cross-border rules (e.g., DPDP Act vs GDPR vs CCPA) with claim verification.
