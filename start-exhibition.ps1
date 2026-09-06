param(
    [ValidateRange(1, 65535)]
    [int]$Port = 5000,
    [string]$Cloudflared = "",
    [switch]$ReuseFlask
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv-local\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

$Arguments = @((Join-Path $PSScriptRoot "scripts\start_exhibition.py"), "--port", "$Port")
if ($Cloudflared) {
    $Arguments += @("--cloudflared", $Cloudflared)
}
if ($ReuseFlask) {
    $Arguments += "--reuse-flask"
}

& $Python @Arguments
exit $LASTEXITCODE
