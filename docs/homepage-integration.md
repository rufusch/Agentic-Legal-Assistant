# Homepage and review integration

The supplied screenshot is a visual reference; its original frontend source was not provided. The local preview follows its burgundy/cream LexiMind layout and calls the actual authenticated APIs. An existing frontend can use these mappings without sharing this preview's HTML.

| Homepage control | Backend / behavior |
|---|---|
| Tenant/user label | `GET /api/v1/home`: `tenant`, `user`; server-resolved tenant; optional `BACKEND_USER_DISPLAY_NAME` deployment label |
| Document badge/statistics | `document_counts`, `storage_bytes`, `retention_days` from `/home` |
| Recent activity | `/home.recent_activity`, tenant-scoped audit entries |
| Notifications | `/home.notifications`; `POST /notifications/{job_id}/read` |
| Global search | `POST /documents/search`; uploaded corpus only |
| Start query / Document Analysis / Clause Auditor | `POST /reviews`, then job status or SSE and `GET /reviews/{id}`; clause audit can supply a focus question |
| Case Law & Documents | Existing upload/library/source-viewer APIs |
| Drafting / full legal research / AI Assistant / autonomous agent | Upcoming; use `/home.workflows[].available`, never call a fabricated backend |

All paths are under `/api/v1`. Pass a bearer session, never a client-supplied tenant ID. The screenshot's Daniel Smith/Apex labels are not authentication data. The local preview uses its actual local tenant instead.

Review creation returns 202 with review/job IDs and `events_url`. Every source must be ready and owned by the session. Upload contracts/case files directly in Contract / Case Review; the local LLM reads the parsed sources. A focus question prioritizes analysis. See llm-review.md for provider setup and limits. Poll jobs or consume the existing authenticated SSE endpoint. Reports include facts, two-sided potential conflicts, explicitly absent material, evidence, warnings, risk priority, model version and exact source citations.

`POST /reviews/{id}/rerun` creates a new report. `GET /reviews/{id}/versions` lists its lineage. POST endpoints support Idempotency-Key. Exports support JSON/DOCX/PDF via authenticated `GET /reviews/{id}/export?format=...`; pending/failed/cancelled reports cannot be exported. Citation controls resolve through the existing document/chunk API.

Current limits: local model reasoning can be wrong; a second pass of the same model is not independent legal verification. No external authority database, treatment/currency certification, identity provider or calibrated legal-risk model is included. Source/OCR and limited cross-packet comparison warnings remain visible. See llm-review.md for exact scope, model setup and later SFT export.
