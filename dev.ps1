# Start backend (Uvicorn, auto-reload) and frontend (Vite) together for development on Windows.
#   pwsh ./dev.ps1
#   pwsh ./dev.ps1 -BackendPort 9000 -FrontendPort 5180
# The same environment variables as dev.sh also work: BACKEND_PORT, FRONTEND_PORT,
# BACKEND_HOST, FRONTEND_HOST, VITE_BACKEND_URL.
param(
  [int]$BackendPort = $(if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 8000 }),
  [int]$FrontendPort = $(if ($env:FRONTEND_PORT) { [int]$env:FRONTEND_PORT } else { 5173 }),
  [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
$frontendDir = Join-Path $root 'frontend'
$BackendHost = if ($env:BACKEND_HOST) { $env:BACKEND_HOST } else { '0.0.0.0' }
$FrontendHost = if ($env:FRONTEND_HOST) { $env:FRONTEND_HOST } else { '0.0.0.0' }
# The Vite dev server forwards /api to the backend; keep it in sync with the backend port.
if (-not $env:VITE_BACKEND_URL) { $env:VITE_BACKEND_URL = "http://127.0.0.1:$BackendPort" }

# Prefer the project's virtual environment when there is one.
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$python = if (Test-Path $venvPython) { $venvPython } else { 'python' }

function Install-BackendDeps {
  # Windows PowerShell 5.1 turns a native command's stderr into a terminating error when
  # $ErrorActionPreference is 'Stop', so check the exit code with errors relaxed.
  $ErrorActionPreference = 'Continue'
  & $python -c "import fastapi, uvicorn" 2>$null | Out-Null
  $ok = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = 'Stop'
  if ($ok) { return }
  Write-Host 'Installing backend dependencies...'
  & $python -m pip install -r (Join-Path $root 'backend/requirements.txt')
  if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
}

function Install-FrontendDeps {
  if (Test-Path (Join-Path $frontendDir 'node_modules\.bin\vite.cmd')) { return }
  Write-Host 'Installing frontend dependencies (npm ci)...'
  Push-Location $frontendDir
  try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
  } finally {
    Pop-Location
  }
}

function Stop-Tree($proc) {
  # npm/vite and uvicorn --reload start child processes; /T stops the whole tree.
  if ($proc -and -not $proc.HasExited) {
    $ErrorActionPreference = 'Continue'
    & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
  }
}

if (-not $SkipInstall) {
  Install-BackendDeps
  Install-FrontendDeps
}

Write-Host ("Starting backend (Uvicorn) on http://{0}:{1} ..." -f $BackendHost, $BackendPort)
$backendArgs = @('-m', 'uvicorn', 'backend.app.main:app', '--reload', '--host', "$BackendHost", '--port', "$BackendPort")
$backendProc = Start-Process -FilePath $python -ArgumentList $backendArgs -WorkingDirectory $root -PassThru -NoNewWindow

Write-Host ("Starting frontend (Vite) on http://{0}:{1} (API proxied to {2}) ..." -f $FrontendHost, $FrontendPort, $env:VITE_BACKEND_URL)
$viteCmd = Join-Path $frontendDir 'node_modules\.bin\vite.cmd'
$frontendArgs = @('--host', "$FrontendHost", '--port', "$FrontendPort", '--strictPort')
$frontendProc = Start-Process -FilePath $viteCmd -ArgumentList $frontendArgs -WorkingDirectory $frontendDir -PassThru -NoNewWindow

Write-Host 'Press Ctrl+C to stop both.'

try {
  # Windows PowerShell 5.1 has no "wait for any", so poll: when one stops, stop the other.
  while (-not $backendProc.HasExited -and -not $frontendProc.HasExited) {
    Start-Sleep -Milliseconds 500
  }
} finally {
  Stop-Tree $backendProc
  Stop-Tree $frontendProc
}
