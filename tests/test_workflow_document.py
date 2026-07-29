"""The workflow document must name one authority, not five stacked dated contracts.

An agent reading five contracts that disagree picks whichever one suits it.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "docs" / "visual-production-workflow.md"
SKILL = ROOT / ".claude" / "skills" / "vcg-visual-producer" / "SKILL.md"
DATED_CONTRACT = re.compile(r"^## (?!SUPERSEDED)(.*(?:Contract|Expansion).*\d{4})\s*$", re.MULTILINE)


def test_only_the_current_contract_claims_authority() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "## The Current Contract" in text
    assert DATED_CONTRACT.findall(text) == [], "a dated contract still sits outside the history appendix"
    assert text.count("single product authority") == 0


def test_superseded_contracts_are_kept_but_clearly_labelled() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    history_start = text.index("# History: superseded contracts")

    superseded = re.findall(r"^## SUPERSEDED — .*$", text, re.MULTILINE)
    assert len(superseded) >= 4
    for heading in superseded:
        assert text.index(heading) > history_start, f"{heading} is above the history appendix"


def test_the_skill_points_at_the_current_contract() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "The Current Contract" in text
    assert "Canonical Cook and Approval Contract" not in text
