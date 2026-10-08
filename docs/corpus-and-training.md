# Corpus ingestion and later training

Four independent workflow model slots are review, drafting, research and chat. All four workflows have implemented inference pipelines. Each slot can point to a separately fine-tuned base model or adapter
hosted by a schema-compatible service. They initially share base weights by default.
This repository does not yet implement generative fine-tuning or distributed training.
The existing classifier trainer is a different, smaller training task.

Uploading Indian statutes, judgments and case documents supplies **retrieval evidence**.
It does not automatically train weights. Training needs curated input/output examples,
human approval, explicit consent, a compatible base-model licence, compute, held-out
evaluation and versioned deployment. Review/drafting/research/chat expose approved JSONL
examples through `/api/v1/models/{workflow}/dataset?format=sft`. Withdraw consent by
posting feedback with `use_for_training:false`. Source deletion removes dependent
examples and reports. Previously downloaded exports or trained external weights cannot
be recalled by this API; those need separate dataset/model retention controls.

## Dataset manifest

Use one JSON object per line, with paths relative to the manifest:

```json
{"path":"laws/example.pdf","metadata":{"corpus_id":"indian-primary-law","corpus_version":"2026-10-08","document_type":"statute","jurisdiction":"IN","title":"Verified source title","source_url":"https://official-source.example/document","effective_from":"2020-01-01","retrieved_at":"2026-10-08","licence":"Record actual reuse terms","language":"en"}}
```

For judgments include `court`, `decided_at`, `neutral_citation` and source provenance.
Use ISO dates. Preserve amended/repealed versions as separate documents with
`effective_to`, `supersedes` and a stable external source identifier. Metadata is
uploader-provided, not verified proof of current law. The current research filter
uses jurisdiction, court and decision/effective-start date; it does **not** certify
amendment history, treatment or temporal applicability. Keep those limitations visible.
Case documents should record access permissions and provenance; do not share them
between tenants. Corpus permission and training consent are separate controls.

`python -m scripts.ingest_corpus manifest.jsonl` validates sequentially with bounded
hashing memory. Set `CORPUS_API_TOKEN` and add `--execute --base-url https://backend.example`
to import through normal authenticated uploads and parsing. An append-only ledger
supports reruns; idempotency prevents duplicate uploads after interruptions. Never
put tokens in manifests. Files remain limited to 25 MB and 150 PDF pages; split large
sources into traceable parts. Archive original manifests and hashes outside this app.

## Scale boundary

The current implementation is a single-worker prototype: encrypted SQLite, local
blobs, in-memory BM25/LSA indexing, 200 documents / 500 MB per tenant and 30-day default
retention. The importer obeys those limits. It is **not** certified for millions of
documents or bulk model training, and increasing quotas alone will not solve scaling.
Before a large import, implement object storage, indexed metadata in PostgreSQL,
persisted hybrid/vector indexes, asynchronous ingestion queues with bounded workers,
deduplicated immutable corpus versions, permission-filtered retrieval, temporal-law
resolution and backup/restore. Select retention explicitly before importing a durable
law corpus. Keep training snapshots and held-out case groups separate from live retrieval.
Measure quality on Indian legal questions and amended-law cases before activating any
trained model. Dataset volume and expected concurrency determine infrastructure sizing.
