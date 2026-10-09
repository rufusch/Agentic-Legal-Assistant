# Local Qwen preview

The preview uses Ollama with `qwen3:4b-instruct` (Q4_K_M), running on this computer. All model roles use the local service; Groq is optional via `run-local.ps1 -Hosted`.

Installed runtime and model weights live in ignored `.runtime/ollama` and `.runtime/models` directories. They are not committed to Git. Run `start-local-model.ps1` to install or start the model on another setup. The installer includes CUDA 12 GPU support.

Start this checkout using the existing Python environment:

```powershell
$env:BACKEND_STORAGE = Join-Path (Get-Location) '.data-preview'
./run-local.ps1 -Reload -PythonPath '../Agentic-Legal-Assistant/.venv/Scripts/python.exe'
```

Open http://127.0.0.1:8765/#workflow-1. Uploading a document parses it and starts a summary without an audit checklist.

Local defaults: 16,384-token context, 4,000 output tokens (6,000 for drafting), up to 12,000 source characters, one loaded model and one parallel request. Source metadata is packed without removing evidence. Support checks use batches of at most five items. There is no hosted daily token quota, but memory, context size and processing speed still impose limits.

Verified on the RTX 4050 Laptop GPU: document upload → parsing → cited summary covered both parties, payment, deadline and notice. A follow-up chat answer returned the notice period, and a research memo returned a cited answer from an official statute. PDF, DOCX and scanned PNG inputs recovered the expected source text. Draft exports were checked in TXT, DOCX and PDF formats.

Drafting accepts a direct file attachment and proceeds automatically after intake processing. Unknown details become bracketed placeholders. Unsupported passages receive one bounded rewrite and must pass the same source checks again; this never rewrites user-edited draft text. Missing or unverifiable authority remains a visible gap.

When structured bail or notice fields are available, drafting assembles their exact captured values into an attributed working document. This path reports `generation_method: literal_intake_template` and does not depend on Qwen to invent a document body or legal authority. Other drafting requests use the local model and source checks. Title-only output is rejected as incomplete.
