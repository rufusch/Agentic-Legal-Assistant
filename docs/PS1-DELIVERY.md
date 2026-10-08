# CaseLens delivery â€” HNX26EPS01

The user-supplied Hacknex2 interface is retained. The backend implements the four Problem Statement 1 workflows with independent model configurations: Contract / Case Review, Legal Drafting, Legal Research and RAG Chat. Clause Auditor adds a visible, exportable source-integrity audit. It is a deterministic checker, not a fifth trained LLM.

## Start and demonstrate

Windows, from the extracted release directory:

```powershell
.\setup.ps1 -LocalModel
.\run-local.ps1
```

Setup downloads Python packages, the official portable Ollama runtime and Qwen3 4B weights; internet access is required. Python must already be installed. Weights are deliberately excluded from the source ZIP. Open http://127.0.0.1:8000/. Linux/macOS can use `sh scripts/run_local.sh` with Ollama and the configured model installed separately. Hosted deployment is described in [cloud-deployment.md](cloud-deployment.md); browser users do not install models.

1. Open **Case Law & Documents**, load the official starter sources or upload your own documents. Wait for Ready. Inspect a source and browse its extracted passages.
2. **Contract / Case Review** reads selected contracts/case documents and returns source-linked facts, chronology, contradictions, evidence and missing information.
3. **Drafting** runs requirements analysis first. Fill missing fields or explicitly proceed with placeholders. Generate, inspect citations, edit, reverify and export. Edits do not remain silently verified.
4. **Legal Research** takes a question, jurisdiction/court and optional case context. It retrieves tenant statutes/judgments and case facts. A contract is not treated as legal authority.
5. **AI Assistant** runs RAG Chat with conversation history and selected sources. History resolves references but is not evidence.
6. **Start Agent â†’ Clause Auditor** selects a completed output, checks quoted spans/offsets and numeric values, opens original citations and exports JSON. Empty answers have no traceability score.

Demo mode is loopback only. A fresh release contains no user documents, sessions or encryption keys. Model-server configuration and API secrets stay server-side. For public access, provision authenticated HTTPS hosting and the chosen identity integration; cloud deployment has not been performed on this laptop.

## Architecture and grounding

Authenticated upload â†’ bounded parser/OCR â†’ encrypted source storage â†’ page/source-part chunks â†’ BM25 + corpus-fitted LSA retrieval with rank fusion â†’ independent workflow prompt/model â†’ exact quote/offset checks â†’ separate model support check â†’ deterministic numeric-value guard â†’ durable output and citations.

Review analyzes bounded source packets and reconciles them; drafting retrieves facts, authorities and past drafts; research separates authority from factual context; chat persists tenant-scoped conversation and evidence. Untrusted document instructions cannot configure tools or providers. Model requests do not follow source URLs. Failed/cancelled generation publishes no completed unchecked result. Workflow exports and original downloads require tenant authorization.

The numeric guard is a necessary check, not semantic entailment: it cannot establish who paid whom, validate names or determine legal applicability. The support checker can share errors with its generating model. Exact citation integrity is measured separately from truth, legal correctness and usefulness. OCR and legal currency warnings remain visible.

## Evaluation and acceptance

The automated suite covers parsing/OCR, source spans, authentication/tenant separation, encrypted storage, retrieval filters, durable jobs/recovery, cancellation/retry, exports, requirements checks, unsupported-output rejection, chat context, consent-controlled datasets and the auditor. Final measured counts and live runs are recorded in [release-validation.json](release-validation.json).

Real-model runs use an isolated synthetic contract; the initial run and retest are retained, including failures. They are smoke tests, not held-out legal accuracy evaluations. See `release-live-ps1*.json`. Public source import and passage browsing were also exercised through the browser.

`scripts/evaluate_grounding.py` compares paired JSONL predictions on identical queries and sources. It reports retrieval precision/recall, source-span validity, numeric mismatches, answer coverage and independently annotated semantic support/usefulness where available. Missing human annotations remain unknown; this release does not substitute automated citation checks for independent semantic scoring. An empty answer receives no perfect groundedness score. `evaluation/public-queries.jsonl` contains public development inputs; `scripts/compare_live_smoke.py` runs a same-model single-pass RAG baseline against a completed live chat result and a numeric-guard ablation. A completed abstention remains an empty prediction with zero answer coverage.

For the required judging comparison, freeze a stronger available baseline and an unseen query split, collect paired outputs, independently annotate every material claim and usefulness, then run:

```powershell
.\.venv\Scripts\python -m scripts.evaluate_grounding --help
```

The repository does **not** establish victory over a strong baseline on unseen judging queries. Do not present source-traceability percentages as that result. The novelty contribution is the inspectable audit and fail-closed checks; its benefit must be measured with the supplied ablation harness rather than asserted.

## Training and scale

All four model connections can later serve independently fine-tuned weights/adapters through their workflow-specific model settings. Consented, approved examples export as SFT JSONL. Uploading laws supplies retrieval evidence; it does not train weights. This release has no newly trained generative weights or full fine-tuning job. See [corpus-and-training.md](corpus-and-training.md).

This release uses one backend process per encrypted SQLite storage directory: 200 documents/500 MB per tenant, 25 MB/file, 150 pages/file, bounded review context. Huge future datasets require a larger ingestion/index/storage service and a separate training environment. The default CPU model may take minutes and can time out; use a tested GPU/server deployment for interactive demonstrations. No claim is made that every laptop can run the model well.

## Final measured release status

79 automated backend tests passed (115.52 seconds), plus frontend contract tests. Real-model review completed with cited findings, drafting produced one cited payment clause, and research withheld an unsupported statutory conclusion. Chat completed safely but abstained on the simple contract fixture even after attribution changes. This is a remaining model-usefulness defect, not evidence of a successful factual answer. The source release is delivered with that limitation exposed; it is not certified perfected or judging-qualified.
