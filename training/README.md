# Dataset → corpus → eval → LoRA fine-tune → Ollama

This pipeline takes a dataset in an unknown format and produces three things: corpus documents
for the app, a verified evaluation set, and grounded SFT data. It then fine-tunes the chat
model (Qwen3-4B-Instruct) and plugs it back into the app through Ollama.

**Rule: never train on held-out evaluation data.** `ingest_dataset.py` writes held-out rows to
`eval.jsonl` only, and asserts they are absent from `sft.jsonl`. `train_lora.py --eval-file`
refuses to start if any held-out id appears in the training data. If judges bring unseen documents,
they are not in your SFT data by construction. Do not ingest them with the training set.

## 1. Ingest the dataset (any machine, app venv, no GPU)

```powershell
.\.venv\Scripts\python -m scripts.ingest_dataset path\to\dataset --out datasets\ds1 --dry-run   # inspect report first
.\.venv\Scripts\python -m scripts.ingest_dataset path\to\dataset --out datasets\ds1
```
Input can be:
* a folder of PDF, DOCX, TXT, MD or HTML files; or
* JSON, JSONL, CSV, TSV or Parquet (`pip install pyarrow`) QA tables or document tables; or
* a SQuAD-style JSON file; or
* an HF `save_to_disk` folder or hub id (`pip install datasets`).

Folders can mix documents and tables. A table whose rows name a file (`file`, `doc`, `path`…) is
used as metadata for the documents in the folder.

| Flag | Use |
|---|---|
| `--map question=Query,answer=Ans,context=Passage,doc=File,quote=Evidence` | when automatic column mapping (shown in `report.json` → `column_mappings`) is wrong. Dotted paths reach nested fields (`meta.text`). |
| `--metadata-defaults jurisdiction=IN,document_type=judgment` | defaults where nothing is inferred |
| `--heldout-frac 0.3`, `--group-by document` | deterministic hash split. `document` keeps every question about a document in one split. |
| `--ignore-source-splits` | ignore `split` columns or `test`/`train` filenames |
| `--strict-doc-isolation` | also drop SFT rows whose documents appear in held-out questions |
| `--limit 50`, `--skip-ocr`, `--force` | quick runs, skip OCR of scanned pages, overwrite the output |

The output is `datasets/ds1/`, containing:
* `documents/`;
* `manifest.jsonl` (corpus schema);
* `eval.jsonl`;
* `sft.jsonl`;
* `report.json`;
* `eval_flagged.jsonl` (rows whose gold quote could not be found in the parsed text);
* `sft_rejected.jsonl` (with reasons).

Gold quotes are located in text parsed by `backend.parsing`. The match is exact first, then
whitespace- and quote-normalized; the stored quote is always the exact parsed substring.
SFT rows exist only when the answer passes `material_values_supported` and lexical overlap
(`--min-overlap 0.6`) with the cited source lines. Unanswerable rows become abstention
examples (`{"propositions": []}`).

Metadata such as `document_type`, `court`, `decided_at`, `neutral_citation` and `title` is
inferred by regex. The inferred keys are listed in `metadata_inferred`, and you should
spot-check them in `manifest.jsonl`.

## 2. Load the corpus into the app

```powershell
.\.venv\Scripts\python -m scripts.ingest_corpus datasets\ds1\manifest.jsonl          # validate
$env:CORPUS_API_TOKEN = "<session token>"   # python -m backend.admin --storage .data issue-session --tenant <t>
.\.venv\Scripts\python -m scripts.ingest_corpus datasets\ds1\manifest.jsonl --execute --base-url http://127.0.0.1:8000
```
The prototype holds 200 documents per tenant. `report.json` warns you when the bundle is larger.

## 3. Train the LoRA adapter

Use a separate venv: `pip install -r training/requirements-train.txt`. Install the CUDA build of
torch first; see the comments in that file. With no NVIDIA GPU, follow [COLAB.md](COLAB.md).
```powershell
python training\train_lora.py --data datasets\ds1\sft.jsonl --eval-file datasets\ds1\eval.jsonl --dry-run
python training\train_lora.py --data datasets\ds1\sft.jsonl --eval-file datasets\ds1\eval.jsonl --out runs\chat-ft --epochs 2
```
* Defaults: `Qwen/Qwen3-4B-Instruct-2507` (the HF weights of Ollama's `qwen3:4b-instruct`), QLoRA 4-bit, rank 16, alpha 32, lr 2e-4, `max-seq-len` 8192.
* Use `--no-4bit` on CPU or Mac.
* Loss is computed on the assistant JSON only.
* Unsloth is used automatically when it is installed.
* A 12 GB+ NVIDIA GPU is comfortable; 8 GB works with `--max-seq-len 4096`.

## 4. Export to Ollama

```powershell
python training\export_to_ollama.py --merged runs\chat-ft\merged --name leximind-chat-ft
```
This runs four steps:
1. It clones llama.cpp.
2. It converts the merged model to an f16 GGUF.
3. It quantizes to q4_K_M, using `llama-quantize` if present or `ollama create --quantize` otherwise.
4. It writes a `Modelfile` (Qwen ChatML template, temperature 0, `num_ctx` 16384) and runs `ollama create`.

Use `--dry-run` to print the commands only.

## 5. Plug in and evaluate base vs fine-tuned

```powershell
$env:LEXIMIND_CHAT_LLM_MODEL = "leximind-chat-ft"; .\run-local.ps1      # chat workflow only
```
Other roles read `LEXIMIND_<ROLE>_LLM_MODEL` (and `_LLM_PROVIDER`, `_BASE_URL`, `_API_KEY`).
Run the eval harness twice on `eval.jsonl`, filtered to `split == "heldout"`:
* the base arm with `qwen3:4b-instruct`;
* the fine-tuned arm with `leximind-chat-ft`.

Report the following, per arm, as the ablation:
* groundedness;
* fabricated-citation count (must be 0);
* retrieval recall against `gold`;
* abstention accuracy on `answerable:false` rows.

The `dev` split is for tuning only.

### What the fine-tune teaches (and does not)

Training examples use the exact `backend.chat.SYSTEM` prompt, user JSON
(`{question, history, sources:[{source_id: E1.., text, document_type, ...}]}`) and `Answer` schema.
The packet is built by `backend.drafting_engine.source_packet` over chunks from `backend.parsing.chunks`.
These are the same line-level source IDs the app produces at inference time.

The fine-tune improves output format, citation of the right source lines, and abstention.
It does not add legal knowledge, and the app's verification pass still gates every proposition.
A small dataset (fewer than 200 rows) mostly teaches format. Always compare against the base
model before switching.
