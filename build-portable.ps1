$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $pythonPath (Join-Path $PSScriptRoot 'tools\build_portable.py')
exit $LASTEXITCODE
