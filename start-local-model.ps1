$ErrorActionPreference = 'Stop'
$taskRuntime = Join-Path $PSScriptRoot '.runtime\ollama'
$taskBinary = Join-Path $taskRuntime 'ollama.exe'
if (-not (Test-Path -LiteralPath $taskBinary)) {
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'scripts\setup_local_model.py')
    if ($LASTEXITCODE -ne 0) { throw 'Local runtime setup failed.' }
}
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $PSScriptRoot '.runtime\models'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 } catch {
    Start-Process -FilePath $taskBinary -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRuntime 'server.stdout.log') -RedirectStandardError (Join-Path $taskRuntime 'server.stderr.log') | Out-Null
    Start-Sleep -Seconds 2
}
& $taskBinary pull 'qwen3:4b-instruct'
if ($LASTEXITCODE -ne 0) { throw 'Local model download failed.' }
