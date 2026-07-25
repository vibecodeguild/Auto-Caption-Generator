from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


PROJECT_DIRECTORIES = ("source", "transcript", "assets", "plans", "working", "renders")


def default_workspace_root() -> Path:
    configured = os.environ.get("VCG_PRIVATE_WORKSPACE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Videos" / "VCG Projects"


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Project name must contain at least one letter or number.")
    return slug


def repository_root(start: Path) -> Path | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return None
    return Path(completed.stdout.strip()).resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def create_project(name: str, root: Path, repo_root: Path | None) -> Path:
    project = (root.expanduser().resolve() / normalize_slug(name)).resolve()
    if repo_root is not None and _is_within(project, repo_root.resolve()):
        raise ValueError(
            f"Refusing to create private project inside public repository: {project}. "
            "Choose a root outside the Git checkout."
        )

    project.mkdir(parents=True, exist_ok=False)
    for directory in PROJECT_DIRECTORIES:
        (project / directory).mkdir()
    (project / ".vcg-private").write_text(
        "Private creator workspace. Never add this directory to a public Git repository.\n",
        encoding="utf-8",
    )
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a private VCG visual-production project outside Git.")
    parser.add_argument("name", help="Human-readable project name")
    parser.add_argument("--root", type=Path, default=default_workspace_root())
    args = parser.parse_args()

    repo = repository_root(Path.cwd())
    try:
        project = create_project(args.name, args.root, repo)
    except (FileExistsError, ValueError) as exc:
        parser.error(str(exc))
    print(project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
