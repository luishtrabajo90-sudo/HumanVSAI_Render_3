param(
    [string]$Source = "C:\Users\gbzk\Downloads\Games\Games\real_vs_ia",
    [string]$Destination = "C:\Users\gbzk\Downloads\respaldo game"
)

$ErrorActionPreference = "Stop"
$Compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $Compiler)) {
    throw "No se encontró el compilador C# requerido: $Compiler"
}

$Executable = Join-Path $env:TEMP "ProjectBackup.exe"
$SourceCode = Join-Path $PSScriptRoot "Program.cs"
& $Compiler /nologo /target:exe /out:$Executable $SourceCode
if ($LASTEXITCODE -ne 0) {
    throw "La compilación de ProjectBackup falló con código $LASTEXITCODE."
}

& $Executable $Source $Destination
exit $LASTEXITCODE
