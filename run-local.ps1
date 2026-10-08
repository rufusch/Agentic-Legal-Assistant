$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:BACKEND_DEMO = '1'
if (!$env:BACKEND_CORS_ORIGINS) { $env:BACKEND_CORS_ORIGINS = 'http://127.0.0.1:5500,http://localhost:5500,http://localhost:5173' }
$env:BACKEND_STORAGE = Join-Path $PSScriptRoot '.data-demo'
if (!$env:LEXIMIND_MODEL_NUM_THREADS) { $env:LEXIMIND_MODEL_NUM_THREADS = '2' }
$taskModelBinary = Join-Path $PSScriptRoot '.runtime\ollama\ollama.exe'
if ((Test-Path -LiteralPath $taskModelBinary) -and (!$env:LEXIMIND_REVIEW_LLM_PROVIDER -or $env:LEXIMIND_REVIEW_LLM_PROVIDER -eq 'ollama')) {
    try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 } catch {
        $env:OLLAMA_HOST = '127.0.0.1:11434'
        $env:OLLAMA_MODELS = Join-Path $PSScriptRoot '.runtime\models'
        $env:OLLAMA_NO_CLOUD = '1'
        $env:OLLAMA_NUM_PARALLEL = '1'
        $env:OLLAMA_MAX_LOADED_MODELS = '1'
        Start-Process -FilePath $taskModelBinary -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime\ollama\server.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime\ollama\server.stderr.log') | Out-Null
    }
}
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
