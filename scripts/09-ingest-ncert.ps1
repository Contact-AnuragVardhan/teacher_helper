param(
    [string]$PythonCommand = "python",
    [string]$File,
    [string]$Directory,
    [switch]$TruncateFirst
)

if ([string]::IsNullOrWhiteSpace($File) -and [string]::IsNullOrWhiteSpace($Directory)) {
    throw "Provide either -File or -Directory."
}

if (-not [string]::IsNullOrWhiteSpace($File) -and -not [string]::IsNullOrWhiteSpace($Directory)) {
    throw "Provide only one of -File or -Directory."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ingestScript = Join-Path $scriptRoot "ingest_ncert.py"

$arguments = @($ingestScript)

if (-not [string]::IsNullOrWhiteSpace($File)) {
    $arguments += @("--file", $File)
}
else {
    $arguments += @("--dir", $Directory)
}

if ($TruncateFirst) {
    $arguments += "--truncate-first"
}

& $PythonCommand @arguments
if ($LASTEXITCODE -ne 0) {
    throw "NCERT ingestion failed with exit code $LASTEXITCODE."
}
