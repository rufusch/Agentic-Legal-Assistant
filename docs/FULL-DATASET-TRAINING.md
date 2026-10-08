# Full local dataset training

The full-corpus job targets the compatible **local Qwen 4B base**, not the weights of hosted Groq Qwen 27B or GPT-OSS 20B/120B services. Those hosted endpoints cannot be modified by this trainer. The objective is raw-text domain adaptation; validated drafting/review/research/chat/verifier targets and task-level evaluation are separate work.

The currently launched pipeline waits for both pinned dataset downloads to report complete, streams **every downloaded Parquet** into deduplicated JSONL shards, then runs one streaming epoch over every accepted training row. It has no document-count or optimizer-step cap by default. Metadata-only records and text shorter than 200 characters are excluded; exact normalized-text duplicates are removed using an on-disk SQLite index. Act/case identities determine stable train/validation/test splits. Near-duplicate/cross-source case matching and legal quality audits remain necessary before production use.

The prepared manifest records input snapshots, row counts, text characters, split counts and shard checksums. All shards are checked before loading the model. Training streams rows into 256-token blocks and never trains on validation/test rows. A small 16-block raw-text validation is logged; it is not a legal reasoning or task-performance benchmark.

## Running job and progress

- Pipeline state: `datasets/india-law/full-training-pipeline.json`
- Pipeline log: `tmp/full-training-pipeline.log`
- Download states: `datasets/india-law/downloads/{kanoon,vaquill}/download-status.json`
- Prepared corpus: `datasets/india-law/full-domain-corpus/manifest.json`
- Training state: `training/output/full-domain-20261009/status.json` (appears after preparation)
- Latest durable checkpoint pointer: `training/output/full-domain-20261009/latest.json`

The pipeline has already been launched locally. Do not launch a second copy while its recorded process is alive. Keep the computer awake, connected, and powered. Completion requires the training status to say `complete: true` and a saved `final-adapter`; a download, preparation stage, partial run or checkpoint is not completed full training.

The laptop trial measured roughly 264 training tokens/second at its tiny test configuration; full throughput varies. A large legal corpus may require weeks or months on this GPU. Full corpus size and actual progress must be measured before quoting a duration. No paid GPU resources are provisioned, and no production adapter is activated automatically.

## Restart and resume

On a fresh checkout, create a Python 3.12 training environment, install a CUDA build of PyTorch appropriate for your driver and the training libraries, and download the pinned base before starting the offline trainer. The tested Windows environment used:

```powershell
python -m venv .venv-training
.\.venv-training\Scripts\python.exe -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv-training\Scripts\python.exe -m pip install pyarrow==25.0.1 huggingface_hub==1.33.0 transformers==5.19.0 peft==0.21.2 accelerate==1.15.0 bitsandbytes==0.50.2
.\.venv-training\Scripts\hf.exe download unsloth/Qwen3-4B-Instruct-2507-bnb-4bit --revision f12db89cd5156e090618dded9b4367f23f8f3b33 --local-dir .runtime/training-base-qwen4b
```

Download the two datasets using `python -m scripts.download_india_law --source kanoon` and `--source vaquill` in an environment with Hugging Face Hub installed and an authorized `HF_TOKEN`. Models, datasets and the training environment are not in Git. This CUDA job requires a suitable GPU host; a CPU-only Codespace can run the website and official-source retrieval, but not this trainer.

After a failed dataset transfer, rerun the appropriate `scripts.download_india_law` command using `.venv-download` and the locally configured `HF_TOKEN`; then restart the pipeline:

```powershell
.\.venv-training\Scripts\python.exe -m scripts.run_full_training
```

The pipeline reuses a completed prepared corpus and resumes the latest complete optimizer checkpoint. It refuses to overwrite incomplete corpus preparation; preserve that folder for inspection and configure a fresh corpus output before repeating preparation. Preparation is streaming but is not resumable midway through a shard.

To resume training directly:

```powershell
.\.venv-training\Scripts\python.exe -m training.train_full_domain --corpus datasets/india-law/full-domain-corpus --out training/output/full-domain-20261009 --resume
```

An adapter, optimizer, RNG states and exact stream position are checkpointed every 100 optimizer steps. The two newest completed checkpoints are retained. An interruption can lose progress since the last completed checkpoint; resuming replays that unsaved work. An optional `--max-steps N` runs a segment, saves a checkpoint, and **does not mark the full epoch complete**.

## Train alongside preparation

Live mode consumes only closed shards with published SHA-256 checksums. It waits for
new shards and completes only after preparation finishes and all training rows have
been consumed. Validation/test rows are excluded from optimization. Do not also run
the waiting pipeline coordinator: it would start a duplicate GPU trainer later.

```powershell
.\.venv-training\Scripts\python.exe -m training.train_full_domain --corpus datasets/india-law/full-domain-corpus --out training/output/full-domain-concurrent-20261009 --follow-preparation --checkpoint-every 10
```

Resume with the same command plus `--resume`. Keep the preparation input list and
published shards unchanged. This trains the local Qwen 4B LoRA adapter; hosted Groq
and Gemini weights remain unchanged.

## Validation performed

The actual GPU smoke test saved a checkpoint after one step, restarted the process, restored adapter/optimizer/stream position, and finished the remaining fixture data at step two. This verifies the resume path, not full-dataset completion. The full preparation code processed all 74,731 rows in the central-legislation/1950 smoke inputs, wrote four shards, and verified their SHA-256 checksums. Those smoke artifacts are separate from the full job.

Training dependencies are isolated from the application; installed versions are recorded in `.runtime/training-environment.txt`. Dataset contents, weights, adapters, environments, logs and tokens remain excluded from Git.
