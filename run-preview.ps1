$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Error 'Create the environment first: python -m venv .venv; then install requirements-cv.txt using that environment.'
    exit 2
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $pythonPath -m gesture_control --config settings.example.json --preview @args
    $resultCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $resultCode
