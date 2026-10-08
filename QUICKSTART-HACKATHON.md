# Quickstart — what to run, in order

Branch: `developments/hackathon-final`. `codex/ps1-delivery` is the untouched fallback.

```powershell
git fetch origin
git checkout developments/hackathon-final
```

## 1. Retrieval ablation (no model, ~1 minute)

```powershell
.\run-eval.ps1 -RetrievalOnly
```

Writes `evaluation/runs/paired-retrieval/results.md`. See `docs/RETRIEVAL-ABLATION.md`
for the numbers measured so far and which of them is safe to quote.

## 2. Paired groundedness run (needs a key)

```powershell
.\run-eval.ps1 -GroqKey "gsk_..." -Limit 3     # smoke first
.\run-eval.ps1 -GroqKey "gsk_..."              # full run
```

Arms: `baseline` (gpt-oss-120b on Groq, plain RAG), `system` (ours), `system_no_verify`,
`system_no_numeric`. The last two are the ablation that answers "what is new
compared with the baseline" — 25% of the score.

Writes `evaluation/runs/paired/results.md`: groundedness, fabrication count,
answer coverage, abstention correctness, retrieval recall@k/MRR, latency.

**The judge should be a different model family from the generator and baseline.**
With only a Groq key the script judges with `openai/gpt-oss-120b`; add
`-GeminiKey` and it moves the judge to Gemini, which is much harder to dispute.

## 3. When the datasets arrive

```powershell
python -m scripts.ingest_dataset <path-to-data> --out datasets\ds1 --dry-run   # check the report first
python -m scripts.ingest_dataset <path-to-data> --out datasets\ds1
python -m scripts.ingest_corpus datasets\ds1\manifest.jsonl --execute --base-url http://127.0.0.1:8000
.\run-eval.ps1 -GroqKey "gsk_..." -Dataset datasets\ds1\eval.jsonl -Out evaluation\runs\ds1
```

Accepts folders of PDF/DOCX/TXT, JSON/JSONL/CSV/Parquet, SQuAD and HF formats.
Gold quotes are verified against parsed text; unverifiable rows are flagged, not
silently kept. Held-out rows never reach `sft.jsonl`.

## 4. Fine-tune (optional, only if time allows)

See `training/README.md`, or `training/COLAB.md` for a free T4. Retrieval and the
independent verifier will almost certainly move groundedness more than a 4B
fine-tune will, so treat the fine-tune as one more ablation arm, not the headline.

**Never evaluate on data you trained on.** `train_lora.py --eval-file` refuses to
train when held-out ids appear in the training data.

## Demo-day settings

```powershell
$env:LEXIMIND_VERIFIER_LLM_PROVIDER="groq"      # independent verifier
$env:LEXIMIND_VERIFIER_LLM_MODEL="openai/gpt-oss-120b"
$env:LEXIMIND_VERIFIER_API_KEY="gsk_..."
$env:LEXIMIND_RETRIEVAL_MODE="full"             # or "hybrid" if MRR matters more
$env:LEXIMIND_EMBEDDINGS="ollama"               # after: ollama pull nomic-embed-text
$env:LEXIMIND_AGENT_MAX_ROUNDS="2"
```

If the judges' documents are large and the local 4B model is slow, point the chat
role at Groq too: `LEXIMIND_CHAT_LLM_PROVIDER=groq`. Grounding checks are
unaffected — they run on retrieved spans, not on the model.
