# Paired evaluation investigation — 2026-10-09

## Evidence from the portable source

The remote `developments/hackathon-final/HANDOFF.md` describes an earlier
attempt with one judge-cache entry and no final paired artifacts. The archive
contains a later `evaluation/runs/smoke/` with 12 predictions: three queries
across four arms. That smoke run reached the end of the loop. Its existence
does not establish what terminated the earlier attempt.

The archived smoke predictions show:

- Baseline: one successful claim, followed by two rate-limit errors.
- System: three generator timeouts.
- System without verification: three successful predictions; generation took
  114–364 seconds per query.
- System without numeric guard: three HTTP 413 errors from Groq.

These are historical artifacts supplied with the project, not new measurements
on this laptop. They are not a full paired evaluation or an independent-judge
result. PowerShell stderr handling was already patched in the supplied launcher.

## Implemented changes

- Evaluation clients retry rate limits and transient HTTP 500/502/503/504 errors up to three times with 15/30/60-second
  waits. Authentication, request-size and generation-timeout errors remain
  explicit failures, rather than being repeatedly retried.
- Structured Gemini daily-quota errors are non-retryable and explicitly labeled.
- Generator/verifier payloads retain every excerpt, source ID and all metadata.
  Document metadata is sent once and referenced by document ID on each excerpt.
  A regression test reconstructs the original packet exactly.
- Progress is printed before generation and judging. Completed query/arm pairs
  are appended to `progress.jsonl`. `status.json` distinguishes interrupted
  and completed runs and records expected/completed pair counts.
- Results tables expose unjudged claims alongside generation failures.
- Judge-cache keys include the question, judging prompt and exact quoted spans,
  preventing a cached judgment from leaking across differently cited claims.
- The launcher resolves paths from its own folder and can load keys saved in
  Windows user environment variables after the parent terminal started.

## Local setup

The laptop's default Python 3.14 cannot install pinned
`rapidocr-onnxruntime==1.4.4` (requires Python below 3.13). The project virtual
environment was rebuilt using the bundled Python 3.12.14 runtime. Original
dependency pins were preserved.

## New live findings on this laptop

- Groq and Gemini authentication/model listing succeeded using locally saved
  user environment variables. Keys were not printed or written into source.
- A three-query Groq baseline diagnostic reproduced a rate limit; the retry
  recovered and all three generations completed.
- Gemini 2.5 Flash inference returned HTTP 404. Google's response stated that
  this model is unavailable to new users and recommended Gemini 3.8 Flash.
  Model listing alone did not
  prove inference availability.
- Gemini 3.8 Flash judged one diagnostic claim, but two later requests returned
  HTTP 503. Transient-service retries were added and regression-tested.
- The first-query verifier source payload shrank from 34,114 to 20,244 bytes.
  One live verifier diagnostic completed without HTTP 413. This does not prove
  every dataset request fits the provider limit.
- The user selected hosted Qwen to avoid local memory pressure (Ollama reported
  approximately 1.4 GiB available RAM). Groq lists `qwen/qwen3.8-27b`.
  The local download was stopped. Paired tests use that generator, GPT-OSS 120B
  baseline/verifier, and an independent Gemini judge.
- The original full suite passed 144 tests; after transient-server regressions,
  43 focused evaluation/provider/cloud/review tests passed. Sandboxed async
  transport tests hung; the same tests passed outside the sandbox.

## Final run configuration

Gemini 3.5 Flash completed structured judging after Gemini 3.8 was repeatedly
overloaded. The paired smoke test with the
compact packet completed 12/12 query/arm pairs, with no model failures or missing
judge labels. It is a diagnostic, not the full result.

Groq Qwen rejected the original packet with HTTP 413: 10,973 requested input
tokens versus a 7,000-token/minute account limit. Reducing only source text to
9,000 characters still requested 7,813 tokens; lowering the output cap did not
change that input limit. A 6,000-character budget plus lossless metadata
deduplication passed the paired smoke test. Every arm uses the same retrieved
chunks and budget. This infrastructure setting was chosen from the first dev
queries/provider errors, without tuning on held-out answers.

The first full attempt (`evaluation/runs/paired-full-20261009/`) was interrupted
after Gemini 3.5 exhausted its 20-request daily free-tier quota. The API's
structured error identified `GenerateRequestsPerDayPerProjectPerModel-FreeTier`
and a reset roughly four hours away. Short retries cannot solve that condition.
The launcher now defaults to Gemini 3.1 Flash Lite, which passed a structured
judge probe. It is a smaller independent judge; report its identity and avoid
claiming equivalence to a stronger judge. Partial 3.5 artifacts remain separate.

The 120B verifier exhausted Groq's 200,000-token daily allowance after the baseline, full system and unverified arm completed. A short retry could not solve this daily quota. The user approved GPT-OSS 20B verification. Both verified arms were rerun consistently; the completed 120B baseline and unverified Qwen arm were retained, with matching inputs and judge. The final assembled comparison is `evaluation/runs/paired-final-20b-20261009/`; its metadata records both source runs and reused arms. It contains all 13 queries and four arms (52 measured pairs). The interrupted 120B run is preserved separately.

Both Gemini and Groq structured daily-quota errors are now non-retryable; transient minute limits and provider overloads retain bounded retries. See `results.md` for final scores and validation.
