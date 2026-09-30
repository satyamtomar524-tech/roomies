$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
}
if ($pythonCommand) {
    & $pythonCommand.Source -m roommate @args
    exit $LASTEXITCODE
}

# Codex ships a Python runtime; use it if Python is not on this computer's PATH.
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython -m roommate @args
    exit $LASTEXITCODE
}

Write-Error 'Python 3.10 or newer is required. Install Python, then run: python -m roommate'
