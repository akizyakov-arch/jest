$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Error 'Create .venv and install requirements-cv.txt first.'
    exit 2
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $pythonPath -m gesture_control --config settings.example.json --control --log-dir logs @args
    $resultCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $resultCode
