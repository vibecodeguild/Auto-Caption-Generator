from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PRIVATE_SUFFIXES = (
    ".vcg.json",
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".wmv",
    ".mxf",
    ".mp3",
    ".m4a",
    ".wav",
    ".aac",
    ".flac",
    ".aiff",
    ".ass",
    ".srt",
    ".vtt",
    ".prproj",
    ".aep",
    ".aepx",
    ".mogrt",
    ".drp",
)
PRIVATE_FILENAMES = {
    "transcript.json",
    "transcript.raw.json",
    "transcript.editor.json",
    "transcript.clean.txt",
    # Populated Graphics Library catalogs are private; only the empty schema may be public.
    "source-receipt.json",
}
TEXT_SUFFIXES = {
    ".css", ".html", ".js", ".json", ".md", ".mjs", ".py", ".ps1",
    ".tsx", ".ts", ".txt", ".yaml", ".yml",
}
PERSONAL_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:" + r"\\Users\\" + r"[^\\\s]+\\", re.IGNORECASE),
    re.compile(r"[A-Za-z]:" + r"\\Claude\\", re.IGNORECASE),
    re.compile("/" + r"Users/[^/\s]+/"),
    re.compile("/" + r"home/[^/\s]+/"),
)
MAX_TRACKED_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    path: str
    reason: str


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout


def tracked_paths(repo: Path) -> list[str]:
    output = _git(repo, "ls-files", "--cached", "--others", "--exclude-standard")
    return [line for line in output.splitlines() if line]


def historical_paths(repo: Path) -> list[str]:
    output = _git(repo, "log", "--all", "--name-only", "--pretty=format:")
    return sorted({line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()})


def forbidden_path_reason(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    lowered = normalized.lower()
    name = Path(lowered).name

    if lowered == "internal" or lowered.startswith("internal/"):
        return "private internal workspace"
    for directory in ("projects", "app/exports", "app/temp"):
        if lowered.startswith(f"{directory}/") and name != ".gitkeep":
            return f"generated/private content under {directory}"
    if name in PRIVATE_FILENAMES:
        return "transcript artifact"
    if name.startswith(".tmp-") or name.startswith(".tmp_"):
        return "local scratch artifact"
    if lowered.endswith(PRIVATE_SUFFIXES):
        return "creator media or project format"
    return None


def scan_tracked_tree(repo: Path, paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        reason = forbidden_path_reason(path)
        if reason:
            findings.append(Finding(path, reason))
            continue

        absolute = repo / path
        if absolute.is_file() and absolute.stat().st_size > MAX_TRACKED_BYTES:
            findings.append(Finding(path, f"tracked file exceeds {MAX_TRACKED_BYTES // (1024 * 1024)} MB"))
            continue

        if absolute.suffix.lower() not in TEXT_SUFFIXES or not absolute.is_file():
            continue
        try:
            content = absolute.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in PERSONAL_PATH_PATTERNS:
            if pattern.search(content):
                findings.append(Finding(path, "contains a personal absolute filesystem path"))
                break
    return findings


def scan_history_paths(paths: list[str]) -> list[Finding]:
    return [
        Finding(path, f"historical path contains {reason}")
        for path in paths
        if (reason := forbidden_path_reason(path)) is not None
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when private creator material is tracked by Git.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--history", action="store_true", help="Also scan file paths from every local Git ref.")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    try:
        findings = scan_tracked_tree(repo, tracked_paths(repo))
        if args.history:
            findings.extend(scan_history_paths(historical_paths(repo)))
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Privacy check could not inspect Git: {exc}", file=sys.stderr)
        return 2

    unique = sorted(set(findings), key=lambda item: (item.path, item.reason))
    if unique:
        print("Privacy check FAILED. Remove these files from Git before publishing:")
        for finding in unique:
            print(f"- {finding.path}: {finding.reason}")
        return 1

    scope = "tracked tree and history paths" if args.history else "tracked tree"
    print(f"Privacy check passed: no private creator material found in the {scope}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
