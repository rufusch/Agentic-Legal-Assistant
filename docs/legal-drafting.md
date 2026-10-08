# Legal Drafting — Part 3 / Workflow 2

The implemented workflow follows the supplied frontend/backend contract and retains the display name **Legal Drafting**. Antigravity owns the production UI; the local preview is an acceptance interface.

## User flow and APIs

1. `POST /api/v1/drafts`: document_type, jurisdiction, instructions, facts, optional court/supporting_document_ids/preferences. Returns 202 with draft_id, job_id and events_url. Built-in intake templates cover bail_application, petition, notice, affidavit and contract_clause; other types use a general intake template. English output is currently supported; unsupported languages are rejected rather than silently ignored.
2. The durable requirements job produces an explicit template checklist. `GET /drafts/{id}/requirements` returns `{draft_id,status,items,missing_requirement_ids}`. This is a drafting-intake checklist, **not** a model-certified jurisdictional filing checklist. Values already supplied under matching facts keys are populated. Free-text facts and supporting documents are read during generation; they are not automatically converted into confirmed answers by the initial checklist. The model may identify additional gaps during drafting as explicit placeholders.
3. `PATCH /drafts/{id}/requirements` accepts `{answers:[{requirement_id,value}]}`. Answer values are strings; supplied facts remain user assertions. Save answers before generation. Unresolved jurisdiction/instructions block generation. Other fields can remain blank only when `POST /drafts/{id}/generate` includes `proceed_with_missing_information:true` and every missing id in acknowledged_requirement_ids. Unknown facts are retained as visible placeholders.
4. Generation runs retrieval → drafting → verification using shared tenant documents, retrieval, encrypted storage and durable jobs. Subscribe with the authenticated fetch-SSE client or poll GET /jobs/{id}. Snapshot and terminal states must be handled. The intake job completes while the resource can remain awaiting_information; its job.completed event includes resource_status. Cancellation is supported for intake, generation and verification.
5. `GET /drafts/{id}` returns the contract's sections/blocks, claims, citations, authorities, confidence, warnings and unresolved_placeholders. Additive fields distinguish fact/legal/draft_language/placeholder, verification status, retrieval scope, model version and whether edits require verification. Every published factual/legal block has a claim and exact source citation. Plain proposed requests/signature labels can be draft language without claiming source-established facts.
6. `PATCH /drafts/{id}/sections/{section_id}` takes `{text,base_version}`. Replaces that section with an explicitly unverified user-edit block, removes its inherited claims/citations and increments the version. Stale writes return 409 VERSION_CONFLICT. `POST /drafts/{id}/verify` grounds edited text without rewriting it, then checks each block. Unsupported text is replaced with an explicit verification placeholder in the new version; the previous edited version remains in history. If the model changes text during grounding, publication fails.
7. `GET /drafts/{id}/versions` exposes immutable snapshots. `GET /drafts/{id}/export?format=docx|pdf|txt` blocks incomplete/unverified content and labels successful exports WORKING DRAFT — HUMAN REVIEW REQUIRED. Citations and remaining warnings/placeholders are included.

Use `integration/api-client.js` with a configurable backend origin and session-token callback. The running OpenAPI document covers request routes; `integration/contracts.json` includes full LegalDraft and request schemas. Existing v1 envelopes, CORS, idempotency and bearer ownership checks apply. Supporting uploads use the common parser/OCR APIs.

## Grounding boundaries

- User facts/instructions/answers become an immutable encrypted intake source for each generation. Citations to that source identify user-provided assertions, not independently proven facts. Its retention follows the shared document policy and it can be downloaded/inspected in the source drawer.
- Case evidence comes from selected ready tenant documents. Governing-law candidates are statute/judgment sources in the same tenant library with exact jurisdiction or national-parent jurisdiction metadata. Unknown/mismatched jurisdiction is not treated as governing authority. Similar uploaded past_draft documents are style examples only; their facts and legal propositions cannot be cited as evidence. Previous generated drafts are not automatically reused without an explicit curated corpus.
- Retrieval selects relevant excerpts within a 24,000-character evidence budget. Scope/counts are returned; this is not exhaustive legal research. It does not query an external legal database, certify source authenticity, establish case treatment, or determine current law. Absent authorities produce visible warnings/placeholders rather than invented citations.
- JSON-schema generation is followed by a separate block-level support/classification pass. Unknown source IDs, uncited factual/legal blocks, unsupported interpretations and missing/duplicate verification decisions cannot publish unchecked propositions. The final mechanical gate checks every claim/citation link and exact stored source span.
- This does **not** prove “zero hallucinations.” The support checker is the same model and can repeat mistakes. Human legal review and a successful deployment-model acceptance run are required. Confidence is about source support, not probability of legal success or filing compliance.

## Independent model and training

Drafting has its own model instance, workflow identity, prompt/schema versions and activation settings:

```text
LEXIMIND_DRAFTING_LLM_PROVIDER=ollama|lmstudio|compatible
LEXIMIND_DRAFTING_BASE_URL=http://private-model:11434
LEXIMIND_DRAFTING_LLM_MODEL=your-drafting-model-or-adapter-id
LEXIMIND_DRAFTING_API_KEY=server-secret-if-required
```

Unspecified connection settings inherit the deployment's server-side model connection, while the drafting instance remains independent of review. Different fine-tuned model IDs can be activated independently. Cloud/local transport rules are shared; cloud users need only a browser.

By default the workflow slots share the same base model weights while using separate instances, prompts and activation settings. This is not four independently trained weight sets. Later fine-tuned artifacts/adapters can replace each slot separately. Ollama CPU allocation defaults to the model server's choice; optional LEXIMIND_MODEL_NUM_THREADS overrides it. The local preview runner sets two threads unless overridden, which was slow in the live smoke test.

`POST /drafts/{id}/feedback` accepts accepted, use_for_training (default false) and base_version. Only an explicitly approved, consented, checked **current version** enters `GET /models/drafting/dataset?format=sft`. Later consent revocation or edits exclude it from subsequent exports. Targets are reconstructed from sanitized published blocks, never rejected candidate text. Source hashes, version and workflow provenance permit grouped evaluation splits. Deleting a source removes dependent drafts, versions, jobs, feedback and training records. Previously exported copies must be handled by the operator's data policy.

All four workflow models are designed to support separate later fine-tuning: Contract / Case Review, Legal Drafting, Legal Research, and RAG Chat. Trainable open-weight models require compatible licences, hardware and a chosen fine-tuning toolchain; hosted model fine-tuning depends on provider support. Review and drafting have SFT export now; research/chat collectors will be implemented with those workflows. The existing hashed classifier trainer trains an auxiliary classifier, **not** the generative LLM. No claim is made that the four LLMs have already been trained or that every hosted model supports fine-tuning.
