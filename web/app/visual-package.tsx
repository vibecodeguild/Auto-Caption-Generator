"use client";

import {
  createElement,
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type SetStateAction,
} from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronUp, Loader2, Lock, LockOpen, Pause, Play, RefreshCw, SkipBack } from "lucide-react";
import {
  assignmentPosterUrl,
  buildPlacementPreview,
  cancelPlacementFinal,
  getActivePlacementFinalJob,
  getPlacementFinalJob,
  getVisualPackageStatus,
  importPlacementImageDialog,
  placementPreviewCompositionUrl,
  placementPreviewSourceUrl,
  runAssignment,
  runMasterbeater,
  runPlacement,
  runScenelayer,
  saveAssignmentOverride,
  saveMasterbeaterBeats,
  savePlacementBeat,
  saveScenelayerOverride,
  startPlacementFinal,
  visualPackageSourceVideoUrl,
  visualRuntimePlayerUrl,
  type AssignmentEligibleUsage,
  type AssignmentPick,
  type AssignmentStatus,
  type MasterbeaterBeat,
  type MasterbeaterEditEvent,
  type MasterbeaterResult,
  type PlacementBeat,
  type PlacementFinalJob,
  type PlacementLine,
  type PlacementPreview,
  type PlacementStatus,
  type ScenelayerPick,
  type ScenelayerStatus,
  type VisualPackageTranscriptWord,
  type VisualPackageStatus,
} from "../lib/api";

type HyperFramesPlayerElement = HTMLElement & {
  currentTime: number;
  duration: number;
  paused: boolean;
  ready: boolean;
  loop: boolean;
  play: () => void;
  pause: () => void;
  seek: (time: number) => void;
  /** hyperframes internal control bridge — wrapped at mount to pin the WebAudio-clock disable. */
  _sendControl?: (action: string, payload?: Record<string, unknown>) => void;
  /** Set once our _sendControl wrapper is installed (see the player ref callback). */
  __vcgAudioClockPinned?: boolean;
};

const OBS_LAYOUT_IDS = [
  "full-screen-talking",
  "talking-left",
  "talking-right",
  "talking-bottom-left",
  "talking-bottom-right",
  "talking-top-left",
  "talking-top-right",
  "computer-screen-only",
] as const;

/** Host element id for the topbar stage rail (filled by portal). */
export const VISUAL_PACKAGE_RAIL_HOST_ID = "visual-package-rail-host";

const BEAT_TYPE_ORDER = [
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
] as const;

function formatClock(sec: number | undefined | null): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return "—";
  const total = Math.floor(sec);
  const m = Math.floor(total / 60);
  const s = total % 60;
  const frac = Math.floor((sec - total) * 10);
  return `${m}:${String(s).padStart(2, "0")}.${frac}`;
}

function endFrameExclusive(beat: MasterbeaterBeat): number | undefined {
  if (beat.endFrameExclusive != null) return beat.endFrameExclusive;
  if (beat.endFrame != null) return beat.endFrame + 1;
  return undefined;
}

function beatStartSec(beat: MasterbeaterBeat, fps: number): number {
  if (beat.startSec != null && Number.isFinite(beat.startSec)) return beat.startSec;
  if (beat.startFrame != null && fps > 0) return beat.startFrame / fps;
  return 0;
}

function beatEndSec(beat: MasterbeaterBeat, fps: number): number {
  if (beat.endSec != null && Number.isFinite(beat.endSec)) return beat.endSec;
  const endEx = endFrameExclusive(beat);
  if (endEx != null && fps > 0) return endEx / fps;
  return beatStartSec(beat, fps) + 1;
}

function joinWords(words: VisualPackageTranscriptWord[]): string {
  return words.map((word) => word.text).join(" ").replace(/\s+/g, " ").trim();
}

function wordIndexMap(words: VisualPackageTranscriptWord[]): Map<string, number> {
  const map = new Map<string, number>();
  words.forEach((word, index) => {
    if (!map.has(word.id)) map.set(word.id, index);
  });
  return map;
}

/** Words belonging to a beat by start/end word ids (Stage 3 speech chips). */
function wordsInBeatRange(
  words: VisualPackageTranscriptWord[],
  beat: MasterbeaterBeat,
  indexById: Map<string, number>,
): VisualPackageTranscriptWord[] {
  const start = indexById.get(String(beat.startWordId || ""));
  const end = indexById.get(String(beat.endWordId || ""));
  if (start == null || end == null || end < start) return [];
  return words.slice(start, end + 1);
}

function frameToClock(frame: number, fps: number): string {
  if (!Number.isFinite(frame) || fps <= 0) return "—";
  return formatClock(frame / fps);
}

/** Rebind frames / exact text from inclusive start/end word IDs. */
function rebindBeat(
  beat: MasterbeaterBeat,
  words: VisualPackageTranscriptWord[],
  startWordId: string,
  endWordId: string,
): MasterbeaterBeat | null {
  const indexById = wordIndexMap(words);
  let start = indexById.get(startWordId);
  let end = indexById.get(endWordId);
  if (start == null || end == null) return null;
  if (end < start) [start, end] = [end, start];
  const span = words.slice(start, end + 1);
  if (!span.length) return null;
  const first = span[0];
  const last = span[span.length - 1];
  const wordsText = joinWords(span);
  return {
    ...beat,
    startWordId: first.id,
    endWordId: last.id,
    wordIds: span.map((word) => word.id),
    wordsText,
    label: wordsText,
    span: wordsText,
    startFrame: first.startFrame,
    endFrame: last.endFrame,
    endFrameExclusive: last.endFrame != null ? last.endFrame + 1 : undefined,
    startSec: first.startSec,
    endSec: last.endSec,
  };
}

type BeatSpan = { beat: MasterbeaterBeat; start: number; end: number };

function placedBeatSpans(
  words: VisualPackageTranscriptWord[],
  beats: MasterbeaterBeat[],
): BeatSpan[] {
  const indexById = wordIndexMap(words);
  const candidates: BeatSpan[] = [];
  for (const beat of beats) {
    const start = indexById.get(String(beat.startWordId || ""));
    const end = indexById.get(String(beat.endWordId || ""));
    if (start == null || end == null || end < start) continue;
    candidates.push({ beat, start, end });
  }
  candidates.sort((a, b) => a.start - b.start || a.end - b.end);
  const placed: BeatSpan[] = [];
  let cursor = 0;
  for (const item of candidates) {
    if (item.end < cursor) continue;
    const start = Math.max(item.start, cursor);
    placed.push({ beat: item.beat, start, end: item.end });
    cursor = item.end + 1;
  }
  return placed;
}

/**
 * Remove an inclusive word range from a beat.
 * Edge trim, interior split, or drop when the whole beat is removed.
 */
function removeWordRangeFromBeat(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  beatId: string,
  fromWordId: string,
  toWordId: string,
): MasterbeaterBeat[] {
  const indexById = wordIndexMap(words);
  let from = indexById.get(fromWordId);
  let to = indexById.get(toWordId);
  if (from == null || to == null) return beats;
  if (to < from) [from, to] = [to, from];

  const next: MasterbeaterBeat[] = [];
  for (const beat of beats) {
    if (beat.id !== beatId) {
      next.push(beat);
      continue;
    }
    const start = indexById.get(String(beat.startWordId || ""));
    const end = indexById.get(String(beat.endWordId || ""));
    if (start == null || end == null) {
      next.push(beat);
      continue;
    }
    // Clamp removal to the beat span.
    const removeFrom = Math.max(from, start);
    const removeTo = Math.min(to, end);
    if (removeFrom > removeTo) {
      next.push(beat);
      continue;
    }
    if (removeFrom === start && removeTo === end) {
      // Whole beat removed.
      continue;
    }
    if (removeFrom === start) {
      const rebound = rebindBeat(beat, words, words[removeTo + 1].id, words[end].id);
      if (rebound) next.push(rebound);
      continue;
    }
    if (removeTo === end) {
      const rebound = rebindBeat(beat, words, words[start].id, words[removeFrom - 1].id);
      if (rebound) next.push(rebound);
      continue;
    }
    // Interior hole: left keeps id; right becomes a split sibling.
    const left = rebindBeat(beat, words, words[start].id, words[removeFrom - 1].id);
    const right = rebindBeat(
      {
        ...beat,
        id: `${beat.id}-split-${words[removeTo + 1].id}`,
        rationale: beat.rationale
          ? `${beat.rationale} (continued after gap)`
          : "Continued after manual gap.",
      },
      words,
      words[removeTo + 1].id,
      words[end].id,
    );
    if (left) next.push(left);
    if (right) next.push(right);
  }
  return sortBeatsByTimeline(next);
}

function removeWordFromBeat(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  beatId: string,
  wordId: string,
): MasterbeaterBeat[] {
  return removeWordRangeFromBeat(beats, words, beatId, wordId, wordId);
}

/** Neighbors for a gap word or contiguous gap selection. */
function neighborsForGapSpan(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  fromWordId: string,
  toWordId: string,
): { prev: MasterbeaterBeat | null; next: MasterbeaterBeat | null } {
  const indexById = wordIndexMap(words);
  let from = indexById.get(fromWordId);
  let to = indexById.get(toWordId);
  if (from == null || to == null) return { prev: null, next: null };
  if (to < from) [from, to] = [to, from];
  const placed = placedBeatSpans(words, beats);
  for (const item of placed) {
    // Selection must not overlap any beat.
    if (!(to < item.start || from > item.end)) {
      return { prev: null, next: null };
    }
  }
  let prev: MasterbeaterBeat | null = null;
  let next: MasterbeaterBeat | null = null;
  for (const item of placed) {
    if (item.end < from) prev = item.beat;
    if (item.start > to && !next) next = item.beat;
  }
  return { prev, next };
}

/**
 * Absorb a gap selection into prev or next beat.
 * Prev: beat end becomes the selection's last word (absorbs intervening gap).
 * Next: beat start becomes the selection's first word.
 */
function addGapRangeToNeighbor(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  fromWordId: string,
  toWordId: string,
  side: "prev" | "next",
): MasterbeaterBeat[] {
  const indexById = wordIndexMap(words);
  let from = indexById.get(fromWordId);
  let to = indexById.get(toWordId);
  if (from == null || to == null) return beats;
  if (to < from) [from, to] = [to, from];
  const { prev, next } = neighborsForGapSpan(beats, words, words[from].id, words[to].id);
  const target = side === "prev" ? prev : next;
  if (!target) return beats;

  return beats.map((beat) => {
    if (beat.id !== target.id) return beat;
    if (side === "prev") {
      const startId = String(beat.startWordId || words[from].id);
      return rebindBeat(beat, words, startId, words[to].id) ?? beat;
    }
    const endId = String(beat.endWordId || words[to].id);
    return rebindBeat(beat, words, words[from].id, endId) ?? beat;
  });
}

function addGapWordToNeighbor(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  wordId: string,
  side: "prev" | "next",
): MasterbeaterBeat[] {
  return addGapRangeToNeighbor(beats, words, wordId, wordId, side);
}

/** Inclusive word-membership selection (gap phrase or in-beat phrase). */
type MembershipSelection = {
  zone: "gap" | "beat";
  beatId?: string;
  /** Anchor for shift-click extension. */
  anchorIndex: number;
  startIndex: number;
  endIndex: number;
};

function normalizeSelectionRange(a: number, b: number): { startIndex: number; endIndex: number } {
  return a <= b ? { startIndex: a, endIndex: b } : { startIndex: b, endIndex: a };
}

function selectionWordText(
  words: VisualPackageTranscriptWord[],
  startIndex: number,
  endIndex: number,
): string {
  return joinWords(words.slice(startIndex, endIndex + 1));
}

function selectionCoversIndex(sel: MembershipSelection | null, index: number): boolean {
  return Boolean(sel && index >= sel.startIndex && index <= sel.endIndex);
}

function newManualBeatId(beats: MasterbeaterBeat[], suffix: string): string {
  const base = `beat-manual-${suffix}`;
  if (!beats.some((beat) => beat.id === base)) return base;
  let n = 2;
  while (beats.some((beat) => beat.id === `${base}-${n}`)) n += 1;
  return `${base}-${n}`;
}

/** Transcript time order for navigation + Place (matches server normalize). */
function sortBeatsByTimeline(beats: MasterbeaterBeat[]): MasterbeaterBeat[] {
  return [...beats].sort((a, b) => {
    const aStart = Number(a.startFrame) || 0;
    const bStart = Number(b.startFrame) || 0;
    if (aStart !== bStart) return aStart - bStart;
    const aEnd = Number(a.endFrameExclusive ?? (a.endFrame != null ? a.endFrame + 1 : aStart + 1)) || 0;
    const bEnd = Number(b.endFrameExclusive ?? (b.endFrame != null ? b.endFrame + 1 : bStart + 1)) || 0;
    if (aEnd !== bEnd) return aEnd - bEnd;
    return String(a.id || "").localeCompare(String(b.id || ""));
  });
}

function changeBeatType(
  beats: MasterbeaterBeat[],
  beatId: string,
  beatType: string,
): MasterbeaterBeat[] {
  return beats.map((beat) => (beat.id === beatId ? { ...beat, beatType } : beat));
}

function deleteBeat(beats: MasterbeaterBeat[], beatId: string): MasterbeaterBeat[] {
  return beats.filter((beat) => beat.id !== beatId);
}

/** Create a new beat over a contiguous gap range (must not overlap existing beats). */
function addBeatFromRange(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  startIndex: number,
  endIndex: number,
  beatType: string,
): { beats: MasterbeaterBeat[]; beat: MasterbeaterBeat } | { error: string } {
  if (startIndex < 0 || endIndex >= words.length || endIndex < startIndex) {
    return { error: "Invalid word range for a new beat." };
  }
  const placed = placedBeatSpans(words, beats);
  for (const item of placed) {
    if (!(endIndex < item.start || startIndex > item.end)) {
      return { error: "That range overlaps an existing beat." };
    }
  }
  const draft: MasterbeaterBeat = {
    id: newManualBeatId(beats, words[startIndex].id),
    beatType,
    rationale: "Created in Visual Package review.",
  };
  const rebound = rebindBeat(draft, words, words[startIndex].id, words[endIndex].id);
  if (!rebound) return { error: "Could not bind new beat to transcript words." };
  return { beats: sortBeatsByTimeline([...beats, rebound]), beat: rebound };
}

function findAdjacentBeats(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  beatId: string,
): { prev: MasterbeaterBeat | null; next: MasterbeaterBeat | null; current: BeatSpan | null } {
  const placed = placedBeatSpans(words, beats);
  const currentIndex = placed.findIndex((item) => item.beat.id === beatId);
  if (currentIndex < 0) return { prev: null, next: null, current: null };
  return {
    current: placed[currentIndex],
    prev: currentIndex > 0 ? placed[currentIndex - 1].beat : null,
    next: currentIndex < placed.length - 1 ? placed[currentIndex + 1].beat : null,
  };
}

/**
 * Merge selected beat with previous or next placed beat.
 * Absorbs any intervening gap words into the merged span. Keeps the earlier beat's id/type.
 */
function mergeBeatWithNeighbor(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  beatId: string,
  side: "prev" | "next",
): { beats: MasterbeaterBeat[]; keptId: string } | { error: string } {
  const { prev, next, current } = findAdjacentBeats(beats, words, beatId);
  if (!current) return { error: "Selected beat is not placed on the transcript." };
  const neighbor = side === "prev" ? prev : next;
  if (!neighbor) return { error: side === "prev" ? "No previous beat to merge with." : "No next beat to merge with." };

  const indexById = wordIndexMap(words);
  const nStart = indexById.get(String(neighbor.startWordId || ""));
  const nEnd = indexById.get(String(neighbor.endWordId || ""));
  if (nStart == null || nEnd == null) return { error: "Neighbor beat is missing word anchors." };

  const mergeStart = side === "prev" ? nStart : current.start;
  const mergeEnd = side === "prev" ? current.end : nEnd;
  // Keep the earlier beat's identity (prev when merging prev; current when merging next).
  const keep = side === "prev" ? neighbor : current.beat;
  const dropId = side === "prev" ? current.beat.id : neighbor.id;
  const rebound = rebindBeat(keep, words, words[mergeStart].id, words[mergeEnd].id);
  if (!rebound) return { error: "Could not rebind merged beat." };
  const nextBeats = sortBeatsByTimeline(
    beats.filter((beat) => beat.id !== dropId && beat.id !== keep.id).concat(rebound),
  );
  return { beats: nextBeats, keptId: rebound.id };
}

/**
 * Split a beat after `afterIndex` (inclusive left, exclusive right start).
 * Left keeps original id; right is a new sibling of the same type.
 */
function splitBeatAfter(
  beats: MasterbeaterBeat[],
  words: VisualPackageTranscriptWord[],
  beatId: string,
  afterIndex: number,
): { beats: MasterbeaterBeat[]; leftId: string; rightId: string } | { error: string } {
  const indexById = wordIndexMap(words);
  const beat = beats.find((item) => item.id === beatId);
  if (!beat) return { error: "Beat not found." };
  const start = indexById.get(String(beat.startWordId || ""));
  const end = indexById.get(String(beat.endWordId || ""));
  if (start == null || end == null) return { error: "Beat is missing word anchors." };
  if (afterIndex < start || afterIndex >= end) {
    return { error: "Split needs at least one word on each side of the cut." };
  }
  const left = rebindBeat(beat, words, words[start].id, words[afterIndex].id);
  const rightDraft: MasterbeaterBeat = {
    ...beat,
    id: newManualBeatId(
      beats.filter((item) => item.id !== beatId),
      `split-${words[afterIndex + 1].id}`,
    ),
    rationale: beat.rationale
      ? `${beat.rationale} (split)`
      : "Split in Visual Package review.",
  };
  const right = rebindBeat(rightDraft, words, words[afterIndex + 1].id, words[end].id);
  if (!left || !right) return { error: "Could not rebind split beats." };
  const nextBeats = sortBeatsByTimeline(
    beats.filter((item) => item.id !== beatId).concat(left, right),
  );
  return { beats: nextBeats, leftId: left.id, rightId: right.id };
}

type StreamGap = { kind: "gap"; key: string; words: VisualPackageTranscriptWord[] };
type StreamBeat = {
  kind: "beat";
  key: string;
  beat: MasterbeaterBeat;
  words: VisualPackageTranscriptWord[];
};
type StreamOrphan = { kind: "orphan"; key: string; beat: MasterbeaterBeat };
type StreamItem = StreamGap | StreamBeat | StreamOrphan;

/**
 * Interleave full transcript words with beat cards in time order.
 * Unbeaten stretches stay as plain gap text so holes are obvious while scrolling.
 */
function buildTranscriptStream(
  words: VisualPackageTranscriptWord[],
  beats: MasterbeaterBeat[],
  typeFilter: string,
  layoutFilter: string = "all",
  layoutByBeat: Record<string, { layoutId?: string | null } | undefined> = {},
): StreamItem[] {
  const passesFilters = (beat: MasterbeaterBeat) => {
    if (typeFilter !== "all" && beat.beatType !== typeFilter) return false;
    if (layoutFilter !== "all") {
      const layoutId = layoutByBeat[beat.id]?.layoutId || "";
      if (layoutFilter === "__unset__") {
        if (layoutId) return false;
      } else if (layoutId !== layoutFilter) {
        return false;
      }
    }
    return true;
  };

  if (!words.length) {
    // No transcript: still show beat cards so the file is reviewable.
    return beats
      .filter(passesFilters)
      .map((beat) => ({ kind: "orphan" as const, key: `orphan-${beat.id}`, beat }));
  }

  const indexById = new Map<string, number>();
  words.forEach((word, index) => {
    if (!indexById.has(word.id)) indexById.set(word.id, index);
  });

  type Placed = { beat: MasterbeaterBeat; start: number; end: number };
  const candidates: Placed[] = [];
  const unmapped: MasterbeaterBeat[] = [];

  for (const beat of beats) {
    if (!passesFilters(beat)) {
      continue;
    }
    const start = indexById.get(String(beat.startWordId || ""));
    const end = indexById.get(String(beat.endWordId || ""));
    if (start == null || end == null || end < start) {
      unmapped.push(beat);
      continue;
    }
    candidates.push({ beat, start, end });
  }

  candidates.sort((a, b) => a.start - b.start || a.end - b.end);

  // Non-overlapping placement (first wins on overlap).
  const placed: Placed[] = [];
  let cursor = 0;
  for (const item of candidates) {
    if (item.end < cursor) continue;
    const start = Math.max(item.start, cursor);
    placed.push({ beat: item.beat, start, end: item.end });
    cursor = item.end + 1;
  }

  const stream: StreamItem[] = [];
  let i = 0;
  for (const item of placed) {
    if (i < item.start) {
      stream.push({
        kind: "gap",
        key: `gap-${i}-${item.start}`,
        words: words.slice(i, item.start),
      });
    }
    stream.push({
      kind: "beat",
      key: item.beat.id,
      beat: item.beat,
      words: words.slice(item.start, item.end + 1),
    });
    i = item.end + 1;
  }
  if (i < words.length) {
    stream.push({
      kind: "gap",
      key: `gap-${i}-end`,
      words: words.slice(i),
    });
  }

  for (const beat of unmapped) {
    stream.push({ kind: "orphan", key: `orphan-${beat.id}`, beat });
  }

  return stream;
}

function PackageWorkflowStage({
  activeStage,
  children,
  setActiveStage,
  stage,
}: {
  activeStage: number;
  children: ReactNode;
  setActiveStage: Dispatch<SetStateAction<number>>;
  stage: number;
}) {
  const active = activeStage === stage;
  return (
    <div className={["workflow-stage", active ? "active" : "", activeStage > stage ? "complete" : ""].join(" ")}>
      <button
        className="workflow-stage-number"
        aria-label={`Open Visual Package stage ${stage}`}
        aria-expanded={active}
        onClick={() => setActiveStage(stage)}
        type="button"
      >
        {stage}
      </button>
      {active && <div className="workflow-stage-content">{children}</div>}
    </div>
  );
}

function BeatCardHeader({ beat, fps }: { beat: MasterbeaterBeat; fps: number }) {
  const endEx = endFrameExclusive(beat);
  return (
    <header className="visual-package-inline-beat-header">
      <span className={`beat-type-badge type-${beat.beatType}`}>{beat.beatType}</span>
      <span className="beat-frames">
        {beat.startFrame != null && endEx != null ? `f ${beat.startFrame}–${endEx}` : "f —"}
      </span>
      <span className="beat-time">
        {formatClock(beatStartSec(beat, fps))}–{formatClock(beatEndSec(beat, fps))}
      </span>
    </header>
  );
}

/** Stage 2: layout dropdown + graphic name/poster. */
function Stage2SidePanel({
  beat,
  layoutPick,
  layoutIds,
  layoutDisabled,
  onLayout,
  assignmentPick,
  eligible,
  assignmentDisabled,
  onUsage,
}: {
  beat: MasterbeaterBeat;
  layoutPick?: ScenelayerPick | null;
  layoutIds: string[];
  layoutDisabled?: boolean;
  onLayout: (layoutId: string | null) => void;
  assignmentPick?: AssignmentPick | null;
  eligible: AssignmentEligibleUsage[];
  assignmentDisabled?: boolean;
  onUsage: (usageId: string | null) => void;
}) {
  const poster = assignmentPosterUrl(assignmentPick?.posterUrl);
  const name =
    assignmentPick?.displayName ||
    (assignmentPick?.usageId ? assignmentPick.usageId : null);
  const layoutId = layoutPick?.layoutId || "";
  const layoutSource = layoutPick?.source;
  const usageSource = assignmentPick?.source;
  return (
    <aside
      className={[
        "visual-package-assignment-side",
        assignmentPick?.usageId ? "has-usage" : "is-empty",
        layoutSource === "human" || usageSource === "human" ? "is-human" : "",
      ].join(" ")}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <div className="visual-package-layout-field">
        <span className="visual-package-layout-label">Layout</span>
        <select
          value={layoutId}
          disabled={layoutDisabled}
          aria-label={`OBS layout for ${beat.beatType}`}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => {
            event.stopPropagation();
            const value = event.target.value;
            onLayout(value ? value : null);
          }}
        >
          <option value="">{layoutIds.length ? "Not set" : "—"}</option>
          {layoutIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        {layoutSource === "human" ? (
          <span className="visual-package-assignment-source">Manual layout</span>
        ) : layoutId ? (
          <span className="visual-package-assignment-source muted">Auto layout</span>
        ) : null}
      </div>
      <div className="visual-package-assignment-poster-wrap">
        {poster ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            className="visual-package-assignment-poster"
            src={poster}
            alt={name ? `${name} poster` : "Graphic poster"}
          />
        ) : (
          <div className="visual-package-assignment-poster-empty" aria-hidden>
            {assignmentPick?.usageId ? "No poster" : "—"}
          </div>
        )}
      </div>
      <div className="visual-package-assignment-meta">
        <div className="visual-package-assignment-name" title={name || undefined}>
          {name || "No graphic"}
        </div>
        {usageSource === "human" ? (
          <span className="visual-package-assignment-source">Manual</span>
        ) : assignmentPick?.usageId ? (
          <span className="visual-package-assignment-source muted">Auto</span>
        ) : null}
        <label className="visual-package-assignment-swap">
          <span className="sr-only">Change graphic for {beat.beatType}</span>
          <select
            value={assignmentPick?.usageId || ""}
            disabled={assignmentDisabled || (!layoutId && eligible.length === 0)}
            onChange={(event) => {
              const value = event.target.value;
              onUsage(value ? value : null);
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <option value="">
              {eligible.length
                ? "No graphic"
                : layoutId
                  ? "No golden for type+layout"
                  : "Set layout first"}
            </option>
            {eligible.map((usage) => (
              <option key={usage.id} value={usage.id}>
                {usage.displayName || usage.id}
              </option>
            ))}
          </select>
        </label>
      </div>
    </aside>
  );
}

/** Inline ↑/↓ after a selection — only way to move words in/out of beats. */
function MembershipArrows({
  upTitle,
  downTitle,
  onUp,
  onDown,
}: {
  upTitle?: string;
  downTitle?: string;
  onUp?: () => void;
  onDown?: () => void;
}) {
  if (!onUp && !onDown) return null;
  return (
    <span className="visual-package-gap-arrows" role="group" aria-label="Move selection with arrows">
      {onUp ? (
        <button
          type="button"
          className="visual-package-gap-arrow"
          title={upTitle || "Move up"}
          aria-label={upTitle || "Move up"}
          onClick={(event) => {
            event.stopPropagation();
            onUp();
          }}
        >
          <ChevronUp size={14} strokeWidth={2.5} />
        </button>
      ) : null}
      {onDown ? (
        <button
          type="button"
          className="visual-package-gap-arrow"
          title={downTitle || "Move down"}
          aria-label={downTitle || "Move down"}
          onClick={(event) => {
            event.stopPropagation();
            onDown();
          }}
        >
          <ChevronDown size={14} strokeWidth={2.5} />
        </button>
      ) : null}
    </span>
  );
}

/** Clickable transcript word chip (in-beat or gap) with optional selection chrome. */
function WordChip({
  word,
  variant,
  title,
  selected,
  selectionEdge,
  onPointerDownWord,
  onPointerEnterWord,
  onClickWord,
  trailing,
}: {
  word: VisualPackageTranscriptWord;
  variant: "in-beat" | "gap";
  title: string;
  selected?: boolean;
  /** Render assign/remove controls after the last selected word. */
  selectionEdge?: boolean;
  onPointerDownWord?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerEnterWord?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onClickWord?: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  trailing?: ReactNode;
}) {
  return (
    <span className={["visual-package-word-unit", selected ? "is-selected" : ""].join(" ")}>
      <button
        type="button"
        className={[
          "visual-package-word-chip",
          `is-${variant}`,
          selected ? "is-selected" : "",
        ].join(" ")}
        title={title}
        onPointerDown={onPointerDownWord}
        onPointerEnter={onPointerEnterWord}
        onClick={onClickWord}
      >
        {word.text}
      </button>
      {selectionEdge ? trailing : null}
    </span>
  );
}

function endsSentenceText(text: string): boolean {
  // Match transcript-editor feel: break after terminal punctuation (incl. quotes).
  return /[.!?]["')\]]*$/.test(String(text || "").trim());
}

/**
 * Group words into sentence rows — same boundary model as the transcript editor
 * (sentence_id), with punctuation fallback when ids are missing.
 */
function groupWordsBySentence(
  words: VisualPackageTranscriptWord[],
): { key: string; words: VisualPackageTranscriptWord[] }[] {
  if (!words.length) return [];
  const hasSentenceIds = words.some((word) => Number(word.sentenceId || 0) > 0);
  if (hasSentenceIds) {
    const groups: { key: string; words: VisualPackageTranscriptWord[] }[] = [];
    let current: VisualPackageTranscriptWord[] = [];
    let currentId: number | null = null;
    for (const word of words) {
      const sid = Number(word.sentenceId || 0);
      if (current.length && sid !== currentId) {
        groups.push({ key: `s-${currentId}-${current[0].id}`, words: current });
        current = [];
      }
      currentId = sid;
      current.push(word);
    }
    if (current.length) {
      groups.push({ key: `s-${currentId}-${current[0].id}`, words: current });
    }
    return groups;
  }
  // Fallback: start a new row after terminal punctuation.
  const groups: { key: string; words: VisualPackageTranscriptWord[] }[] = [];
  let current: VisualPackageTranscriptWord[] = [];
  for (const word of words) {
    current.push(word);
    if (endsSentenceText(word.text)) {
      groups.push({ key: `p-${current[0].id}`, words: current });
      current = [];
    }
  }
  if (current.length) {
    groups.push({ key: `p-${current[0].id}`, words: current });
  }
  return groups;
}

export default function VisualPackageWorkspace({
  hasVideoProject,
  projectName,
}: {
  hasVideoProject: boolean;
  projectName?: string | null;
}) {
  const [activeStage, setActiveStage] = useState(1);
  const [status, setStatus] = useState<VisualPackageStatus | null>(null);
  /** Working set (reviewed copy if present, else original). */
  const [result, setResult] = useState<MasterbeaterResult | null>(null);
  /** Optimistic local beats while auto-save is in flight. */
  const [draftBeats, setDraftBeats] = useState<MasterbeaterBeat[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [placementFinalJob, setPlacementFinalJob] = useState<PlacementFinalJob | null>(null);
  /** Keep the Final progress modal open after complete/fail until the user dismisses it. */
  const [finalModalOpen, setFinalModalOpen] = useState(false);
  const [finalCanceling, setFinalCanceling] = useState(false);
  const [autoSaveState, setAutoSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [message, setMessage] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [layoutFilter, setLayoutFilter] = useState<string>("all");
  const [railHost, setRailHost] = useState<HTMLElement | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  /** Default off everywhere — one-shot play per click (Stage 1/2 video + Stage 3 live). */
  const [loopBeat, setLoopBeat] = useState(false);
  /** When on, clicking a beat card seeks and plays that span. */
  const [autoplayOnSelect, setAutoplayOnSelect] = useState(true);
  /** Inclusive phrase selection for multi-word assign/remove. */
  const [membershipSel, setMembershipSel] = useState<MembershipSelection | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const runtimePlayerRef = useRef<HyperFramesPlayerElement | null>(null);
  const streamRef = useRef<HTMLDivElement | null>(null);
  /** Latest-wins counter so rapid clicks don't apply stale auto-save responses. */
  const autoSaveGen = useRef(0);
  const placementPreviewGen = useRef(0);
  const resultRef = useRef<MasterbeaterResult | null>(null);
  const [placementPreview, setPlacementPreview] = useState<PlacementPreview | null>(null);
  const [placementPreviewBusy, setPlacementPreviewBusy] = useState(false);
  const [placementPreviewError, setPlacementPreviewError] = useState<string | null>(null);
  const [runtimeScriptReady, setRuntimeScriptReady] = useState(false);
  const [runtimeReady, setRuntimeReady] = useState(false);
  /** Absolute locked-cut frame of the active Stage 3 playhead (source or live composition). */
  const [playheadFrame, setPlayheadFrame] = useState(0);
  /** Display-only mirror of the craft panel's draft lines so reveal ticks track live edits. */
  const [draftPlacementLines, setDraftPlacementLines] = useState<PlacementLine[] | null>(null);
  /** Live Ends draft so the progress rail can mark graphic undock without waiting for autosave. */
  const [draftPlacementEndFrame, setDraftPlacementEndFrame] = useState<number | null>(null);
  /** Live motion draft (e.g. punch-zoom zoomIn/Out frames) for progress ticks. */
  const [draftPlacementMotion, setDraftPlacementMotion] = useState<Record<
    string,
    unknown
  > | null>(null);
  /** Right-column host under the graphic card — craft panel portals word chips here. */
  const [placementSpeechHostEl, setPlacementSpeechHostEl] = useState<HTMLDivElement | null>(
    null,
  );

  // Drop live draft mirrors when leaving a beat so the rail never ticks with stale Ends.
  useEffect(() => {
    setDraftPlacementLines(null);
    setDraftPlacementEndFrame(null);
    setDraftPlacementMotion(null);
  }, [selectedId]);
  /** App audio is buffered enough to play the whole beat without hitting the cliff. */
  const [previewAudioReady, setPreviewAudioReady] = useState(false);
  /** Stage 3 craft aid: 10×10 tenths grid over the live preview (not baked into renders). */
  const [placementGridOn, setPlacementGridOn] = useState(false);
  /** Stall watchdog bookkeeping — last observed frame and when it last changed. */
  const stallRef = useRef({ frame: -1, changedAt: 0 });
  /** Drag-select anchor only — does not commit selection until the pointer moves or click. */
  const dragAnchorRef = useRef<{
    zone: "gap" | "beat";
    beatId?: string;
    index: number;
  } | null>(null);
  /** True when pointer drag extended past the anchor word — suppress the following click. */
  const dragMovedRef = useRef(false);
  const suppressClickRef = useRef(false);

  const fps = result?.fps || status?.fps || 30;
  const videoUrl = hasVideoProject ? visualPackageSourceVideoUrl() : null;
  const transcriptWords = status?.transcriptWords ?? [];
  const wordIndexById = useMemo(() => wordIndexMap(transcriptWords), [transcriptWords]);
  const ledgerEntryCount = status?.ledgerEntryCount ?? result?.ledgerEntryCount ?? 0;
  const hasReviewed = Boolean(status?.reviewedExists);
  const assignment: AssignmentStatus | undefined = status?.assignment;
  const assignmentByBeat = assignment?.byBeatId ?? {};
  const assignmentLedgerCount = assignment?.ledgerEntryCount ?? 0;
  const scenelayer: ScenelayerStatus | undefined = status?.scenelayer;
  const scenelayerByBeat = scenelayer?.byBeatId ?? {};
  const scenelayerLedgerCount = scenelayer?.ledgerEntryCount ?? 0;
  const layoutIds =
    scenelayer?.layoutIds && scenelayer.layoutIds.length > 0
      ? scenelayer.layoutIds
      : [...OBS_LAYOUT_IDS];
  const stage2 = activeStage === 2;
  const stage3 = activeStage === 3;
  const placement: PlacementStatus | undefined = status?.placement;
  const placementByBeat = placement?.byBeatId ?? {};

  const eligibleForBeat = useCallback(
    (beat: MasterbeaterBeat): AssignmentEligibleUsage[] => {
      const typeList = assignment?.eligibleByBeatType?.[beat.beatType] ?? [];
      const layoutId = scenelayerByBeat[beat.id]?.layoutId;
      if (!layoutId) return [];
      return typeList.filter((usage) => {
        const full = assignment?.usages?.[usage.id];
        const allowed = full?.allowedLayouts;
        if (!allowed || allowed.length === 0) return false;
        return allowed.includes(layoutId);
      });
    },
    [assignment?.eligibleByBeatType, assignment?.usages, scenelayerByBeat],
  );

  const refresh = useCallback(async () => {
    if (!hasVideoProject) {
      setStatus(null);
      setResult(null);
      resultRef.current = null;
      setDraftBeats(null);
      setAutoSaveState("idle");
      return;
    }
    const data = await getVisualPackageStatus();
    setStatus(data);
    setResult(data.result);
    resultRef.current = data.result;
    setDraftBeats(null);
    setMembershipSel(null);
    dragAnchorRef.current = null;
    dragMovedRef.current = false;
    setAutoSaveState(data.reviewedExists ? "saved" : "idle");
  }, [hasVideoProject]);

  useEffect(() => {
    void refresh().catch((error: Error) => {
      setMessage(error.message || "Could not load Visual Package status.");
      setStatus(null);
      setResult(null);
      resultRef.current = null;
    });
  }, [refresh]);

  useEffect(() => {
    const resolve = () => {
      setRailHost(document.getElementById(VISUAL_PACKAGE_RAIL_HOST_ID));
    };
    resolve();
    const timer = window.setInterval(resolve, 200);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const endDrag = () => {
      if (dragMovedRef.current) {
        // Phrase was painted by drag — ignore the synthetic click that follows.
        suppressClickRef.current = true;
      }
      dragAnchorRef.current = null;
      dragMovedRef.current = false;
    };
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    return () => {
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
    };
  }, []);

  const serverBeats = result?.beats ?? [];
  const beats = draftBeats ?? serverBeats;
  const filteredBeats = useMemo(() => {
    return sortBeatsByTimeline(
      beats.filter((beat) => {
        if (typeFilter !== "all" && beat.beatType !== typeFilter) return false;
        if (layoutFilter !== "all") {
          const layoutId = scenelayerByBeat[beat.id]?.layoutId || "";
          if (layoutFilter === "__unset__") {
            if (layoutId) return false;
          } else if (layoutId !== layoutFilter) {
            return false;
          }
        }
        return true;
      }),
    );
  }, [beats, typeFilter, layoutFilter, scenelayerByBeat]);

  /**
   * Stage 3 navigation pool: every assigned/placed beat.
   * Stage 2 type/layout filters must NOT hide beats in Placement.
   */
  const placementBeats = useMemo(() => {
    const placed = beats.filter(
      (b) => placementByBeat[b.id] || assignmentByBeat[b.id]?.usageId,
    );
    return sortBeatsByTimeline(placed.length ? placed : beats);
  }, [beats, placementByBeat, assignmentByBeat]);

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const beat of beats) {
      counts.set(beat.beatType, (counts.get(beat.beatType) ?? 0) + 1);
    }
    return counts;
  }, [beats]);

  const layoutCounts = useMemo(() => {
    const counts = new Map<string, number>();
    let unset = 0;
    for (const beat of beats) {
      const layoutId = scenelayerByBeat[beat.id]?.layoutId;
      if (!layoutId) {
        unset += 1;
        continue;
      }
      counts.set(layoutId, (counts.get(layoutId) ?? 0) + 1);
    }
    if (unset > 0) counts.set("__unset__", unset);
    return counts;
  }, [beats, scenelayerByBeat]);

  const stream = useMemo(
    () =>
      buildTranscriptStream(
        transcriptWords,
        beats,
        typeFilter,
        layoutFilter,
        scenelayerByBeat,
      ),
    [transcriptWords, beats, typeFilter, layoutFilter, scenelayerByBeat],
  );

  const selected = useMemo(
    () => beats.find((beat) => beat.id === selectedId) ?? null,
    [beats, selectedId],
  );

  const autoSaveBeats = useCallback(
    async (next: MasterbeaterBeat[], edit: MasterbeaterEditEvent) => {
      const gen = ++autoSaveGen.current;
      setDraftBeats(next);
      setMembershipSel(null);
      dragAnchorRef.current = null;
      dragMovedRef.current = false;
      setAutoSaveState("saving");
      try {
        const current = resultRef.current;
        const saved = await saveMasterbeaterBeats({
          beats: next,
          mode: current?.mode,
          gaps: current?.gaps,
          edit,
        });
        if (gen !== autoSaveGen.current) return;
        setResult(saved);
        resultRef.current = saved;
        setDraftBeats(null);
        setStatus((prev) =>
          prev
            ? {
                ...prev,
                result: saved,
                reviewed: saved,
                reviewedExists: true,
                beatCount: saved.beatCount ?? saved.beats?.length ?? prev.beatCount,
                ledgerEntryCount: saved.ledgerEntryCount ?? (prev.ledgerEntryCount ?? 0) + 1,
                ledgerExists: true,
              }
            : prev,
        );
        setAutoSaveState("saved");
        const wordLabel = edit.wordText ? ` “${edit.wordText}”` : "";
        const seedNote = saved.seededManualBaseline ? " · seeded project baseline" : "";
        setMessage(
          `Auto-saved${wordLabel}${seedNote} · working copy + ledger (${saved.ledgerEntryCount ?? "?"} edits).`,
        );
      } catch (error) {
        if (gen !== autoSaveGen.current) return;
        setAutoSaveState("error");
        setMessage(error instanceof Error ? error.message : "Auto-save failed.");
      }
    },
    [],
  );

  const assignGapSelection = useCallback(
    (startIndex: number, endIndex: number, side: "prev" | "next") => {
      const fromWord = transcriptWords[startIndex];
      const toWord = transcriptWords[endIndex];
      if (!fromWord || !toWord) return;
      const { prev, next } = neighborsForGapSpan(beats, transcriptWords, fromWord.id, toWord.id);
      const target = side === "prev" ? prev : next;
      if (!target) {
        setMessage(
          side === "prev"
            ? "No previous beat to move that into."
            : "No next beat to move that into.",
        );
        return;
      }
      const nextBeats = addGapRangeToNeighbor(
        beats,
        transcriptWords,
        fromWord.id,
        toWord.id,
        side,
      );
      const phrase = selectionWordText(transcriptWords, startIndex, endIndex);
      void autoSaveBeats(nextBeats, {
        op: side === "prev" ? "addWordPrev" : "addWordNext",
        beatId: target.id,
        wordId: side === "prev" ? toWord.id : fromWord.id,
        wordText: phrase,
        side,
        detail:
          startIndex === endIndex
            ? undefined
            : `range ${fromWord.id}..${toWord.id} (${endIndex - startIndex + 1} words)`,
      });
    },
    [autoSaveBeats, beats, transcriptWords],
  );

  /** Beat + ↓: eject selection into plain transcript (yellow gap). */
  const ejectBeatSelectionToTranscript = useCallback(
    (beatId: string, startIndex: number, endIndex: number) => {
      const fromWord = transcriptWords[startIndex];
      const toWord = transcriptWords[endIndex];
      if (!fromWord || !toWord) return;
      const nextBeats = removeWordRangeFromBeat(
        beats,
        transcriptWords,
        beatId,
        fromWord.id,
        toWord.id,
      );
      const phrase = selectionWordText(transcriptWords, startIndex, endIndex);
      void autoSaveBeats(nextBeats, {
        op: startIndex === endIndex ? "removeWord" : "removeWordRange",
        beatId,
        wordId: fromWord.id,
        wordText: phrase,
        side: "next",
        detail:
          startIndex === endIndex
            ? "eject to transcript"
            : `eject range ${fromWord.id}..${toWord.id} to transcript`,
      });
    },
    [autoSaveBeats, beats, transcriptWords],
  );

  /** Start a potential drag-select (does not commit selection by itself). */
  const onWordPointerDown = useCallback(
    (
      zone: "gap" | "beat",
      beatId: string | undefined,
      wordIndex: number,
      event: ReactPointerEvent<HTMLButtonElement>,
    ) => {
      if (event.button !== 0 || wordIndex < 0) return;
      event.preventDefault();
      dragMovedRef.current = false;
      dragAnchorRef.current = { zone, beatId, index: wordIndex };
    },
    [],
  );

  /** Extend selection only after the pointer moves onto another word. */
  const onWordPointerEnter = useCallback(
    (
      zone: "gap" | "beat",
      beatId: string | undefined,
      wordIndex: number,
      event: ReactPointerEvent<HTMLButtonElement>,
    ) => {
      if ((event.buttons & 1) === 0 || wordIndex < 0) return;
      const anchor = dragAnchorRef.current;
      if (!anchor || anchor.zone !== zone || anchor.beatId !== beatId) return;
      if (wordIndex === anchor.index && !dragMovedRef.current) return;
      dragMovedRef.current = true;
      const range = normalizeSelectionRange(anchor.index, wordIndex);
      setMembershipSel({
        zone,
        beatId,
        anchorIndex: anchor.index,
        startIndex: range.startIndex,
        endIndex: range.endIndex,
      });
    },
    [],
  );

  /** Click only selects / unselects — never moves membership. */
  const onWordSelectClick = useCallback(
    (
      zone: "gap" | "beat",
      beatId: string | undefined,
      wordId: string,
      event: ReactMouseEvent<HTMLButtonElement>,
    ) => {
      event.stopPropagation();
      if (suppressClickRef.current) {
        suppressClickRef.current = false;
        return;
      }
      const index = wordIndexById.get(wordId);
      if (index == null) return;

      if (event.shiftKey) {
        setMembershipSel((prev) => {
          if (prev && prev.zone === zone && prev.beatId === beatId) {
            const range = normalizeSelectionRange(prev.anchorIndex, index);
            return { ...prev, ...range };
          }
          return {
            zone,
            beatId,
            anchorIndex: index,
            startIndex: index,
            endIndex: index,
          };
        });
        return;
      }

      // Toggle off when clicking inside the current selection.
      if (
        membershipSel &&
        membershipSel.zone === zone &&
        membershipSel.beatId === beatId &&
        selectionCoversIndex(membershipSel, index)
      ) {
        setMembershipSel(null);
        return;
      }

      // Replace with a new single-word selection.
      setMembershipSel({
        zone,
        beatId,
        anchorIndex: index,
        startIndex: index,
        endIndex: index,
      });
    },
    [membershipSel, wordIndexById],
  );

  const selectionArrowActions = useMemo(() => {
    if (!membershipSel) return null;
    const { zone, beatId, startIndex, endIndex } = membershipSel;
    const fromWord = transcriptWords[startIndex];
    const toWord = transcriptWords[endIndex];
    if (!fromWord || !toWord) return null;

    if (zone === "gap") {
      const { prev, next } = neighborsForGapSpan(
        beats,
        transcriptWords,
        fromWord.id,
        toWord.id,
      );
      return {
        zone: "gap" as const,
        onUp: prev
          ? () => assignGapSelection(startIndex, endIndex, "prev")
          : undefined,
        onDown: next
          ? () => assignGapSelection(startIndex, endIndex, "next")
          : undefined,
        upTitle: prev
          ? `Move into previous beat (${prev.beatType})`
          : undefined,
        downTitle: next
          ? `Move into next beat (${next.beatType})`
          : undefined,
      };
    }

    // In-beat: both arrows eject into plain transcript (never auto-merge into a neighbor card).
    if (!beatId) return null;
    const eject = () => ejectBeatSelectionToTranscript(beatId, startIndex, endIndex);
    return {
      zone: "beat" as const,
      onUp: eject,
      onDown: eject,
      upTitle: "Split out into transcript (out of this beat)",
      downTitle: "Split out into transcript (out of this beat)",
    };
  }, [
    assignGapSelection,
    beats,
    ejectBeatSelectionToTranscript,
    membershipSel,
    transcriptWords,
  ]);

  const adjacentForSelected = useMemo(() => {
    if (!selected) return { prev: null, next: null, current: null };
    return findAdjacentBeats(beats, transcriptWords, selected.id);
  }, [beats, selected, transcriptWords]);

  const [newBeatType, setNewBeatType] = useState<string>("setup");

  const onChangeSelectedType = useCallback(
    (beatType: string) => {
      if (!selected || selected.beatType === beatType) return;
      const next = changeBeatType(beats, selected.id, beatType);
      void autoSaveBeats(next, {
        op: "changeBeatType",
        beatId: selected.id,
        detail: `${selected.beatType} → ${beatType}`,
      });
    },
    [autoSaveBeats, beats, selected],
  );

  const onDeleteSelectedBeat = useCallback(() => {
    if (!selected) return;
    if (beats.length <= 1) {
      setMessage("Cannot delete the last beat — add another first, or eject its words instead.");
      return;
    }
    const next = deleteBeat(beats, selected.id);
    const removedId = selected.id;
    const fallbackId = next[0]?.id ?? null;
    setSelectedId((prev) => (prev === removedId ? fallbackId : prev));
    setMembershipSel(null);
    void autoSaveBeats(next, {
      op: "deleteBeat",
      beatId: removedId,
      detail: `deleted ${selected.beatType} beat`,
    });
  }, [autoSaveBeats, beats, selected]);

  const onMergeSelected = useCallback(
    (side: "prev" | "next") => {
      if (!selected) return;
      const result = mergeBeatWithNeighbor(beats, transcriptWords, selected.id, side);
      if ("error" in result) {
        setMessage(result.error);
        return;
      }
      setSelectedId(result.keptId);
      setMembershipSel(null);
      void autoSaveBeats(result.beats, {
        op: "mergeBeats",
        beatId: result.keptId,
        side,
        detail: `merged ${side} into ${result.keptId}`,
      });
    },
    [autoSaveBeats, beats, selected, transcriptWords],
  );

  const onSplitAfterSelection = useCallback(() => {
    if (!membershipSel || membershipSel.zone !== "beat" || !membershipSel.beatId) {
      setMessage("Select words inside a beat, then Split (cut after the selection).");
      return;
    }
    const result = splitBeatAfter(
      beats,
      transcriptWords,
      membershipSel.beatId,
      membershipSel.endIndex,
    );
    if ("error" in result) {
      setMessage(result.error);
      return;
    }
    setSelectedId(result.leftId);
    setMembershipSel(null);
    void autoSaveBeats(result.beats, {
      op: "splitBeat",
      beatId: result.leftId,
      wordId: transcriptWords[membershipSel.endIndex]?.id,
      detail: `split → ${result.leftId} + ${result.rightId}`,
    });
  }, [autoSaveBeats, beats, membershipSel, transcriptWords]);

  const onAddBeatFromSelection = useCallback(() => {
    if (!membershipSel || membershipSel.zone !== "gap") {
      setMessage("Select yellow transcript words first, then New beat.");
      return;
    }
    const result = addBeatFromRange(
      beats,
      transcriptWords,
      membershipSel.startIndex,
      membershipSel.endIndex,
      newBeatType,
    );
    if ("error" in result) {
      setMessage(result.error);
      return;
    }
    setSelectedId(result.beat.id);
    setMembershipSel(null);
    const phrase = selectionWordText(
      transcriptWords,
      membershipSel.startIndex,
      membershipSel.endIndex,
    );
    void autoSaveBeats(result.beats, {
      op: "addBeat",
      beatId: result.beat.id,
      wordId: result.beat.startWordId,
      wordText: phrase,
      detail: `new ${newBeatType} beat`,
    });
  }, [autoSaveBeats, beats, membershipSel, newBeatType, transcriptWords]);

  const canSplitAfterSelection = useMemo(() => {
    if (!membershipSel || membershipSel.zone !== "beat" || !membershipSel.beatId) return false;
    const indexById = wordIndexById;
    const beat = beats.find((item) => item.id === membershipSel.beatId);
    if (!beat) return false;
    const start = indexById.get(String(beat.startWordId || ""));
    const end = indexById.get(String(beat.endWordId || ""));
    if (start == null || end == null) return false;
    return membershipSel.endIndex >= start && membershipSel.endIndex < end;
  }, [beats, membershipSel, wordIndexById]);

  const canAddBeatFromSelection = Boolean(
    membershipSel && membershipSel.zone === "gap",
  );

  useEffect(() => {
    // Stage 2/1: respect type/layout filters. Stage 3: full placement set.
    const pool = stage3 ? placementBeats : filteredBeats;
    if (!selectedId && pool.length > 0) {
      setSelectedId(pool[0].id);
      return;
    }
    if (selectedId && !beats.some((b) => b.id === selectedId) && pool.length > 0) {
      setSelectedId(pool[0].id);
      return;
    }
    // Stage 3: if current selection is not a placeable beat, jump to first placeable.
    if (
      stage3 &&
      selectedId &&
      pool.length > 0 &&
      !pool.some((b) => b.id === selectedId)
    ) {
      setSelectedId(pool[0].id);
    }
  }, [beats, filteredBeats, placementBeats, selectedId, stage3]);

  const stage3LivePreview =
    stage3 &&
    Boolean(placementPreview?.available && placementPreview.cacheKey) &&
    runtimeScriptReady;

  const compositionRangeStartSec = placementPreview?.rangeStartSec ?? 0;
  /** Full Stage 3 preview clip length (composition is already trimmed to this beat). */
  const compositionDurationSec = Math.max(
    0.05,
    Number(placementPreview?.durationSec) || 0.05,
  );

  /**
   * Stage 3 progress rail: end caps are always the *beat* span.
   * Yellow ticks = line reveal frames + graphic Ends (when trimmed before beat end).
   */
  const beatProgress = useMemo(() => {
    if (!stage3 || !selected) return null;
    const pb = placementByBeat[selected.id];
    const startFrame =
      pb?.startFrame ?? placementPreview?.startFrame ?? selected.startFrame;
    // Right end cap = natural beat end (not the trimmed graphic end).
    const beatEndFrameExclusive =
      selected.endFrameExclusive ??
      (selected.endFrame != null ? selected.endFrame + 1 : undefined) ??
      pb?.endFrameExclusive ??
      placementPreview?.endFrameExclusive;
    if (
      startFrame == null ||
      beatEndFrameExclusive == null ||
      beatEndFrameExclusive <= startFrame
    ) {
      return null;
    }
    const lines = draftPlacementLines ?? pb?.lines ?? [];
    const graphicEnd =
      draftPlacementEndFrame ??
      pb?.endFrameExclusive ??
      placementPreview?.endFrameExclusive ??
      null;
    const motionBag = draftPlacementMotion ?? pb?.motion ?? {};
    const motionTicks = (["zoomInFrame", "zoomOutFrame"] as const)
      .map((key) => {
        const raw = motionBag[key];
        const frame = typeof raw === "number" ? raw : Number(raw);
        return Number.isFinite(frame) ? frame : null;
      })
      .filter(
        (frame): frame is number =>
          frame != null && frame >= startFrame && frame < beatEndFrameExclusive,
      );
    const revealTicks = lines
      .map((line) => {
        const frame = line.revealFrame;
        if (!Number.isFinite(frame)) return null;
        const slot = String(line.slot || "");
        let label = slot || "reveal";
        if (slot === "text" || slot === "title") label = "Title";
        else if (slot === "startLabel") label = "Start";
        else if (slot === "targetLabel") label = "Target";
        else if (slot.startsWith("milestones.")) {
          label = `Stop ${Number(slot.slice("milestones.".length)) + 1}`;
        } else if (slot.includes(".")) {
          const [head, idx] = slot.split(".");
          label = `${head} ${Number(idx) + 1}`;
        }
        return { frame: frame as number, label };
      })
      .filter(
        (tick): tick is { frame: number; label: string } =>
          tick != null &&
          tick.frame >= startFrame &&
          tick.frame < beatEndFrameExclusive,
      );
    return {
      startFrame,
      endFrameExclusive: beatEndFrameExclusive,
      revealTicks,
      graphicEndFrame:
        graphicEnd != null &&
        Number.isFinite(graphicEnd) &&
        graphicEnd > startFrame &&
        graphicEnd < beatEndFrameExclusive
          ? graphicEnd
          : null,
      motionFrames: motionTicks,
    };
  }, [
    stage3,
    selected,
    placementByBeat,
    placementPreview,
    draftPlacementLines,
    draftPlacementEndFrame,
    draftPlacementMotion,
  ]);

  /**
   * Simple Stage 3 transport — same pattern as visual-production:
   * mount player once per composition, play/pause/seek only. No remount thrash.
   */
  /**
   * Stage 3 speech audio is an app-owned <audio> element, NOT part of the composition.
   * The HyperFrames transport derives its master clock from in-composition audio and
   * can pin (freeze) on it mid-play; preview compositions are built without #main-audio
   * so the runtime clock is pure monotonic time. This element mirrors the player:
   * drift-corrected on timeupdate, played/paused/seeked alongside the transport.
   */
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const syncPreviewAudio = useCallback(
    (localSec: number, action?: "play" | "pause") => {
      const audio = previewAudioRef.current;
      if (!audio) return;
      try {
        // Never seek a still-buffering element (readyState < HAVE_FUTURE_DATA):
        // each seek restarts its fetch, which starves it into a permanent stall.
        if (
          Number.isFinite(localSec) &&
          audio.readyState >= 3 &&
          Math.abs(audio.currentTime - localSec) > 0.12
        ) {
          audio.currentTime = Math.max(0, localSec);
        }
        if (action === "play" && audio.paused) {
          void audio.play().catch((error: unknown) => {
            // Surface the reason (autoplay policy, decode, fetch) instead of silent mute.
            console.warn("[visual-package] preview audio failed to start:", error);
          });
        } else if (action === "pause" && !audio.paused) {
          audio.pause();
        }
      } catch {
        /* audio is best-effort — never block the visual transport */
      }
    },
    [],
  );

  const stopStage3Preview = useCallback(() => {
    const player = runtimePlayerRef.current;
    try {
      player?.pause();
    } catch {
      /* ignore */
    }
    syncPreviewAudio(Number.NaN, "pause");
    setPlaying(false);
  }, [syncPreviewAudio]);

  const playStage3Preview = useCallback(() => {
    const player = runtimePlayerRef.current;
    if (!player) return;
    try {
      // HF play() already seeks to 0 when currentTime >= duration.
      const duration = Math.max(
        0.05,
        Number(player.duration) || Number(placementPreview?.durationSec) || 0.05,
      );
      let t = Number(player.currentTime) || 0;
      if (t >= duration - 0.12 || t < 0) {
        player.seek(0);
        t = 0;
      }
      player.play();
      syncPreviewAudio(t, "play");
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
  }, [placementPreview?.durationSec, syncPreviewAudio]);

  const seekToBeat = useCallback(
    (beat: MasterbeaterBeat, autoplay: boolean) => {
      const start = beatStartSec(beat, fps);
      setPlayheadFrame(Math.round(start * fps));

      if (stage3 && runtimePlayerRef.current && placementPreview?.available) {
        const player = runtimePlayerRef.current;
        // Composition local 0 = start of this beat's preview package.
        try {
          player.seek(0);
          if (autoplay) {
            player.play();
            syncPreviewAudio(0, "play");
            setPlaying(true);
          } else {
            player.pause();
            syncPreviewAudio(0, "pause");
            setPlaying(false);
          }
        } catch {
          setPlaying(false);
        }
        setPlayheadFrame(Math.round((placementPreview.rangeStartSec ?? start) * fps));
        return;
      }

      const video = videoRef.current;
      if (!video) return;
      const apply = () => {
        video.currentTime = Math.max(0, start);
        if (autoplay) {
          void video.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
        } else {
          video.pause();
          setPlaying(false);
        }
      };
      if (video.readyState >= 1) apply();
      else video.addEventListener("loadedmetadata", apply, { once: true });
    },
    [fps, placementPreview, stage3, syncPreviewAudio],
  );

  const selectBeat = useCallback(
    (beat: MasterbeaterBeat, autoplay?: boolean) => {
      const shouldPlay = autoplay ?? autoplayOnSelect;
      setSelectedId(beat.id);
      seekToBeat(beat, shouldPlay);
      const node = streamRef.current?.querySelector(`[data-beat-id="${beat.id}"]`);
      node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
    [autoplayOnSelect, seekToBeat],
  );

  const onTimeUpdate = () => {
    const video = videoRef.current;
    if (!video || !selected || stage3LivePreview) return;
    setPlayheadFrame(Math.round(video.currentTime * fps));
    const end = beatEndSec(selected, fps);
    if (video.currentTime >= end - 0.02) {
      if (loopBeat) {
        video.currentTime = beatStartSec(selected, fps);
      } else {
        video.pause();
        setPlaying(false);
        video.currentTime = end;
      }
    }
  };

  const togglePlay = () => {
    if (!selected) return;

    if (stage3LivePreview) {
      // React state owns the button — player.paused is unreliable after natural end.
      if (playing) stopStage3Preview();
      else playStage3Preview();
      return;
    }

    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      const start = beatStartSec(selected, fps);
      const end = beatEndSec(selected, fps);
      if (video.currentTime < start - 0.05 || video.currentTime >= end - 0.05) {
        video.currentTime = start;
      }
      void video.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    } else {
      video.pause();
      setPlaying(false);
    }
  };

  const seekAbsoluteFrame = useCallback(
    (frame: number, autoplay = false) => {
      const clamped = Math.max(0, Math.round(frame));
      setPlayheadFrame(clamped);
      const absSec = clamped / Math.max(fps, 1);

      if (stage3LivePreview && runtimePlayerRef.current && placementPreview) {
        const local = Math.max(0, absSec - (placementPreview.rangeStartSec ?? 0));
        const player = runtimePlayerRef.current;
        try {
          player.seek(local);
          if (autoplay) {
            player.play();
            syncPreviewAudio(local, "play");
            setPlaying(true);
          } else {
            player.pause();
            syncPreviewAudio(local, "pause");
            setPlaying(false);
          }
        } catch {
          setPlaying(false);
        }
        return;
      }

      const video = videoRef.current;
      if (!video) return;
      video.pause();
      setPlaying(false);
      video.currentTime = Math.max(0, absSec);
    },
    [fps, placementPreview, stage3LivePreview, syncPreviewAudio],
  );

  const refreshPlacementPreview = useCallback(
    async (
      beatId: string,
      draft?: {
        lines?: PlacementLine[];
        meta?: Record<string, unknown>;
        assets?: Record<string, unknown>;
        motion?: Record<string, unknown>;
        endFrameExclusive?: number;
        force?: boolean;
      },
    ) => {
      if (!hasVideoProject || !beatId) return;
      const gen = ++placementPreviewGen.current;
      setPlacementPreviewBusy(true);
      setPlacementPreviewError(null);
      // Unmount the live player + app audio before the server rewrites the
      // HyperFrames workspace. Leaving source.mp4 open on Windows causes
      // WinError 32 when the next build tries to clear the same fingerprint dir.
      setPlacementPreview(null);
      setRuntimeReady(false);
      setPlaying(false);
      try {
        const data = await buildPlacementPreview({
          beatId,
          lines: draft?.lines,
          meta: draft?.meta,
          assets: draft?.assets,
          motion: draft?.motion,
          endFrameExclusive: draft?.endFrameExclusive,
          force: draft?.force,
        });
        if (gen !== placementPreviewGen.current) return;
        if (data.available && data.cacheKey) {
          setPlacementPreview(data);
          setPlacementPreviewError(null);
        } else {
          setPlacementPreview(null);
          setPlacementPreviewError("Live preview composition is not available for this beat.");
        }
        setRuntimeReady(false);
      } catch (error) {
        if (gen !== placementPreviewGen.current) return;
        setPlacementPreview(null);
        const detail =
          error instanceof Error
            ? error.message
            : "Could not build live placement preview.";
        setPlacementPreviewError(detail);
        setMessage(detail);
      } finally {
        if (gen === placementPreviewGen.current) {
          setPlacementPreviewBusy(false);
        }
      }
    },
    [hasVideoProject],
  );

  // Load HyperFrames player CE once; only mark ready after the custom element is defined.
  useEffect(() => {
    let cancelled = false;
    const markReady = () => {
      if (!cancelled) setRuntimeScriptReady(true);
    };
    if (customElements.get("hyperframes-player")) {
      markReady();
      return () => {
        cancelled = true;
      };
    }
    let script = document.querySelector<HTMLScriptElement>(
      'script[data-vcg-hyperframes-player="true"]',
    );
    if (!script) {
      script = document.createElement("script");
      script.src = visualRuntimePlayerUrl();
      script.async = true;
      script.dataset.vcgHyperframesPlayer = "true";
      document.head.appendChild(script);
    }
    const onError = () => {
      if (!cancelled) {
        setRuntimeScriptReady(false);
        setPlacementPreviewError("Could not load the HyperFrames player script.");
      }
    };
    const waitForDefine = () => {
      void customElements
        .whenDefined("hyperframes-player")
        .then(markReady)
        .catch(onError);
    };
    if (script.getAttribute("data-loaded") === "true" || customElements.get("hyperframes-player")) {
      waitForDefine();
    } else {
      script.addEventListener("load", () => {
        script?.setAttribute("data-loaded", "true");
        waitForDefine();
      }, { once: true });
      script.addEventListener("error", onError, { once: true });
      // Script may already have finished loading before listeners attached.
      if ((script as HTMLScriptElement & { readyState?: string }).readyState === "complete") {
        waitForDefine();
      }
    }
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedPlacement = selectedId ? placementByBeat[selectedId] : undefined;

  // Build live Tier B when Stage 3 opens a beat — not on every craft keystroke.
  // Craft edits stay local until "Save & update preview"; that path rebuilds once.
  useEffect(() => {
    if (!stage3) {
      setPlacementPreview(null);
      setPlacementPreviewError(null);
      setRuntimeReady(false);
      setPlaying(false);
      return;
    }
    if (!selectedId || !selectedPlacement) {
      setPlacementPreview(null);
      setRuntimeReady(false);
      setPlaying(false);
      if (selectedId && !selectedPlacement) {
        setPlacementPreviewError(
          placement?.originalExists
            ? "This beat has no placement yet (unassigned or skipped)."
            : "Press Place to draft lines, then live graphics load here.",
        );
      } else {
        setPlacementPreviewError(null);
      }
      return;
    }
    setPlaying(false);
    void refreshPlacementPreview(selectedId, {
      lines: selectedPlacement.lines,
      meta: (selectedPlacement.meta || {}) as Record<string, unknown>,
      assets: (selectedPlacement.assets || {}) as Record<string, unknown>,
      motion: (selectedPlacement.motion || {}) as Record<string, unknown>,
      endFrameExclusive: selectedPlacement.endFrameExclusive,
      force: false,
    });
    // Only when the selected beat changes — not when autosaved craft echoes back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage3, selectedId, refreshPlacementPreview]);

  // Simple HF player wiring — mount once per cacheKey. No native loop: the live
  // preview plays a beat ONCE per click (loop wraps re-seek media mid-flight and
  // were implicated in transport stalls; one-shot keeps the pipeline simple).
  useEffect(() => {
    if (!stage3LivePreview) return;
    const player = runtimePlayerRef.current;
    if (!player || !runtimeScriptReady) return;

    try {
      player.loop = false;
    } catch {
      /* ignore */
    }

    const onReady = () => {
      setRuntimeReady(true);
      try {
        player.loop = false;
        player.seek(0);
      } catch {
        /* ignore */
      }
      // The runtime's WebAudio transport can pin the master clock to a suspended
      // AudioContext ~0.6s after play (composition iframe is cross-origin, so it
      // may never get user activation) — playback then freezes mid-beat while
      // still reporting "playing". Force the native audio-element clock instead,
      // same configuration the slideshow player ships with. Must be sent after
      // ready: the player's own _replayBridgeState resets this flag on ready.
      try {
        player._sendControl?.("set-web-audio-media-disabled", { disabled: true });
      } catch {
        /* ignore */
      }
      setPlayheadFrame(Math.round(compositionRangeStartSec * fps));
      // "ready" can late-fire after the user already hit Play (Play arms on audio
      // buffering, not player readiness) — never kill a run that's in flight.
      if (player.paused) {
        syncPreviewAudio(0, "pause");
        setPlaying(false);
      }
    };
    const onTimeUpdate = (event: Event) => {
      const detail = (event as CustomEvent<{ currentTime?: number }>).detail;
      const local = Number.isFinite(detail?.currentTime)
        ? Number(detail?.currentTime)
        : Number(player.currentTime) || 0;
      const frame = Math.round((local + compositionRangeStartSec) * fps);
      if (frame !== stallRef.current.frame) {
        stallRef.current.frame = frame;
        stallRef.current.changedAt = performance.now();
      }
      // Keep the app-owned speech audio glued to the transport (loop wraps included).
      syncPreviewAudio(local);
      setPlayheadFrame(frame);
    };
    const onPlay = () => {
      // Re-assert on every play: transport restarts must keep the fragile
      // WebAudio clock off for the whole session (see onReady).
      try {
        player._sendControl?.("set-web-audio-media-disabled", { disabled: true });
      } catch {
        /* ignore */
      }
      stallRef.current.changedAt = performance.now();
      syncPreviewAudio(Number(player.currentTime) || 0, "play");
      setPlaying(true);
    };
    const onPause = () => {
      syncPreviewAudio(Number.NaN, "pause");
      setPlaying(false);
    };
    const stopAtEnd = () => {
      // One-shot: hard stop (pause + rewind). Never leave the transport "playing"
      // after a seek-to-0 — that restarts the clip and looks like a loop.
      try {
        player.pause();
      } catch {
        /* ignore */
      }
      try {
        player.loop = false;
      } catch {
        /* ignore */
      }
      syncPreviewAudio(Number.NaN, "pause");
      setPlaying(false);
      try {
        player.seek(0);
      } catch {
        /* ignore */
      }
      syncPreviewAudio(0);
    };
    const onEnded = () => {
      stopAtEnd();
    };
    const onTimeUpdateGuard = (event: Event) => {
      onTimeUpdate(event);
      // Some HF builds wrap without a clean "ended" — stop when we hit the tail.
      const duration = Math.max(
        0.05,
        Number(player.duration) || Number(placementPreview?.durationSec) || 0.05,
      );
      const local = Number(player.currentTime) || 0;
      if (local >= duration - 0.04 && !player.paused) {
        stopAtEnd();
      }
    };

    player.addEventListener("ready", onReady);
    player.addEventListener("timeupdate", onTimeUpdateGuard);
    player.addEventListener("play", onPlay);
    player.addEventListener("pause", onPause);
    player.addEventListener("ended", onEnded);
    if (player.ready) onReady();
    return () => {
      player.removeEventListener("ready", onReady);
      player.removeEventListener("timeupdate", onTimeUpdateGuard);
      player.removeEventListener("play", onPlay);
      player.removeEventListener("pause", onPause);
      player.removeEventListener("ended", onEnded);
    };
  }, [
    stage3LivePreview,
    runtimeScriptReady,
    placementPreview?.cacheKey,
    placementPreview?.durationSec,
    fps,
    compositionRangeStartSec,
    syncPreviewAudio,
  ]);

  /**
   * Stall watchdog — detection only, no auto-recovery. If the playhead stops
   * advancing for ~1.5s while "playing", stop cleanly and log. Automatic
   * pause/seek/play + remount cycles fought the stall and made the window jank
   * worse; a clean stop leaves the user one click from trying again.
   */
  useEffect(() => {
    if (!playing || !stage3LivePreview) return;
    stallRef.current.changedAt = performance.now();
    const timer = window.setInterval(() => {
      const state = stallRef.current;
      const now = performance.now();
      // Hidden tab: rAF (and therefore the transport clock) is legitimately parked.
      if (document.hidden) {
        state.changedAt = now;
        return;
      }
      if (now - state.changedAt < 1500) return;
      console.warn("[visual-package] live preview stalled — stopping (no auto-recovery)");
      const player = runtimePlayerRef.current;
      try {
        player?.pause();
      } catch {
        /* ignore */
      }
      syncPreviewAudio(Number.NaN, "pause");
      setPlaying(false);
    }, 400);
    return () => window.clearInterval(timer);
  }, [playing, stage3LivePreview, syncPreviewAudio]);

  /**
   * Beats to step through in Stage 2/3 transport.
   * Stage 2: filtered by type/layout. Stage 3: full placement set (filters ignored).
   */
  const reviewBeats = useMemo(() => {
    if (!stage3) return filteredBeats;
    return placementBeats;
  }, [stage3, filteredBeats, placementBeats]);
  const reviewIndex = useMemo(() => {
    if (!reviewBeats.length || !selectedId) return -1;
    return reviewBeats.findIndex((b) => b.id === selectedId);
  }, [reviewBeats, selectedId]);

  const stepBeat = useCallback(
    (delta: number) => {
      if (!reviewBeats.length) return;
      const index = Math.max(0, reviewBeats.findIndex((b) => b.id === selectedId));
      const nextIndex = Math.min(reviewBeats.length - 1, Math.max(0, index + delta));
      const next = reviewBeats[nextIndex];
      if (!next) return;
      // Stage 3 has no Autoplay pill: stepping just navigates; Play is explicit.
      selectBeat(next, stage3 ? false : autoplayOnSelect);
    },
    [reviewBeats, selectedId, autoplayOnSelect, selectBeat, stage3],
  );

  // Keyboard: ← / → (and j / k) step beats during Stage 2 layout review.
  useEffect(() => {
    if (!stage2) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || target?.isContentEditable) {
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "j" || event.key === "J") {
        event.preventDefault();
        stepBeat(-1);
      } else if (event.key === "ArrowRight" || event.key === "k" || event.key === "K") {
        event.preventDefault();
        stepBeat(1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stage2, stepBeat]);

  const onRun = async () => {
    if (!hasVideoProject || busy) return;
    setBusy(true);
    setMessage("Running Masterbeater via API (experimental)… prefer Grok skill + Refresh for production.");
    try {
      const data = await runMasterbeater();
      setResult(data);
      await refresh();
      setMessage(`Masterbeater finished: ${data.beatCount ?? data.beats?.length ?? 0} beats.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Masterbeater failed.");
    } finally {
      setBusy(false);
    }
  };

  const onScenelayer = async () => {
    if (!hasVideoProject || busy) return;
    if (!status?.outputExists && !status?.reviewedExists) {
      setMessage("Place at least one Stage 1 beat (manual or Masterbeater) before Scenelayer.");
      return;
    }
    setBusy(true);
    setMessage(
      scenelayer?.originalExists
        ? "Re-running scenelayer (keeping your manual layouts)…"
        : "Labeling layouts from first frame of each beat…",
    );
    try {
      const data = await runScenelayer();
      await refresh();
      const labeled = data.labeledCount ?? 0;
      const unlabeled = data.unlabeledCount ?? 0;
      setMessage(
        data.firstRun
          ? `Scenelayer labeled ${labeled} beat(s)${unlabeled ? ` · ${unlabeled} unlabeled` : ""}.`
          : `Scenelayer re-ran · ${labeled} labeled · manual layouts kept.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Scenelayer failed.");
    } finally {
      setBusy(false);
    }
  };

  const onAssign = async () => {
    if (!hasVideoProject || busy) return;
    if (!status?.outputExists && !status?.reviewedExists) {
      setMessage("Place at least one Stage 1 beat (manual or Masterbeater) before Assign.");
      return;
    }
    setBusy(true);
    setMessage(
      assignment?.originalExists
        ? "Re-running assignment (keeping your manual picks)…"
        : "Assigning golden graphics…",
    );
    try {
      const data = await runAssignment();
      await refresh();
      const assigned = data.assignedCount ?? 0;
      const unassigned = data.unassignedCount ?? 0;
      setMessage(
        data.firstRun
          ? `Assigned ${assigned} graphic(s)${unassigned ? ` · ${unassigned} empty (type/layout)` : ""}.`
          : `Re-dealt algorithm picks · ${assigned} assigned · manual overrides kept.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Assignment failed.");
    } finally {
      setBusy(false);
    }
  };

  const onLayoutSwap = useCallback(
    async (beatId: string, layoutId: string | null, advanceAfter?: boolean) => {
      if (busy) return;
      if (!scenelayer?.originalExists) {
        setMessage("Press Scenelayer first, then change layouts.");
        return;
      }
      setBusy(true);
      try {
        await saveScenelayerOverride({
          beatId,
          layoutId,
          detail: layoutId ? `layout → ${layoutId}` : "clear layout",
        });
        await refresh();
        setMessage(
          layoutId
            ? `Layout set to ${layoutId} on ${beatId}${advanceAfter ? " · next beat" : ""}.`
            : `Cleared layout on ${beatId}.`,
        );
        if (advanceAfter) {
          // After save, jump to next in the current filter list.
          const list = reviewBeats;
          const idx = list.findIndex((b) => b.id === beatId);
          const next = idx >= 0 && idx < list.length - 1 ? list[idx + 1] : null;
          if (next) selectBeat(next, autoplayOnSelect);
        }
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Could not save layout.");
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh, scenelayer?.originalExists, reviewBeats, selectBeat, autoplayOnSelect],
  );

  const onAssignmentSwap = useCallback(
    async (beatId: string, usageId: string | null) => {
      if (busy) return;
      setBusy(true);
      try {
        await saveAssignmentOverride({
          beatId,
          usageId,
          detail: usageId ? `swap to ${usageId}` : "clear usage",
        });
        await refresh();
        setMessage(usageId ? `Saved graphic override on ${beatId}.` : `Cleared graphic on ${beatId}.`);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Could not save graphic override.");
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh],
  );

  const onPlace = async () => {
    if (!hasVideoProject || busy) return;
    setBusy(true);
    setMessage(
      placement?.originalExists
        ? "Re-placing unlocked beats (locked beats kept)…"
        : "Drafting placement lines + reveal frames…",
    );
    try {
      const data = await runPlacement();
      await refresh();
      setMessage(
        data.firstRun
          ? `Placed ${data.placementCount ?? 0} beat(s). Edit lines, preview span, then Lock.`
          : `Re-placed unlocked · ${data.lockedCount ?? 0} locked kept · ${data.unlockedCount ?? 0} open.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Place failed.");
    } finally {
      setBusy(false);
    }
  };

  const finalRunning =
    placementFinalJob?.status === "running" || placementFinalJob?.status === "canceling";

  /** Full-episode Final: locked placements → HyperFrames encode + locked-cut audio remux. */
  const onFinal = async () => {
    if (!hasVideoProject || busy || finalRunning) return;
    if (!placement?.finalRenderReady) {
      setMessage(
        `Lock remaining beats (${placement?.unlockedCount ?? "?"} unlocked) before Final.`,
      );
      return;
    }
    setBusy(true);
    setFinalCanceling(false);
    setFinalModalOpen(true);
    setMessage("Starting full-episode Final (graphics + locked-cut audio)…");
    try {
      const started = await startPlacementFinal({ quality: "standard", force: true });
      const job = started.job;
      setPlacementFinalJob(job);
      setFinalModalOpen(true);
      if (started.reconnected) {
        setMessage(
          `Final already running · ${Math.round(job.value)}% · ${job.message || "rendering"}`,
        );
      } else {
        setMessage(job.message || "Final render started…");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start Final.");
      setPlacementFinalJob(null);
      setFinalModalOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const onCancelFinal = async () => {
    if (!placementFinalJob?.job_id || finalCanceling) return;
    if (placementFinalJob.status !== "running" && placementFinalJob.status !== "canceling") {
      return;
    }
    setFinalCanceling(true);
    setMessage("Canceling Final render…");
    try {
      const result = await cancelPlacementFinal(placementFinalJob.job_id);
      setPlacementFinalJob(result.job);
      setMessage(result.job.message || "Canceling Final render…");
    } catch (error) {
      setFinalCanceling(false);
      setMessage(error instanceof Error ? error.message : "Could not cancel Final.");
    }
  };

  // Poll active Final job; reconnect after refresh / reload.
  useEffect(() => {
    if (!hasVideoProject) {
      setPlacementFinalJob(null);
      setFinalModalOpen(false);
      return;
    }
    let cancelled = false;
    const hydrate = async () => {
      try {
        const active = await getActivePlacementFinalJob();
        if (!cancelled && active.job) {
          setPlacementFinalJob(active.job);
          if (active.job.status === "running" || active.job.status === "canceling") {
            setFinalModalOpen(true);
          }
        }
      } catch {
        /* no open job is fine */
      }
    };
    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [hasVideoProject, projectName]);

  useEffect(() => {
    if (
      !placementFinalJob ||
      !placementFinalJob.job_id ||
      (placementFinalJob.status !== "running" && placementFinalJob.status !== "canceling")
    ) {
      return;
    }
    let cancelled = false;
    const jobId = placementFinalJob.job_id;
    const tick = async () => {
      try {
        const next = await getPlacementFinalJob(jobId);
        if (cancelled) return;
        setPlacementFinalJob(next);
        if (next.status === "running" || next.status === "canceling") {
          setMessage(
            `Final ${Math.round(next.value)}% · ${next.message || next.stage || "rendering"}`,
          );
        } else if (next.status === "complete") {
          setFinalCanceling(false);
          setMessage(
            next.output_path
              ? `Final ready · ${next.output_path}`
              : "Final video ready (exports/final-video.mp4).",
          );
        } else if (next.status === "canceled") {
          setFinalCanceling(false);
          setMessage("Final render canceled.");
        } else if (next.status === "failed") {
          setFinalCanceling(false);
          setMessage(next.error || next.message || "Final render failed.");
        }
      } catch (error) {
        if (!cancelled) {
          setMessage(error instanceof Error ? error.message : "Lost Final job status.");
        }
      }
    };
    const handle = window.setInterval(() => {
      void tick();
    }, 1500);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [placementFinalJob?.job_id, placementFinalJob?.status]);

  /** Saves serialize so rapid commits never race. Preview rebuilds only after a real save. */
  const placementSaveQueue = useRef<Promise<void>>(Promise.resolve());
  const onSavePlacement = useCallback(
    (beatId: string, patch: {
      lines?: PlacementLine[];
      meta?: Record<string, unknown>;
      assets?: Record<string, unknown>;
      motion?: Record<string, unknown>;
      endFrameExclusive?: number;
      locked?: boolean;
      detail?: string;
    }) => {
      const quiet = Boolean(patch.detail?.includes("(auto)") || patch.detail?.includes("leave"));
      const updatePreview = patch.detail !== "unlock" && patch.detail !== "lock-only";
      const run = async () => {
        setBusy(true);
        try {
          const data = await savePlacementBeat({ beatId, ...patch });
          await refresh();
          if (!quiet) {
            if (patch.locked === true) {
              setMessage(`Locked ${beatId}.`);
            } else if (patch.locked === false) {
              setMessage(`Unlocked ${beatId}.`);
            } else {
              setMessage(`Saved placement on ${beatId} · updating preview…`);
            }
            if (data.finalRenderReady) {
              setMessage((m) => `${m} All beats locked — Final is ready.`);
            }
          }
          // One forced rebuild after an explicit craft commit (or lock with lines).
          // No longer rebuilds on every keystroke / autosave race.
          if (updatePreview) {
            await refreshPlacementPreview(beatId, {
              lines: patch.lines,
              meta: patch.meta,
              assets: patch.assets,
              motion: patch.motion,
              endFrameExclusive: patch.endFrameExclusive,
              force: true,
            });
          }
        } catch (error) {
          setMessage(error instanceof Error ? error.message : "Could not save placement.");
        } finally {
          setBusy(false);
        }
      };
      const next = placementSaveQueue.current.then(run, run);
      placementSaveQueue.current = next;
      return next;
    },
    [refresh, refreshPlacementPreview],
  );

  const rail = (
    <nav className="workflow-rail" aria-label="Visual Package workflow">
      <PackageWorkflowStage stage={1} activeStage={activeStage} setActiveStage={setActiveStage}>
        <span className="workflow-stage-label">Masterbeater</span>
        <button
          className="workflow-action"
          type="button"
          onClick={() => void refresh()}
          disabled={busy || !hasVideoProject}
        >
          <RefreshCw size={15} /> Refresh
        </button>
        <button
          className="workflow-action emphasized"
          type="button"
          onClick={() => void onRun()}
          disabled={busy || !hasVideoProject || !status?.transcriptExists}
          title="Run Masterbeater on the locked final transcript"
        >
          {busy ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
          {busy ? "Running…" : "Masterbeater"}
        </button>
        <span className="workflow-status">
          {!hasVideoProject
            ? "Open a private project"
            : status?.outputExists || status?.reviewedExists
              ? `${status.beatCount || 0} beats · review below`
              : "Manual beats or Masterbeater · then Refresh"}
        </span>
      </PackageWorkflowStage>
      <PackageWorkflowStage stage={2} activeStage={activeStage} setActiveStage={setActiveStage}>
        <span className="workflow-stage-label">Assignment</span>
        <button
          className="workflow-action"
          type="button"
          onClick={() => void refresh()}
          disabled={busy || !hasVideoProject}
        >
          <RefreshCw size={15} /> Refresh
        </button>
        <button
          className="workflow-action emphasized"
          type="button"
          onClick={() => void onScenelayer()}
          disabled={
            busy ||
            !hasVideoProject ||
            !(status?.outputExists || status?.reviewedExists) ||
            !status?.reviewVideoExists
          }
          title={
            scenelayer?.originalExists
              ? "Re-label algorithm layouts; keep manual layout overrides"
              : "Label OBS layout from first frame of each beat"
          }
        >
          {busy && stage2 ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
          {busy && stage2 ? "…" : "Scenelayer"}
        </button>
        <button
          className="workflow-action emphasized"
          type="button"
          onClick={() => void onAssign()}
          disabled={
            busy ||
            !hasVideoProject ||
            !(status?.outputExists || status?.reviewedExists)
          }
          title={
            assignment?.originalExists
              ? "Re-deal algorithm picks; keep manual overrides"
              : "Deal golden graphics (type + layout filter)"
          }
        >
          {busy && stage2 ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
          Assign
        </button>
        <span className="workflow-status">
          {!hasVideoProject
            ? "Open a private project"
            : scenelayer?.originalExists
              ? `${scenelayer.labeledCount ?? 0} layouts · ${assignment?.assignedCount ?? 0} graphics`
              : "Scenelayer → Assign"}
        </span>
      </PackageWorkflowStage>
      <PackageWorkflowStage stage={3} activeStage={activeStage} setActiveStage={setActiveStage}>
        <span className="workflow-stage-label">Placement</span>
        <button
          className="workflow-action"
          type="button"
          onClick={() => void refresh()}
          disabled={busy || !hasVideoProject}
        >
          <RefreshCw size={15} /> Refresh
        </button>
        <button
          className="workflow-action emphasized"
          type="button"
          onClick={() => void onPlace()}
          disabled={
            busy ||
            !hasVideoProject ||
            !(assignment?.originalExists || (assignment?.assignedCount ?? 0) > 0)
          }
          title="Draft lines + reveal frames for assigned beats (skips locked)"
        >
          {busy && stage3 ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
          Place
        </button>
        <button
          className="workflow-action emphasized"
          type="button"
          disabled={busy || finalRunning || !placement?.finalRenderReady}
          title={
            finalRunning
              ? `Final render in progress · ${Math.round(placementFinalJob?.value ?? 0)}%`
              : placement?.finalRenderReady
                ? "Full episode render: all locked graphics on the locked cut (audio stream-copied)"
                : "Lock every assigned beat before final render"
          }
          onClick={() => void onFinal()}
        >
          {finalRunning ? (
            <>
              <Loader2 size={15} className="spin" /> Final {Math.round(placementFinalJob?.value ?? 0)}%
            </>
          ) : (
            "Final"
          )}
        </button>
        <span className="workflow-status">
          {!hasVideoProject
            ? "Open a private project"
            : finalRunning
              ? `Final ${Math.round(placementFinalJob?.value ?? 0)}%`
              : placementFinalJob?.status === "complete"
                ? "Final ready"
                : placement?.originalExists
                  ? `${placement.lockedCount ?? 0}/${placement.placementCount ?? 0} locked`
                  : "Place → edit lines → lock"}
        </span>
      </PackageWorkflowStage>
    </nav>
  );

  if (!hasVideoProject) {
    return (
      <div className="visual-package-workspace">
        {railHost ? createPortal(rail, railHost) : null}
        <div className="visual-package-empty-state">
          <h3>Open a private video project</h3>
          <p>Visual Package needs a locked cut and transcript in the active project.</p>
        </div>
      </div>
    );
  }

  // Drafts count: manual Stage 1 works before any server result exists.
  const hasBeats = beats.length > 0 || Boolean(result?.beatCount);
  const hasTranscript = transcriptWords.length > 0;

  /** Stage 3 header: jump to any placed beat (row under title + lock). */
  const stage3BeatJump =
    stage3 && reviewBeats.length > 0 ? (
      <label className="visual-package-beat-jump is-header">
        <span className="visual-package-beat-jump-label">Jump</span>
        <select
          className="visual-package-beat-jump-select"
          value={
            selectedId && reviewBeats.some((b) => b.id === selectedId) ? selectedId : ""
          }
          onChange={(event) => {
            const next = reviewBeats.find((b) => b.id === event.target.value);
            if (next) selectBeat(next, false);
          }}
          aria-label="Jump to beat"
          title="Jump to a specific beat"
        >
          {!selectedId || !reviewBeats.some((b) => b.id === selectedId) ? (
            <option value="" disabled>
              Pick a beat…
            </option>
          ) : null}
          {reviewBeats.map((beat, index) => {
            const pb = placementByBeat[beat.id];
            const ap = assignmentByBeat[beat.id];
            const engine =
              pb?.displayName ||
              pb?.engineId ||
              ap?.displayName ||
              ap?.engineId ||
              "";
            const typeLabel = beat.beatType
              ? beat.beatType.charAt(0).toUpperCase() + beat.beatType.slice(1)
              : "Beat";
            const words = String(beat.wordsText || "")
              .replace(/\s+/g, " ")
              .trim();
            const snippet =
              words.length > 28 ? `${words.slice(0, 28).trimEnd()}…` : words;
            const parts = [
              `${index + 1}/${reviewBeats.length}`,
              typeLabel,
              engine || null,
              snippet ? `“${snippet}”` : null,
            ].filter(Boolean);
            return (
              <option key={beat.id} value={beat.id}>
                {parts.join(" · ")}
              </option>
            );
          })}
        </select>
      </label>
    ) : null;

  /** Shared transport buttons — right panel in Stage 1/2, craft panel in Stage 3. */
  const playerTransportControls = (
    <div className="visual-package-player-controls">
      <button
        type="button"
        className="workflow-action"
        onClick={() => stepBeat(-1)}
        disabled={!reviewBeats.length || reviewIndex <= 0}
      >
        ← Prev
      </button>
      <button
        type="button"
        className="workflow-action emphasized"
        onClick={togglePlay}
        disabled={
          !selected ||
          !(status?.reviewVideoExists || stage3LivePreview) ||
          (stage3LivePreview && !previewAudioReady)
        }
        title={
          stage3LivePreview && !previewAudioReady
            ? "Buffering this beat's media — Play arms in a moment"
            : undefined
        }
      >
        {stage3LivePreview && !previewAudioReady ? (
          <>
            <Loader2 size={16} className="spin" /> Buffering…
          </>
        ) : (
          <>
            {playing ? <Pause size={16} /> : <Play size={16} />}
            {playing ? "Pause" : "Play"}
          </>
        )}
      </button>
      {/* Stage 3 is one-shot (auto-rewinds at end; Play restarts) — Reset is Stage 1/2 only. */}
      {stage3 ? null : (
        <button
          type="button"
          className="workflow-action"
          onClick={() => {
            if (!selected) return;
            seekToBeat(selected, false);
          }}
          disabled={!selected}
          title="Reset to beat start"
        >
          <SkipBack size={16} /> Reset
        </button>
      )}
      <button
        type="button"
        className="workflow-action"
        onClick={() => stepBeat(1)}
        disabled={
          !reviewBeats.length ||
          reviewIndex < 0 ||
          reviewIndex >= reviewBeats.length - 1
        }
      >
        Next →
      </button>
      {/* Stage 3: Lock rides the transport row, far right. */}
      {stage3 && selected && placementByBeat[selected.id] ? (
        placementByBeat[selected.id].locked ? (
          <button
            type="button"
            className="workflow-action visual-package-transport-lock"
            disabled={busy}
            onClick={() => void onSavePlacement(selected.id, { locked: false, detail: "unlock" })}
          >
            Unlock
          </button>
        ) : (
          <button
            type="button"
            className="workflow-action visual-package-placement-lock visual-package-transport-lock"
            disabled={busy}
            onClick={() => {
              const row = placementByBeat[selected.id];
              // Flush any unsaved craft with the lock so stack edits aren't dropped.
              void onSavePlacement(selected.id, {
                lines: draftPlacementLines ?? row.lines ?? [],
                meta: (row.meta || {}) as Record<string, unknown>,
                assets: (row.assets || {}) as Record<string, unknown>,
                motion: (draftPlacementMotion || row.motion || {}) as Record<string, unknown>,
                endFrameExclusive:
                  draftPlacementEndFrame ?? row.endFrameExclusive,
                locked: true,
                detail: "lock",
              });
            }}
          >
            Lock
          </button>
        )
      ) : null}
      {/* Stage 3 is one-shot playback — Loop/Autoplay pills are Stage 1/2 only. */}
      {stage3 ? null : (
        <>
          <button
            type="button"
            className={["visual-package-toggle", loopBeat ? "is-on" : ""].join(" ")}
            role="switch"
            aria-checked={loopBeat}
            onClick={() => setLoopBeat((value) => !value)}
            title="Loop the selected beat"
          >
            <span className="visual-package-toggle-track" aria-hidden>
              <span className="visual-package-toggle-thumb" />
            </span>
            Loop
          </button>
          <button
            type="button"
            className={["visual-package-toggle", autoplayOnSelect ? "is-on" : ""].join(" ")}
            role="switch"
            aria-checked={autoplayOnSelect}
            title="Play the beat span when you click a card"
            onClick={() => setAutoplayOnSelect((value) => !value)}
          >
            <span className="visual-package-toggle-track" aria-hidden>
              <span className="visual-package-toggle-thumb" />
            </span>
            Autoplay
          </button>
        </>
      )}
    </div>
  );

  /** Stage 3: full transport cluster (progress rail + readout + buttons) rendered
   *  inside the craft panel, directly under the reveal-timing nudges (mockup). */
  const stage3TransportCluster =
    stage3 && selected ? (
      <div className="visual-package-placement-transport-cluster">
        {beatProgress ? (
          <PlacementBeatProgress
            startFrame={beatProgress.startFrame}
            endFrameExclusive={beatProgress.endFrameExclusive}
            playheadFrame={playheadFrame}
            revealTicks={beatProgress.revealTicks}
            graphicEndFrame={beatProgress.graphicEndFrame}
            motionFrames={beatProgress.motionFrames}
          />
        ) : null}
        <div className="visual-package-placement-transport-readout" aria-live="polite">
          <span className="visual-package-placement-clock">
            {formatClock(playheadFrame / Math.max(fps, 1))}
          </span>
          <span className="muted">f {playheadFrame}</span>
          {stage3LivePreview && placementPreview ? (
            <>
              <span className="muted">·</span>
              <span className="visual-package-placement-local-time">
                {formatClock(
                  Math.max(
                    0,
                    playheadFrame / Math.max(fps, 1) - compositionRangeStartSec,
                  ),
                )}
                {" / "}
                {formatClock(compositionDurationSec)}
              </span>
              <span className="muted">clip</span>
            </>
          ) : null}
          {placementPreview?.startFrame != null &&
          placementPreview?.endFrameExclusive != null ? (
            <span className="muted">
              · beat f {placementPreview.startFrame}–{placementPreview.endFrameExclusive}
            </span>
          ) : null}
        </div>
        {playerTransportControls}
      </div>
    ) : null;

  return (
    <div className="visual-package-workspace">
      {railHost ? createPortal(rail, railHost) : null}
      {!railHost ? <div className="visual-package-rail-fallback">{rail}</div> : null}

      {activeStage > 3 ? (
        <section className="visual-package-stage-body">
          <div className="visual-package-empty-state">
            <h3>Stage {activeStage} not built yet</h3>
            <p>Later stage after placement.</p>
          </div>
        </section>
      ) : !hasBeats && !hasTranscript ? (
        <section className="visual-package-stage-body">
          <div className="visual-package-empty-state">
            <h3>No Masterbeater output yet</h3>
            <p>
              Produce <code>masterbeater-beats.json</code> in the project root with Grok, then hit{" "}
              <strong>Refresh</strong>.
            </p>
          </div>
        </section>
      ) : (
        <section
          className={[
            "visual-package-review",
            stage2 ? "is-stage-2" : "",
            stage3 ? "is-stage-3" : "",
          ].join(" ")}
        >
          {/* Stage 3 (images/6): craft LEFT (primary) · live preview RIGHT */}
          {stage3 ? (
            <PlacementEditorPanel
              selected={selected}
              placement={selected ? placementByBeat[selected.id] : undefined}
              assignment={selected ? assignmentByBeat[selected.id] : undefined}
              interfaceSpec={
                selected && placementByBeat[selected.id]?.engineId
                  ? placement?.engineInterfaces?.[placementByBeat[selected.id].engineId!]
                  : undefined
              }
              beatWords={
                selected
                  ? wordsInBeatRange(transcriptWords, selected, wordIndexById)
                  : []
              }
              fps={fps}
              busy={busy}
              previewBusy={placementPreviewBusy}
              hasPlacements={Boolean(placement?.originalExists)}
              allLocked={Boolean(placement?.finalRenderReady)}
              beatIndex={reviewIndex}
              beatTotal={reviewBeats.length}
              livePreviewReady={Boolean(placementPreview?.available)}
              onSave={(patch) => {
                if (!selected) return;
                void onSavePlacement(selected.id, patch);
              }}
              onSeekReveal={(frame) => seekAbsoluteFrame(frame, false)}
              onDraftPreview={(lines, extras) => {
                if (!selected) return;
                void refreshPlacementPreview(selected.id, {
                  lines,
                  meta: extras?.meta,
                  assets: extras?.assets,
                  motion: extras?.motion,
                  endFrameExclusive: extras?.endFrameExclusive,
                });
              }}
              onLinesChange={setDraftPlacementLines}
              onEndFrameChange={setDraftPlacementEndFrame}
              onMotionChange={setDraftPlacementMotion}
              transportSlot={stage3TransportCluster}
              beatJumpSlot={stage3BeatJump}
              speechHostEl={placementSpeechHostEl}
            />
          ) : null}

          <div className="visual-package-player-panel">
            <div
              className={[
                "visual-package-player-frame",
                stage3 ? "is-placement-live" : "",
              ].join(" ")}
            >
              {stage3 && stage3LivePreview && placementPreview?.cacheKey ? (
                createElement("hyperframes-player", {
                  key: placementPreview.cacheKey,
                  ref: (element: HyperFramesPlayerElement | null) => {
                    runtimePlayerRef.current = element;
                    if (element) {
                      try {
                        element.loop = false;
                      } catch {
                        /* ignore */
                      }
                      // Pin the WebAudio-clock disable at the message channel. The player's
                      // own _replayBridgeState re-sends disabled:false AFTER dispatching
                      // "ready" (and again on runtime-ready), clobbering any one-shot
                      // disable we send from event handlers — that race was the freeze
                      // flakiness. Wrapping _sendControl rewrites every replay in flight,
                      // so the fragile AudioContext clock can never re-arm.
                      try {
                        if (element._sendControl && !element.__vcgAudioClockPinned) {
                          const original = element._sendControl.bind(element);
                          element._sendControl = (action, payload) =>
                            action === "set-web-audio-media-disabled"
                              ? original(action, { disabled: true })
                              : original(action, payload);
                          element.__vcgAudioClockPinned = true;
                        }
                      } catch {
                        /* ignore */
                      }
                    }
                  },
                  className: "visual-package-video visual-package-hyperframes-player",
                  src: placementPreviewCompositionUrl(placementPreview.cacheKey),
                  controls: false,
                  width: placementPreview.width || 1920,
                  height: placementPreview.height || 1080,
                })
              ) : status?.reviewVideoExists && videoUrl ? (
                <video
                  ref={videoRef}
                  className="visual-package-video"
                  src={videoUrl}
                  controls={false}
                  playsInline
                  preload="metadata"
                  onTimeUpdate={onTimeUpdate}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onLoadedMetadata={() => {
                    if (selected) seekToBeat(selected, false);
                  }}
                />
              ) : (
                <div className="visual-package-video-missing">
                  No review video (locked cut / source). Export a locked cut if needed.
                </div>
              )}
              {stage3 && placementPreview?.cacheKey ? (
                // Speech audio for the live preview — the composition itself is
                // audio-free so the HyperFrames clock can never pin on it.
                <audio
                  ref={previewAudioRef}
                  key={`preview-audio:${placementPreview.cacheKey}`}
                  src={placementPreviewSourceUrl(placementPreview.cacheKey)}
                  preload="auto"
                  style={{ display: "none" }}
                  onLoadStart={() => setPreviewAudioReady(false)}
                  onCanPlayThrough={() => setPreviewAudioReady(true)}
                  // Broken audio must never block the visual preview — play silent.
                  onError={() => setPreviewAudioReady(true)}
                />
              ) : null}
              {stage3 && placementPreviewBusy ? (
                <div className="visual-package-preview-busy" aria-live="polite">
                  <Loader2 size={16} className="spin" /> Building live graphic…
                </div>
              ) : null}
              {stage3 &&
              !placementPreviewBusy &&
              !stage3LivePreview &&
              (placementPreviewError || selectedPlacement) ? (
                <div
                  className={[
                    "visual-package-preview-busy",
                    placementPreviewError ? "is-error" : "",
                  ].join(" ")}
                  aria-live="polite"
                >
                  {placementPreviewError
                    ? placementPreviewError
                    : !runtimeScriptReady
                      ? "Loading HyperFrames player…"
                      : "Preparing live graphic…"}
                </div>
              ) : null}
              {stage3 && placementPreview?.available && !placementPreviewBusy ? (
                <div
                  className="visual-package-preview-badge"
                  title="Live HyperFrames composition (Tier B)"
                >
                  Live preview · HyperFrames · no encode
                  {runtimeReady ? "" : " · loading"}
                </div>
              ) : null}
              {stage3 ? (
                <>
                  <button
                    type="button"
                    className={[
                      "visual-package-placement-grid-toggle",
                      placementGridOn ? "is-on" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    aria-pressed={placementGridOn}
                    title="Show a 10×10 tenths grid over the preview (craft aid only)"
                    onClick={() => setPlacementGridOn((on) => !on)}
                  >
                    Grid
                  </button>
                  {placementGridOn ? (
                    <div
                      className="visual-package-placement-grid"
                      aria-hidden
                    >
                      {Array.from({ length: 9 }, (_, i) => {
                        const pct = (i + 1) * 10;
                        return (
                          <Fragment key={pct}>
                            <div
                              className="visual-package-placement-grid-line is-v"
                              style={{ left: `${pct}%` }}
                            />
                            <div
                              className="visual-package-placement-grid-line is-h"
                              style={{ top: `${pct}%` }}
                            />
                            <span
                              className="visual-package-placement-grid-label is-x"
                              style={{ left: `${pct}%` }}
                            >
                              0.{i + 1}
                            </span>
                            <span
                              className="visual-package-placement-grid-label is-y"
                              style={{ top: `${pct}%` }}
                            >
                              0.{i + 1}
                            </span>
                          </Fragment>
                        );
                      })}
                    </div>
                  ) : null}
                </>
              ) : null}
            </div>

            {/* Stage 3: graphic identity (poster + name + layout/status) under the player. */}
            {stage3 && selected ? (() => {
              const pb = placementByBeat[selected.id];
              const ap = assignmentByBeat[selected.id];
              const graphicPoster = assignmentPosterUrl(ap?.posterUrl || null);
              const graphicName =
                pb?.displayName || pb?.engineId || ap?.displayName || ap?.engineId || "—";
              const graphicLayout = ap?.layoutId || null;
              return (
                <div className="visual-package-placement-graphic-card">
                  <div className="visual-package-assignment-poster-wrap compact">
                    {graphicPoster ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        className="visual-package-assignment-poster"
                        src={graphicPoster}
                        alt={graphicName}
                      />
                    ) : (
                      <div className="visual-package-assignment-poster-empty" aria-hidden>
                        —
                      </div>
                    )}
                  </div>
                  <div className="visual-package-placement-graphic-meta">
                    <span className="visual-package-assignment-name">{graphicName}</span>
                    {graphicLayout ? (
                      <span className="visual-package-placement-layout-pill">
                        {graphicLayout.replace(/-/g, " ")}
                      </span>
                    ) : null}
                    {pb?.locked ? (
                      <span className="visual-package-assignment-source">Locked</span>
                    ) : pb ? (
                      <span className="visual-package-assignment-source muted">
                        {placementPreview?.available ? "Editing · live" : "Editing"}
                      </span>
                    ) : null}
                  </div>
                </div>
              );
            })() : null}

            {/* Stage 3: spoken-word chips portal target — under graphic card, right column. */}
            {stage3 ? (
              <div
                ref={setPlacementSpeechHostEl}
                className="visual-package-placement-speech-host"
              />
            ) : null}

            {/* Stage 3 moves the whole transport cluster into the craft panel. */}
            {stage3 ? null : playerTransportControls}

            {stage2 ? (
              <div className="visual-package-layout-review" aria-label="Layout review">
                <div className="visual-package-layout-review-top">
                  <span className="visual-package-layout-review-label">Layout review</span>
                  <span className="visual-package-layout-review-index">
                    {reviewBeats.length
                      ? `${Math.max(1, reviewIndex + 1)} / ${reviewBeats.length}`
                      : "0 / 0"}
                  </span>
                </div>
                <div className="visual-package-layout-review-nav">
                  <button
                    type="button"
                    className="workflow-action"
                    onClick={() => stepBeat(-1)}
                    disabled={!reviewBeats.length || reviewIndex <= 0}
                  >
                    <ChevronUp size={16} /> Prev
                  </button>
                  <button
                    type="button"
                    className="workflow-action emphasized"
                    onClick={() => stepBeat(1)}
                    disabled={
                      !reviewBeats.length ||
                      reviewIndex < 0 ||
                      reviewIndex >= reviewBeats.length - 1
                    }
                  >
                    Next <ChevronDown size={16} />
                  </button>
                  <button
                    type="button"
                    className="workflow-action"
                    onClick={togglePlay}
                    disabled={!selected || !status?.reviewVideoExists}
                  >
                    {playing ? <Pause size={16} /> : <Play size={16} />}
                    {playing ? "Pause" : "Play"}
                  </button>
                </div>
                {/* Locked under nav — never moves when beat text length changes. */}
                <div className="visual-package-layout-review-field is-pinned">
                  <span>OBS layout</span>
                  <div
                    className="usage-layout-pills visual-package-layout-choice"
                    role="radiogroup"
                    aria-label="OBS layout for this beat"
                  >
                    {layoutIds.map((id) => {
                      const isSelected =
                        Boolean(selected) &&
                        scenelayerByBeat[selected!.id]?.layoutId === id;
                      return (
                        <button
                          key={id}
                          type="button"
                          role="radio"
                          aria-checked={isSelected}
                          className={["usage-layout-pill", isSelected ? "is-selected" : ""].join(" ")}
                          disabled={!selected || busy || !scenelayer?.originalExists}
                          title={id}
                          onClick={() => {
                            if (!selected || isSelected) return;
                            void onLayoutSwap(selected.id, id, true);
                          }}
                        >
                          {id}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="visual-package-layout-review-body">
                  {selected ? (
                    <>
                      <div className="visual-package-layout-review-meta">
                        <span className={`beat-type-badge type-${selected.beatType}`}>
                          {selected.beatType}
                        </span>
                        <span className="beat-id">{selected.id}</span>
                        {scenelayerByBeat[selected.id]?.source === "human" ? (
                          <span className="visual-package-assignment-source">Manual</span>
                        ) : scenelayerByBeat[selected.id]?.layoutId ? (
                          <span className="visual-package-assignment-source muted">Auto</span>
                        ) : (
                          <span className="visual-package-assignment-source muted">Unset</span>
                        )}
                      </div>
                      <div className="visual-package-layout-review-words">
                        {selected.wordsText || selected.span || selected.label || "—"}
                      </div>
                      <p className="visual-package-layout-review-algo">
                        Algorithm said:{" "}
                        <strong>
                          {scenelayer?.originalByBeatId?.[selected.id]?.layoutId || "—"}
                        </strong>
                        {scenelayerByBeat[selected.id]?.source === "human" &&
                        scenelayerByBeat[selected.id]?.layoutId
                          ? ` · you set ${scenelayerByBeat[selected.id]?.layoutId}`
                          : null}
                        {scenelayerLedgerCount > 0
                          ? ` · ${scenelayerLedgerCount} correction${scenelayerLedgerCount === 1 ? "" : "s"} logged`
                          : null}
                      </p>
                      <p className="visual-package-layout-review-hint">
                        ← → or J / K steps beats (seeks to first frame). Play only if Autoplay on
                        select is on. Change the layout when wrong — fixes save to the ledger.
                      </p>
                    </>
                  ) : (
                    <p className="visual-package-layout-review-hint">
                      {scenelayer?.originalExists
                        ? "Select a beat or press Next to start layout QA."
                        : "Press Scenelayer in the rail first, then step through beats here."}
                    </p>
                  )}
                </div>
              </div>
            ) : null}

            {!stage2 && !stage3 ? (
            <div className="visual-package-edit-strip" aria-label="Beat structure and word membership">
              <div className="visual-package-edit-strip-label">Beat structure</div>
              <p className="visual-package-edit-strip-hint">
                Select a beat card to change type, delete, merge, or split. Select yellow transcript
                words to create a new beat. Word ↑/↓ still moves membership only. All actions
                auto-save the working copy; original Masterbeater stays intact.
              </p>

              {selected ? (
                <div className="visual-package-structure-panel">
                  <div className="visual-package-edit-strip-selected">
                    <span className={`beat-type-badge type-${selected.beatType}`}>{selected.beatType}</span>
                    <span className="beat-id">{selected.id}</span>
                    <span className="muted">
                      {selected.startWordId && selected.endWordId
                        ? `${selected.startWordId} → ${selected.endWordId}`
                        : "No word anchors"}
                    </span>
                  </div>
                  <div className="visual-package-structure-row">
                    <label className="visual-package-structure-field">
                      Type
                      <select
                        value={selected.beatType}
                        onChange={(event) => onChangeSelectedType(event.target.value)}
                        disabled={autoSaveState === "saving"}
                      >
                        {BEAT_TYPE_ORDER.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                        {!BEAT_TYPE_ORDER.includes(selected.beatType as (typeof BEAT_TYPE_ORDER)[number]) ? (
                          <option value={selected.beatType}>{selected.beatType}</option>
                        ) : null}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="workflow-action"
                      onClick={onDeleteSelectedBeat}
                      disabled={autoSaveState === "saving" || beats.length <= 1}
                      title={beats.length <= 1 ? "Cannot delete the last beat" : "Remove this beat (words become transcript)"}
                    >
                      Delete beat
                    </button>
                    <button
                      type="button"
                      className="workflow-action"
                      onClick={() => onMergeSelected("prev")}
                      disabled={autoSaveState === "saving" || !adjacentForSelected.prev}
                      title={
                        adjacentForSelected.prev
                          ? `Merge with previous (${adjacentForSelected.prev.beatType})`
                          : "No previous beat"
                      }
                    >
                      Merge ←
                    </button>
                    <button
                      type="button"
                      className="workflow-action"
                      onClick={() => onMergeSelected("next")}
                      disabled={autoSaveState === "saving" || !adjacentForSelected.next}
                      title={
                        adjacentForSelected.next
                          ? `Merge with next (${adjacentForSelected.next.beatType})`
                          : "No next beat"
                      }
                    >
                      Merge →
                    </button>
                    <button
                      type="button"
                      className="workflow-action"
                      onClick={onSplitAfterSelection}
                      disabled={autoSaveState === "saving" || !canSplitAfterSelection}
                      title="Select words inside the beat; split keeps them on the left card and creates a new card after"
                    >
                      Split after selection
                    </button>
                  </div>
                </div>
              ) : (
                <p className="visual-package-edit-strip-hint">Select a beat card to edit structure.</p>
              )}

              <div className="visual-package-structure-panel secondary">
                <div className="visual-package-edit-strip-label">New beat from transcript</div>
                <div className="visual-package-structure-row">
                  <label className="visual-package-structure-field">
                    Type
                    <select
                      value={newBeatType}
                      onChange={(event) => setNewBeatType(event.target.value)}
                      disabled={autoSaveState === "saving"}
                    >
                      {BEAT_TYPE_ORDER.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="workflow-action emphasized"
                    onClick={onAddBeatFromSelection}
                    disabled={autoSaveState === "saving" || !canAddBeatFromSelection}
                    title="Select yellow transcript words first"
                  >
                    New beat from selection
                  </button>
                </div>
              </div>

              {membershipSel ? (
                <div className="visual-package-selection-status">
                  <span>
                    Selected {membershipSel.endIndex - membershipSel.startIndex + 1} word
                    {membershipSel.endIndex === membershipSel.startIndex ? "" : "s"}
                    {membershipSel.zone === "gap" ? " (transcript)" : " (in beat)"}:{" "}
                    <strong>
                      {selectionWordText(
                        transcriptWords,
                        membershipSel.startIndex,
                        membershipSel.endIndex,
                      ) || "—"}
                    </strong>
                    {membershipSel.zone === "gap"
                      ? " · New beat, or ↑/↓ into a neighbor"
                      : canSplitAfterSelection
                        ? " · Split after selection, or ↑/↓ to transcript"
                        : selectionArrowActions?.onUp || selectionArrowActions?.onDown
                          ? " · use ↑/↓ beside the selection"
                          : ""}
                  </span>
                  <button
                    type="button"
                    className="workflow-action"
                    onClick={() => {
                      setMembershipSel(null);
                      dragAnchorRef.current = null;
                    }}
                  >
                    Clear
                  </button>
                </div>
              ) : null}

              <div className="visual-package-edit-strip-actions">
                <span
                  className={[
                    "pill",
                    autoSaveState === "error"
                      ? "warn"
                      : autoSaveState === "saved" || hasReviewed
                        ? "ok"
                        : "muted",
                  ].join(" ")}
                >
                  {autoSaveState === "saving"
                    ? "Auto-saving…"
                    : autoSaveState === "error"
                      ? "Auto-save failed"
                      : hasReviewed
                        ? "Working copy auto-saved"
                        : "Edits auto-save"}
                </span>
                <span className="pill muted" title="Append-only log of membership edits vs original">
                  Ledger · {ledgerEntryCount} edit{ledgerEntryCount === 1 ? "" : "s"}
                </span>
                <span className="pill muted" title="Original Masterbeater agent output is never overwritten">
                  Original kept
                </span>
              </div>
            </div>
            ) : null}
          </div>

          {!stage3 ? (
          <div className="visual-package-stream-panel">
            <div className="visual-package-stream-toolbar">
              <div className="visual-package-summary compact">
                <div>
                  <strong>{result?.beatCount ?? beats.length}</strong>
                  <span>beats</span>
                </div>
                <div>
                  <strong>{transcriptWords.length || "—"}</strong>
                  <span>words</span>
                </div>
                <div>
                  <strong>{result?.mode || "—"}</strong>
                  <span>mode</span>
                </div>
                {stage2 ? (
                  <div>
                    <strong>{assignment?.assignedCount ?? "—"}</strong>
                    <span>graphics</span>
                  </div>
                ) : null}
                <div className="visual-package-filters">
                  <label>
                    Beat type
                    <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                      <option value="all">All types</option>
                      {BEAT_TYPE_ORDER.filter((type) => typeCounts.has(type)).map((type) => (
                        <option key={type} value={type}>
                          {type} ({typeCounts.get(type)})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Layout
                    <select
                      value={layoutFilter}
                      onChange={(event) => setLayoutFilter(event.target.value)}
                    >
                      <option value="all">All layouts</option>
                      {layoutIds
                        .filter((id) => layoutCounts.has(id))
                        .map((id) => (
                          <option key={id} value={id}>
                            {id} ({layoutCounts.get(id)})
                          </option>
                        ))}
                      {layoutCounts.has("__unset__") ? (
                        <option value="__unset__">
                          Unset ({layoutCounts.get("__unset__")})
                        </option>
                      ) : null}
                      {/* Show catalog layouts even if count 0 when scenelayer ran */}
                      {scenelayer?.originalExists
                        ? layoutIds
                            .filter((id) => !layoutCounts.has(id))
                            .map((id) => (
                              <option key={`empty-${id}`} value={id}>
                                {id} (0)
                              </option>
                            ))
                        : null}
                    </select>
                  </label>
                </div>
              </div>
              {(result?.gaps || []).length > 0 ? (
                <details className="visual-package-gaps">
                  <summary>Agent gap notes ({result?.gaps?.length})</summary>
                  <ul>
                    {(result?.gaps || []).map((gap, index) => (
                      <li key={`gap-note-${index}`}>{gap}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>

            <div
              className="visual-package-stream"
              ref={streamRef}
              role="list"
              aria-label="Transcript with inline beat cards"
            >
              {!hasBeats && hasTranscript ? (
                <p className="visual-package-empty">
                  Select transcript words in the yellow gaps, choose a beat type, then{" "}
                  <strong>New beat</strong>. Masterbeater is optional — auto-save writes the project
                  working copy as you place beats.
                </p>
              ) : null}
              {!hasBeats && !hasTranscript ? (
                <p className="visual-package-empty">
                  No transcript words loaded. Finish the locked cut / final transcript first, then Refresh.
                </p>
              ) : null}

              {stream.map((item) => {
                if (item.kind === "gap") {
                  if (!item.words.length) return null;
                  const gapStart = wordIndexById.get(item.words[0].id);
                  const gapEnd = wordIndexById.get(item.words[item.words.length - 1].id);
                  const selInThisGap =
                    membershipSel?.zone === "gap" &&
                    gapStart != null &&
                    gapEnd != null &&
                    membershipSel.startIndex >= gapStart &&
                    membershipSel.endIndex <= gapEnd;
                  const arrows =
                    selInThisGap && selectionArrowActions?.zone === "gap"
                      ? selectionArrowActions
                      : null;

                  return (
                    <div key={item.key} className="visual-package-gap-words" role="listitem">
                      <div className="visual-package-word-row" aria-label="Unbeaten transcript words">
                        {groupWordsBySentence(item.words).map((sentence) => (
                          <div
                            key={sentence.key}
                            className="visual-package-sentence"
                            data-sentence={sentence.key}
                          >
                            {sentence.words.map((word) => {
                              const index = wordIndexById.get(word.id) ?? -1;
                              const isSelected = selectionCoversIndex(membershipSel, index);
                              const isEdge =
                                Boolean(arrows) &&
                                membershipSel != null &&
                                index === membershipSel.endIndex;
                              const trailing =
                                isEdge && arrows ? (
                                  <MembershipArrows
                                    upTitle={arrows.upTitle}
                                    downTitle={arrows.downTitle}
                                    onUp={arrows.onUp}
                                    onDown={arrows.onDown}
                                  />
                                ) : null;
                              return (
                                <WordChip
                                  key={word.id}
                                  word={word}
                                  variant="gap"
                                  selected={isSelected}
                                  selectionEdge={Boolean(trailing)}
                                  title="Click to select/unselect · drag or Shift-click a phrase · then ↑/↓"
                                  trailing={trailing}
                                  onPointerDownWord={(event) =>
                                    onWordPointerDown("gap", undefined, index, event)
                                  }
                                  onPointerEnterWord={(event) =>
                                    onWordPointerEnter("gap", undefined, index, event)
                                  }
                                  onClickWord={(event) =>
                                    onWordSelectClick("gap", undefined, word.id, event)
                                  }
                                />
                              );
                            })}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                }

                if (item.kind === "orphan") {
                  const active = item.beat.id === selectedId;
                  const orphanPick = assignmentByBeat[item.beat.id];
                  const orphanLayout = scenelayerByBeat[item.beat.id];
                  const orphanEligible = eligibleForBeat(item.beat);
                  return (
                    <div
                      key={item.key}
                      role="listitem"
                      data-beat-id={item.beat.id}
                      className={[
                        "visual-package-inline-beat",
                        "is-orphan",
                        active ? "is-selected" : "",
                        stage2 ? "has-assignment" : "",
                      ].join(" ")}
                      tabIndex={0}
                      onClick={() => selectBeat(item.beat)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          selectBeat(item.beat);
                        }
                      }}
                    >
                      <BeatCardHeader beat={item.beat} fps={fps} />
                      <div className="visual-package-inline-beat-body">
                        <div className="visual-package-inline-beat-main">
                          <div className="visual-package-inline-beat-words">
                            {item.beat.wordsText || item.beat.span || item.beat.label || "—"}
                          </div>
                          <div className="visual-package-inline-beat-note">
                            Word anchors missing from transcript — card not placed inline.
                          </div>
                        </div>
                        {stage2 ? (
                          <Stage2SidePanel
                            beat={item.beat}
                            layoutPick={orphanLayout}
                            layoutIds={layoutIds}
                            layoutDisabled={busy || !scenelayer?.originalExists}
                            onLayout={(layoutId) => void onLayoutSwap(item.beat.id, layoutId)}
                            assignmentPick={orphanPick}
                            eligible={orphanEligible}
                            assignmentDisabled={busy || !assignment?.originalExists}
                            onUsage={(usageId) => void onAssignmentSwap(item.beat.id, usageId)}
                          />
                        ) : null}
                      </div>
                    </div>
                  );
                }

                const active = item.beat.id === selectedId;
                const selInBeat =
                  !stage2 &&
                  !stage3 &&
                  membershipSel?.zone === "beat" &&
                  membershipSel.beatId === item.beat.id;
                const arrows =
                  selInBeat && selectionArrowActions?.zone === "beat"
                    ? selectionArrowActions
                    : null;
                const pick = assignmentByBeat[item.beat.id];
                const layoutPick = scenelayerByBeat[item.beat.id];
                const eligible = eligibleForBeat(item.beat);
                return (
                  <div
                    key={item.key}
                    role="listitem"
                    data-beat-id={item.beat.id}
                    className={[
                      "visual-package-inline-beat",
                      active ? "is-selected" : "",
                      stage2 || stage3 ? "has-assignment" : "",
                    ].join(" ")}
                    tabIndex={0}
                    onClick={() => selectBeat(item.beat)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        selectBeat(item.beat);
                      }
                    }}
                  >
                    <BeatCardHeader beat={item.beat} fps={fps} />
                    <div className="visual-package-inline-beat-body">
                      <div className="visual-package-inline-beat-main">
                        <div
                          className="visual-package-inline-beat-words visual-package-word-row"
                          aria-label={`Words in ${item.beat.beatType} beat`}
                        >
                          {item.words.length ? (
                            groupWordsBySentence(item.words).map((sentence) => (
                              <div
                                key={sentence.key}
                                className="visual-package-sentence"
                                data-sentence={sentence.key}
                              >
                                {sentence.words.map((word) => {
                                  const index = wordIndexById.get(word.id) ?? -1;
                                  const isSelected =
                                    selInBeat && selectionCoversIndex(membershipSel, index);
                                  const isEdge =
                                    Boolean(arrows) &&
                                    membershipSel != null &&
                                    index === membershipSel.endIndex;
                                  const trailing =
                                    isEdge && arrows ? (
                                      <MembershipArrows
                                        upTitle={arrows.upTitle}
                                        downTitle={arrows.downTitle}
                                        onUp={arrows.onUp}
                                        onDown={arrows.onDown}
                                      />
                                    ) : null;
                                  return (
                                    <WordChip
                                      key={word.id}
                                      word={word}
                                      variant="in-beat"
                                      selected={isSelected}
                                      selectionEdge={Boolean(trailing)}
                                      title={
                                        stage3
                                          ? "Stage 3 — placement on the left; lock status on the right"
                                          : stage2
                                            ? "Stage 2 — layout + graphic on the right"
                                            : "Click to select/unselect · drag or Shift-click a phrase · ↑/↓ to transcript"
                                      }
                                      trailing={trailing}
                                      onPointerDownWord={
                                        stage2
                                          ? undefined
                                          : (event) =>
                                              onWordPointerDown("beat", item.beat.id, index, event)
                                      }
                                      onPointerEnterWord={
                                        stage2
                                          ? undefined
                                          : (event) =>
                                              onWordPointerEnter("beat", item.beat.id, index, event)
                                      }
                                      onClickWord={
                                        stage2
                                          ? undefined
                                          : (event) =>
                                              onWordSelectClick("beat", item.beat.id, word.id, event)
                                      }
                                    />
                                  );
                                })}
                              </div>
                            ))
                          ) : (
                            item.beat.wordsText || item.beat.span || item.beat.label || "—"
                          )}
                        </div>
                        {item.beat.rationale ? (
                          <div className="visual-package-inline-beat-rationale">
                            {item.beat.rationale}
                          </div>
                        ) : null}
                      </div>
                      {stage2 ? (
                        <Stage2SidePanel
                          beat={item.beat}
                          layoutPick={layoutPick}
                          layoutIds={layoutIds}
                          layoutDisabled={busy || !scenelayer?.originalExists}
                          onLayout={(layoutId) => void onLayoutSwap(item.beat.id, layoutId)}
                          assignmentPick={pick}
                          eligible={eligible}
                          assignmentDisabled={busy || !assignment?.originalExists}
                          onUsage={(usageId) => void onAssignmentSwap(item.beat.id, usageId)}
                        />
                      ) : null}
                      {stage3 ? (
                        <aside
                          className={[
                            "visual-package-assignment-side",
                            placementByBeat[item.beat.id]?.locked ? "is-human" : "",
                          ].join(" ")}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="visual-package-assignment-name">
                            {placementByBeat[item.beat.id]?.displayName ||
                              placementByBeat[item.beat.id]?.engineId ||
                              "Not placed"}
                          </div>
                          <span
                            className={[
                              "visual-package-assignment-source",
                              placementByBeat[item.beat.id]?.locked ? "" : "muted",
                            ].join(" ")}
                          >
                            {placementByBeat[item.beat.id]?.locked
                              ? "Locked"
                              : placementByBeat[item.beat.id]
                                ? "Open"
                                : "—"}
                          </span>
                          <div className="visual-package-assignment-meta">
                            <span className="muted" style={{ fontSize: 11 }}>
                              {(placementByBeat[item.beat.id]?.lines || []).length} line
                              {(placementByBeat[item.beat.id]?.lines || []).length === 1 ? "" : "s"}
                            </span>
                          </div>
                        </aside>
                      ) : null}
                    </div>
                  </div>
                );
              })}

              {hasBeats && stream.length === 0 ? (
                <p className="visual-package-empty">No beats match this filter.</p>
              ) : null}
            </div>
          </div>
          ) : null}
        </section>
      )}

      {finalModalOpen && placementFinalJob ? (
        <PlacementFinalProgressModal
          job={placementFinalJob}
          canceling={finalCanceling || placementFinalJob.status === "canceling"}
          onCancel={() => void onCancelFinal()}
          onClose={() => {
            setFinalModalOpen(false);
            setFinalCanceling(false);
          }}
        />
      ) : null}

      {/* Status/error footer: fixed slot at the very bottom so appearing and
          disappearing messages never shift the controls above. */}
      <div className="visual-package-message-footer" aria-live="polite">
        {message ? <p className="visual-package-message">{message}</p> : null}
      </div>
    </div>
  );
}

function formatFinalDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m <= 0) return `${s}s`;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function PlacementFinalProgressModal({
  job,
  canceling,
  onCancel,
  onClose,
}: {
  job: PlacementFinalJob;
  canceling: boolean;
  onCancel: () => void;
  onClose: () => void;
}) {
  const running = job.status === "running";
  const isCanceling = job.status === "canceling" || canceling;
  const failed = job.status === "failed";
  const canceled = job.status === "canceled";
  const complete = job.status === "complete";
  const active = running || isCanceling;
  const clamped = Math.max(0, Math.min(100, Math.round(job.value || 0)));
  const title = isCanceling
    ? "Canceling Final…"
    : running
      ? "Exporting Final video"
      : failed
        ? "Final export failed"
        : canceled
          ? "Final export canceled"
          : "Final video ready";

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="placement-final-title">
      <div className={failed ? "progress-modal failed" : "progress-modal"}>
        <span className="eyebrow">Placement Final</span>
        <h2 id="placement-final-title">{title}</h2>
        <p>{job.message || (active ? "Rendering full-episode graphics…" : "Done.")}</p>
        {job.output_path ? <p className="modal-path">{job.output_path}</p> : null}
        <div className={active && clamped < 2 ? "progress-track indeterminate" : "progress-track"}>
          <div
            className="progress-bar"
            style={active && clamped < 2 ? undefined : { width: `${complete ? 100 : clamped}%` }}
          />
        </div>
        <div className="placement-final-progress-meta">
          <strong>{active ? `${clamped}%` : complete ? "100%" : failed || canceled ? "—" : `${clamped}%`}</strong>
          <span>
            Elapsed {formatFinalDuration(job.elapsed_seconds)}
            {active && job.eta_seconds != null ? ` · ETA ~${formatFinalDuration(job.eta_seconds)}` : ""}
          </span>
        </div>
        <p className="placement-final-progress-hint">
          {active
            ? "Same HyperFrames engines as placement preview · GPU encode + parallel capture when available"
            : complete
              ? "Published to exports/final-video.mp4 (locked-cut audio stream-copied)"
              : canceled
                ? "No final video was published. You can start Final again when ready."
                : "Check the message above, then try again."}
        </p>
        <div className="placement-final-progress-actions">
          {active ? (
            <button
              type="button"
              className="modal-action"
              onClick={onCancel}
              disabled={isCanceling}
            >
              {isCanceling ? "Canceling…" : "Cancel"}
            </button>
          ) : (
            <button type="button" className="modal-action" onClick={onClose}>
              {failed ? "Close" : canceled ? "Close" : "Done"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Stage 3 beat progress rail under the preview.
 * End caps = full beat span. Yellow ticks = line revealFrames, graphic Ends
 * (when earlier than beat end), and motion anchors (punch-zoom in/out).
 * Fill tracks playheadFrame.
 */
function PlacementBeatProgress({
  startFrame,
  endFrameExclusive,
  playheadFrame,
  revealTicks = [],
  graphicEndFrame = null,
  motionFrames = [],
}: {
  startFrame: number;
  endFrameExclusive: number;
  playheadFrame: number;
  /** Line reveals with human labels (Title, Stop 1, …) for tick tooltips. */
  revealTicks?: { frame: number; label: string }[];
  /** Placement graphic undock frame when earlier than beat end. */
  graphicEndFrame?: number | null;
  /** Camera / motion anchor frames (e.g. punch zoom in/out). */
  motionFrames?: number[];
}) {
  const span = endFrameExclusive - startFrame;
  const fraction = Math.max(0, Math.min(1, (playheadFrame - startFrame) / span));
  const ticks: {
    frame: number;
    kind: "reveal" | "end" | "motion";
    key: string;
    title: string;
  }[] = [];
  for (const [index, tick] of revealTicks.entries()) {
    if (tick.frame >= startFrame && tick.frame < endFrameExclusive) {
      ticks.push({
        frame: tick.frame,
        kind: "reveal",
        key: `reveal-${tick.frame}-${index}`,
        title: `${tick.label} · f ${tick.frame}`,
      });
    }
  }
  if (
    graphicEndFrame != null &&
    graphicEndFrame > startFrame &&
    graphicEndFrame < endFrameExclusive
  ) {
    ticks.push({
      frame: graphicEndFrame,
      kind: "end",
      key: `end-${graphicEndFrame}`,
      title: `Ends · f ${graphicEndFrame}`,
    });
  }
  for (const [index, frame] of motionFrames.entries()) {
    if (frame >= startFrame && frame < endFrameExclusive) {
      ticks.push({
        frame,
        kind: "motion",
        key: `motion-${frame}-${index}`,
        title: `motion · f ${frame}`,
      });
    }
  }
  return (
    <div className="visual-package-beat-progress">
      <span className="visual-package-beat-progress-endlabel">f {startFrame}</span>
      <div className="visual-package-beat-progress-rail">
        <div
          className="visual-package-beat-progress-fill"
          style={{ width: `${fraction * 100}%` }}
        />
        {ticks.map((tick) => (
          <div
            key={tick.key}
            className={[
              "visual-package-beat-progress-tick",
              tick.kind === "end" ? "is-graphic-end" : "",
              tick.kind === "motion" ? "is-motion" : "",
            ].join(" ")}
            style={{ left: `${((tick.frame - startFrame) / span) * 100}%` }}
            title={tick.title}
          />
        ))}
      </div>
      <span className="visual-package-beat-progress-endlabel">f {endFrameExclusive}</span>
    </div>
  );
}

/** Placement boolean meta keys (schema type boolean — not free-text). */
const BOOLEAN_META_KEYS = new Set(["showNumber"]);

function coerceBoolKnob(value: unknown, fallback = true): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const text = String(value ?? "")
    .trim()
    .toLowerCase();
  if (["1", "true", "yes", "y", "on"].includes(text)) return true;
  if (["0", "false", "no", "n", "off"].includes(text)) return false;
  return fallback;
}

/** Meta knob drafts hold raw input strings; normalize (numbers, drop empties) at send time. */
function normalizeKnobBag(bag: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(bag)) {
    if (BOOLEAN_META_KEYS.has(key)) {
      out[key] = coerceBoolKnob(value, true);
      continue;
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (!trimmed) continue;
      out[key] = /^-?\d*\.?\d+$/.test(trimmed) ? Number(trimmed) : value;
    } else if (value != null) {
      out[key] = value;
    }
  }
  return out;
}

/** Canonical content fingerprint for placement lines (field-order independent). */
function linesFingerprint(lines: PlacementLine[]): string {
  return lines
    .map((line) => `${line.slot}\u0000${line.text}\u0000${line.revealFrame}`)
    .join("\n");
}

/**
 * Stage 3 left craft panel (mockup images/6.jpg).
 * Primary surface for copy + reveal timing; live preview sits to the right.
 */
function PlacementEditorPanel({
  selected,
  placement,
  assignment,
  interfaceSpec,
  beatWords,
  fps,
  busy,
  previewBusy = false,
  hasPlacements,
  allLocked,
  beatIndex,
  beatTotal,
  livePreviewReady,
  onSave,
  onSeekReveal,
  onDraftPreview,
  onLinesChange,
  onEndFrameChange,
  onMotionChange,
  transportSlot,
  beatJumpSlot,
  speechHostEl = null,
}: {
  selected: MasterbeaterBeat | null;
  placement?: PlacementBeat;
  assignment?: AssignmentPick;
  interfaceSpec?: {
    listSlot?: string | null;
    listMax?: number;
    notes?: string;
    /** Engine-declared knobs (ENGINE_REGISTRY) — rendered generically, never hardcoded. */
    metaKeys?: string[];
    assetKeys?: string[];
    motionKeys?: string[];
  };
  beatWords: VisualPackageTranscriptWord[];
  fps: number;
  /** Place / Save / Lock in flight — may disable save actions. */
  busy: boolean;
  /** Live composition rebuild — must NOT block typing or frame nudges. */
  previewBusy?: boolean;
  hasPlacements: boolean;
  allLocked: boolean;
  beatIndex: number;
  beatTotal: number;
  livePreviewReady: boolean;
  onSave: (patch: {
    lines?: PlacementLine[];
    meta?: Record<string, unknown>;
    assets?: Record<string, unknown>;
    motion?: Record<string, unknown>;
    endFrameExclusive?: number;
    locked?: boolean;
    detail?: string;
  }) => void;
  onSeekReveal: (frame: number) => void;
  onDraftPreview: (
    lines: PlacementLine[],
    extras?: {
      meta?: Record<string, unknown>;
      assets?: Record<string, unknown>;
      motion?: Record<string, unknown>;
      endFrameExclusive?: number;
    },
  ) => void;
  /** Display-only mirror for the parent (progress rail ticks); not part of save/preview flow. */
  onLinesChange?: (lines: PlacementLine[]) => void;
  /** Live Ends draft for the progress rail graphic-end tick. */
  onEndFrameChange?: (endFrameExclusive: number | null) => void;
  /** Live motion draft (punch-zoom frames, etc.) for progress rail ticks. */
  onMotionChange?: (motion: Record<string, unknown> | null) => void;
  /** Transport cluster (progress + readout + buttons) rendered under the nudges. */
  transportSlot?: ReactNode;
  /** Header jump control — full-width row under title + lock. */
  beatJumpSlot?: ReactNode;
  /** Right-column host under the graphic card; word chips portal here when set. */
  speechHostEl?: HTMLDivElement | null;
}) {
  type ArmedKind = "line" | "end" | "zoomIn" | "zoomOut";
  const [draftLines, setDraftLines] = useState<PlacementLine[]>([]);
  const [armedIndex, setArmedIndex] = useState(0);
  /** One armed target for the shared hero nudges. */
  const [armedKind, setArmedKind] = useState<ArmedKind>("line");
  /** Engine-declared knob drafts (meta/assets bags) — generic, driven by interfaceSpec. */
  const [metaDraft, setMetaDraft] = useState<Record<string, unknown>>({});
  const [assetsDraft, setAssetsDraft] = useState<Record<string, unknown>>({});
  const [motionDraft, setMotionDraft] = useState<Record<string, unknown>>({});
  /** Graphic end frame (placement endFrameExclusive). Default = beat end. */
  const [endFrameDraft, setEndFrameDraft] = useState<number | null>(null);
  /** Canonical fingerprint of the lines we last sent to the server (echo detection). */
  const lastSentLines = useRef<string>("");
  /** Last end frame we saved — skip clobber when server echoes our write. */
  const lastSentEndFrame = useRef<number | null>(null);
  const lastSentMotion = useRef<string>("");
  const lastSentMeta = useRef<string>("");
  const lastSentAssets = useRef<string>("");
  /** Beat the draft currently mirrors — a change always forces a full re-sync. */
  const prevBeatId = useRef<string | null>(null);
  /** Latest draft for flush-on-leave (beat switch must not drop unsaved stack edits). */
  const draftSnapshotRef = useRef<{
    beatId: string;
    lines: PlacementLine[];
    meta: Record<string, unknown>;
    assets: Record<string, unknown>;
    motion: Record<string, unknown>;
    endFrameExclusive?: number;
    dirty: boolean;
  } | null>(null);
  const locked = Boolean(placement?.locked);
  /** Only re-sync draft from server when beat/lock/server lines actually change — not object identity. */
  const serverLinesKey = placement
    ? `${placement.beatId}|${placement.locked ? "1" : "0"}|${JSON.stringify(placement.lines || [])}|${placement.endFrameExclusive ?? ""}|${JSON.stringify(placement.motion || {})}|${JSON.stringify(placement.meta || {})}|${JSON.stringify(placement.assets || {})}`
    : "";

  useEffect(() => {
    if (!placement) {
      setDraftLines([]);
      setArmedIndex(0);
      setArmedKind("line");
      setMetaDraft({});
      setAssetsDraft({});
      setMotionDraft({});
      setEndFrameDraft(null);
      lastSentLines.current = "";
      lastSentEndFrame.current = null;
      lastSentMotion.current = "";
      lastSentMeta.current = "";
      lastSentAssets.current = "";
      prevBeatId.current = null;
      return;
    }
    const beatChanged = placement.beatId !== prevBeatId.current;
    prevBeatId.current = placement.beatId;
    if (beatChanged) {
      lastSentLines.current = "";
      lastSentEndFrame.current = null;
      lastSentMotion.current = "";
      lastSentMeta.current = "";
      lastSentAssets.current = "";
      // Punch-zoom has no copy lines — arm Zoom in by default.
      setArmedKind(
        placement.engineId === "source-punch-zoom" ? "zoomIn" : "line",
      );
    }
    const incoming = (placement.lines || []).map((line) => ({
      slot: line.slot,
      text: line.text || "",
      revealFrame: line.revealFrame ?? 0,
    }));
    const serverEnd = Number(placement.endFrameExclusive ?? 0) || 0;
    const serverMotion = { ...(placement.motion || {}) };
    // Seed absolute frame anchors for older punch-zoom placements that only had settleSec.
    if (placement.engineId === "source-punch-zoom") {
      const start = Number(placement.startFrame ?? 0) || 0;
      const end = serverEnd > start ? serverEnd : start + 1;
      const span = Math.max(1, end - start);
      if (serverMotion.zoomInFrame == null || serverMotion.zoomInFrame === "") {
        serverMotion.zoomInFrame = start;
      }
      if (serverMotion.zoomOutFrame == null || serverMotion.zoomOutFrame === "") {
        serverMotion.zoomOutFrame = Math.max(start + 1, end - Math.max(1, Math.floor(span / 6)));
      }
    }
    const serverMotionKey = JSON.stringify(serverMotion);
    const serverMetaKey = JSON.stringify(placement.meta || {});
    const serverAssetsKey = JSON.stringify(placement.assets || {});
    // Our own save echoing back must not clobber newer draft edits or
    // reset the armed line — only real external changes (beat switch, re-Place,
    // unlock reset) re-sync the draft.
    const linesEcho = !beatChanged && linesFingerprint(incoming) === lastSentLines.current;
    const endEcho = !beatChanged && lastSentEndFrame.current != null && serverEnd === lastSentEndFrame.current;
    const motionEcho = !beatChanged && lastSentMotion.current !== "" && serverMotionKey === lastSentMotion.current;
    const metaEcho = !beatChanged && lastSentMeta.current !== "" && serverMetaKey === lastSentMeta.current;
    const assetsEcho = !beatChanged && lastSentAssets.current !== "" && serverAssetsKey === lastSentAssets.current;
    if (linesEcho && endEcho && motionEcho && metaEcho && assetsEcho) return;
    if (!linesEcho) {
      setDraftLines(incoming);
      if (beatChanged) setArmedIndex(0);
    }
    if (!endEcho || beatChanged) {
      setEndFrameDraft(serverEnd > 0 ? serverEnd : null);
    }
    if (!motionEcho || beatChanged) {
      setMotionDraft(serverMotion);
    }
    if (!metaEcho || beatChanged) {
      setMetaDraft({ ...(placement.meta || {}) });
    }
    if (!assetsEcho || beatChanged) {
      setAssetsDraft({ ...(placement.assets || {}) });
    }
    // serverLinesKey captures content; avoid placement.lines identity thrash mid-edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverLinesKey]);

  useEffect(() => {
    onLinesChange?.(draftLines);
  }, [draftLines, onLinesChange]);

  useEffect(() => {
    onEndFrameChange?.(endFrameDraft);
  }, [endFrameDraft, onEndFrameChange]);

  useEffect(() => {
    onMotionChange?.(motionDraft);
  }, [motionDraft, onMotionChange]);

  // Prefer server interface; fall back to slot shape so list engines still edit if status lags.
  const listSlot =
    interfaceSpec?.listSlot ||
    (() => {
      const sample = (placement?.lines || []).find((l) => String(l.slot || "").includes("."));
      if (!sample?.slot) return null;
      return String(sample.slot).split(".")[0] || null;
    })();
  const listMax = interfaceSpec?.listMax ?? (listSlot === "nodes" ? 6 : listSlot ? 12 : 0);
  const armed = draftLines[armedIndex] || null;
  const editDisabled = locked; // never block craft on preview rebuild
  const motionKeys = interfaceSpec?.motionKeys || [];
  const hasZoomIn = motionKeys.includes("zoomInFrame");
  const hasZoomOut = motionKeys.includes("zoomOutFrame");

  const craftPayload = useCallback(
    (
      lines: PlacementLine[] = draftLines,
      knobs?: {
        meta?: Record<string, unknown>;
        assets?: Record<string, unknown>;
        motion?: Record<string, unknown>;
        endFrameExclusive?: number;
      },
    ) => {
      const meta = normalizeKnobBag(knobs?.meta ?? metaDraft);
      delete meta.holdSec;
      const assets = normalizeKnobBag(knobs?.assets ?? assetsDraft);
      const motion = normalizeKnobBag(knobs?.motion ?? motionDraft);
      const endFrame =
        knobs?.endFrameExclusive ??
        endFrameDraft ??
        placement?.endFrameExclusive ??
        undefined;
      return { lines, meta, assets, motion, endFrameExclusive: endFrame };
    },
    [draftLines, metaDraft, assetsDraft, motionDraft, endFrameDraft, placement?.endFrameExclusive],
  );

  const isDirty = useMemo(() => {
    if (!placement || locked) return false;
    const serverLines = (placement.lines || []).map((line) => ({
      slot: line.slot,
      text: line.text || "",
      revealFrame: line.revealFrame ?? 0,
    }));
    if (linesFingerprint(draftLines) !== linesFingerprint(serverLines)) return true;
    const serverEnd = Number(placement.endFrameExclusive ?? 0) || 0;
    const draftEnd = Number(endFrameDraft ?? 0) || 0;
    if (draftEnd !== serverEnd) return true;
    const payload = craftPayload();
    if (JSON.stringify(payload.motion) !== JSON.stringify(placement.motion || {})) return true;
    if (JSON.stringify(payload.meta) !== JSON.stringify(placement.meta || {})) return true;
    if (JSON.stringify(payload.assets) !== JSON.stringify(placement.assets || {})) return true;
    return false;
  }, [placement, locked, draftLines, endFrameDraft, craftPayload]);

  /** Explicit commit: one save + one preview rebuild. No per-keystroke races. */
  const commitCraft = useCallback(
    (detail = "save craft") => {
      if (locked || !placement) return;
      const payload = craftPayload();
      lastSentLines.current = linesFingerprint(payload.lines);
      if (payload.endFrameExclusive != null) {
        lastSentEndFrame.current = payload.endFrameExclusive;
      }
      lastSentMotion.current = JSON.stringify(payload.motion);
      lastSentMeta.current = JSON.stringify(payload.meta);
      lastSentAssets.current = JSON.stringify(payload.assets);
      onSave({
        lines: payload.lines,
        meta: payload.meta,
        assets: payload.assets,
        motion: payload.motion,
        endFrameExclusive: payload.endFrameExclusive,
        detail,
      });
    },
    [locked, placement, craftPayload, onSave],
  );

  // Keep snapshot current so beat-switch flush can save without losing edits.
  useEffect(() => {
    if (!placement || locked) {
      draftSnapshotRef.current = null;
      return;
    }
    const payload = craftPayload();
    draftSnapshotRef.current = {
      beatId: placement.beatId,
      lines: payload.lines,
      meta: payload.meta,
      assets: payload.assets,
      motion: payload.motion,
      endFrameExclusive: payload.endFrameExclusive,
      dirty: isDirty,
    };
  }, [placement, locked, craftPayload, isDirty]);

  // Leaving a beat with unsaved craft: flush once so Dependency Stack edits aren't dropped.
  useEffect(() => {
    return () => {
      const snap = draftSnapshotRef.current;
      if (!snap?.dirty || !snap.beatId) return;
      lastSentLines.current = linesFingerprint(snap.lines);
      if (snap.endFrameExclusive != null) lastSentEndFrame.current = snap.endFrameExclusive;
      lastSentMotion.current = JSON.stringify(snap.motion);
      lastSentMeta.current = JSON.stringify(snap.meta);
      lastSentAssets.current = JSON.stringify(snap.assets);
      onSave({
        lines: snap.lines,
        meta: snap.meta,
        assets: snap.assets,
        motion: snap.motion,
        endFrameExclusive: snap.endFrameExclusive,
        detail: "flush on leave (auto)",
      });
    };
    // Only when the placed beat identity changes / panel unmounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placement?.beatId]);

  /** Knob edits stay local until Save & update preview. */
  const updateKnobs = useCallback(
    (patch: {
      meta?: Record<string, unknown>;
      assets?: Record<string, unknown>;
      motion?: Record<string, unknown>;
    }) => {
      if (patch.meta) setMetaDraft(patch.meta);
      if (patch.assets) setAssetsDraft(patch.assets);
      if (patch.motion) setMotionDraft(patch.motion);
    },
    [],
  );

  /** Placement span end — when the graphic undocks back to full talking-head. */
  const spanStartFrame = placement?.startFrame ?? selected?.startFrame ?? 0;
  const beatEndFrame =
    selected?.endFrameExclusive ??
    (selected?.endFrame != null ? selected.endFrame + 1 : undefined) ??
    placement?.endFrameExclusive ??
    spanStartFrame + 1;
  const minEndFrame = (() => {
    const latestReveal = draftLines.reduce(
      (max, line) => Math.max(max, Number(line.revealFrame) || 0),
      spanStartFrame,
    );
    return Math.max(spanStartFrame + 1, latestReveal + 1);
  })();

  const setEndFrame = useCallback(
    (raw: number) => {
      if (locked) return;
      const next = Math.max(minEndFrame, Math.min(beatEndFrame, Math.round(raw)));
      setEndFrameDraft(next);
      // Seek to the last frame still inside the graphic (end is exclusive).
      onSeekReveal(Math.max(spanStartFrame, next - 1));
    },
    [locked, minEndFrame, beatEndFrame, onSeekReveal, spanStartFrame],
  );

  const setMotionFrame = useCallback(
    (key: "zoomInFrame" | "zoomOutFrame", raw: number) => {
      if (locked) return;
      const next = Math.max(spanStartFrame, Math.min(beatEndFrame - 1, Math.round(raw)));
      const updated = { ...motionDraft, [key]: next };
      // Keep zoom-out after zoom-in when both exist.
      if (key === "zoomInFrame" && updated.zoomOutFrame != null) {
        const outF = Number(updated.zoomOutFrame);
        if (Number.isFinite(outF) && outF <= next) {
          updated.zoomOutFrame = Math.min(beatEndFrame - 1, next + 1);
        }
      }
      if (key === "zoomOutFrame" && updated.zoomInFrame != null) {
        const inF = Number(updated.zoomInFrame);
        if (Number.isFinite(inF) && next <= inF) {
          updated.zoomInFrame = Math.max(spanStartFrame, next - 1);
        }
      }
      setMotionDraft(updated);
      onSeekReveal(next);
    },
    [locked, spanStartFrame, beatEndFrame, motionDraft, onSeekReveal],
  );

  const updateLine = (index: number, patch: Partial<PlacementLine>) => {
    setDraftLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  };

  const armLine = (index: number) => {
    setArmedKind("line");
    setArmedIndex(index);
  };

  const armEnd = () => {
    setArmedKind("end");
  };

  /** Shared hero nudges — only the armed target moves. */
  const nudgeArmed = (delta: number) => {
    if (locked) return;
    if (armedKind === "end") {
      if (endFrameDraft == null) return;
      setEndFrame(endFrameDraft + delta);
      return;
    }
    if (armedKind === "zoomIn") {
      const cur = Number(motionDraft.zoomInFrame ?? spanStartFrame);
      setMotionFrame("zoomInFrame", cur + delta);
      return;
    }
    if (armedKind === "zoomOut") {
      const cur = Number(motionDraft.zoomOutFrame ?? beatEndFrame - 1);
      setMotionFrame("zoomOutFrame", cur + delta);
      return;
    }
    if (!armed || armedIndex < 0) return;
    // Reveal must stay inside the graphic span (respect live Ends draft).
    const spanEnd = (endFrameDraft ?? placement?.endFrameExclusive ?? spanStartFrame + 1) - 1;
    const nextFrame = Math.max(spanStartFrame, Math.min(spanEnd, armed.revealFrame + delta));
    updateLine(armedIndex, { revealFrame: nextFrame });
    onSeekReveal(nextFrame);
  };

  const setArmedFrame = (frame: number) => {
    if (locked) return;
    if (armedKind === "end") {
      setEndFrame(frame);
      return;
    }
    if (armedKind === "zoomIn") {
      setMotionFrame("zoomInFrame", frame);
      return;
    }
    if (armedKind === "zoomOut") {
      setMotionFrame("zoomOutFrame", frame);
      return;
    }
    if (!armed || armedIndex < 0) return;
    const spanEnd = (endFrameDraft ?? placement?.endFrameExclusive ?? spanStartFrame + 1) - 1;
    const nextFrame = Math.max(spanStartFrame, Math.min(spanEnd, Math.round(frame)));
    updateLine(armedIndex, { revealFrame: nextFrame });
    onSeekReveal(nextFrame);
  };

  const motionFrameDisplay = (key: "zoomInFrame" | "zoomOutFrame"): string | number => {
    const raw = motionDraft[key];
    if (raw == null || raw === "") return "";
    const n = Number(raw);
    return Number.isFinite(n) ? n : "";
  };
  const heroFrameValue: string | number =
    armedKind === "end"
      ? (endFrameDraft ?? "")
      : armedKind === "zoomIn"
        ? motionFrameDisplay("zoomInFrame")
        : armedKind === "zoomOut"
          ? motionFrameDisplay("zoomOutFrame")
          : (armed?.revealFrame ?? "");
  const heroCanNudge =
    !editDisabled &&
    (armedKind === "end"
      ? endFrameDraft != null
      : armedKind === "zoomIn" || armedKind === "zoomOut"
        ? true
        : Boolean(armed));

  const metaKeys = interfaceSpec?.metaKeys || [];
  const assetKeys = interfaceSpec?.assetKeys || [];
  /** "holdSec" → "Hold sec" — generic humanizer, no per-engine strings. */
  const knobLabel = (key: string) => {
    // ui-callout ring geometry (normalized 0–1).
    if (key === "x") return "X (left)";
    if (key === "y") return "Y (top)";
    if (key === "width") return "Width";
    if (key === "height") return "Height";
    return key
      .replace(/([A-Z])/g, " $1")
      .replace(/^./, (c) => c.toUpperCase())
      .replace(/ Asset Id$/i, "");
  };

  const setMetaValue = (key: string, raw: string | boolean) => {
    updateKnobs({ meta: { ...metaDraft, [key]: raw } });
  };

  const pickImageForKey = async (key: string) => {
    try {
      const result = await importPlacementImageDialog();
      updateKnobs({ assets: { ...assetsDraft, [key]: result.assetId } });
    } catch (error) {
      // Cancelled dialog surfaces as a 400 — quiet; real failures still logged.
      console.warn("[visual-package] image import:", error);
    }
  };

  const wordStartFrame = (word: VisualPackageTranscriptWord) =>
    word.startFrame != null && Number.isFinite(word.startFrame)
      ? Math.round(word.startFrame)
      : Math.round((word.startSec ?? 0) * fps);

  const setTimingFromWord = (word: VisualPackageTranscriptWord) => {
    if (locked) return;
    // Word chips drive whatever timing target is armed (line reveal, Ends, zoom).
    if (armedKind === "end") {
      // Ends is exclusive: undock as this word starts (graphic no longer covers it).
      setArmedFrame(wordStartFrame(word));
      return;
    }
    if (armedKind === "zoomIn" || armedKind === "zoomOut") {
      setArmedFrame(wordStartFrame(word));
      return;
    }
    if (armedKind !== "line" || !armed) return;
    setArmedFrame(wordStartFrame(word));
  };

  /** Chips are live whenever a timing target is armed (not only copy lines). */
  const wordChipsEnabled =
    !editDisabled &&
    (armedKind === "end" ||
      armedKind === "zoomIn" ||
      armedKind === "zoomOut" ||
      (armedKind === "line" && Boolean(armed)));

  const addListLine = () => {
    if (!listSlot || locked) return;
    setDraftLines((prev) => {
      const listLines = prev.filter((l) => l.slot.startsWith(`${listSlot}.`));
      if (listMax > 0 && listLines.length >= listMax) return prev;
      const nextIndex = listLines.length;
      const lastFrame = prev.length ? prev[prev.length - 1].revealFrame : placement?.startFrame || 0;
      const next = [
        ...prev,
        {
          slot: `${listSlot}.${nextIndex}`,
          text: "",
          revealFrame: lastFrame + 15,
        },
      ];
      setArmedIndex(next.length - 1);
      return next;
    });
  };

  const removeListLine = (index: number) => {
    if (locked || !listSlot) return;
    setDraftLines((prev) => {
      const row = prev[index];
      if (!row?.slot.startsWith(`${listSlot}.`)) return prev;
      const filtered = prev.filter((_, i) => i !== index);
      let n = 0;
      const next = filtered.map((line) => {
        if (!line.slot.startsWith(`${listSlot}.`)) return line;
        const re = { ...line, slot: `${listSlot}.${n}` };
        n += 1;
        return re;
      });
      setArmedIndex((current) => Math.max(0, Math.min(current, next.length - 1)));
      return next;
    });
  };

  const positionLabel =
    beatTotal > 0 && beatIndex >= 0
      ? `${beatIndex + 1} of ${beatTotal}`
      : beatTotal > 0
        ? `— of ${beatTotal}`
        : "—";

  const slotLabel = (slot: string, index: number) => {
    if (listSlot && slot.startsWith(`${listSlot}.`)) {
      const n = slot.slice(listSlot.length + 1);
      // Progress-scale stops sit on the bar — not generic "bullets".
      if (listSlot === "milestones") return `Stop ${Number(n) + 1}`;
      return `Bullet ${Number(n) + 1}`;
    }
    if (slot === "text" || slot === "title" || slot === "phrase" || slot === "thesis") {
      return "Title";
    }
    if (slot === "startLabel") return "Start";
    if (slot === "targetLabel") return "Target";
    if (slot === "label") return "Label";
    if (slot === "detail") return "Detail";
    if (slot === "action") return "Action";
    if (slot === "destination") return "Link";
    if (slot === "prompt") return "Prompt";
    return slot || `Line ${index + 1}`;
  };

  const heroTargetLabel =
    armedKind === "end"
      ? "Ends (undock)"
      : armedKind === "zoomIn"
        ? "Zoom in"
        : armedKind === "zoomOut"
          ? "Zoom out"
          : armed
            ? slotLabel(armed.slot, armedIndex)
            : "arm a timing target";

  const editor = (
    <aside className="visual-package-placement-editor" aria-label="Placement craft panel">
      <header className="visual-package-placement-panel-head">
        <div className="visual-package-placement-panel-title-row">
          <h3 className="visual-package-placement-panel-title">
            {selected?.beatType
              ? selected.beatType.charAt(0).toUpperCase() + selected.beatType.slice(1)
              : "Placement"}
            <span className="visual-package-placement-panel-beat">
              · beat {positionLabel}
            </span>
          </h3>
          {selected && placement ? (
            <span
              className="visual-package-placement-lock-indicator"
              title={locked ? "Beat locked for the final render" : "Beat unlocked — editing"}
              aria-label={locked ? "Locked" : "Unlocked"}
            >
              {locked ? <Lock size={20} /> : <LockOpen size={20} />}
            </span>
          ) : null}
        </div>
        {beatJumpSlot ? (
          <div className="visual-package-placement-panel-jump-row">{beatJumpSlot}</div>
        ) : null}
        {/* Graphic poster + name moved below the video player (parent renders it). */}
      </header>

      {/* Transport pinned directly under the header — fixed position across beats,
          no matter how many line rows the engine below it has. */}
      {transportSlot}

      {selected && placement && !locked ? (
        <div className="visual-package-craft-commit" role="status">
          <span
            className={[
              "visual-package-craft-commit-status",
              isDirty ? "is-dirty" : previewBusy ? "is-busy" : "is-clean",
            ].join(" ")}
          >
            {previewBusy
              ? "Updating preview…"
              : isDirty
                ? "Unsaved edits — preview still shows last save"
                : livePreviewReady
                  ? "Saved · preview matches craft"
                  : "Saved"}
          </span>
          <button
            type="button"
            className="workflow-action emphasized visual-package-craft-commit-btn"
            disabled={busy || previewBusy || !isDirty}
            title="Save lines, knobs, and timing, then rebuild the live HyperFrames preview once"
            onClick={() => commitCraft("save craft")}
          >
            {previewBusy ? (
              <>
                <Loader2 size={14} className="spin" /> Updating…
              </>
            ) : (
              "Save & update preview"
            )}
          </button>
        </div>
      ) : null}

      {!hasPlacements ? (
        <p className="visual-package-layout-review-hint">
          Press <strong>Place</strong> in the stage rail to draft lines for assigned beats.
        </p>
      ) : !selected || !placement ? (
        <p className="visual-package-layout-review-hint">
          Use Prev / Next under the preview to open a placed beat.
        </p>
      ) : (
        <>
          <div className="visual-package-placement-lines" role="list">
            {draftLines.length === 0 && !hasZoomIn && !hasZoomOut ? (
              <p className="visual-package-layout-review-hint">
                Motion-only engine — no copy lines. Scrub live preview and Lock when ready.
              </p>
            ) : null}
            {draftLines.length > 0 ? (
              draftLines.map((line, index) => {
                const isList = Boolean(listSlot && line.slot.startsWith(`${listSlot}.`));
                const isArmed = armedKind === "line" && index === armedIndex;
                return (
                  <div
                    key={`${line.slot}-${index}`}
                    role="listitem"
                    className={[
                      "visual-package-placement-line-row",
                      isArmed ? "is-armed" : "",
                    ].join(" ")}
                    onClick={() => armLine(index)}
                  >
                    <span className="visual-package-placement-slot" title={line.slot}>
                      {slotLabel(line.slot, index)}
                    </span>
                    <input
                      className="visual-package-placement-text"
                      type="text"
                      value={line.text}
                      disabled={editDisabled}
                      onFocus={() => armLine(index)}
                      onChange={(e) => updateLine(index, { text: e.target.value })}
                      onClick={(e) => e.stopPropagation()}
                    />
                    <button
                      type="button"
                      className={[
                        "visual-package-placement-line-frame",
                        isArmed ? "is-armed" : "",
                      ].join(" ")}
                      title="Arm this line and jump to its reveal frame"
                      disabled={editDisabled}
                      onClick={(e) => {
                        e.stopPropagation();
                        armLine(index);
                        onSeekReveal(line.revealFrame);
                      }}
                    >
                      f {line.revealFrame}
                    </button>
                    {isArmed ? (
                      <span className="visual-package-placement-armed-check" aria-hidden>
                        ✓
                      </span>
                    ) : (
                      <span className="visual-package-placement-armed-check muted" aria-hidden />
                    )}
                    {isList && !locked ? (
                      <button
                        type="button"
                        className="visual-package-placement-remove"
                        title="Remove bullet"
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          removeListLine(index);
                        }}
                      >
                        ×
                      </button>
                    ) : null}
                  </div>
                );
              })
            ) : null}

            {/* Punch-zoom: arm Zoom in / Zoom out like Title, then use shared hero nudges. */}
            {hasZoomIn ? (
              <div
                role="listitem"
                className={[
                  "visual-package-placement-line-row",
                  armedKind === "zoomIn" ? "is-armed" : "",
                ].join(" ")}
                onClick={() => {
                  setArmedKind("zoomIn");
                  const f = Number(motionDraft.zoomInFrame ?? spanStartFrame);
                  if (Number.isFinite(f)) onSeekReveal(f);
                }}
              >
                <span className="visual-package-placement-slot" title="Frame when zoom-in starts">
                  Zoom in
                </span>
                <span className="visual-package-placement-end-hint">
                  Camera punches in (starts)
                </span>
                <button
                  type="button"
                  className={[
                    "visual-package-placement-line-frame",
                    armedKind === "zoomIn" ? "is-armed" : "",
                  ].join(" ")}
                  title="Arm Zoom in and jump to frame"
                  disabled={editDisabled}
                  onClick={(e) => {
                    e.stopPropagation();
                    setArmedKind("zoomIn");
                    const f = Number(motionDraft.zoomInFrame ?? spanStartFrame);
                    if (Number.isFinite(f)) onSeekReveal(f);
                  }}
                >
                  f {String(motionDraft.zoomInFrame ?? "—")}
                </button>
                {armedKind === "zoomIn" ? (
                  <span className="visual-package-placement-armed-check" aria-hidden>
                    ✓
                  </span>
                ) : (
                  <span className="visual-package-placement-armed-check muted" aria-hidden />
                )}
              </div>
            ) : null}
            {hasZoomOut ? (
              <div
                role="listitem"
                className={[
                  "visual-package-placement-line-row",
                  armedKind === "zoomOut" ? "is-armed" : "",
                ].join(" ")}
                onClick={() => {
                  setArmedKind("zoomOut");
                  const f = Number(motionDraft.zoomOutFrame ?? beatEndFrame - 1);
                  if (Number.isFinite(f)) onSeekReveal(f);
                }}
              >
                <span className="visual-package-placement-slot" title="Frame when zoom-out starts">
                  Zoom out
                </span>
                <span className="visual-package-placement-end-hint">
                  Camera returns to full (starts)
                </span>
                <button
                  type="button"
                  className={[
                    "visual-package-placement-line-frame",
                    armedKind === "zoomOut" ? "is-armed" : "",
                  ].join(" ")}
                  title="Arm Zoom out and jump to frame"
                  disabled={editDisabled}
                  onClick={(e) => {
                    e.stopPropagation();
                    setArmedKind("zoomOut");
                    const f = Number(motionDraft.zoomOutFrame ?? beatEndFrame - 1);
                    if (Number.isFinite(f)) onSeekReveal(f);
                  }}
                >
                  f {String(motionDraft.zoomOutFrame ?? "—")}
                </button>
                {armedKind === "zoomOut" ? (
                  <span className="visual-package-placement-armed-check" aria-hidden>
                    ✓
                  </span>
                ) : (
                  <span className="visual-package-placement-armed-check muted" aria-hidden />
                )}
              </div>
            ) : null}

            {/* Ends is a peer of Title: click to arm, then use the shared hero nudges. */}
            <div
              role="listitem"
              className={[
                "visual-package-placement-line-row",
                armedKind === "end" ? "is-armed" : "",
              ].join(" ")}
              onClick={() => {
                armEnd();
                if (endFrameDraft != null) {
                  onSeekReveal(Math.max(spanStartFrame, endFrameDraft - 1));
                }
              }}
            >
              <span
                className="visual-package-placement-slot"
                title="Frame where the graphic undocks back to full talking-head"
              >
                Ends
              </span>
              <span className="visual-package-placement-end-hint">
                {endFrameDraft != null && endFrameDraft < beatEndFrame
                  ? `Undock before beat end (beat f ${beatEndFrame})`
                  : "Undock at beat end (default)"}
              </span>
              <button
                type="button"
                className={[
                  "visual-package-placement-line-frame",
                  armedKind === "end" ? "is-armed" : "",
                ].join(" ")}
                title="Arm Ends and jump to undock"
                disabled={editDisabled || endFrameDraft == null}
                onClick={(e) => {
                  e.stopPropagation();
                  armEnd();
                  if (endFrameDraft != null) {
                    onSeekReveal(Math.max(spanStartFrame, endFrameDraft - 1));
                  }
                }}
              >
                f {endFrameDraft ?? "—"}
              </button>
              {armedKind === "end" ? (
                <span className="visual-package-placement-armed-check" aria-hidden>
                  ✓
                </span>
              ) : (
                <span className="visual-package-placement-armed-check muted" aria-hidden />
              )}
              {endFrameDraft != null && endFrameDraft < beatEndFrame ? (
                <button
                  type="button"
                  className="visual-package-placement-reset-end-inline"
                  disabled={editDisabled}
                  title={`Reset to beat end f ${beatEndFrame}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    armEnd();
                    setEndFrame(beatEndFrame);
                  }}
                >
                  Reset
                </button>
              ) : null}
            </div>

            {/* Image / other knobs — not frame-armed; neutral chrome. */}
            {assetKeys.length > 0 || metaKeys.filter((k) => k !== "holdSec").length > 0 ? (
              <div
                className="visual-package-placement-knobs"
                role="group"
                aria-label="Graphic knobs"
              >
                {assetKeys.map((key) => (
                  <div className="visual-package-placement-knob" key={key}>
                    <span className="visual-package-placement-knob-label">{knobLabel(key)}</span>
                    <span
                      className="visual-package-placement-knob-value"
                      title={String(assetsDraft[key] ?? "")}
                    >
                      {String(assetsDraft[key] || "demo")}
                    </span>
                    <button
                      type="button"
                      className="visual-package-placement-knob-action"
                      disabled={editDisabled}
                      onClick={() => void pickImageForKey(key)}
                    >
                      Choose…
                    </button>
                  </div>
                ))}
                {metaKeys
                  .filter((key) => key !== "holdSec")
                  .map((key) => {
                    if (BOOLEAN_META_KEYS.has(key)) {
                      const on = coerceBoolKnob(metaDraft[key], true);
                      return (
                        <button
                          type="button"
                          key={key}
                          className={[
                            "visual-package-toggle",
                            "visual-package-placement-knob-toggle",
                            on ? "is-on" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          role="switch"
                          aria-checked={on}
                          disabled={editDisabled}
                          onClick={() => setMetaValue(key, !on)}
                        >
                          <span className="visual-package-toggle-track" aria-hidden>
                            <span className="visual-package-toggle-thumb" />
                          </span>
                          {knobLabel(key)}
                        </button>
                      );
                    }
                    const boundsHint =
                      key === "x" || key === "y" || key === "width" || key === "height"
                        ? "Normalized 0–1 of the frame (upper-left + size for the ring)"
                        : undefined;
                    return (
                      <label className="visual-package-placement-knob" key={key} title={boundsHint}>
                        <span className="visual-package-placement-knob-label">{knobLabel(key)}</span>
                        <input
                          type="text"
                          inputMode="decimal"
                          value={String(metaDraft[key] ?? "")}
                          placeholder={boundsHint ? "0–1" : "default"}
                          disabled={editDisabled}
                          onChange={(event) => setMetaValue(key, event.target.value)}
                        />
                      </label>
                    );
                  })}
              </div>
            ) : null}
          </div>

          {listSlot && !locked ? (
            <button
              type="button"
              className="workflow-action visual-package-placement-add"
              disabled={busy}
              onClick={addListLine}
            >
              Add bullet
            </button>
          ) : null}

          {/* Shared hero frame control — drives only the armed target. */}
          <div className="visual-package-placement-frame-hero" aria-label="Frame fine-tune">
            <span className="visual-package-placement-speech-label" style={{ width: "100%", textAlign: "center" }}>
              {armedKind === "end"
                ? "Graphic end"
                : armedKind === "zoomIn" || armedKind === "zoomOut"
                  ? "Camera timing"
                  : "Reveal timing"}{" "}
              · {heroTargetLabel}
              {previewBusy ? " · updating live preview…" : ""}
            </span>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={!heroCanNudge}
              onClick={() => nudgeArmed(-10)}
            >
              ←10
            </button>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={!heroCanNudge}
              onClick={() => nudgeArmed(-5)}
            >
              ←5
            </button>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={!heroCanNudge}
              onClick={() => nudgeArmed(-1)}
            >
              ←1
            </button>
            <label className="visual-package-placement-frame-display">
              <span className="visual-package-placement-frame-prefix">f</span>
              <input
                type="number"
                value={heroFrameValue}
                disabled={!heroCanNudge}
                onChange={(e) => setArmedFrame(Number(e.target.value) || 0)}
                title={
                  armedKind === "end"
                    ? "Graphic end frame (exclusive) — when the card undocks"
                    : armedKind === "zoomIn"
                      ? "Frame when zoom-in starts (absolute on locked cut)"
                      : armedKind === "zoomOut"
                        ? "Frame when zoom-out starts (absolute on locked cut)"
                        : "Reveal frame (absolute on locked cut) for the armed line"
                }
              />
            </label>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={!heroCanNudge}
              onClick={() => nudgeArmed(1)}
            >
              1→
            </button>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={!heroCanNudge}
              onClick={() => nudgeArmed(5)}
            >
              5→
            </button>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={!heroCanNudge}
              onClick={() => nudgeArmed(10)}
            >
              10→
            </button>
          </div>

        </>
      )}
    </aside>
  );

  const speechCard =
    selected && placement ? (
      <section
        className="visual-package-placement-speech-card"
        aria-label="Spoken words in this beat"
      >
        <div className="visual-package-placement-word-chips">
          {beatWords.length === 0 ? (
            <span className="muted" style={{ fontSize: 12 }}>
              No word timing for this beat.
            </span>
          ) : (
            beatWords.map((word) => {
              const frame = wordStartFrame(word);
              const isMark =
                (armedKind === "line" &&
                  armed != null &&
                  Math.abs((armed.revealFrame || 0) - frame) <= 1) ||
                (armedKind === "end" &&
                  endFrameDraft != null &&
                  Math.abs(endFrameDraft - frame) <= 1) ||
                (armedKind === "zoomIn" &&
                  Math.abs(Number(motionDraft.zoomInFrame ?? NaN) - frame) <= 1) ||
                (armedKind === "zoomOut" &&
                  Math.abs(Number(motionDraft.zoomOutFrame ?? NaN) - frame) <= 1);
              const chipTitle =
                armedKind === "end"
                  ? `Set Ends (undock) · f ${frame} · ${frameToClock(frame, fps)}`
                  : armedKind === "zoomIn"
                    ? `Set zoom-in · f ${frame} · ${frameToClock(frame, fps)}`
                    : armedKind === "zoomOut"
                      ? `Set zoom-out · f ${frame} · ${frameToClock(frame, fps)}`
                      : `Set reveal · f ${frame} · ${frameToClock(frame, fps)}`;
              return (
                <button
                  key={word.id}
                  type="button"
                  className={[
                    "visual-package-placement-word-chip",
                    isMark ? "is-reveal" : "",
                  ].join(" ")}
                  disabled={!wordChipsEnabled}
                  title={chipTitle}
                  onClick={() => setTimingFromWord(word)}
                >
                  {word.text}
                </button>
              );
            })
          )}
        </div>
      </section>
    ) : null;

  return (
    <>
      {editor}
      {speechCard && speechHostEl
        ? createPortal(speechCard, speechHostEl)
        : speechCard}
    </>
  );
}
