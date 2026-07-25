from pathlib import Path

import pytest

from scripts.check_repo_privacy import forbidden_path_reason, scan_tracked_tree
from scripts.new_visual_project import PROJECT_DIRECTORIES, create_project, normalize_slug


@pytest.mark.parametrize(
    "path",
    [
        "internal/pilot/video.mp4",
        "projects/customer.vcg.json",
        "app/exports/final.mp4",
        "app/temp/transcript.json",
        "somewhere/interview.srt",
        "edit/project.prproj",
    ],
)
def test_private_paths_are_rejected(path: str) -> None:
    assert forbidden_path_reason(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        "app/exports/.gitkeep",
        "app/temp/.gitkeep",
        "projects/.gitkeep",
        "visual-production/modules/catalog.json",
        "docs/assets/sanitized-example.png",
    ],
)
def test_public_paths_are_allowed(path: str) -> None:
    assert forbidden_path_reason(path) is None


def test_scan_rejects_personal_absolute_path(tmp_path: Path) -> None:
    document = tmp_path / "notes.md"
    personal_path = "C:" + "\\Users\\creator\\Videos\\source.mp4"
    document.write_text(f"Private input: {personal_path}", encoding="utf-8")

    findings = scan_tracked_tree(tmp_path, ["notes.md"])

    assert findings
    assert "personal absolute" in findings[0].reason


def test_create_project_builds_private_structure(tmp_path: Path) -> None:
    project = create_project("My Next Video", tmp_path / "private", repo_root=None)

    assert project.name == "my-next-video"
    assert (project / ".vcg-private").is_file()
    assert all((project / name).is_dir() for name in PROJECT_DIRECTORIES)


def test_create_project_refuses_public_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError, match="Refusing"):
        create_project("private video", repo / "internal", repo_root=repo)


def test_normalize_slug_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        normalize_slug("---")
