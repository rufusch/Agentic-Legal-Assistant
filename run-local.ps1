param(
    [ValidateRange(1,65535)][int]$Port = 8765,
    [string]$PythonPath = '',
    [switch]$Reload,
    [switch]$Hosted
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:BACKEND_DEMO = '1'
if (!$env:BACKEND_CORS_ORIGINS) { $env:BACKEND_CORS_ORIGINS = 'http://127.0.0.1:5500,http://localhost:5500,http://localhost:5173' }
if (!$env:BACKEND_STORAGE) { $env:BACKEND_STORAGE = Join-Path $PSScriptRoot '.data-demo' }
if (!$env:LEXIMIND_MODEL_NUM_THREADS) { $env:LEXIMIND_MODEL_NUM_THREADS = '2' }
# Use the configured hosted service when its key is saved in Windows.
# Credentials stay in the process environment and are never written to source.
if ($Hosted -and !$env:GROQ_API_KEY) { $env:GROQ_API_KEY = [Environment]::GetEnvironmentVariable('GROQ_API_KEY', 'User') }
if ($Hosted -and !$env:GROQ_API_KEY) { throw 'Hosted mode requires GROQ_API_KEY in the process or Windows user environment.' }
if ($Hosted -and !$env:LEXIMIND_LLM_PROVIDER -and !$env:LEXIMIND_REVIEW_LLM_PROVIDER) {
    $env:LEXIMIND_LLM_PROVIDER = 'groq'
    $env:LEXIMIND_LLM_MODEL = 'qwen/qwen3.8-27b'
    $env:LEXIMIND_VERIFIER_LLM_PROVIDER = 'groq'
    $env:LEXIMIND_VERIFIER_LLM_MODEL = 'openai/gpt-oss-20b'
}
$taskModelBinary = Join-Path $PSScriptRoot '.runtime\ollama\ollama.exe'
if (!$Hosted) {
    if (!(Test-Path -LiteralPath $taskModelBinary)) { throw 'Local Ollama is missing. Run start-local-model.ps1 first to install Qwen.' }
    # Explicit local mode also clears inherited role overrides from hosted runs.
    $env:LEXIMIND_LLM_PROVIDER='ollama'
    $env:LEXIMIND_LLM_MODEL='qwen3:4b-instruct'
    $env:LEXIMIND_LLM_BASE_URL='http://127.0.0.1:11434'
    foreach ($taskRole in @('REVIEW','CHAT','DRAFTING','RESEARCH','VERIFIER','RERANK','REWRITE')) {
        [Environment]::SetEnvironmentVariable("LEXIMIND_${taskRole}_LLM_PROVIDER",'ollama','Process')
        [Environment]::SetEnvironmentVariable("LEXIMIND_${taskRole}_LLM_MODEL",'qwen3:4b-instruct','Process')
        [Environment]::SetEnvironmentVariable("LEXIMIND_${taskRole}_BASE_URL",'http://127.0.0.1:11434','Process')
    }
    if (!$env:LEXIMIND_MODEL_CONTEXT_LENGTH) { $env:LEXIMIND_MODEL_CONTEXT_LENGTH='16384' }
    if (!$env:LEXIMIND_SOURCE_CONTEXT_CHARACTERS) { $env:LEXIMIND_SOURCE_CONTEXT_CHARACTERS='12000' }
    if (!$env:LEXIMIND_MODEL_MAX_OUTPUT_TOKENS) { $env:LEXIMIND_MODEL_MAX_OUTPUT_TOKENS='4000' }
    if (!$env:LEXIMIND_DRAFTING_MAX_OUTPUT_TOKENS) { $env:LEXIMIND_DRAFTING_MAX_OUTPUT_TOKENS='6000' }
}
if ((Test-Path -LiteralPath $taskModelBinary) -and (!$env:LEXIMIND_LLM_PROVIDER -or $env:LEXIMIND_LLM_PROVIDER -eq 'ollama') -and (!$env:LEXIMIND_REVIEW_LLM_PROVIDER -or $env:LEXIMIND_REVIEW_LLM_PROVIDER -eq 'ollama')) {
    try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 } catch {
        $env:OLLAMA_HOST = '127.0.0.1:11434'
        $env:OLLAMA_MODELS = Join-Path $PSScriptRoot '.runtime\models'
        $env:OLLAMA_NO_CLOUD = '1'
        $env:OLLAMA_NUM_PARALLEL = '1'
        $env:OLLAMA_MAX_LOADED_MODELS = '1'
        $env:OLLAMA_FLASH_ATTENTION = '1'
        $env:OLLAMA_KV_CACHE_TYPE = 'q8_0'
        Start-Process -FilePath $taskModelBinary -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime\ollama\server.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime\ollama\server.stderr.log') | Out-Null
    }
}
if (!$PythonPath) { $PythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (!(Test-Path -LiteralPath $PythonPath)) { throw 'Python environment is missing. Run setup.ps1 or pass -PythonPath pointing to your installed project environment.' }
$taskServerArguments = @('-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',"$Port",'--no-access-log')
if ($Reload) { $taskServerArguments += @('--reload','--reload-dir','backend') }
Write-Host "Open http://127.0.0.1:$Port"
& $PythonPath @taskServerArguments
