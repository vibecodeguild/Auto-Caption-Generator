$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "This command must run inside the VCG AutoCaption Git repository."
}

$hookPath = Join-Path $repoRoot ".git\hooks\pre-commit"
$hook = @'
#!/bin/sh
set -e

if [ -x ./.venv/Scripts/python.exe ]; then
  ./.venv/Scripts/python.exe scripts/check_repo_privacy.py --history
else
  python scripts/check_repo_privacy.py --history
fi
'@

Set-Content -LiteralPath $hookPath -Value $hook -Encoding ascii
Write-Host "Installed privacy pre-commit hook at $hookPath"
