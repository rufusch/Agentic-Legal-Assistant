# Auxiliary topic classifiers and later training

**Updated:** Review now runs a real local LLM by default. See [LLM review](llm-review.md) for its configuration and consented SFT export. The classifier instructions below apply to the optional legacy extraction engine (`LEXIMIND_REVIEW_ENGINE=extractive`), not to LLM fine-tuning.

Each workflow has its own model instance, label set, artifact path and version: `review`, `drafting`, `research`, `chat`, `novelty`. See `backend/models/registry.py`. No shared mutable weights or cross-workflow activation is used. Review and Legal Drafting execution and approved SFT export now exist. Research and RAG Chat remain planned; their independent datasets will be implemented with those workflows. See legal-drafting.md for generative-model training limitations.

The legacy review model is a deterministic source-extractive baseline. A trained artifact replaces its topic classifier; it does **not** become a trained legal reasoning or generative model. Exact-span verification remains mandatory. Legal quality and authority validity need separate evaluation. The implemented local generative adapter satisfies a versioned report schema, exact source-span gate and model-based interpretation check before publishing output.

## Collect approved labels

`POST /api/v1/reviews/{id}/feedback` accepts `accepted`, `use_for_training` (defaults false), and `annotations`. Each annotation contains `chunk_id`, absolute `start_offset`, `end_offset` and a label from `GET /api/v1/models`. The server extracts the exact selected text; arbitrary training text cannot be submitted through this endpoint. Labels are user assertions, not independently certified expert judgments.

Only feedback explicitly marked both accepted and consented is included in authenticated `GET /api/v1/models/review/dataset`. Export is tenant-scoped JSONL, carrying model version, report/source provenance and file-hash groups. Deleting a source removes dependent reports and feedback. Previously downloaded datasets remain the operator's responsibility; keep them private and apply the same deletion policy.

## Train offline

```powershell
.\.venv\Scripts\python -m backend.models.train --workflow review --dataset datasets/review.jsonl --version review-v1 --output models/artifacts/review-v1.json
$env:LEXIMIND_REVIEW_MODEL = (Resolve-Path models/artifacts/review-v1.json)
.\run-local.ps1
```

Use `LEXIMIND_DRAFTING_MODEL`, `LEXIMIND_RESEARCH_MODEL`, `LEXIMIND_CHAT_MODEL`, and `LEXIMIND_NOVELTY_MODEL` for the other independent artifacts. Restart the backend to activate a deliberately selected artifact. Training never deploys automatically or overwrites an artifact. Each artifact records dataset SHA-256, labels, version and held-out accuracy.

The trainer requires at least three independent provenance groups, two represented training labels, matching workflow, explicit approval and consent. It holds out complete source groups and rejects identical text assigned to different groups. Group related matters/documents together when preparing datasets: file hashes alone cannot detect semantic duplicates or documents from the same matter. Evaluate with representative expert-labeled data before activation; small synthetic fixtures only prove the training mechanism works.

No user data trains a model automatically. No external model/API receives documents. The current training implementation is a local hashed-feature softmax classifier; generative fine-tuning is a later implementation, not an implemented capability.
