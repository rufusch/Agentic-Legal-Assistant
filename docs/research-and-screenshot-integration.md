# Legal Research and Document Drafting integration

The supplied Antigravity frontend ZIP has now been integrated. Its active adapters use real authenticated APIs; see [integration notes](antigravity-integration.md) for validation and remaining limitations.

Copy `integration/api-client.js` and `integration/workflow-adapters.js` into the
frontend and import `createApiClient` / `createWorkflowAdapters`. Configure the API
base URL and an authenticated token provider; never place model keys in browser code.
Use `integration/contracts.json` for request and completed-result JSON Schemas.
Requests return `{data,meta}`; the client unwraps `data`. Job starts return 202 and an
`events_url`. Use bearer-authenticated fetch streaming, not native EventSource.

| Screenshot control | Backend mapping |
| --- | --- |
| Document type | `POST /api/v1/drafts`: `document_type`; both `Anticipatory Bail Application` and `anticipatory_bail_application` select the bail checklist |
| Jurisdiction dropdown | `jurisdiction: "IN-MH"`; adapter extracts the code from the displayed screenshot label |
| Court / Authority | `court: "High Court of Bombay"` |
| Instructions & Context | `instructions`; no additional facts field is required to start |
| Supporting checkboxes | `supporting_document_ids`: real ready document UUIDs |
| Analyze Requirements | Create draft → follow job → GET `/drafts/{id}/requirements` |
| Missing-info answers | PATCH `/drafts/{id}/requirements` with `{answers:[{requirement_id,value}]}`; value is a string |
| Generate draft | POST `/drafts/{id}/generate`; explicitly acknowledge each unresolved non-blocking requirement |
| Research Question | `POST /api/v1/research`: `question` |
| Jurisdiction / Court optional input | adapter maps IN codes to `filters.jurisdictions`, court names to `filters.courts`; blank means unrestricted workspace scope |
| Context Documents | `context_document_ids`: optional ready UUIDs |
| Run Research | Create research → follow job → GET `/research/{id}` |

The optional research free-text scope accepts a single court name or jurisdiction code.
Adapter aliases normalize Supreme Court, Delhi High Court and Bombay High Court.
Use a structured jurisdiction/court picker if the frontend must accept multiple values
or natural-language combinations; do not silently guess complex user input.
Document filenames are display labels; they must never serve as IDs or fixture lookups.

Upload through the shared three-step API: create upload, PUT bytes, complete with
metadata, then wait until ready. Set `document_type` to `statute`, `judgment`, `case`,
`contract`, `secondary` or `past_draft` as appropriate. Research only treats explicitly
classified statutes/judgments as primary authority. Set canonical jurisdiction/court
and ISO dates; an active date filter excludes sources whose required date is unknown.
Selected authority checkboxes cannot bypass jurisdiction/court/date filters.

The Docker image includes Antiword text extraction for legacy binary DOC files.
See its [packaged manual](https://manpages.debian.org/testing/antiword/antiword.1.en.html).
Windows preview does not currently have this executable. Read authenticated
`GET /api/v1/documents/capabilities` before advertising DOC support. PDF/DOCX are
supported locally; DOC conversion is implemented but not exercised with a real DOC
fixture in the current environment. DOC images/layout/page numbers are not indexed.

Set `BACKEND_CORS_ORIGINS` to exact frontend origins. The local launcher includes
`http://127.0.0.1:5500` and `http://localhost:5500`; production must use its real HTTPS
frontend origin. Production authentication remains deployment configuration.

Research endpoints also include list, config, search-log, refine, feedback and export
(JSON/DOCX/PDF). Refinement creates a linked new memo without overwriting the original.
Model config uses independent `LEXIMIND_RESEARCH_*` variables. Source deletion cascades
research reports, jobs, feedback and training candidates. Latest consent controls SFT
export eligibility. Original uploads remain unchanged by either workflow.

Research currently searches uploaded workspace data, with 24,000-character excerpt
budget, primary sources before secondary, exact source quotes and offsets, and a
second check by the same model. Unknown citations and unsupported propositions are
omitted; incomplete verification fails the job. With no authority, the result explains
the evidence gap without inventing law. No external legal database, citator, certified
binding-treatment analysis or automated comprehensive conflicting-authorities section
is implemented. The output reserves that section as an empty array; this is a remaining
research capability, not a claim that authorities never conflict. Human review remains
necessary. Actual research model quality/latency and cloud Docker execution are unverified.
