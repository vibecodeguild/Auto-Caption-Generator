"""Project-owned Shorts decisions, independent caption transcripts, and rendering.

The locked cut and its final transcript are read-only inputs. Caption words come
from the assembled short, never from remapping the long-form transcript.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
import textwrap
import threading
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from app.core.ass_builder import build_ass_document, seconds_to_ass_time
from app.core.caption_grouping import group_words
from app.core.ffmpeg_locator import find_ffmpeg
from app.core.file_utils import is_within, sha256_file, slug
from app.core.masterbeater import extract_words, load_transcript_document, transcript_fps
from app.core.process_utils import hidden_subprocess_flags, terminate_process_tree
from app.core.settings import (
    COMPUTE_OPTIONS, DEFAULT_COMPUTE_LABEL, DEFAULT_MODEL_LABEL, MODEL_OPTIONS,
    PRESETS, CaptionPreset, CaptionStyle, WordTimestamp, fonts_dir, project_root,
)
from app.core.style_library import BUILT_IN_STYLES
from app.core.shorts_platforms import CHECKED_ON, PROFILES, guidance
from app.core.transcriber import transcribe_audio
from app.core.parakeet import transcription_notice
from app.core.video_cutter import frame_intervals_to_seconds, run_cut
from app.core.video_project import load_video_project, resolve_video_project_path, video_project_root
from app.core.visual_production import probe_visual_source

PLATFORMS = ("Facebook", "LinkedIn", "YouTube", "TikTok", "Instagram", "Threads")
ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
LAYOUT = {"width": 1080, "height": 1920, "videoY": 500, "videoHeight": 608,
          "titleY": 250, "titleSize": 80, "captionY": 1200, "titleFont": "Inter"}
LOCKS: dict[str, threading.RLock] = {}
LOCKS_GUARD = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=32)
def _file_hash(path: str, size: int, modified: int) -> str:
    return sha256_file(Path(path))


def media_hash(path: Path) -> str:
    stat = path.stat()
    return _file_hash(str(path), stat.st_size, stat.st_mtime_ns)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer frame.")
    return value


def title_lines(title: str) -> list[str]:
    if not isinstance(title, str):
        raise ValueError("Enter a text title.")
    title = " ".join(title.replace("\\", "").replace("{", "").replace("}", "").split())
    if not title or len(title) > 100:
        raise ValueError("Enter a title between 1 and 100 characters.")
    lines = textwrap.wrap(title, width=22)
    if len(lines) > 4:
        raise ValueError("Shorten the title to fit four lines above the video.")
    return lines


def defaults() -> dict:
    style = replace(BUILT_IN_STYLES["Magenta Pop"], main_font_size=64, active_font_size=70,
                    position="Top", margin_v=LAYOUT["captionY"])
    return {"style": asdict(style), "preset": asdict(next(iter(PRESETS.values()))),
            "modelLabel": DEFAULT_MODEL_LABEL, "computeLabel": DEFAULT_COMPUTE_LABEL}


def validate_settings(data: dict) -> dict:
    base = defaults()
    if not isinstance(data, dict):
        raise ValueError("Caption settings must be an object.")
    try:
        style = CaptionStyle(**{**base["style"], **data.get("style", {})})
        preset = CaptionPreset(**{**base["preset"], **data.get("preset", {})})
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid caption style or grouping settings.") from exc
    for field in ("main_font_size", "active_font_size", "outline_width", "shadow_depth", "glow_strength"):
        integer(getattr(style, field), field)
    for field in ("bold", "active_bold", "outline_enabled", "shadow_enabled", "glow_enabled"):
        if not isinstance(getattr(style, field), bool):
            raise ValueError(f"{field} must be true or false.")
    integer(preset.max_words, "max_words")
    integer(preset.max_chars, "max_chars")
    if not isinstance(preset.max_duration, (int, float)) or not math.isfinite(preset.max_duration):
        raise ValueError("Caption group duration must be finite.")
    for field in ("main_color", "active_color", "outline_color", "shadow_color", "glow_color"):
        if not isinstance(getattr(style, field), str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", getattr(style, field)):
            raise ValueError("Caption colors must use #RRGGBB.")
    if (not isinstance(style.font_family, str) or not re.fullmatch(r"[\w -]{1,80}", style.font_family)
            or not 24 <= style.main_font_size <= 96 or not 24 <= style.active_font_size <= 110
            or not 0 <= style.outline_width <= 12 or not 0 <= style.shadow_depth <= 12
            or not 0 <= style.glow_strength <= 12):
        raise ValueError("Caption font or effect size is outside supported limits.")
    if not 1 <= preset.max_words <= 10 or not 1 <= preset.max_chars <= 80 or not .1 <= preset.max_duration <= 10:
        raise ValueError("Caption grouping settings are outside supported limits.")
    model = data.get("modelLabel", base["modelLabel"])
    compute = data.get("computeLabel", base["computeLabel"])
    if model not in MODEL_OPTIONS or compute not in COMPUTE_OPTIONS:
        raise ValueError("Choose a supported transcription model and compute device.")
    return {"style": asdict(replace(style, position="Top", margin_v=LAYOUT["captionY"])),
            "preset": asdict(preset), "modelLabel": model, "computeLabel": compute}


def edit_key(short: dict) -> str:
    return digest({"source": short["source"], "sections": short["sections"]})


def render_key(short: dict) -> str:
    return digest({"edit": edit_key(short), "title": title_lines(short["title"]),
                   "settings": short["settings"], "caption": short.get("caption"), "layout": LAYOUT})


class ShortsProject:
    def __init__(self, manifest_path: Path):
        self.manifest_path = Path(manifest_path).resolve()
        self.manifest = load_video_project(self.manifest_path)
        self.root = video_project_root(self.manifest_path)
        if is_within(self.root, project_root()):
            raise ValueError("Shorts require a private project outside the public checkout.")
        with LOCKS_GUARD:
            self.lock = LOCKS.setdefault(str(self.root), threading.RLock())
        self.folder = self.path("shorts")
        self.state_path = self.folder / "shorts-plan.reviewed.json"

    def path(self, relative: str) -> Path:
        result = (self.root / relative).resolve()
        if not is_within(result, self.root) or result == self.root:
            raise ValueError("Shorts artifact path escapes the private project.")
        return result

    def source(self) -> dict:
        manifest = load_video_project(self.manifest_path)
        media = resolve_video_project_path(self.manifest_path, manifest, "lockedCut")
        transcript_path = resolve_video_project_path(self.manifest_path, manifest, "finalTranscript")
        if not media.is_file() or not transcript_path.is_file():
            raise ValueError("Export the locked cut and final transcript before creating Shorts.")
        document = load_transcript_document(transcript_path)
        project = document.get("project") or document
        proof = (project.get("generation") or {}).get("lockedTranscript") or {}
        source_hash = media_hash(media)
        if proof.get("lockedCutSha256") != source_hash:
            raise ValueError("The final transcript does not match this locked cut. Re-export the locked cut first.")
        if "sourceSequence" in manifest and (manifest.get("artifacts") or {}).get("lockedCutRevision") != int(manifest.get("sequenceRevision") or 0):
            raise ValueError("The source sequence changed. Export a current locked cut before creating Shorts.")
        fps = transcript_fps(document)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("The final transcript has an invalid frame rate.")
        words = extract_words(document)
        if not words or len({w["id"] for w in words}) != len(words):
            raise ValueError("A final transcript with unique word ids is required.")
        return {"projectId": manifest["id"], "lockedCutSha256": source_hash,
                "transcriptSha256": media_hash(transcript_path), "fps": fps}

    def source_details(self) -> dict:
        source = self.source()
        media = resolve_video_project_path(self.manifest_path, self.manifest, "lockedCut")
        probe = probe_visual_source(media)
        if int(probe.get("width", 0)) <= int(probe.get("height", 0)):
            raise ValueError("Shorts currently require a landscape talking-head locked cut.")
        if abs(float(probe["fps"]) - source["fps"]) > .01:
            raise ValueError("The locked cut frame rate does not match its final transcript.")
        return {"source": source, "durationFrames": int(round(float(probe["durationSec"]) * source["fps"])),
                "durationSec": probe["durationSec"], "media": media}

    def load(self) -> dict:
        with self.lock:
            data = read_json(self.state_path, {"schemaVersion": 1, "revision": 0, "shorts": []})
            if data.get("schemaVersion") != 1 or not isinstance(data.get("shorts"), list):
                raise ValueError("Unsupported Shorts project format.")
            return data

    def _save(self, data: dict, event: dict) -> None:
        data["revision"] += 1
        data["updatedAt"] = now()
        # The reviewed document is authoritative; ledger records its committed revision.
        write_json(self.state_path, data)
        ledger_path = self.folder / "shorts-edit-ledger.json"
        ledger = read_json(ledger_path, {"schemaVersion": 1, "events": []})
        ledger["events"].append({**event, "at": now(), "revision": data["revision"]})
        write_json(ledger_path, ledger)

    def find(self, data: dict, short_id: str) -> dict:
        return next((s for s in data["shorts"] if s["id"] == short_id), None) or self._missing()

    @staticmethod
    def _missing():
        raise ValueError("Short not found in this project.")

    def sections(self, rows: Any, duration: int) -> list[dict]:
        if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
            raise ValueError("A short needs between 1 and 50 source sections.")
        seen = set()
        result = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Every source section must be an object.")
            section_id = str(row.get("id") or "")
            if not ID_RE.fullmatch(section_id) or section_id in seen:
                raise ValueError("Source sections need unique safe ids.")
            start = integer(row.get("startFrame"), "Source IN")
            end = integer(row.get("endFrameExclusive"), "Source OUT")
            if not 0 <= start < end <= duration:
                raise ValueError("Source sections must have positive length inside the locked cut.")
            seen.add(section_id)
            result.append({"id": section_id, "startFrame": start, "endFrameExclusive": end})
        return result

    def add(self, payload: dict, *, imported: bool = False) -> dict:
        with self.lock:
            details = self.source_details()
            if payload.get("source") != details["source"]:
                raise ValueError("This plan belongs to a different locked cut or transcript. Export a fresh candidate brief.")
            if payload.get("schemaVersion") != 1:
                raise ValueError("Unsupported Shorts plan version.")
            candidates = payload.get("shorts")
            if not isinstance(candidates, list) or not 1 <= len(candidates) <= 100:
                raise ValueError("A plan needs between 1 and 100 shorts.")
            data = self.load()
            ids = {s["id"] for s in data["shorts"]}
            words = {w["id"]: w for w in extract_words(load_transcript_document(
                resolve_video_project_path(self.manifest_path, self.manifest, "finalTranscript")))}
            added = []
            for item in candidates:
                if not isinstance(item, dict):
                    raise ValueError("Every candidate must be an object.")
                short_id = str(item.get("id") or "")
                if not ID_RE.fullmatch(short_id) or short_id in ids:
                    raise ValueError("Short ids must be unique; rename duplicate candidate ids before importing.")
                ids.add(short_id)
                title = str(item.get("title") or "").strip()
                title_lines(title)
                rows = copy.deepcopy(item.get("sections"))
                if imported:
                    if not isinstance(rows, list):
                        raise ValueError("Every candidate needs word-anchored sections.")
                    for row in rows:
                        if not isinstance(row, dict):
                            raise ValueError("Every source section must be an object.")
                        try:
                            first, last = words[row["startWordId"]], words[row["endWordId"]]
                        except (KeyError, TypeError) as exc:
                            raise ValueError("Candidate section contains unknown transcript word ids.") from exc
                        row["startFrame"] = first["startFrame"]
                        row["endFrameExclusive"] = last["endFrameExclusive"]
                sections = self.sections(rows, details["durationFrames"])
                added.append({"id": short_id, "title": title, "source": details["source"],
                              "sections": sections, "rationale": str(item.get("rationale") or ""),
                              "concerns": str(item.get("concerns") or ""), "revision": 1,
                              "settings": defaults(), "posting": {p: {"title": "", "text": ""} for p in PLATFORMS},
                              "postingEditKey": None, "postingCaptionSha256": None,
                              "assembly": None, "caption": None, "delivery": None})
            if imported:
                receipt = self.folder / "imports" / f"{uuid.uuid4().hex}.json"
                write_json(receipt, payload)
                original = read_json(self.folder / "shorts-plan.original.json", {"schemaVersion": 1, "imports": []})
                original["imports"].append(receipt.relative_to(self.root).as_posix())
                write_json(self.folder / "shorts-plan.original.json", original)
            data["shorts"].extend(added)
            self._save(data, {"action": "import" if imported else "create", "ids": [s["id"] for s in added]})
            return data

    def update(self, short_id: str, payload: dict) -> dict:
        with self.lock:
            data = self.load()
            short = self.find(data, short_id)
            if payload.get("revision") != short["revision"]:
                raise ValueError("This short changed elsewhere. Refresh before saving.")
            if short["source"] != self.source():
                raise ValueError("This short uses an older locked cut. Create candidates against the current source.")
            before = copy.deepcopy(short)
            if "title" in payload:
                title_lines(payload["title"])
                short["title"] = payload["title"].strip()
            if "sections" in payload:
                proposed = self.sections(payload["sections"], self.source_details()["durationFrames"])
                if [s["id"] for s in proposed] != [s["id"] for s in short["sections"]]:
                    raise ValueError("This editor adjusts boundaries only; import a new candidate to change section order.")
                short["sections"] = proposed
            if "settings" in payload:
                short["settings"] = validate_settings(payload["settings"])
            if "posting" in payload:
                posting = payload["posting"]
                if not isinstance(posting, dict) or set(posting) != set(PLATFORMS):
                    raise ValueError("Posting drafts must include every supported destination.")
                for draft in posting.values():
                    if not isinstance(draft, dict) or any(not isinstance(draft.get(k), str) or len(draft[k]) > 12000 for k in ("title", "text")):
                        raise ValueError("Posting drafts need title and text strings (up to 12000 characters each).")
                short["posting"] = posting
                if payload.get("reviewPosting"):
                    if not self.caption_current(short):
                        raise ValueError("Prepare current captions before reviewing posting copy.")
                    if any(not draft["text"].strip() for draft in posting.values()):
                        raise ValueError("Add posting text for each destination before marking the package reviewed.")
                    short["postingEditKey"] = edit_key(short)
                    short["postingCaptionSha256"] = short["caption"]["sha256"]
                elif posting != before["posting"]:
                    short["postingEditKey"] = None
                    short["postingCaptionSha256"] = None
            short["revision"] += 1
            self._save(data, {"action": "review", "shortId": short_id, "before": before, "after": copy.deepcopy(short)})
            return data

    def assembly_current(self, short: dict) -> bool:
        receipt = short.get("assembly") or {}
        return (receipt.get("editKey") == edit_key(short) and self.path(receipt["path"]).is_file()
                and media_hash(self.path(receipt["path"])) == receipt.get("sha256"))

    def caption_current(self, short: dict) -> bool:
        receipt = short.get("caption") or {}
        return (self.assembly_current(short) and receipt.get("editKey") == edit_key(short)
                and self.path(receipt["path"]).is_file()
                and media_hash(self.path(receipt["path"])) == receipt.get("sha256")
                and receipt.get("assemblySha256") == (short.get("assembly") or {}).get("sha256"))

    def caption_document(self, short: dict) -> dict:
        receipt = short.get("caption") or {}
        if receipt.get("path") and self.path(receipt["path"]).is_file() and media_hash(self.path(receipt["path"])) != receipt.get("sha256"):
            raise ValueError("The saved caption transcript changed. Regenerate captions before exporting.")
        if not self.caption_current(short):
            raise ValueError("Captions need regeneration for the current short edit.")
        path = self.path(short["caption"]["path"])
        if media_hash(path) != short["caption"]["sha256"]:
            raise ValueError("The saved caption transcript changed. Regenerate captions before exporting.")
        return read_json(path)

    def posting_current(self, short: dict) -> bool:
        return (self.caption_current(short) and short.get("postingEditKey") == edit_key(short)
                and short.get("postingCaptionSha256") == short["caption"]["sha256"])

    def view(self) -> dict:
        with self.lock:
            details = self.source_details()
            data = self.load()
            shorts = []
            for raw in data["shorts"]:
                short = copy.deepcopy(raw)
                source_current = short["source"] == details["source"]
                short["sourceCurrent"] = source_current
                short["assemblyCurrent"] = source_current and self.assembly_current(short)
                short["captionCurrent"] = source_current and self.caption_current(short)
                short["postingCurrent"] = source_current and self.posting_current(short)
                short["deliveryCurrent"] = (source_current and (short.get("delivery") or {}).get("renderKey") == render_key(short)
                                            and self.path(short["delivery"]["path"]).is_file())
                short["durationSec"] = sum(s["endFrameExclusive"] - s["startFrame"] for s in short["sections"]) / short["source"]["fps"]
                short["platformGuidance"] = guidance(short["durationSec"], short["source"]["fps"], short["posting"])
                short["titleLines"] = title_lines(short["title"])
                short["warnings"] = ["Sections repeat or overlap source content; review the assembled short."] if any(
                    max(a["startFrame"], b["startFrame"]) < min(a["endFrameExclusive"], b["endFrameExclusive"])
                    for i, a in enumerate(short["sections"]) for b in short["sections"][i + 1:]) else []
                if short["captionCurrent"]:
                    caption = self.caption_document(short)
                    short["words"] = caption["words"]
                    short["groups"] = caption_groups(short, caption)
                else:
                    short["words"], short["groups"] = [], []
                shorts.append(short)
            return {"ready": True, "source": details["source"], "durationFrames": details["durationFrames"],
                    "durationSec": details["durationSec"], "revision": data["revision"], "shorts": shorts,
                    "layout": LAYOUT, "platforms": PLATFORMS}

    def brief(self) -> dict:
        details = self.source_details()
        words = extract_words(load_transcript_document(resolve_video_project_path(self.manifest_path, self.manifest, "finalTranscript")))
        return {"instructions": "Suggest talking-head shorts with strong openings, useful substance and complete endings. No preferred duration or CTA. Preserve meaning. You may stitch sections in explicit playback order. Return only the plan shape; use word ids, never guessed frame numbers. Include rationale and concerns. Do not invent performance scores. Choose unique ids not already used.",
                "existingShortIds": [s["id"] for s in self.load()["shorts"]],
                "platformProfiles": {"checkedOn": CHECKED_ON, "profiles": PROFILES},
                "planShape": {"schemaVersion": 1, "source": details["source"], "shorts": [{"id": "unique-short-id", "title": "On-video title", "rationale": "Why this works alone", "concerns": "Context or joins to review", "sections": [{"id": "section-1", "startWordId": "copy-real-word-id", "endWordId": "copy-real-word-id"}]}]},
                "words": words}


def caption_groups(short: dict, document: dict) -> list[dict]:
    settings = short["settings"]
    preset = settings["preset"]
    groups = group_words([WordTimestamp(**w) for w in document["words"]],
                        max_words=preset["max_words"], max_duration=preset["max_duration"], max_chars=preset["max_chars"])
    return [{"start": g.start, "end": g.end, "words": [asdict(w) for w in g.words]} for g in groups]


def short_ass(short: dict, document: dict) -> str:
    groups = caption_groups(short, document)
    style = CaptionStyle(**short["settings"]["style"])
    script = build_ass_document([type_group(g) for g in groups], style, 1080, 1920)
    duration = sum(s["endFrameExclusive"] - s["startFrame"] for s in short["sections"]) / short["source"]["fps"]
    title = r"\N".join(title_lines(short["title"]))
    return script + (f"\nDialogue: 1,0:00:00.00,{seconds_to_ass_time(duration)},Default,,0,0,0,,"
                     f"{{\\an5\\pos(540,{LAYOUT['titleY']})\\fn{LAYOUT['titleFont']}\\fs{LAYOUT['titleSize']}\\b1\\c&HFFFFFF&\\bord0\\shad0}}{title}\n")


def type_group(group: dict):
    from app.core.settings import CaptionGroup
    return CaptionGroup([WordTimestamp(**w) for w in group["words"]])


def composition_filter() -> str:
    font_path = str(fonts_dir().resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"'\''")
    return (f"scale=1080:608:force_original_aspect_ratio=decrease,pad=1080:608:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,pad=1080:1920:0:{LAYOUT['videoY']}:black,ass=short.ass:fontsdir='{font_path}'")


def ffmpeg_job(command: list[str], work: Path, job) -> None:
    log_path = work / "ffmpeg.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=work, stdout=log, stderr=log,
                                   creationflags=hidden_subprocess_flags())
        job.set_process(process)
        try:
            while process.poll() is None:
                job.check()
                job.cancel.wait(.2)
            job.check()
            if process.returncode:
                raise RuntimeError("Shorts render failed: " + log_path.read_text(encoding="utf-8", errors="replace")[-1600:])
        finally:
            terminate_process_tree(process)
            job.set_process(None)


def verify_video(path: Path, duration: float, fps: float, *, vertical: bool = False) -> None:
    probe = probe_visual_source(path)
    if not path.is_file() or path.stat().st_size == 0 or abs(float(probe["durationSec"]) - duration) > max(.15, 3 / fps):
        raise RuntimeError("Shorts output duration does not match the reviewed edit.")
    if vertical and (int(probe["width"]), int(probe["height"])) != (1080, 1920):
        raise RuntimeError("Shorts output is not 1080 by 1920.")


def next_delivery_path(project: ShortsProject, short: dict, number: int) -> Path:
    """Choose a readable flat package name without replacing any prior file.

    Called under the project lock so exports of different shorts cannot choose
    the same destination. The numeric prefix also avoids Windows device names.
    """
    stem = f"{number:02d}-{slug(short['title'])[:70].rstrip('-')}"
    version = 1
    while True:
        name = stem if version == 1 else f"{stem}-{version}"
        output = project.path(f"exports/shorts/{name}.mp4")
        if not any(path.exists() for path in (
            output, output.with_name(f"{name}-posting.json"), output.with_name(f"{name}-posting.txt"),
        )):
            return output
        version += 1


def execute(project: ShortsProject, short: dict, operation: str, job) -> dict:
    """Build into a new job directory; publish only against the captured revision."""
    job.check()
    notice = ""
    if short["source"] != project.source():
        raise ValueError("The locked cut changed. Create a new candidate plan before rendering.")
    key = edit_key(short)
    work = project.path(f"working/shorts/{short['id']}/{job.id}")
    work.mkdir(parents=True, exist_ok=True)
    assembly = short.get("assembly")
    expected = sum(s["endFrameExclusive"] - s["startFrame"] for s in short["sections"]) / short["source"]["fps"]
    candidate = copy.deepcopy(short)
    if operation in ("assemble", "captions") and not project.assembly_current(short):
        job.update(5, "Assembling the reviewed source sections…")
        assembled = work / "assembled.mp4"
        source = resolve_video_project_path(project.manifest_path, project.manifest, "lockedCut")
        intervals = frame_intervals_to_seconds([(s["startFrame"], s["endFrameExclusive"] - 1) for s in short["sections"]], short["source"]["fps"])
        run_cut(ffmpeg=find_ffmpeg(), input_video=source, output_video=assembled, intervals=intervals,
                progress_callback=lambda p: job.update(5 + int(p * 40), "Assembling short…"),
                cancel_check=job.cancel.is_set, on_process=job.set_process)
        job.check()
        verify_video(assembled, expected, short["source"]["fps"])
        assembly = {"editKey": key, "path": assembled.relative_to(project.root).as_posix(), "sha256": media_hash(assembled)}
        candidate["assembly"] = assembly
    if operation == "captions":
        if not assembly:
            raise ValueError("Assemble the short first.")
        assembled = project.path(assembly["path"])
        if media_hash(assembled) != assembly["sha256"]:
            raise ValueError("Assembled media changed. Rebuild the short before transcribing.")
        audio = work / "audio.wav"
        job.update(50, "Extracting assembled-short audio…")
        ffmpeg_job([str(find_ffmpeg()), "-y", "-i", str(assembled), "-vn", "-ac", "1", "-ar", "16000", str(audio)], work, job)
        job.update(60, "Transcribing this short's own audio…")
        settings = short["settings"]
        words = transcribe_audio(audio, model_size=MODEL_OPTIONS[settings["modelLabel"]], compute_mode=settings["computeLabel"])
        notice = transcription_notice(words)
        job.check()
        valid = []
        for word in words:
            if not all(math.isfinite(t) for t in (word.start, word.end)) or word.end <= word.start:
                continue
            start, end = max(0., word.start), min(expected, word.end)
            if end > start and word.text.strip():
                valid.append({"text": word.text, "start": start, "end": end})
        if not valid:
            raise ValueError("No speech was detected in the assembled short.")
        valid.sort(key=lambda w: (w["start"], w["end"]))
        transcript_path = project.path(f"shorts/{short['id']}/transcripts/{job.id}.json")
        document = {"schemaVersion": 1, "editKey": key, "assemblySha256": assembly["sha256"],
                    "modelLabel": settings["modelLabel"], "computeLabel": settings["computeLabel"],
                    "durationSec": expected, "createdAt": now(), "words": valid,
                    "execution": getattr(words, "metadata", {}), "transcriptionNotice": notice}
        write_json(transcript_path, document)
        candidate["caption"] = {"editKey": key, "assemblySha256": assembly["sha256"], "path": transcript_path.relative_to(project.root).as_posix(), "sha256": media_hash(transcript_path)}
    if operation == "export":
        document = project.caption_document(short)
        assembly_path = project.path(short["assembly"]["path"])
        if media_hash(assembly_path) != short["assembly"]["sha256"]:
            raise ValueError("Assembled media changed. Rebuild the short and its captions.")
        (work / "short.ass").write_text(short_ass(short, document), encoding="utf-8-sig")
        job.update(10, "Rendering the title, full widescreen picture, and saved captions…")
        staged = work / "vertical.mp4"
        ffmpeg_job([str(find_ffmpeg()), "-y", "-i", str(assembly_path), "-vf", composition_filter(),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "copy", "-movflags", "+faststart", str(staged)], work, job)
        verify_video(staged, expected, short["source"]["fps"], vertical=True)
    job.check()
    with project.lock:
        data = project.load()
        current = project.find(data, short["id"])
        if current["revision"] != short["revision"] or project.source() != short["source"]:
            raise ValueError("The short or source changed during this job. Previous outputs were preserved; run again for the current edit.")
        if operation == "export":
            output = next_delivery_path(project, short, data["shorts"].index(current) + 1)
            candidate["delivery"] = {"renderKey": render_key(short), "path": output.relative_to(project.root).as_posix(), "postingCurrent": project.posting_current(short)}
            package = {"schemaVersion": 1, "shortId": short["id"], "title": short["title"], "durationSec": expected,
                       "postingCurrent": project.posting_current(short), "posting": short["posting"],
                       "captionTranscript": short["caption"], "source": short["source"],
                       "platformGuidance": guidance(expected, short["source"]["fps"], short["posting"])}
            staged_posting = work / "posting.json"
            staged_text = work / "posting.txt"
            write_json(staged_posting, package)
            lines = [short["title"], "", "Posting copy: " + ("reviewed" if package["postingCurrent"] else "draft; review before posting"), ""]
            for platform, draft in short["posting"].items():
                lines.extend([platform, draft["title"], draft["text"], ""])
            staged_text.write_text("\n".join(lines), encoding="utf-8")
            job.check()
            output.parent.mkdir(parents=True, exist_ok=True)
            published = []
            try:
                for source, destination in (
                    (staged, output),
                    (staged_posting, output.with_name(f"{output.stem}-posting.json")),
                    (staged_text, output.with_name(f"{output.stem}-posting.txt")),
                ):
                    source.replace(destination)
                    published.append(destination)
            except OSError:
                for destination in published:
                    destination.unlink(missing_ok=True)
                raise
            current["delivery"] = candidate["delivery"]
        else:
            current["assembly"] = candidate["assembly"]
            if operation == "captions":
                current["caption"] = candidate["caption"]
        current["revision"] += 1
        project._save(data, {"action": operation, "shortId": short["id"], "jobId": job.id})
    return {"shortId": short["id"], "operation": operation,
            "transcriptionNotice": notice,
            "outputPath": str(project.path(candidate["delivery"]["path"])) if operation == "export" else None}
