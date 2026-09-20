$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = "$root"
if (-not $env:AGENT_BACKEND) { $env:AGENT_BACKEND = "ollama" }
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "llama3.1" }
if (-not $env:HOST) { $env:HOST = "127.0.0.1" }
if (-not $env:PORT) { $env:PORT = "8000" }
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
if (Test-Path $ollama) {
    $env:PATH = "$ollama;$env:PATH"
}
Set-Location (Join-Path $root "service")
Write-Host "Agent service $env:AGENT_BACKEND model=$env:OLLAMA_MODEL"
Write-Host "Health: http://127.0.0.1:$($env:PORT)/health"
python -m uvicorn app:app --host $env:HOST --port $env:PORT
