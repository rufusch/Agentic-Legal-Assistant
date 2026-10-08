<#
  Paired groundedness evaluation: our system vs a strong baseline, plus ablations.

  Usage (from the repo root):
      .\run-eval.ps1 -GroqKey "gsk_..."                  # full paired run
      .\run-eval.ps1 -RetrievalOnly                      # no model needed, ~1 min
      .\run-eval.ps1 -GroqKey "gsk_..." -GeminiKey "..." # judge on a second family (best)

  The judge should not be the same family as the generator or baseline. With a
  Gemini key the judge moves to Gemini and the scores get much harder to dispute.
#>
param(
  [string]$GroqKey = $env:GROQ_API_KEY,
  [string]$GeminiKey = $env:GEMINI_API_KEY,
  [string]$Dataset = "evaluation/datasets/public_dev.jsonl",
  [string]$Out = "evaluation/runs/paired",
  [string]$Arms = "baseline,system,system_no_verify,system_no_numeric",
  [int]$Limit = 0,
  # llama-3.3-70b-versatile was retired from Groq (404 model_not_found), so the
  # hosted roles default to gpt-oss-120b, the strongest Groq model available.
  [string]$BaselineModel = "openai/gpt-oss-120b",
  [string]$VerifierModel = "openai/gpt-oss-120b",
  [string]$GeminiJudgeModel = "gemini-2.5-flash",
  [switch]$RetrievalOnly
)
$ErrorActionPreference = "Stop"
$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }

if ($RetrievalOnly) {
  $ErrorActionPreference = "Continue"   # PS 5.1 treats any stderr line from python as fatal under "Stop"
  & $python -m scripts.run_eval --dataset $Dataset --retrieval-only `
      --retrievers hybrid,bm25_plain,'hybrid+rewrite',full --out "$Out-retrieval"
  Write-Host "`nRetrieval ablation written to $Out-retrieval\results.md" -ForegroundColor Green
  exit $LASTEXITCODE
}

if (-not $GroqKey) { throw "Pass -GroqKey or set GROQ_API_KEY. Use -RetrievalOnly to run without any model." }

# Baseline: a strong hosted general-purpose model doing plain RAG on identical inputs.
$env:LEXIMIND_BASELINE_LLM_PROVIDER = "groq"
$env:LEXIMIND_BASELINE_LLM_MODEL    = $BaselineModel
$env:LEXIMIND_BASELINE_API_KEY      = $GroqKey

# Our system: local generator, independent hosted verifier.
$env:LEXIMIND_CHAT_LLM_PROVIDER     = "ollama"
$env:LEXIMIND_CHAT_LLM_MODEL        = if ($env:LEXIMIND_CHAT_LLM_MODEL) { $env:LEXIMIND_CHAT_LLM_MODEL } else { "qwen3:4b-instruct" }
$env:LEXIMIND_VERIFIER_LLM_PROVIDER = "groq"
$env:LEXIMIND_VERIFIER_LLM_MODEL    = $VerifierModel
$env:LEXIMIND_VERIFIER_API_KEY      = $GroqKey

# Judge: prefer a different family from both generator and baseline.
if ($GeminiKey) {
  $env:LEXIMIND_JUDGE_LLM_PROVIDER = "gemini"
  $env:LEXIMIND_JUDGE_LLM_MODEL    = $GeminiJudgeModel
  $env:LEXIMIND_JUDGE_API_KEY      = $GeminiKey
} else {
  Write-Host "No Gemini key: judging with gpt-oss-120b, the SAME model as the baseline. Report this." -ForegroundColor Yellow
  Write-Host "A separate provider for the judge makes the 35% groundedness score far more defensible." -ForegroundColor Yellow
  $env:LEXIMIND_JUDGE_LLM_PROVIDER = "groq"
  $env:LEXIMIND_JUDGE_LLM_MODEL    = "openai/gpt-oss-120b"
  $env:LEXIMIND_JUDGE_API_KEY      = $GroqKey
}

$arguments = @("-m","scripts.run_eval","--dataset",$Dataset,"--arms",$Arms,"--split","all","--out",$Out)
if ($Limit -gt 0) { $arguments += @("--limit","$Limit") }
$ErrorActionPreference = "Continue"     # progress and warnings go to stderr; only the exit code matters
& $python @arguments
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Host "`nEvaluation exited with code $code" -ForegroundColor Red; exit $code }
Write-Host "`nResults table: $Out\results.md" -ForegroundColor Green
Write-Host "Paste the groundedness and fabrication rows straight into the write-up." -ForegroundColor Green
