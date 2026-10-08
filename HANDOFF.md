# HANDOFF — read this first

Any agent (Claude Code, Codex, a teammate) picking up this work: read this file,
then `QUICKSTART-HACKATHON.md`. Written 2026-10-08 23:15 IST.

Branch: `developments/hackathon-final`. Fallback: `codex/ps1-delivery` (untouched, known-good).

## The one thing that matters

Problem statement HNX26EPS01. The judging rubric:

| Weight | Criterion |
|---|---|
| **pass/fail** | **Zero fabricated facts or citations. A single fabrication is a hard failure.** |
| 35% | Groundedness vs baseline: % of claims traceable to a real source |
| 25% | Research contribution vs baseline, shown by ablation |
| 20% | Retrieval quality vs baseline |
| 20% | Usefulness of the output |

Judges bring **unseen documents and queries** with known correct source references.
Baseline = a strong general LLM doing RAG on identical inputs.

**Depth on one workflow beats shallow coverage of four.** Lead with RAG Chat + Review.

## State: what is done and what is unproven

Done and tested (141 tests pass, `python -m pytest -q`):

- **Plug-and-play models.** `LocalReviewLLM.for_role(role)` in `backend/models/review_llm.py`.
  Providers: ollama, lmstudio, compatible, openai, gemini, groq, openrouter, together,
  mistral, deepseek, anthropic. Roles: review, drafting, research, chat, verifier,
  baseline, judge. Env: `LEXIMIND_<ROLE>_LLM_PROVIDER/_BASE_URL/_LLM_MODEL/_API_KEY`,
  falling back to shared `LEXIMIND_LLM_*`. Hosted providers need only a model id + key.
- **Evaluation harness.** `scripts/run_eval.py` + `evaluation/harness/`. Arms: baseline,
  system, system_no_verify, system_no_numeric, system_no_authority. LLM judge with disk
  cache + deterministic fabrication detection. Metrics: groundedness, fabrication rate,
  answer coverage, abstention correctness, recall@k, MRR, nDCG, latency. `--retrieval-only`
  runs with no model at all.
- **Retrieval v2.** `backend/retrieval.py` (modes: bm25, lsa, hybrid, hybrid+rewrite, full),
  `query_rewrite.py` (section normalisation, CrPC↔BNSS / IPC↔BNS aliases), `embeddings.py`,
  `rerank.py`. `mode='hybrid'` reproduces the old pipeline exactly (a test pins this).
- **Agentic loop.** `backend/agent_loop.py`. Independent verifier model, verify →
  re-retrieve → regenerate (max 2 rounds, `agent_trace` in output), computed confidence
  replacing a hardcoded 0.6, research `conflicting_authorities`, follow-up-aware chat
  retrieval, drafting fields prefilled from documents with exact-quote citations.
- **Dataset + training.** `scripts/ingest_dataset.py` (folders of PDF/DOCX/TXT,
  JSON/JSONL/CSV/Parquet, SQuAD, HF → corpus manifest + verified-gold eval.jsonl +
  sft.jsonl, with a held-out leak guard). `training/` has LoRA, Colab, Ollama export.

**NOT verified — this is the gap.** No LLM arm has ever run against a real model.
Every test uses mocks. The build sandbox could not reach Groq (egress allowlist) and had
no Ollama. **Running the paired eval on a real model is the next action and the whole
qualifying case depends on it.**

## Honest findings — do not paper over these

1. **The retrieval result is mixed.** On the independent 13-query set, the new `full`
   default wins recall@10 (1.000 vs 0.950) but **loses MRR** (0.650 vs 0.719 for the old
   hybrid, 0.729 for plain BM25). It clearly wins on section-number queries ("u/s 438")
   that the old default missed entirely. See `docs/RETRIEVAL-ABLATION.md`: it holds two
   tables and says which is safe to quote. **Quote the independent set, not the tuned one.**
2. **The old `hybrid` default never beat plain BM25** on either query set. The LSA half
   was not earning its cost.
3. **Chat abstained** on a simple contract fixture in the previous release's live run.
   Abstention is honest but scores zero on usefulness. Watch `answer_coverage`.
4. **Generator and verifier were the same model**, so errors correlated. Fixed by setting
   `LEXIMIND_VERIFIER_*`, but that path has not run live either.
5. **The legal alias tables are curated, not authoritative** (`backend/legal_aliases.py`).
   They only widen search and are never shown as citations, so a wrong row hurts ranking
   but cannot invent a citation. Verify before claiming correctness.

## Rules that must not be broken

The pass/fail gate lives in the code. Do not weaken any of these to make a number move:

- A claim is published **only** if the verifier passes it AND every citation resolves to
  an exact stored source span (offsets checked) AND the numeric guard passes AND legal
  propositions cite statute/judgment sources.
- Failed verification publishes **nothing**. Never downgrade a check to raise coverage.
- `EvidenceBundle.validate_source_spans` is the last gate. Keep it.
- **Never train or tune on held-out eval data.** `ingest_dataset.py` enforces the split;
  `train_lora.py --eval-file` refuses to train when held-out ids leak in.
- An empty answer gets **no** groundedness score. Abstention is not a perfect score.

## Live-run findings (2026-10-09 00:15 IST, Windows + Groq)

The first real-model attempt happened on the author's Windows machine. It did not
finish. What it established:

- **`llama-3.3-70b-versatile` is retired from Groq** (404 model_not_found). Hosted
  roles now default to `openai/gpt-oss-120b`. Fixed in `run-eval.ps1`.
- **PowerShell 5.1 aborts on stderr** under `ErrorActionPreference=Stop`, including
  Python's ordinary progress output. Every run died before producing results. Fixed.
- **The paired run never completed.** `evaluation/runs/paired/` does not exist and the
  judge cache holds exactly one entry (one claim, judged `supported`). So the Groq
  path works end to end for at least one claim, but something stops the run after
  that. **Diagnosing this is the first task.** Run with `-Limit 3` and read stderr.
- **The retrieval ablation reproduced exactly** on different hardware: `full` at
  recall@10 1.000 / MRR 0.650, `hybrid` at 0.950 / 0.719.
- **UNRESOLVED, and it matters for 35% of the score:** with only a Groq key, the
  baseline, the verifier and the judge are all `openai/gpt-oss-120b` — the same
  model grading its own output. Get a free Gemini key (aistudio.google.com/apikey)
  and pass `-GeminiKey`; the runner already routes the judge to Gemini. If you
  cannot, **state the limitation explicitly in the write-up** rather than quoting
  the groundedness number as if it were independent.
- A nested clone may exist at `agentic-legal-assistant-review/` inside the repo. It
  is untracked and must not be committed. Delete it.

## Next actions, in order

1. `.\run-eval.ps1 -GroqKey "..." -Limit 3` — find why the paired run stops after the
   first judged claim (see the live-run findings above). Groq may also reject
   `response_format: json_schema` (a json_object fallback exists — confirm it fires).
2. Full paired run. Read `evaluation/runs/paired/results.md`. **Fabrication must be 0.**
3. If groundedness does not beat the baseline, say so. Do not tune on the test set.
4. `ollama pull nomic-embed-text`, set `LEXIMIND_EMBEDDINGS=ollama`, re-run the retrieval
   ablation. If `full` still trails on MRR, set `LEXIMIND_RETRIEVAL_MODE=hybrid`.
5. When datasets arrive: `scripts/ingest_dataset.py --dry-run` first, always read report.json.
6. Write-up: architecture, results table, ablation, limitations. 2 pages.
7. Fix the CSP blocking Google Fonts (self-host the fonts; conference wifi is unreliable).

## Known loose ends

- Three frontends exist (`frontend/`, `antigravity-frontend/`, `hacknex2-frontend/`).
  `hacknex2-frontend` is the live one. Archive the others before judging.
- UI does not yet display: `agent_trace`, `conflicting_authorities`, per-field drafting
  citations, verifier identity.
- Corpus has only 2 documents. `corpus/recommended-sources.md` lists official URLs for
  BNSS/BNS/BSA and bail authorities; `scripts/fetch_public_corpus.py` downloads them.
- A Groq API key was shared in plaintext during development. **Rotate it.**
