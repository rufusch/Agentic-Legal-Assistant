# Session handoff — 9 October 2026

The runner fixes and all-pair attempt are complete. Provider quota failures limit the comparison. Read `results.md` and
`docs/EVALUATION-DIAGNOSIS.md` before repeating earlier diagnostics.

- Full run: `evaluation/runs/paired-final-20b-20261009/`.
- Coverage: 52/52 pairs, all 13 queries and four arms.
- Model failures: 15. Unjudged claims: 0.
- System groundedness: 94.4%; baseline: 100.0%.
- Answer coverage: system 80.0%; baseline 100.0%.
- Full-system fabricated claims: 0.
- Final validation: 156 project tests passed.

Models: Groq `qwen/qwen3.8-27b` generator, Groq
`openai/gpt-oss-120b` baseline and `openai/gpt-oss-20b` verifier,
Gemini `gemini-3.1-flash-lite` as the sole independent judge. The user
selected hosted Qwen instead of local 4B due to memory pressure. Shared source
budget: 6000 characters. This is a smaller Flash Lite
judge; do not claim results from Gemini 2.5/3.5/3.8 or local Qwen.

`run-eval.ps1` can load `GROQ_API_KEY` and `GEMINI_API_KEY` from Windows user
environment variables without printing them. No credentials are stored in
source. `.venv` uses Python 3.12.14; Python 3.14 cannot install the pinned OCR
dependency. The unused local service and incomplete weight download were removed.

Changes: lossless document-metadata deduplication in evaluation packets, shared
context budget, bounded transient retries, explicit non-retryable Gemini daily
quota errors, progress/checkpoint files, unjudged-claim reporting, and judge
cache keys that distinguish quoted spans/questions. Guard checks were preserved.

The original earlier one-claim exit cannot be uniquely reconstructed from the
supplied logs. Historical smoke artifacts actually contain 12 completed pairs
with rate limits, local timeouts and request-size failures. New runs reproduced
rate limits and HTTP 413. Gemini 2.5 is unavailable to new users, 3.8 was
overloaded, and 3.5 exhausted a 20-request daily quota. Interrupted diagnostics
remain separate and are not full-run results.

Remaining research work: evaluate more independent documents, audit rejection
reasons and conditional groundedness versus answer coverage, and measure the
production multi-round agent loop/UI separately. Do not tune on held-out
answers. This continuation did not certify zero fabrication on unseen inputs
or complete the unrelated UI/corpus/training loose ends in the old handoff.

Provenance: baseline and system_no_verify reuse completed measured checkpoints from paired-full-gemini31-20261009; both verified arms come from verified-20b-20261009. The latter encountered 15 provider failures (3 system, 12 no_numeric), so numeric-guard ablation is inconclusive. All emitted claims were judged. No failure is a successful abstention. Source runs and assembly/audit scripts are preserved with the final artifacts.
