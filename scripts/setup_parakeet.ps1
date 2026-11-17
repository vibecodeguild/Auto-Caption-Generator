param([string]$Python = ".\.venv\Scripts\python.exe")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (!(Test-Path -LiteralPath ".venv-parakeet\Scripts\python.exe")) {
        & $Python -m venv .venv-parakeet
        if ($LASTEXITCODE -ne 0) { throw "Could not create isolated Parakeet environment. Use Python 3.12." }
    }
    & .\.venv-parakeet\Scripts\python.exe -m pip install -r requirements-parakeet.txt
    if ($LASTEXITCODE -ne 0) { throw "Parakeet runtime installation failed." }
    $modelName = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
    New-Item -ItemType Directory -Force models | Out-Null
    if (!(Test-Path -LiteralPath "models\$modelName\tokens.txt")) {
        & curl.exe -L --fail --retry 3 -o models/parakeet.tar.bz2.partial "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$modelName.tar.bz2"
        if ($LASTEXITCODE -ne 0) { throw "Parakeet model download failed." }
        Move-Item -LiteralPath models/parakeet.tar.bz2.partial -Destination models/parakeet.tar.bz2 -Force
        $entries = & tar -tf models/parakeet.tar.bz2
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect model archive." }
        foreach ($entry in $entries) {
            if (!$entry.StartsWith("$modelName/") -or $entry -match '(^|/)\.\.(/|$)') {
                throw "Unexpected path in model archive: $entry"
            }
        }
        & tar -xf models/parakeet.tar.bz2 -C models
        if ($LASTEXITCODE -ne 0) { throw "Parakeet model extraction failed." }
    }
    & .\.venv-parakeet\Scripts\python.exe scripts/probe_parakeet.py "models/$modelName" "models/$modelName/test_wavs/en.wav"
    if ($LASTEXITCODE -ne 0) { throw "Parakeet GPU probe failed; inspect the diagnostic before using CPU fallback." }
    Write-Output "Runtime installed. Check app/temp/parakeet-probe/cuda-result.json for executed providers."
} finally {
    Pop-Location
}
