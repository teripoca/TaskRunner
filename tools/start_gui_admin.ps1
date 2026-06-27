$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $PSScriptRoot
$appDir = Join-Path $base 'app'
$script = Join-Path $appDir 'script_task_runner_gui.py'

if (-not (Test-Path $script)) {
    Write-Host "Task runner script not found: $script"
    exit 1
}

Start-Process -FilePath 'pythonw.exe' -ArgumentList @("`"$script`"") -WorkingDirectory $appDir -Verb RunAs
