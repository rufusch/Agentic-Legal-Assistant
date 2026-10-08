# Evaluation harness

Paired, claim-level evaluation of the **baseline** (single-pass RAG) against the **system** (the grounded
chat pipeline) and its ablations. Every arm runs on the identical query set and the identical retrieved
chunks; the runner refuses to report a comparison otherwise.

## Dataset format (JSONL, one query per line)

```json
{"id": "ica-remote-loss", "split": "dev", "workflow": "research",
 "question": "Is compensation payable for remote and indirect loss?",
 "documents": [{"path": "../../corpus/public-starter/indian-contract-act-1872.pdf", "id": "contract-act"}],
 "sources": [{"id": "memo", "text": "inline text ...", "metadata": {"document_type": "contract"}}],
 "gold": [{"doc": "contract-act", "quote": "Such compensation is not to be given for any remote and indirect loss"}],
 "answerable": true, "reference_answer": "optional"}
```

| field | meaning |
|---|---|
| `split` | `dev` or `heldout` (default `dev`). Do not tune prompts on `heldout`. |
| `workflow` | `chat` (default), `research` or `review`. Recorded for reporting. |
| `documents` | PDF/DOCX/TXT paths, relative to the dataset file, the cwd, or absolute. Parsed with `backend.parsing.extract` and chunked with `backend.parsing.chunks` like production. Metadata (e.g. `document_type`) comes from a sibling `manifest.jsonl` or the `metadata` key. |
| `sources` | Inline text sources `{id, text, metadata}`. You can use these with `documents` or on their own. |
| `gold` | `{doc, quote}`. The `quote` must be a verbatim substring of the **parsed** text of `doc`; otherwise loading fails. Each quote is mapped to the chunk ids it overlaps (these are the retrieval gold). |
| `answerable` | `false` means the correct behaviour is to abstain. Gold may then be empty. |

`evaluation/datasets/public_dev.jsonl` contains 13 queries over the two public starter PDFs:
10 answerable and 3 unanswerable, with 4 marked `heldout`. The gold quotes were taken from the parser's output.

## Arms

| arm | what runs |
|---|---|
| `baseline` | Role `baseline` model. It sees the same retrieved chunks, each whole, as `[S1]..[Sn]`, and returns `{claims:[{text, source_ids}]}`. |
| `system` | `run_system()`, a pure-function replica of `backend/chat.py`. It uses a line-level `source_catalog` packet, the chat `SYSTEM` prompt, then the verifier `CHECK` pass, the numeric guard and the authority-type filter. |
| `system_no_verify` / `system_no_numeric` / `system_no_authority` / `system_generation_only` | Ablations that switch those stages off. |
| `<arm>@<retriever>` | Runs the arm on another retriever, e.g. `system@bm25`. |

Retrievers (`evaluation/harness/retrievers.py`):

- `hybrid`: production `backend.retrieval.search`.
- `bm25`: the lexical component only.
- `dense`: the LSA component only.
- `bm25_plain`: textbook BM25.
- Any `package.module:function` with the signature `(chunks, query, limit)`.

To add a variant, register it in `RETRIEVERS`.

Models are chosen per role through environment variables:
`LEXIMIND_{BASELINE,CHAT,VERIFIER,JUDGE}_LLM_PROVIDER / _BASE_URL / _LLM_MODEL / _API_KEY`
(these fall back to `LEXIMIND_LLM_*`). Use a judge from a different model family than the generators; the runner warns if they match.

## Judging

Each claim is labelled `supported | partially_supported | unsupported | fabricated`.

1. **Deterministic checks (no model).** A claim is marked `fabricated` when it does any of the following:
   - cites a source id that was never shown;
   - contains a number that appears in no retrieved source;
   - contains a statute section that appears in no retrieved source;
   - contains a reporter citation (SCC, AIR, INSC, ...) that appears in no retrieved source;
   - names a case party that appears in no retrieved source.

   A claim with no citations is marked `unsupported`.
2. **LLM judge (role `judge`).** One schema-constrained call per prediction labels the remaining claims against the cited chunks. Results are cached in `evaluation/runs/.judge-cache/`, keyed by sha256 of (claim, cited chunks, retrieved set, judge model).

## Metrics

| metric | definition |
|---|---|
| `groundedness` | (supported + 0.5 x partially supported) / judged claims |
| `strict_groundedness` | supported / judged claims |
| `fabricated_claims`, `fabrication_rate` | Fabricated claims, as a count and as a share of claims. This must be 0 for `system`. |
| `answer_coverage` | Answerable queries that got at least one claim. Model errors count as no answer. |
| `correct_abstention` | Unanswerable queries that got zero claims and no error. |
| `context_recall` | Gold chunks present in the arm's model context. |
| retrieval (`--retrieval-only`) | recall@5/10, MRR, nDCG@5/10 against the gold chunk ids. Computed from the retriever alone, so no model is needed. |
| `mean_latency_s` | Mean latency per arm. |

All metrics are reported overall and per split.

## Commands

```bash
# Retrieval ablation (no LLM)
python -m scripts.run_eval --dataset evaluation/datasets/public_dev.jsonl --retrieval-only \
    --retrievers hybrid,bm25,dense,bm25_plain --out evaluation/runs/retrieval-public-dev

# Full paired run (models via env vars); --limit N for a smoke run
python -m scripts.run_eval --dataset evaluation/datasets/public_dev.jsonl \
    --arms baseline,system,system_no_verify,system_no_numeric --split all --out evaluation/runs/full
```

Outputs:

- `predictions.jsonl`: claims, citations, retrieved chunk ids, latency and any error.
- `judgments.jsonl`: per-claim label, reason and deterministic flags.
- `metrics.json`
- `results.md`: tables ready to paste into the write-up.

The retrieval-only mode writes `retrieval.json` and `results.md`.
