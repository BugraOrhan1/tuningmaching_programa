$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$appPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $appPython)) {
    $appPython = Join-Path $PSScriptRoot '.runtime\python\python.exe'
}
if (-not (Test-Path -LiteralPath $appPython)) {
    Write-Error 'Installeer Python 3.12+ en volg de installatie in README.md.'
}
& $appPython -m app.main gui
