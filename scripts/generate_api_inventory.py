"""Regenerate the API Inventory section of docs/current-system.md from the route table.

The inventory was hand-maintained and had fallen 55 routes behind the code. Run this after
adding or removing a route:

    python scripts/generate_api_inventory.py

Purposes come from each handler's docstring when it has one, so the way to document a route is to
document the function.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_API = ROOT / "app" / "web_api.py"
DOC = ROOT / "docs" / "current-system.md"
HEADING = "## API Inventory"
HTTP_METHODS = {"get", "post", "patch", "put", "delete", "head", "options"}
GROUPS = [
    ("/api/visual", "Visual Production"),
    ("/api/creator-library", "Creator Library"),
    ("/api/video-project", "Video projects"),
    ("/api/audio", "Audio"),
    ("/api/projects", "Transcript projects"),
]


def routes() -> list[tuple[str, str, str]]:
    tree = ast.parse(WEB_API.read_text(encoding="utf-8"))
    found: list[tuple[str, str, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            function = decorator.func
            if not (isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name)):
                continue
            if function.value.id != "app" or function.attr.lower() not in HTTP_METHODS:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue
            summary = (ast.get_docstring(node) or "").strip().splitlines()
            purpose = summary[0] if summary else node.name.replace("_", " ").capitalize()
            found.append((function.attr.upper(), decorator.args[0].value, purpose.rstrip(".")))
    return found


def markdown() -> str:
    grouped: dict[str, list[tuple[str, str, str]]] = {label: [] for _prefix, label in GROUPS}
    grouped["Other"] = []
    for method, path, purpose in routes():
        label = next((label for prefix, label in GROUPS if path.startswith(prefix)), "Other")
        grouped[label].append((method, path, purpose))

    lines = [
        HEADING,
        "",
        f"Generated from `app/web_api.py` by `scripts/generate_api_inventory.py`. {len(routes())} routes.",
        "Edit the route or its docstring, then regenerate; do not edit this section by hand.",
    ]
    for label, entries in grouped.items():
        if not entries:
            continue
        lines += ["", f"### {label}", "", "| Method | Route | Purpose |", "| --- | --- | --- |"]
        lines += [
            f"| {method} | `{path}` | {purpose} |"
            for method, path, purpose in sorted(entries, key=lambda item: (item[1], item[0]))
        ]
    return "\n".join(lines) + "\n"


def rewrite() -> bool:
    text = DOC.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(HEADING)}\n.*?(?=^## (?!#)|\Z)", re.DOTALL | re.MULTILINE)
    if not pattern.search(text):
        raise SystemExit(f"Could not find the '{HEADING}' section in {DOC}.")
    updated = pattern.sub(markdown() + "\n", text)
    if updated == text:
        return False
    DOC.write_text(updated, encoding="utf-8")
    return True


if __name__ == "__main__":
    print("Updated" if rewrite() else "Already current", DOC.relative_to(ROOT).as_posix())
    sys.exit(0)
