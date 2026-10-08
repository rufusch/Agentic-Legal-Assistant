# Train on a free GPU (Colab / Kaggle T4)

Use this when laptops have no NVIDIA GPU. Qwen3-4B QLoRA fits a 16 GB T4 at `--max-seq-len 8192`
with batch 1; drop to `--max-seq-len 4096` if you hit out-of-memory. Expect roughly 1–2 minutes per
100 examples per epoch with Unsloth on a T4 (more without it).

**Upload only `sft.jsonl` and `eval.jsonl`** (the eval file is used only for the leak check). Never upload
or train on the judges' held-out documents. Case files may be confidential: check you are allowed to put
them on a third-party GPU before you upload.

Colab: Runtime → Change runtime type → T4 GPU. Kaggle: Settings → Accelerator → GPU T4, Internet on.

### Cell 1: install
```python
!pip -q install unsloth            # pulls compatible torch/transformers/trl/peft/bitsandbytes
!git clone --depth 1 <YOUR-REPO-URL> ala   # or upload training/train_lora.py + export_to_ollama.py
%cd ala
```
If you cannot clone, upload `training/train_lora.py` and run it from the upload folder. It has no app imports.

### Cell 2: upload data
```python
from google.colab import files      # Kaggle: add the files as a Dataset and use /kaggle/input/...
up = files.upload()                 # pick sft.jsonl and eval.jsonl
```

### Cell 3: dry run (validates rows, lengths, leak check)
```python
!python training/train_lora.py --data sft.jsonl --eval-file eval.jsonl --dry-run
```

### Cell 4: train (QLoRA)
```python
!python training/train_lora.py --data sft.jsonl --eval-file eval.jsonl --out runs/chat-ft \
    --epochs 2 --rank 16 --lr 2e-4 --max-seq-len 8192
```
With fewer than ~200 examples, use `--epochs 3`. Outputs: `runs/chat-ft/adapter` (about 130 MB) and `runs/chat-ft/merged` (about 8 GB fp16).

### Cell 5: convert to GGUF on the GPU box (avoids downloading 8 GB)
```python
!python training/export_to_ollama.py --merged runs/chat-ft/merged --skip-ollama --quant f16
# Optional smaller file: build llama-quantize (needs cmake), then rerun with --quant q4_K_M
#   !cd runs/chat-ft/llama.cpp && cmake -B build && cmake --build build --target llama-quantize -j
#   !python training/export_to_ollama.py --merged runs/chat-ft/merged --skip-ollama \
#        --llama-quantize runs/chat-ft/llama.cpp/build/bin/llama-quantize
!ls -lh runs/chat-ft/gguf
```

### Cell 6: download
```python
!cd runs/chat-ft && zip -r gguf.zip gguf -x "gguf/model-f16.gguf"   # keep the f16 file only if you did not quantize
files.download('runs/chat-ft/gguf.zip')   # or download runs/chat-ft/gguf/*.gguf + Modelfile individually
```
For f16-only exports, download `model-f16.gguf` (about 8 GB) and `Modelfile`.

### On the laptop
```powershell
cd path\to\gguf         # folder holding the Modelfile and .gguf
ollama create leximind-chat-ft -f Modelfile                     # if the GGUF is already q4_K_M
ollama create leximind-chat-ft -f Modelfile --quantize q4_K_M   # if you downloaded the f16 GGUF
$env:LEXIMIND_CHAT_LLM_MODEL = "leximind-chat-ft"; .\run-local.ps1
```
