# Full paired evaluation — 9 October 2026

Completed **52/52 query/arm pairs**: all 13 dataset queries, four arms, no query limit.
Generation failures: **15**. Unjudged claims: **0**. Context identity across arms was verified for every query.

Completion means every requested pair has a recorded outcome; it does not mean every model call succeeded. Daily provider quotas prevented a fully successful comparison. Failures count as non-answers and cannot demonstrate correct abstention or safety. The numeric-guard ablation is inconclusive when its model calls fail.

## Configuration

| Role | Provider | Model |
|---|---|---|
| Baseline | Groq | openai/gpt-oss-120b |
| System generator | Groq | qwen/qwen3.8-27b |
| Verifier | Groq | openai/gpt-oss-20b |
| Independent judge | Gemini | gemini-3.1-flash-lite |

Dataset: `evaluation\datasets\public_dev.jsonl`. SHA-256: `507ec904e7b146acb29de086b7b77330c93a6d2418c9e8da26378df865795335`.
Retriever: `hybrid`. Shared source-text budget: **6000 characters**. Document metadata was deduplicated without removing excerpts, evidence IDs or metadata.
Hosted Qwen was selected by the user because the laptop lacked enough free RAM for the original local 4B generator. These measurements do not establish local-model performance.

The 120B daily token quota was exhausted during the earlier run. With user approval, both verified arms were rerun using GPT-OSS 20B. The completed 120B baseline and unverified Qwen arm were retained from that earlier run. Dataset hash, query IDs, retrieval, shared budget, generator, judge and retrieved chunk IDs match; metrics were recomputed from the 52 measured pairs. See metrics.json provenance for source runs.

## Main findings

System groundedness: **94.4%**; baseline: **100.0%**. These scores are conditional on claims that were emitted and judged.
Answer coverage: system **80.0%**, baseline **100.0%**. Correct abstention on unanswerable queries: system **0.0%**, baseline **100.0%**.
Observed fabricated claims in the full system: **0** across **27** emitted claims.
No full-system fabrication was detected among the emitted claims in this finite run; quota failures prevent certifying successful behavior on every query, and this is not a guarantee for unseen documents.
The system answered fewer answerable questions than the baseline and had lower conditional groundedness. Its three failures were the unanswerable queries, so abstention performance could not be measured successfully with this verifier quota.
The system did not improve conditional groundedness over the baseline on this run.

## Measured results

# Evaluation results: evaluation\datasets\public_dev.jsonl

Queries: 13 | split: all | default retriever: hybrid | judge: gemini-3.1-flash-lite

Shared source-text budget: 6000 characters per query (identical retrieved chunks across arms).

## Split: all

| Arm | Grounded | Strict | Fabricated | Claims | Unjudged | Coverage | Abstain OK | Ctx recall | Failures | Latency s |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 1.000 | 1.000 | 0 | 15 | 0 | 1.000 | 1.000 | 0.900 | 0 | 9.019 |
| system | 0.944 | 0.889 | 0 | 27 | 0 | 0.800 | 0.000 | 0.900 | 3 | 27.201 |
| system_no_verify | 0.944 | 0.889 | 0 | 27 | 0 | 0.800 | 1.000 | 0.900 | 0 | 31.765 |
| system_no_numeric | 1.000 | 1.000 | 0 | 1 | 0 | 0.100 | 0.000 | 0.900 | 12 | 1.969 |

## Split: dev

| Arm | Grounded | Strict | Fabricated | Claims | Unjudged | Coverage | Abstain OK | Ctx recall | Failures | Latency s |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 1.000 | 1.000 | 0 | 8 | 0 | 1.000 | 1.000 | 0.857 | 0 | 10.264 |
| system | 1.000 | 1.000 | 0 | 16 | 0 | 0.714 | 0.000 | 0.857 | 2 | 26.489 |
| system_no_verify | 1.000 | 1.000 | 0 | 16 | 0 | 0.714 | 1.000 | 0.857 | 0 | 31.729 |
| system_no_numeric | - | - | 0 | 0 | 0 | 0.000 | 0.000 | 0.857 | 9 | - |

## Split: heldout

| Arm | Grounded | Strict | Fabricated | Claims | Unjudged | Coverage | Abstain OK | Ctx recall | Failures | Latency s |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 1.000 | 1.000 | 0 | 7 | 0 | 1.000 | 1.000 | 1.000 | 0 | 6.219 |
| system | 0.864 | 0.727 | 0 | 11 | 0 | 1.000 | 0.000 | 1.000 | 1 | 28.864 |
| system_no_verify | 0.864 | 0.727 | 0 | 11 | 0 | 1.000 | 1.000 | 1.000 | 0 | 31.847 |
| system_no_numeric | 1.000 | 1.000 | 0 | 1 | 0 | 0.333 | 0.000 | 1.000 | 3 | 1.969 |

Grounded = (supported + 0.5 x partially supported) / judged claims. Fabricated = cites an unseen source or asserts a
section, citation, case party or number found in no retrieved source (deterministic check) or judged fabricated.

## Why proposed answers were withheld

Failed checks on rejected propositions (a proposition may fail more than one check):

| Arm | Rejection reasons |
|---|---|
| baseline | none |
| system | numeric: 3 |
| system_no_verify | numeric: 3 |
| system_no_numeric | none |

## Diagnosis and fix

The archive contains a later smoke run that reached all 12 selected query/arm pairs despite only one initial baseline judgment. Its subsequent failures were rate limits, local inference timeouts and HTTP 413 request-size errors. The original earlier exit cannot be uniquely reconstructed from the supplied logs; the PowerShell stderr workaround was already present.
This laptop reproduced rate limiting, request-size failures and unavailable/overloaded Gemini models. The fix adds bounded transient retries, progress/checkpoint files, lossless metadata compaction, a shared configurable context budget, working model configuration, and citation-span-aware judge caching. Verification, numeric and authority checks remain enforced in the full system.

## Validation and limitations

- Final full project test suite: 156 passed, with two existing dependency deprecation warnings (Python 3.12.14).
- The dataset is small: 13 queries, including unanswerable cases; inspect the separate dev and held-out tables. No training or prompt tuning was performed on held-out answers.
- The account limit dictated a smaller context budget than the original 18,000-character default. Report the observed context recall; this is not a retrieval-only ablation result.
- The harness tests single-pass generation, verification and guards. It does not measure the complete UI or the production multi-round agent loop.
- Groundedness is weighted across emitted claims, so verbose answers contribute more; it is not the percentage of queries answered correctly. Packet compaction and the shared budget apply to this evaluation harness.
- Mean latency covers successful generation/verification calls, including their retries; failed calls and judging time are excluded. It is not total wall-clock runtime.
- LLM judgments are fallible. Inspect `judgments.jsonl` and exact citations for consequential claims.

Gemini 3.5 Flash was replaced after its 20-request daily free-tier quota was exhausted. This run uses only Gemini 3.1 Flash Lite judgments, a smaller independent judge; its scores are not calibrated against the originally intended stronger judge or human annotations.

## Reproduce

```powershell
.\run-eval.ps1 -ChatProvider groq -ChatModel 'qwen/qwen3.8-27b' -VerifierModel 'openai/gpt-oss-20b' -GeminiJudgeModel 'gemini-3.1-flash-lite' -ContextCharacters 6000 -Out evaluation/runs/paired-full-rerun
```

The command reproduces the configuration as a fresh four-arm run when provider quota is available. This report assembles the two measured source runs described above. Keys are loaded from locally configured environment variables. Machine-readable artifacts: `predictions.jsonl`, `judgments.jsonl`, `metrics.json`, `coverage.json`, and `status.json` in `evaluation/runs/paired-final-20b-20261009/`. Partial diagnostics are in separate directories and are not used as full-run results.

## Repository snapshot

The final machine-readable artifacts are committed under `docs/evaluation-20261009/`. Local runtime caches and raw evaluation run directories are excluded from Git.
