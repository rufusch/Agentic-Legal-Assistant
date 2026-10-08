# India-law training status — 9 October 2026

A bounded Qwen 4B domain-adaptation pilot has completed locally. Full-corpus and workflow-specialist training have not completed. Earlier inspection notes below are retained as historical context.

## Full-corpus continuation and official-source fallback

At the user's request, a separate full-corpus pipeline has been launched. Both pinned datasets are fully downloaded: KanoonGPT's 77 structured Parquets (10,927,252,353 bytes) and Vaquill's 75 Parquets (53,967,090,215 bytes). The pipeline has entered full-corpus preparation. Its live stage is recorded in `datasets/india-law/full-training-pipeline.json`; it prepares every downloaded Parquet without a document cap, then trains one streaming domain-adaptation epoch with durable adapter/optimizer/RNG/stream-position checkpoints. It targets the compatible local Qwen 4B model; hosted service weights are not trainable through this pipeline. Full completion is not claimed while the pipeline is preparing or checkpointing.

The actual GPU checkpoint test resumed from one optimizer step and completed the remaining small fixture at step two. Full preparation was separately tested on all 74,731 rows of the central-legislation and 1950 inputs, producing 71,182 unique rows across four checksum-verified shards. These are smoke checks, not full-dataset completion. See `docs/FULL-DATASET-TRAINING.md` for progress and resume commands.

Official PDF retrieval is now enabled independently of training, including automatic catalog discovery, manual official URL import, exact quoted passages and source URL/date/hash provenance. The running website successfully imported the Indian Contract Act and a Supreme Court judgment from live official URLs. Catalog coverage is limited and authority currency is not certified; failed sources are excluded or explicitly represented as dated, hash-verified official snapshots. See `docs/OFFICIAL-SOURCES.md`.

## Completed local pilot

Run: `training/output/domain-pilot-20261009/status.json`; saved adapter: `training/output/domain-pilot-20261009/adapter/` (ignored by Git).

- Source model: `unsloth/Qwen3-4B-Instruct-2507-bnb-4bit`, revision `f12db89cd5156e090618dded9b4367f23f8f3b33`; downloaded weights match the published SHA-256.
- Pilot v2: 243 original documents (100 Acts, 100 Sikkim cases, 43 KanoonGPT headnote cases), 22,699 unique text rows. Document-grouped train/validation/test rows: 15,524 / 2,772 / 4,403. Sikkim and central-legislation files downloaded successfully; Sikkim checksum verified against the pinned repository.
- Actual optimizer input: 1,024 prepared training blocks, 32 steps, four microbatches per step, up to 256 tokens per microbatch. This does not consume the entire pilot corpus.
- Validation: 16 blocks from 16 held-out documents; base mean block loss 2.387319, adapter mean block loss 2.185665. This tiny raw-text validation is not legal task accuracy, specialist evaluation, or a full-corpus result. The test split was not used for training or validation.
- Hardware: RTX 4050 Laptop GPU; peak allocated GPU memory 4,209,276,928 bytes; training plus final validation 124 seconds (excludes loading and initial validation).
- Torch 2.11.0+cu128, Transformers 5.19.0, PEFT 0.21.2, Accelerate 1.15.0, bitsandbytes 0.50.2. Installed environment snapshot: `.runtime/training-environment.txt`.
- Hosted production models were not changed. No review, drafting, research, chat or verifier specialist is claimed trained by this raw-text pilot. Those workflows still need validated task targets and task-level evaluation.

KanoonGPT's structured snapshot is complete: 77 Parquet files, 10,927,252,353 bytes. Vaquill's pinned snapshot continues separately in `.venv-download`. Check each `datasets/india-law/downloads/*/download-status.json` for completion; directories containing partial files are not complete datasets. All 170 application and training utility tests passed in 49.05 seconds (two dependency deprecation warnings). The saved adapter contains 144 finite tensors, 2,949,120 trainable parameters, and an 11,815,504-byte safetensors file.

## Local training continuation

The user subsequently authorized local downloads and training. Hugging Face access has now been configured locally; Vaquill's central-legislation Parquet (74,484 rows) was downloaded successfully. Complete KanoonGPT and Vaquill downloads are in progress under `datasets/india-law/downloads/`, with pinned revisions and resumable metadata. Their `download-status.json` files are authoritative; incomplete directories are not complete datasets.

`training/prepare_domain_corpus.py` prepared a bounded raw-text pilot from 100 Acts plus 43 KanoonGPT headnote-bearing cases: 22,088 unique normalized text rows across 143 source documents, with 15,047 training, 2,738 validation and 4,303 untouched test rows. Sections from an Act share a split. The initial pilot Act titles were checked and did not include the existing benchmark's Indian Contract Act; the 1950 judgment partition does not contain the benchmark's 2026 bail judgment. Near-duplicate and broader benchmark-overlap audits remain necessary before production training.

`training/train_domain_lora.py` is a small QLoRA causal-language-model trial, explicitly not workflow SFT. It refuses cross-split repeated document IDs or identical normalized text and requires CUDA. Defaults: pinned quantized Qwen 4B weights, rank 8 on q/v projections, 256-token blocks, 32 optimizer steps, accumulation 4, learning rate 5e-5. It records base/adapter validation losses, completed steps and peak GPU memory, and saves an adapter only after actual training. No production model is activated automatically.

CUDA PyTorch and model downloads initially stalled. Public installer/model range downloads now use published SHA-256 checks before publishing completed files. Nine focused data-audit, leakage and checksum tests passed. No completed training is claimed until a run's `status.json` reports complete with actual step counts and saved adapter files.

Historical access blockers below describe the earlier inspection; live download/run status takes precedence.

## Sources inspected

| Source | Observed status |
|---|---|
| https://oss-data-in.vaquill.ai/index.html | HTTP 403 from this environment |
| https://huggingface.co/datasets/vaquill/open-india-law | Public metadata and README accessible; gated dataset (`gated: auto`), Parquet request returned HTTP 401. Listed files total approximately 53.97 GB. Revision `58ea6d8b6859f8039ee68dff5af636f787b02463`. Dataset card declares CC BY 4.0. |
| https://huggingface.co/datasets/KanoonGPT/indian-case-laws/tree/main/structured/v1 | Public structured metadata, not a complete supervised task dataset. Revision `42dd6a97345e9811b3d6219f15c250f1ce2bc5af`. Dataset card declares Apache 2.0. |

The Vaquill website and Hugging Face repository belong to the same source project; do not count them as independent corpora. KanoonGPT and Vaquill include overlapping court material. Deduplicate across sources before assigning final training/test membership.

## Work actually completed

- Created `.venv-training` using Python 3.12 and installed PyArrow 25.0.1, isolated from the running application.
- Downloaded KanoonGPT's 1950 Parquet partition (209,786 bytes). Its SHA-256 matches the published LFS digest: `48e6c12aa704f1f0278988bbe329f6f0b803f53bcbb1a99eea59d941acfa4a9f`.
- Inspected all 247 records: 43 have nonempty `headnote_text`. Metadata/indexable text must not be treated as full judgment reasoning.
- Ran the existing ingestion pipeline on 30 records with explicit mappings and strict document isolation. It recognized 30 documents and generated zero evaluation or SFT rows: there were no question/answer labels.
- Produced an initial case-ID split manifest: 167 train, 39 validation, 41 test. No repeated case IDs or exact headnote hashes in this one partition. This is not a full-corpus leakage audit or a training-ready split.
- Added `training/audit_india_law.py`; three targeted tests passed.
- Local files: `datasets/india-law/sources.json`, `inspection.json`, `sample-record.json`, `audit/report.json`, `audit/case-split-manifest.jsonl`. Downloaded data and environments are excluded from Git.

One inspected 1950 record names a much later presiding judge; source metadata/headnote correspondence requires validation against original judgments before using such fields as training truth.

## What blocks training all present models

1. **Data access:** request Vaquill dataset access on Hugging Face and configure an authorized read token as `HF_TOKEN` locally. Never paste or commit the token.
2. **Task targets:** case law and legislation do not supply validated intake-to-draft examples, full review outputs, research memos, grounded chat answers or verifier labels. Each workflow requires targets matching its actual schema. Raw-text domain training is a separate objective and is not implemented by the current SFT script. Teacher-generated targets must be labeled as synthetic, checked against sources, and evaluated independently.
3. **Model scope:** the existing trainer targets `Qwen/Qwen3-4B-Instruct-2507` chat adapters. Review, drafting, research and verifier schemas need separate preparation/validation. It cannot directly change the currently hosted Groq Qwen 27B or GPT-OSS 20B/120B weights. A locally trained 4B adapter is a different model/configuration; no silent replacement is made.
4. **Compute:** the laptop has an RTX 4050 with 6,141 MiB VRAM (5,921 MiB free at inspection). Default 4B/8192-token QLoRA has not been validated on this hardware. A GPU runtime must be selected and tested before a substantial run. Hosted 27B/20B/120B training is beyond this laptop. No paid GPU resources were provisioned.
5. **Environment:** only Parquet preparation dependencies have been installed in the isolated environment. CUDA PyTorch, Transformers, PEFT, TRL and bitsandbytes remain to be installed and validated on the selected training machine. Existing training dependency ranges are not a reproducible GPU lockfile.
6. **Acceptance:** hold out entire deduplicated cases/documents; preserve the existing evaluation set; train each compatible role adapter; compare against its identical base model; audit citation support, fabrication, coverage and abstention; test export and application integration before activating it.

## Repeat the inspection

```powershell
.\.venv-training\Scripts\python.exe training/audit_india_law.py --input datasets/india-law/raw/kanoon-1950.parquet --out datasets/india-law/audit
.\.venv\Scripts\python.exe -m pytest tests/test_india_law_audit.py -q
```

The current app and hosted model settings remain running. The local pilot adapter described above has been saved; production model weights have not changed.
