param([switch]$LocalModel)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $taskPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
}
& $taskPython -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if ($LocalModel) {
    $taskModel = Join-Path $PSScriptRoot '.runtime\ollama\ollama.exe'
    if (!(Test-Path -LiteralPath $taskModel)) {
        & $taskPython -m scripts.setup_local_model
        if ($LASTEXITCODE -ne 0) { throw 'Official model runtime download failed.' }
    }
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $env:OLLAMA_MODELS = Join-Path $PSScriptRoot '.runtime\models'
    $env:OLLAMA_NO_CLOUD = '1'
    try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 } catch {
        Start-Process -FilePath $taskModel -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime\ollama\server.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime\ollama\server.stderr.log') | Out-Null
        $taskReady = $false
        for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
            try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2; $taskReady = $true; break } catch { Start-Sleep -Seconds 1 }
        }
        if (!$taskReady) { throw 'Local model service did not start.' }
    }
    & $taskModel pull qwen3:4b-instruct
    if ($LASTEXITCODE -ne 0) { throw 'Model weight download failed.' }
}
Write-Host 'Setup complete. Run .\run-local.ps1 and open http://127.0.0.1:8000/.'
