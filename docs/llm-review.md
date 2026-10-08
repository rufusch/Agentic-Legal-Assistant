# Contract and case understanding with a local LLM

The review workflow now accepts arbitrary uploaded contracts and case documents. The filenames in the old preview were demonstration sources, not the intended scope. Upload directly in **Document Analysis**; existing library selection is optional and collapsed by default.

## Run locally

This workspace has a portable CPU Ollama runtime under `.runtime/ollama` and a `qwen3:4b-instruct` model under `.runtime/models`. Both are ignored by Git. The backend calls loopback only. The model is pretrained; this implementation does not claim to have trained a legal specialist.

```powershell
# First setup, or resume a model download:
.\start-local-model.ps1
# Run the application; starts the portable model server if needed:
.\run-local.ps1
```

No API key is needed. Inference sends extracted document text only to the local server. Runtime/model installation downloads official software and weights. The launcher binds Ollama to `127.0.0.1:11434` and sets `OLLAMA_NO_CLOUD=1`. The review adapter rejects non-loopback endpoints and cloud model names. It does not follow redirects, use proxies or let documents invoke tools/URLs.

To use an already running LM Studio server instead:

```powershell
$env:LEXIMIND_REVIEW_LLM_PROVIDER = 'lmstudio'
$env:LEXIMIND_REVIEW_BASE_URL = 'http://127.0.0.1:1234'
$env:LEXIMIND_REVIEW_LLM_MODEL = 'your-loaded-local-model-id'
.\run-local.ps1
```

Use the server root URL, without `/v1`; the adapter appends the route. Ollama uses `/api/chat` with a JSON schema; LM Studio uses `/v1/chat/completions` with `response_format`. Implemented against [Ollama's chat API](https://docs.ollama.com/api/chat) and [LM Studio's structured-output API](https://lmstudio.ai/docs/developer/openai-compat/structured-output). The selected [Qwen model](https://ollama.com/library/qwen3:4b-instruct) is approximately 2.5 GB. Larger capable local models can replace it by changing the review-specific model ID. On this machine inference is CPU-based and can take several minutes per analysis/checking pass.

## Pipeline

1. Upload, validate and store the original encrypted file. Parse PDF/DOCX/TXT or OCR scanned PDF/images. Preserve source chunks, page/section anchors and OCR/partial-page warnings.
2. Assign evidence IDs to contiguous source lines. Preserve the exact text and offsets on the server. Read every supplied source passage in bounded packets, without the old payment/termination keyword filter.
3. Ask the review LLM to classify the packet as contract/case/mixed/other and produce a cited overview, facts, chronology, potential contradictions, information gaps, relevant evidence and review-priority concerns. Case analysis distinguishes allegations, findings and inferences. Conflicts can occur within one document or across files.
4. Reconcile cross-packet source-linked notes when they fit the synthesis budget. Preserve packet findings. If synthesis cannot fit, prominently mark cross-packet comparison incomplete.
5. Reject invented evidence IDs. Resolve valid IDs to exact stored quotes and server-derived offsets. Ask the model in a separate checking pass whether each proposed interpretation is supported by its quoted evidence and context; remove rejected findings. Missing/duplicated verification decisions fail the job.
6. Validate the final typed report, citation references, exact quotes and interpretation-check records before publication. Store model identity/digest, prompt hash, source hashes and coverage. Export the resulting report and retain immutable version history.

Mechanical quote verification establishes provenance, not legal truth. The same LLM performs analysis and its second check, so correlated reasoning errors remain possible. No independent authority database, legal treatment check or certified enforceability determination is connected. Reports state these limits and retain source/OCR warnings.

## Scope and failure behavior

- PDF, DOCX, UTF-8 TXT, PNG/JPEG/TIFF; one document is enough, up to 20 sources per review.
- Up to 120,000 extracted source characters and 16 model packets per run. Oversized scopes fail explicitly; source text is never silently truncated. Structured output limits prioritize findings and may omit issues even when every source passage was read.
- Local model unavailable, invalid structured output, timeout, no supported findings and verification failures have distinct errors. No automatic fallback to the rule engine impersonates an LLM result.
- Job progress/recovery/cancellation, source retention/deletion, tenant isolation and exports remain shared backend services. A job can be reopened from review history. Each model request has a 15-minute cap; cancellation aborts the in-flight HTTP request.
- `GET /api/v1/review/config` shows runtime readiness, provider/model and limits without secrets.

## Later training

The review LLM has its own `LEXIMIND_REVIEW_LLM_MODEL` setting; future workflows should have separate adapters and artifact IDs. An approved, consented review can be exported via `GET /api/v1/models/review/dataset?format=sft`. JSONL records contain system/source messages and source-linked structured targets, model/source provenance and a source-hash group. Feedback without explicit acceptance **and** training consent is excluded. The latest feedback for a report controls eligibility; consent withdrawal removes it from subsequent exports. Previously downloaded copies must be handled separately.

The older `format=classification` dataset and NumPy topic trainer remain auxiliary tools for the explicit legacy extraction mode. They do not train the LLM. Actual LoRA/QLoRA/full fine-tuning, expert labeling, matter-level splits, evaluation and importing the resulting local model are later training operations; no user documents automatically change model weights.
