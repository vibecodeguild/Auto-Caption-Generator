"""Masterbeater Stage 1 — run the skill against a locked transcript.

Canonical beat timing is **frames**, resolved from transcript word IDs.
Seconds are informational for human review only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.process_utils import hidden_subprocess_flags
from app.core.video_project import (
    preferred_stage_source,
    resolve_video_project_path,
    video_project_root,
)

BEAT_TYPES = frozenset(
    {
        "hook",
        "setup",
        "punchline",
        "aftershock",
        "callback",
        "proof",
        "context",
        "cta",
        "example",
        "prompt",
        "list",
        "structure",
        "ui",
    }
)

# Agent Stage 1 suggestion — never overwritten by human UI edits.
OUTPUT_FILENAME = "masterbeater-beats.json"
# Human working copy (auto-saved as membership edits are made).
REVIEWED_FILENAME = "masterbeater-beats-reviewed.json"
# Append-only log of membership edits for process refinement.
LEDGER_FILENAME = "masterbeater-edit-ledger.json"

# LLM returns word anchors; app resolves frames + exact text.
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "beats"],
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["talking-head", "tutorial", "hybrid"],
        },
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "beatType",
                    "startWordId",
                    "endWordId",
                    "rationale",
                ],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "beatType": {
                        "type": "string",
                        "enum": sorted(BEAT_TYPES),
                    },
                    "startWordId": {"type": "string", "minLength": 1},
                    "endWordId": {"type": "string", "minLength": 1},
                    "span": {
                        "type": "string",
                        "description": "Optional short editorial label; exact words come from the transcript.",
                    },
                    "rationale": {"type": "string", "minLength": 1},
                },
            },
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skill_path(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / ".grok" / "skills" / "masterbeater" / "SKILL.md"


def universe_path(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / "docs" / "vcg-graphics-process" / "beat-universe.md"


def output_path_for_project(project_root: Path) -> Path:
    """Original Masterbeater agent output (immutable from the review UI)."""
    return Path(project_root).expanduser().resolve() / OUTPUT_FILENAME


def reviewed_path_for_project(project_root: Path) -> Path:
    """Human-edited working copy used by Visual Package Stage 1."""
    return Path(project_root).expanduser().resolve() / REVIEWED_FILENAME


def ledger_path_for_project(project_root: Path) -> Path:
    """Append-only edit ledger for comparing human fixes vs agent suggestions."""
    return Path(project_root).expanduser().resolve() / LEDGER_FILENAME


def final_transcript_path(manifest_path: Path, manifest: dict) -> Path:
    return resolve_video_project_path(manifest_path, manifest, "finalTranscript")


def load_transcript_document(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def transcript_fps(document: dict) -> float:
    project = document.get("project") or document
    try:
        return float(project.get("fps") or 30.0)
    except (TypeError, ValueError):
        return 30.0


def extract_words(document: dict) -> list[dict[str, Any]]:
    """Normalize transcript words with frame-first fields."""

    project = document.get("project") or document
    raw_words = project.get("words") or []
    fps = transcript_fps(document)
    out: list[dict[str, Any]] = []
    for word in raw_words:
        word_id = str(word.get("id") or "").strip()
        if not word_id:
            continue
        text = str(word.get("text") or word.get("raw") or "").strip()
        if not text:
            continue

        start_frame = word.get("start_frame", word.get("startFrame"))
        end_frame = word.get("end_frame", word.get("endFrame"))
        start_sec = word.get("start")
        end_sec = word.get("end")

        if start_frame is None and start_sec is not None:
            start_frame = int(round(float(start_sec) * fps))
        if end_frame is None and end_sec is not None:
            # Inclusive end frame from exclusive-ish seconds boundary.
            end_frame = max(int(start_frame or 0), int(round(float(end_sec) * fps)) - 1)

        if start_frame is None or end_frame is None:
            continue
        start_frame = int(start_frame)
        end_frame = int(end_frame)
        if end_frame < start_frame:
            end_frame = start_frame

        if start_sec is None:
            start_sec = start_frame / fps
        if end_sec is None:
            end_sec = (end_frame + 1) / fps

        out.append(
            {
                "id": word_id,
                "text": text,
                "startFrame": start_frame,
                "endFrame": end_frame,  # inclusive word end frame in source transcript
                "endFrameExclusive": end_frame + 1,
                "startSec": float(start_sec),
                "endSec": float(end_sec),
            }
        )
    return out


def format_words_for_prompt(words: list[dict[str, Any]], *, fps: float) -> str:
    """Compact word index: id | frames | clock | text."""

    lines = [
        f"fps={fps:g}",
        "Each line: wordId | startFrame-endFrameInclusive | startSec-endSec | text",
        "Pick startWordId and endWordId from this index. App resolves frames.",
        "",
    ]
    for word in words:
        lines.append(
            f"{word['id']} | {word['startFrame']}-{word['endFrame']} | "
            f"{word['startSec']:.2f}-{word['endSec']:.2f} | {word['text']}"
        )
    return "\n".join(lines)


def format_sentences_for_prompt(document: dict) -> str:
    """Readable sentence overview (secondary context for the model)."""

    words = extract_words(document)
    if not words:
        return ""
    # Group consecutive words into loose lines of ~12 words for readability.
    chunks: list[str] = []
    buf: list[dict[str, Any]] = []
    for word in words:
        buf.append(word)
        if len(buf) >= 12 or word["text"].endswith((".", "?", "!")):
            text = " ".join(item["text"] for item in buf)
            chunks.append(
                f"[{buf[0]['startSec']:.1f}-{buf[-1]['endSec']:.1f} | "
                f"{buf[0]['id']}..{buf[-1]['id']}] {text}"
            )
            buf = []
    if buf:
        text = " ".join(item["text"] for item in buf)
        chunks.append(
            f"[{buf[0]['startSec']:.1f}-{buf[-1]['endSec']:.1f} | "
            f"{buf[0]['id']}..{buf[-1]['id']}] {text}"
        )
    return "\n".join(chunks)


def canonicalize_word_id(raw: str, words: list[dict[str, Any]]) -> str | None:
    """Map model word-id variants onto real transcript ids (e.g. w1 → w000001)."""

    token = str(raw or "").strip()
    if not token:
        return None
    by_id = {word["id"]: word["id"] for word in words}
    if token in by_id:
        return token
    lower_map = {word["id"].lower(): word["id"] for word in words}
    if token.lower() in lower_map:
        return lower_map[token.lower()]

    digits = re.search(r"(\d+)", token)
    if not digits:
        return None
    number = int(digits.group(1))
    # Prefer common zero-padded forms used by this app (w000001).
    for width in (6, 5, 4, 3, 2, 1):
        candidate = f"w{number:0{width}d}"
        if candidate in by_id:
            return candidate
        candidate_upper = f"W{number:0{width}d}"
        if candidate_upper in by_id:
            return candidate_upper
    for word in words:
        match = re.search(r"(\d+)", word["id"])
        if match and int(match.group(1)) == number:
            return word["id"]
    return None


def resolve_word_span(
    words: list[dict[str, Any]],
    *,
    start_word_id: str,
    end_word_id: str,
) -> dict[str, Any] | None:
    """Resolve inclusive word span to frames, times, and exact transcript text."""

    start_word_id = canonicalize_word_id(start_word_id, words) or ""
    end_word_id = canonicalize_word_id(end_word_id, words) or ""
    by_id = {word["id"]: (index, word) for index, word in enumerate(words)}
    if start_word_id not in by_id or end_word_id not in by_id:
        return None
    start_index, start_word = by_id[start_word_id]
    end_index, end_word = by_id[end_word_id]
    if end_index < start_index:
        start_index, end_index = end_index, start_index
        start_word, end_word = end_word, start_word
        start_word_id, end_word_id = end_word_id, start_word_id

    span_words = words[start_index : end_index + 1]
    exact = " ".join(item["text"] for item in span_words).strip()
    start_frame = int(start_word["startFrame"])
    end_frame_inclusive = int(end_word["endFrame"])
    end_frame_exclusive = end_frame_inclusive + 1
    return {
        "startWordId": start_word_id,
        "endWordId": end_word_id,
        "wordIds": [item["id"] for item in span_words],
        "wordsText": exact,
        "startFrame": start_frame,
        "endFrame": end_frame_inclusive,
        "endFrameExclusive": end_frame_exclusive,
        "startSec": float(start_word["startSec"]),
        "endSec": float(end_word["endSec"]),
    }


def resolve_word_span_from_seconds(
    words: list[dict[str, Any]],
    *,
    start_sec: float,
    end_sec: float,
) -> dict[str, Any] | None:
    """Legacy fallback: map a time range onto overlapping transcript words."""

    if end_sec <= start_sec or not words:
        return None
    selected = [
        word
        for word in words
        if word["endSec"] > start_sec and word["startSec"] < end_sec
    ]
    if not selected:
        # nearest word to start
        nearest = min(words, key=lambda item: abs(item["startSec"] - start_sec))
        selected = [nearest]
    return resolve_word_span(
        words,
        start_word_id=selected[0]["id"],
        end_word_id=selected[-1]["id"],
    )


def resolve_grok_executable() -> Path:
    env = (os.environ.get("GROK_CLI") or os.environ.get("VCG_GROK_CLI") or "").strip()
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return path
    which = shutil.which("grok")
    if which:
        return Path(which)
    home = Path.home() / ".grok" / "bin" / "grok.exe"
    if home.is_file():
        return home
    home_unix = Path.home() / ".grok" / "bin" / "grok"
    if home_unix.is_file():
        return home_unix
    raise FileNotFoundError(
        "Grok CLI not found. Install Grok Build or set GROK_CLI to the grok executable."
    )


def _extract_json_payload(raw: str) -> dict:
    raw = raw.strip()
    if not raw:
        raise ValueError("Masterbeater returned empty output.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ValueError("Masterbeater output was not valid JSON.") from None
        payload = json.loads(match.group(0))

    if isinstance(payload, dict) and "text" in payload and "beats" not in payload:
        text = payload.get("text")
        if isinstance(text, str):
            return _extract_json_payload(text)
        if isinstance(text, dict):
            payload = text
    if not isinstance(payload, dict):
        raise ValueError("Masterbeater JSON root must be an object.")
    return payload


def normalize_masterbeater_result(
    payload: dict,
    *,
    project_root: Path,
    transcript_path: Path,
    document: dict | None = None,
    duration_sec: float | None = None,
) -> dict[str, Any]:
    """Validate model output and bind every beat to transcript frames + words."""

    mode = str(payload.get("mode") or "tutorial").strip()
    if mode not in {"talking-head", "tutorial", "hybrid"}:
        mode = "tutorial"

    if document is None:
        document = load_transcript_document(transcript_path)
    words = extract_words(document)
    fps = transcript_fps(document)
    if not words:
        raise ValueError("Transcript has no words to bind beats against.")

    beats_out: list[dict[str, Any]] = []
    drop_reasons: list[str] = []
    for index, beat in enumerate(payload.get("beats") or [], start=1):
        if not isinstance(beat, dict):
            drop_reasons.append(f"beat[{index}]: not an object")
            continue
        beat_type = str(beat.get("beatType") or "").strip()
        if beat_type not in BEAT_TYPES:
            drop_reasons.append(f"beat[{index}]: unknown type {beat_type!r}")
            continue
        rationale = str(beat.get("rationale") or "").strip()
        if not rationale:
            drop_reasons.append(f"beat[{index}]: missing rationale")
            continue

        start_word_id = str(
            beat.get("startWordId") or beat.get("start_word_id") or ""
        ).strip()
        end_word_id = str(beat.get("endWordId") or beat.get("end_word_id") or "").strip()
        resolved: dict[str, Any] | None = None
        if start_word_id and end_word_id:
            resolved = resolve_word_span(
                words,
                start_word_id=start_word_id,
                end_word_id=end_word_id,
            )
            if resolved is None:
                drop_reasons.append(
                    f"beat[{index}]: word ids not in transcript "
                    f"({start_word_id!r}..{end_word_id!r})"
                )

        # Legacy / partial model output: time only → map onto words, then frames.
        if resolved is None:
            start_sec = beat.get("startSec", beat.get("start"))
            end_sec = beat.get("endSec", beat.get("end"))
            try:
                start_sec_f = float(start_sec)
                end_sec_f = float(end_sec)
            except (TypeError, ValueError):
                if start_word_id or end_word_id:
                    # already recorded word-id failure
                    continue
                drop_reasons.append(f"beat[{index}]: no word ids and no usable times")
                continue
            resolved = resolve_word_span_from_seconds(
                words, start_sec=start_sec_f, end_sec=end_sec_f
            )
            if resolved is None:
                drop_reasons.append(
                    f"beat[{index}]: could not map times {start_sec_f}-{end_sec_f} to words"
                )
                continue
        if resolved is None:
            continue

        editorial = str(beat.get("span") or "").strip()
        beat_id = str(beat.get("id") or f"beat-{index:03d}").strip() or f"beat-{index:03d}"
        beats_out.append(
            {
                "id": beat_id,
                "beatType": beat_type,
                "rationale": rationale,
                # Human labels
                "label": editorial or resolved["wordsText"],
                "span": editorial or resolved["wordsText"],
                # Exact transcript evidence
                "wordsText": resolved["wordsText"],
                "startWordId": resolved["startWordId"],
                "endWordId": resolved["endWordId"],
                "wordIds": resolved["wordIds"],
                # Canonical timing for graphic designer / build
                "startFrame": resolved["startFrame"],
                "endFrame": resolved["endFrame"],
                "endFrameExclusive": resolved["endFrameExclusive"],
                # Informational only
                "startSec": resolved["startSec"],
                "endSec": resolved["endSec"],
            }
        )

    gaps = [
        str(item).strip()
        for item in (payload.get("gaps") or [])
        if str(item).strip()
    ]
    if drop_reasons:
        gaps.append(
            f"Dropped {len(drop_reasons)} invalid beat(s) that could not bind to transcript words/frames."
        )
        # Keep a short sample of reasons for UI/debug (not hundreds of lines).
        gaps.extend(drop_reasons[:12])
        if len(drop_reasons) > 12:
            gaps.append(f"…and {len(drop_reasons) - 12} more drop reasons.")

    if duration_sec is None and words:
        duration_sec = float(words[-1]["endSec"])

    return {
        "agent": "masterbeater",
        "schemaVersion": 2,
        "mode": mode,
        "modeInferred": True,
        "timingAuthority": "frames",
        "fps": fps,
        "source": {
            "projectRoot": str(project_root),
            "transcript": str(transcript_path),
            "approxDurationSec": duration_sec,
            "wordCount": len(words),
        },
        "beatCount": len(beats_out),
        "beats": beats_out,
        "gaps": gaps,
        "notes": (
            "Canonical timing is startFrame/endFrameExclusive from transcript words. "
            "startSec/endSec are informational for human review. No graphicId at this stage."
        ),
    }


def load_masterbeater_output(project_root: Path) -> dict | None:
    """Load the original agent Masterbeater suggestion."""
    path = output_path_for_project(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_masterbeater_reviewed(project_root: Path) -> dict | None:
    """Load the human-edited working copy, if any."""
    path = reviewed_path_for_project(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_masterbeater_ledger(project_root: Path) -> dict[str, Any]:
    path = ledger_path_for_project(project_root)
    if not path.is_file():
        return {
            "schemaVersion": 1,
            "agent": "masterbeater-edit-ledger",
            "originalFile": OUTPUT_FILENAME,
            "reviewedFile": REVIEWED_FILENAME,
            "entries": [],
        }
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Edit ledger must be a JSON object.")
    entries = data.get("entries")
    if not isinstance(entries, list):
        data["entries"] = []
    return data


def write_masterbeater_output(project_root: Path, result: dict[str, Any]) -> Path:
    """Write original agent output (Masterbeater run only)."""
    path = output_path_for_project(project_root)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_masterbeater_reviewed(project_root: Path, result: dict[str, Any]) -> Path:
    path = reviewed_path_for_project(project_root)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_masterbeater_ledger(project_root: Path, ledger: dict[str, Any]) -> Path:
    path = ledger_path_for_project(project_root)
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _beat_span_snapshot(beat: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(beat, dict):
        return None
    return {
        "id": beat.get("id"),
        "beatType": beat.get("beatType"),
        "startWordId": beat.get("startWordId"),
        "endWordId": beat.get("endWordId"),
        "wordsText": beat.get("wordsText"),
        "wordIds": list(beat.get("wordIds") or []),
    }


def append_edit_ledger_entry(
    project_root: Path,
    *,
    edit: dict[str, Any] | None,
    previous_beats: list[dict[str, Any]],
    next_beats: list[dict[str, Any]],
) -> dict[str, Any]:
    """Append one membership edit to the process ledger (auto-save side effect)."""

    ledger = load_masterbeater_ledger(project_root)
    entries: list[Any] = list(ledger.get("entries") or [])
    prev_by_id = {
        str(b.get("id")): b for b in previous_beats if isinstance(b, dict) and b.get("id")
    }
    next_by_id = {
        str(b.get("id")): b for b in next_beats if isinstance(b, dict) and b.get("id")
    }
    edit = edit if isinstance(edit, dict) else {}
    op = str(edit.get("op") or "membershipChange").strip() or "membershipChange"
    beat_id = str(edit.get("beatId") or "").strip() or None
    word_id = str(edit.get("wordId") or "").strip() or None
    word_text = str(edit.get("wordText") or "").strip() or None
    side = str(edit.get("side") or "").strip() or None

    # Capture before/after for the primary beat when known.
    before = _beat_span_snapshot(prev_by_id.get(beat_id or "")) if beat_id else None
    after = _beat_span_snapshot(next_by_id.get(beat_id or "")) if beat_id else None
    if beat_id and before is None and after is None:
        # Beat may have been dropped or split — record id presence.
        before = {"id": beat_id, "present": beat_id in prev_by_id}
        after = {"id": beat_id, "present": beat_id in next_by_id}

    entry = {
        "id": f"e-{len(entries) + 1:04d}",
        "at": datetime.now(timezone.utc).isoformat(),
        "op": op,
        "beatId": beat_id,
        "wordId": word_id,
        "wordText": word_text,
        "side": side,
        "before": before,
        "after": after,
        "beatCountBefore": len(previous_beats),
        "beatCountAfter": len(next_beats),
    }
    if edit.get("detail"):
        entry["detail"] = str(edit.get("detail"))
    entries.append(entry)
    ledger["schemaVersion"] = 1
    ledger["agent"] = "masterbeater-edit-ledger"
    ledger["originalFile"] = OUTPUT_FILENAME
    ledger["reviewedFile"] = REVIEWED_FILENAME
    ledger["entries"] = entries
    ledger["entryCount"] = len(entries)
    ledger["updatedAt"] = entry["at"]
    write_masterbeater_ledger(project_root, ledger)
    return entry


def save_masterbeater_edits_for_video_project(
    manifest_path: Path,
    manifest: dict,
    payload: dict,
) -> dict[str, Any]:
    """Auto-save human word-bound edits to the reviewed working copy.

    The original ``masterbeater-beats.json`` is left untouched. Each save also
    appends an entry to ``masterbeater-edit-ledger.json`` for process review.
    """

    root = video_project_root(manifest_path)
    transcript = final_transcript_path(manifest_path, manifest)
    if not transcript.is_file():
        raise FileNotFoundError(
            f"Locked final transcript not found at {transcript}. "
            "Finish Transcript Edit export first."
        )

    original = load_masterbeater_output(root)
    if original is None:
        raise FileNotFoundError(
            f"Original Masterbeater output missing at {output_path_for_project(root)}. "
            "Run Masterbeater before editing."
        )

    previous = load_masterbeater_reviewed(root) or original
    previous_beats = list(previous.get("beats") or [])

    beats_in = payload.get("beats")
    if not isinstance(beats_in, list):
        raise ValueError("Request must include a beats array.")
    if not beats_in:
        raise ValueError("Beats array is empty — refuse to wipe the reviewed working copy.")

    mode = str(
        payload.get("mode")
        or previous.get("mode")
        or original.get("mode")
        or "tutorial"
    ).strip()
    gaps_source = (
        payload["gaps"]
        if "gaps" in payload
        else previous.get("gaps")
        if previous.get("gaps") is not None
        else original.get("gaps")
        or []
    )
    normalize_payload = {
        "mode": mode,
        "beats": beats_in,
        "gaps": gaps_source if isinstance(gaps_source, list) else [],
    }
    document = load_transcript_document(transcript)
    result = normalize_masterbeater_result(
        normalize_payload,
        project_root=root,
        transcript_path=transcript,
        document=document,
    )
    if not result.get("beats"):
        raise ValueError(
            "No beats could be bound to transcript words after edit. "
            "Check startWordId/endWordId values."
        )

    result["agent"] = "masterbeater-reviewed"
    result["edited"] = True
    result["originalFile"] = OUTPUT_FILENAME
    result["originalBeatCount"] = int(original.get("beatCount") or len(original.get("beats") or []))
    result["basedOnOriginal"] = True
    ledger_entry = append_edit_ledger_entry(
        root,
        edit=payload.get("edit") if isinstance(payload.get("edit"), dict) else None,
        previous_beats=previous_beats,
        next_beats=list(result.get("beats") or []),
    )
    out_path = write_masterbeater_reviewed(root, result)
    # Original must remain byte-stable for this save path.
    result["outputPath"] = str(out_path)
    result["originalPath"] = str(output_path_for_project(root))
    result["ledgerPath"] = str(ledger_path_for_project(root))
    result["ledgerEntry"] = ledger_entry
    result["ledgerEntryCount"] = int(load_masterbeater_ledger(root).get("entryCount") or 0)
    result["ok"] = True
    result["role"] = "reviewed"
    return result


def run_masterbeater_for_video_project(
    manifest_path: Path,
    manifest: dict,
    *,
    timeout_sec: int = 900,
    repo: Path | None = None,
) -> dict[str, Any]:
    """Run Masterbeater on the project's final transcript; write and return result."""

    root = video_project_root(manifest_path)
    transcript = final_transcript_path(manifest_path, manifest)
    if not transcript.is_file():
        raise FileNotFoundError(
            f"Locked final transcript not found at {transcript}. "
            "Finish Transcript Edit export first."
        )

    document = load_transcript_document(transcript)
    words = extract_words(document)
    if not words:
        raise ValueError("Transcript has no words to analyze.")

    base = repo or repo_root()
    skill = skill_path(base)
    universe = universe_path(base)
    if not skill.is_file():
        raise FileNotFoundError(f"Masterbeater skill missing: {skill}")
    if not universe.is_file():
        raise FileNotFoundError(f"Beat universe missing: {universe}")

    skill_body = skill.read_text(encoding="utf-8")
    if skill_body.startswith("---"):
        parts = skill_body.split("---", 2)
        if len(parts) >= 3:
            skill_body = parts[2].strip()
    universe_body = universe.read_text(encoding="utf-8")
    fps = transcript_fps(document)
    word_index = format_words_for_prompt(words, fps=fps)
    sentence_view = format_sentences_for_prompt(document)
    duration = float(words[-1]["endSec"])

    combined_prompt = (
        f"{skill_body}\n\n"
        f"---\n\n"
        f"# Beat universe (binding)\n\n"
        f"{universe_body}\n\n"
        "---\n\n"
        "You are running as Masterbeater in production Stage 1.\n"
        "Return structured JSON only (mode, beats, gaps).\n"
        "CRITICAL TIMING RULES:\n"
        "- Anchor every beat with startWordId and endWordId copied EXACTLY from the WORD INDEX "
        "(example format: w000001, w000024 — keep the leading zeros).\n"
        "- Never invent ids like w1 or W1; only ids that appear in the index.\n"
        "- Do NOT invent frame numbers or rely on clock times as authority.\n"
        "- The app will resolve startFrame/endFrameExclusive from those word IDs.\n"
        "- Sparse is correct. Use only the 13 beat types. No graphics.\n\n"
        f"Approximate duration: {duration:.1f}s · fps={fps:g} · words={len(words)}\n"
        f"First word id: {words[0]['id']} · Last word id: {words[-1]['id']}\n\n"
        "READABLE OVERVIEW (context only):\n"
        f"{sentence_view}\n\n"
        "WORD INDEX (authoritative for anchors):\n"
        f"{word_index}\n"
    )

    grok = resolve_grok_executable()
    schema_json = json.dumps(OUTPUT_SCHEMA, separators=(",", ":"))

    with tempfile.TemporaryDirectory(prefix="vcg-masterbeater-") as tmp:
        tmp_path = Path(tmp)
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text(combined_prompt, encoding="utf-8")

        cmd = [
            str(grok),
            "--prompt-file",
            str(prompt_file),
            "--output-format",
            "json",
            "--json-schema",
            schema_json,
            "--max-turns",
            "2",
            "--always-approve",
            "--cwd",
            str(base),
            "--disable-web-search",
        ]

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                check=False,
                creationflags=hidden_subprocess_flags(),
                env={**os.environ, "GROK_AGENT": os.environ.get("GROK_AGENT", "1")},
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"Masterbeater timed out after {timeout_sec}s."
            ) from exc

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0 and not stdout:
        raise RuntimeError(
            f"Masterbeater failed (exit {completed.returncode}). {stderr or stdout}"
        )

    try:
        payload = _extract_json_payload(stdout)
    except ValueError:
        if stderr:
            try:
                payload = _extract_json_payload(stderr)
            except ValueError:
                raise ValueError(
                    f"Could not parse Masterbeater JSON. stderr={stderr[:500]!r} "
                    f"stdout={stdout[:500]!r}"
                ) from None
        else:
            raise

    raw_path = root / "masterbeater-raw.json"
    try:
        raw_path.write_text(
            json.dumps(
                {
                    "stdout": stdout[:200000],
                    "stderr": stderr[:50000],
                    "returncode": completed.returncode,
                    "parsed": payload,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        raw_path = None

    result = normalize_masterbeater_result(
        payload,
        project_root=root,
        transcript_path=transcript,
        document=document,
        duration_sec=duration,
    )
    if result["beatCount"] == 0:
        sample = payload.get("beats")
        sample_preview = ""
        if isinstance(sample, list) and sample:
            sample_preview = f" First model beat keys={list(sample[0].keys()) if isinstance(sample[0], dict) else type(sample[0])}."
        gaps = "; ".join(result.get("gaps") or [])[:500]
        raise ValueError(
            "Masterbeater returned zero valid beats bound to transcript words. "
            f"Model beat count={len(sample) if isinstance(sample, list) else 0}. "
            f"{gaps}"
            f"{sample_preview} "
            f"Raw output: {raw_path or 'unavailable'}."
        )

    out_path = output_path_for_project(root)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result["outputPath"] = str(out_path)
    result["rawPath"] = str(raw_path) if raw_path else None
    result["ok"] = True
    return result


def status_for_video_project(manifest_path: Path, manifest: dict) -> dict[str, Any]:
    root = video_project_root(manifest_path)
    transcript = final_transcript_path(manifest_path, manifest)
    output = output_path_for_project(root)
    reviewed_path = reviewed_path_for_project(root)
    ledger_path = ledger_path_for_project(root)

    original = None
    if output.is_file():
        try:
            original = load_masterbeater_output(root)
        except (OSError, json.JSONDecodeError):
            original = None

    reviewed = None
    if reviewed_path.is_file():
        try:
            reviewed = load_masterbeater_reviewed(root)
        except (OSError, json.JSONDecodeError):
            reviewed = None

    # Working set for the UI: reviewed if present, else original agent suggestion.
    working = reviewed if reviewed is not None else original

    ledger_entry_count = 0
    if ledger_path.is_file():
        try:
            ledger_entry_count = int(load_masterbeater_ledger(root).get("entryCount") or 0)
            if not ledger_entry_count:
                ledger_entry_count = len(load_masterbeater_ledger(root).get("entries") or [])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            ledger_entry_count = 0

    review_video = preferred_stage_source(manifest_path, manifest)
    locked = resolve_video_project_path(manifest_path, manifest, "lockedCut")
    review_kind = (
        "lockedCut"
        if review_video.resolve() == locked.resolve() and locked.is_file()
        else "sourceVideo"
    )
    # Compact word list for Stage 1 UI (inline transcript + beat cards).
    transcript_words: list[dict[str, Any]] = []
    transcript_fps_value = float((working or original or {}).get("fps") or 30)
    if transcript.is_file():
        try:
            document = load_transcript_document(transcript)
            transcript_fps_value = float(transcript_fps(document) or transcript_fps_value)
            transcript_words = [
                {
                    "id": word["id"],
                    "text": word["text"],
                    "startFrame": word["startFrame"],
                    "endFrame": word["endFrame"],
                    "startSec": word["startSec"],
                    "endSec": word["endSec"],
                }
                for word in extract_words(document)
            ]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            transcript_words = []

    original_count = int((original or {}).get("beatCount") or len((original or {}).get("beats") or []))
    working_count = int((working or {}).get("beatCount") or len((working or {}).get("beats") or []))
    return {
        "ok": True,
        "projectRoot": str(root),
        "transcriptPath": str(transcript),
        "transcriptExists": transcript.is_file(),
        "transcriptWords": transcript_words,
        "transcriptWordCount": len(transcript_words),
        "outputPath": str(output),
        "outputExists": output.is_file(),
        "reviewedPath": str(reviewed_path),
        "reviewedExists": reviewed is not None,
        "ledgerPath": str(ledger_path),
        "ledgerExists": ledger_path.is_file(),
        "ledgerEntryCount": ledger_entry_count,
        # Backward-compatible: result = working set the UI edits.
        "result": working,
        "original": original,
        "reviewed": reviewed,
        "beatCount": working_count,
        "originalBeatCount": original_count,
        "reviewVideoPath": str(review_video),
        "reviewVideoExists": review_video.is_file(),
        "reviewVideoKind": review_kind,
        "fps": (working or original or {}).get("fps") or transcript_fps_value or 30,
    }
