"""The authoring skill is part of the contract, so it is version-controlled and checked.

It previously lived only in `app/temp/`, unversioned, and referenced a file that did not exist.
An agent following a broken reference invents the missing guidance.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".claude" / "skills" / "vcg-visual-producer"
LINK = re.compile(r"\[[^\]]+\]\((?P<target>[^)#]+)\)")
BACKTICK_PATH = re.compile(r"`(?P<target>(?:docs|visual-production|scripts|app|web|tests)/[A-Za-z0-9._/-]+)`")


def _markdown_files() -> list[Path]:
    return sorted(SKILL_ROOT.rglob("*.md"))


def test_the_skill_is_version_controlled() -> None:
    assert (SKILL_ROOT / "SKILL.md").is_file()
    assert _markdown_files()


@pytest.mark.parametrize("document", _markdown_files(), ids=lambda path: path.name)
def test_every_relative_link_in_the_skill_resolves(document: Path) -> None:
    text = document.read_text(encoding="utf-8")
    missing = [
        target
        for target in (match.group("target").strip() for match in LINK.finditer(text))
        if not target.startswith(("http://", "https://", "mailto:"))
        and not (document.parent / target).exists()
    ]

    assert missing == []


@pytest.mark.parametrize("document", _markdown_files(), ids=lambda path: path.name)
def test_every_repository_path_the_skill_names_exists(document: Path) -> None:
    text = document.read_text(encoding="utf-8")
    missing = sorted({
        target
        for target in (match.group("target") for match in BACKTICK_PATH.finditer(text))
        if not (ROOT / target).exists()
    })

    assert missing == []
