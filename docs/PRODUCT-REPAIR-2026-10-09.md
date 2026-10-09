# Product repair and verification — 9 October 2026

The preview runs from `repo-publish` at http://127.0.0.1:8765. Existing source
edits and the separate local evaluation copy are preserved. This report records the initial repair validation; later validation is recorded in WORKFLOW-VALIDATION-2026-10-09.md.

## Repaired upload-to-output failures

- Chat upload returned immediately after setting its busy flag, preventing all
  attachment uploads and blocking subsequent questions. Removed that exit and
  added a real browser attachment regression, including a generic binary MIME.
- Known document extensions now resolve consistently for upload validation and
  transfer. Empty files and unsupported legacy DOC produce actionable errors.
- Research uploads select the parsed documents as context automatically, reject
  concurrent batches, reset the picker and update the document count.
- Review accepts the same TXT/scanned-image formats as the repository. Its date
  default follows the browser's local calendar rather than UTC.
- The repository displays parser errors and disables source inspection until a
  source is ready.
- Chat reserves context for explicitly selected documents before supplemental
  statutes. A live agreement question previously retrieved only statutory chunks
  and abstained; the repaired run answered the payment question with a citation.
- The local runner supports configurable ports, backend reload, explicit Python
  paths, and opt-in hosted mode using a saved Windows Groq key. Credentials are
  never written to source. Access logs are disabled to avoid logging upload URLs.

## Verification

The complete backend suite passed (190 tests), including the added selected-source
budget regression. Browser tests passed
for upload retry, chat attachment and recovery, review, drafting, research,
navigation, output rendering and PDF download using controlled API responses.

Real server verification used a synthetic agreement, never private test content:
upload and parsing completed, stored source text matched, chat identified Alpha
Ltd's INR 5000 payment to Beta Ltd by 15 October 2026 with a citation, and review
returned three cited facts plus findings about termination and missing Schedule A.
The generator was Groq Qwen and verifier Groq GPT-OSS-20B. Hosted mode was enabled
only after explicit user approval for selected document analysis.

Model/provider quotas, OCR quality, official website availability and legal
correctness remain external limits. Live hosted drafting and research were not
certified by this smoke test; their API and UI regressions use controlled models.

Restart example (use your installed project Python environment):

```powershell
./run-local.ps1 -Port 8765 -Hosted -Reload -PythonPath '../Agentic-Legal-Assistant/.venv/Scripts/python.exe'
```

`-Hosted` sends selected evidence to the configured Groq service. Omit it for the
local model configuration. Set BACKEND_STORAGE before launch to reuse a specific
workspace; otherwise the runner uses `.data-demo`.
