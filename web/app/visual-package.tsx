"use client";

import {
  createElement,
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
import { ChevronDown, ChevronUp, Loader2, Pause, Play, RefreshCw, SkipBack } from "lucide-react";
import {
  assignmentPosterUrl,
  buildPlacementPreview,
  getVisualPackageStatus,
  placementPreviewCompositionUrl,
  runAssignment,
  runMasterbeater,
  runPlacement,
  runScenelayer,
  saveAssignmentOverride,
  saveMasterbeaterBeats,
  savePlacementBeat,
  saveScenelayerOverride,
  visualPackageSourceVideoUrl,
  visualRuntimePlayerUrl,
  type AssignmentEligibleUsage,
  type AssignmentPick,
  type AssignmentStatus,
  type MasterbeaterBeat,
  type MasterbeaterEditEvent,
  type MasterbeaterResult,
  type PlacementBeat,
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
  return next;
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
  return { beats: [...beats, rebound], beat: rebound };
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
  const nextBeats = beats
    .filter((beat) => beat.id !== dropId && beat.id !== keep.id)
    .concat(rebound);
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
  const nextBeats = beats.filter((item) => item.id !== beatId).concat(left, right);
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
  const [autoSaveState, setAutoSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [message, setMessage] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [layoutFilter, setLayoutFilter] = useState<string>("all");
  const [railHost, setRailHost] = useState<HTMLElement | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loopBeat, setLoopBeat] = useState(true);
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
    return beats.filter((beat) => {
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
    });
  }, [beats, typeFilter, layoutFilter, scenelayerByBeat]);

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
        setMessage(
          `Auto-saved${wordLabel} · working copy + ledger (${saved.ledgerEntryCount ?? "?"} edits). Original suggestion kept.`,
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
    const pool = stage3
      ? (() => {
          const placed = filteredBeats.filter(
            (b) => placementByBeat[b.id] || assignmentByBeat[b.id]?.usageId,
          );
          return placed.length ? placed : filteredBeats;
        })()
      : filteredBeats;
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
  }, [
    beats,
    filteredBeats,
    selectedId,
    stage3,
    placementByBeat,
    assignmentByBeat,
  ]);

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
   * Simple Stage 3 transport — same pattern as visual-production:
   * mount player once per composition, play/pause/seek only. No remount thrash.
   */
  const stopStage3Preview = useCallback(() => {
    const player = runtimePlayerRef.current;
    try {
      player?.pause();
    } catch {
      /* ignore */
    }
    setPlaying(false);
  }, []);

  const playStage3Preview = useCallback(() => {
    const player = runtimePlayerRef.current;
    if (!player) return;
    try {
      // HF play() already seeks to 0 when currentTime >= duration.
      const duration = Math.max(
        0.05,
        Number(player.duration) || Number(placementPreview?.durationSec) || 0.05,
      );
      const t = Number(player.currentTime) || 0;
      if (t >= duration - 0.12 || t < 0) {
        player.seek(0);
      }
      player.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
  }, [placementPreview?.durationSec]);

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
            setPlaying(true);
          } else {
            player.pause();
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
    [fps, placementPreview, stage3],
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
            setPlaying(true);
          } else {
            player.pause();
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
    [fps, placementPreview, stage3LivePreview],
  );

  const refreshPlacementPreview = useCallback(
    async (
      beatId: string,
      draft?: {
        lines?: PlacementLine[];
        force?: boolean;
      },
    ) => {
      if (!hasVideoProject || !beatId) return;
      const gen = ++placementPreviewGen.current;
      setPlacementPreviewBusy(true);
      setPlacementPreviewError(null);
      try {
        const data = await buildPlacementPreview({
          beatId,
          lines: draft?.lines,
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
  const selectedPlacementKey = selectedPlacement
    ? [
        selectedPlacement.beatId,
        selectedPlacement.locked ? "1" : "0",
        selectedPlacement.engineId || "",
        selectedPlacement.startFrame ?? "",
        selectedPlacement.endFrameExclusive ?? "",
        JSON.stringify(selectedPlacement.lines || []),
      ].join("|")
    : "";

  // Build live Tier B when Stage 3 selects a placed beat (or its saved lines change).
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
    void refreshPlacementPreview(selectedId);
    // selectedPlacementKey captures line/lock changes without object identity thrash.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage3, selectedId, selectedPlacementKey, refreshPlacementPreview]);

  // Simple HF player wiring — mount once per cacheKey, native loop, no remount thrash.
  useEffect(() => {
    if (!stage3LivePreview) return;
    const player = runtimePlayerRef.current;
    if (!player || !runtimeScriptReady) return;

    try {
      player.loop = loopBeat;
    } catch {
      /* ignore */
    }

    const onReady = () => {
      setRuntimeReady(true);
      try {
        player.loop = loopBeat;
        player.seek(0);
      } catch {
        /* ignore */
      }
      setPlayheadFrame(Math.round(compositionRangeStartSec * fps));
      setPlaying(false);
    };
    const onTimeUpdate = (event: Event) => {
      const detail = (event as CustomEvent<{ currentTime?: number }>).detail;
      const local = Number.isFinite(detail?.currentTime)
        ? Number(detail?.currentTime)
        : Number(player.currentTime) || 0;
      setPlayheadFrame(Math.round((local + compositionRangeStartSec) * fps));
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => {
      // Native loop restarts via player.loop; we only clear UI when loop is off.
      if (!loopBeat) {
        setPlaying(false);
        try {
          player.seek(0);
        } catch {
          /* ignore */
        }
      }
    };

    player.addEventListener("ready", onReady);
    player.addEventListener("timeupdate", onTimeUpdate);
    player.addEventListener("play", onPlay);
    player.addEventListener("pause", onPause);
    player.addEventListener("ended", onEnded);
    if (player.ready) onReady();
    return () => {
      player.removeEventListener("ready", onReady);
      player.removeEventListener("timeupdate", onTimeUpdate);
      player.removeEventListener("play", onPlay);
      player.removeEventListener("pause", onPause);
      player.removeEventListener("ended", onEnded);
    };
  }, [
    stage3LivePreview,
    runtimeScriptReady,
    placementPreview?.cacheKey,
    fps,
    compositionRangeStartSec,
    loopBeat,
  ]);

  /**
   * Beats to step through in Stage 2/3 transport.
   * Stage 3: only assigned/placed beats (graphics already chosen) — one at a time via Prev/Next.
   */
  const reviewBeats = useMemo(() => {
    if (!stage3) return filteredBeats;
    const placed = filteredBeats.filter(
      (b) => placementByBeat[b.id] || assignmentByBeat[b.id]?.usageId,
    );
    return placed.length ? placed : filteredBeats;
  }, [stage3, filteredBeats, placementByBeat, assignmentByBeat]);
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
      // Seek (and play only if Autoplay on select is on).
      selectBeat(next, autoplayOnSelect);
    },
    [reviewBeats, selectedId, autoplayOnSelect, selectBeat],
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
      setMessage("Finish Stage 1 Masterbeater beats before Scenelayer.");
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
      setMessage("Finish Stage 1 Masterbeater beats before Assign.");
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

  const onSavePlacement = useCallback(
    async (beatId: string, patch: {
      lines?: PlacementLine[];
      locked?: boolean;
      detail?: string;
    }) => {
      if (busy) return;
      setBusy(true);
      try {
        const data = await savePlacementBeat({ beatId, ...patch });
        await refresh();
        if (patch.locked === true) {
          setMessage(`Locked ${beatId}.`);
        } else if (patch.locked === false) {
          setMessage(`Unlocked ${beatId}.`);
        } else {
          setMessage(`Saved placement on ${beatId}.`);
        }
        if (data.finalRenderReady) {
          setMessage((m) => `${m} All beats locked — Final is ready.`);
        }
        // Refresh live Tier B from saved rows (useEffect also fires on key change).
        void refreshPlacementPreview(beatId, { lines: patch.lines, force: true });
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Could not save placement.");
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh, refreshPlacementPreview],
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
            : status?.outputExists
              ? `${status.beatCount || 0} beats · review below`
              : "Load masterbeater-beats.json (Grok) or Refresh"}
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
          disabled={busy || !placement?.finalRenderReady}
          title={
            placement?.finalRenderReady
              ? "All beats locked — full episode render (coming next)"
              : "Lock every assigned beat before final render"
          }
          onClick={() => {
            setMessage(
              placement?.finalRenderReady
                ? "All beats locked. Full episode render will wire to the engine path next — placement data is ready."
                : `Lock remaining beats (${placement?.unlockedCount ?? "?"} unlocked).`,
            );
          }}
        >
          Final
        </button>
        <span className="workflow-status">
          {!hasVideoProject
            ? "Open a private project"
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

  const hasBeats = Boolean(result && (result.beatCount || beats.length));
  const hasTranscript = transcriptWords.length > 0;

  return (
    <div className="visual-package-workspace">
      {railHost ? createPortal(rail, railHost) : null}
      {!railHost ? <div className="visual-package-rail-fallback">{rail}</div> : null}

      {message ? <p className="visual-package-message">{message}</p> : null}

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
              playheadFrame={playheadFrame}
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
              onPinPlayhead={(frame) => seekAbsoluteFrame(frame, false)}
              onDraftPreview={(lines) => {
                if (!selected) return;
                void refreshPlacementPreview(selected.id, { lines });
              }}
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
                        element.loop = loopBeat;
                      } catch {
                        /* ignore */
                      }
                    }
                  },
                  className: "visual-package-video visual-package-hyperframes-player",
                  src: placementPreviewCompositionUrl(placementPreview.cacheKey),
                  controls: false,
                  ...(loopBeat ? { loop: "" } : {}),
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
            </div>

            {stage3 && selected ? (
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
            ) : null}

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
                  !(status?.reviewVideoExists || stage3LivePreview)
                }
              >
                {playing ? <Pause size={16} /> : <Play size={16} />}
                {playing ? "Pause" : "Play"}
              </button>
              <button
                type="button"
                className="workflow-action"
                onClick={() => {
                  if (!selected) return;
                  if (stage3LivePreview && runtimePlayerRef.current) {
                    stopStage3Preview();
                    try {
                      runtimePlayerRef.current.seek(0);
                    } catch {
                      /* ignore */
                    }
                    setPlayheadFrame(Math.round(compositionRangeStartSec * fps));
                    return;
                  }
                  seekToBeat(selected, false);
                }}
                disabled={!selected}
                title={stage3 ? "Seek this beat preview to the start" : "Reset to beat start"}
              >
                <SkipBack size={16} /> Reset
              </button>
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
              <button
                type="button"
                className={["visual-package-toggle", loopBeat ? "is-on" : ""].join(" ")}
                role="switch"
                aria-checked={loopBeat}
                onClick={() => setLoopBeat((value) => !value)}
                title={stage3 ? "Loop this beat’s live preview clip" : "Loop the selected beat"}
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
                title={
                  stage3
                    ? "Auto-play when stepping to the next beat"
                    : "Play the beat span when you click a card"
                }
                onClick={() => setAutoplayOnSelect((value) => !value)}
              >
                <span className="visual-package-toggle-track" aria-hidden>
                  <span className="visual-package-toggle-thumb" />
                </span>
                Autoplay
              </button>
            </div>

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
              {!hasBeats ? (
                <p className="visual-package-empty">
                  Transcript loaded, but no <code>masterbeater-beats.json</code> yet. Run Masterbeater,
                  then Refresh.
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
                        {item.words.map((word) => {
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
                            item.words.map((word) => {
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
                            })
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
    </div>
  );
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
  playheadFrame,
  busy,
  previewBusy = false,
  hasPlacements,
  allLocked,
  beatIndex,
  beatTotal,
  livePreviewReady,
  onSave,
  onSeekReveal,
  onPinPlayhead,
  onDraftPreview,
}: {
  selected: MasterbeaterBeat | null;
  placement?: PlacementBeat;
  assignment?: AssignmentPick;
  interfaceSpec?: {
    listSlot?: string | null;
    listMax?: number;
    notes?: string;
  };
  beatWords: VisualPackageTranscriptWord[];
  fps: number;
  playheadFrame: number;
  /** Place / Save / Lock in flight — may disable save actions. */
  busy: boolean;
  /** Live composition rebuild — must NOT block typing or frame nudges. */
  previewBusy?: boolean;
  hasPlacements: boolean;
  allLocked: boolean;
  beatIndex: number;
  beatTotal: number;
  livePreviewReady: boolean;
  onSave: (patch: { lines?: PlacementLine[]; locked?: boolean; detail?: string }) => void;
  onSeekReveal: (frame: number) => void;
  onPinPlayhead: (frame: number) => void;
  onDraftPreview: (lines: PlacementLine[]) => void;
}) {
  const [draftLines, setDraftLines] = useState<PlacementLine[]>([]);
  const [armedIndex, setArmedIndex] = useState(0);
  const previewTimer = useRef<number | null>(null);
  const locked = Boolean(placement?.locked);
  /** Only re-sync draft from server when beat/lock/server lines actually change — not object identity. */
  const serverLinesKey = placement
    ? `${placement.beatId}|${placement.locked ? "1" : "0"}|${JSON.stringify(placement.lines || [])}`
    : "";

  useEffect(() => {
    if (!placement) {
      setDraftLines([]);
      setArmedIndex(0);
      return;
    }
    setDraftLines(
      (placement.lines || []).map((line) => ({
        slot: line.slot,
        text: line.text || "",
        revealFrame: line.revealFrame ?? 0,
      })),
    );
    setArmedIndex(0);
    // serverLinesKey captures content; avoid placement.lines identity thrash mid-edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverLinesKey]);

  useEffect(() => {
    return () => {
      if (previewTimer.current != null) window.clearTimeout(previewTimer.current);
    };
  }, []);

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

  const schedulePreview = useCallback(
    (lines: PlacementLine[]) => {
      if (locked) return;
      if (previewTimer.current != null) window.clearTimeout(previewTimer.current);
      previewTimer.current = window.setTimeout(() => {
        onDraftPreview(lines);
      }, 450);
    },
    [locked, onDraftPreview],
  );

  const updateLine = (index: number, patch: Partial<PlacementLine>) => {
    setDraftLines((prev) => {
      const next = prev.map((line, i) => (i === index ? { ...line, ...patch } : line));
      schedulePreview(next);
      return next;
    });
  };

  const nudgeArmed = (delta: number) => {
    if (locked || !armed || armedIndex < 0) return;
    const spanStart = placement?.startFrame ?? 0;
    const spanEnd = (placement?.endFrameExclusive ?? spanStart + 1) - 1;
    const nextFrame = Math.max(spanStart, Math.min(spanEnd, armed.revealFrame + delta));
    updateLine(armedIndex, { revealFrame: nextFrame });
    onSeekReveal(nextFrame);
  };

  const setArmedFrame = (frame: number) => {
    if (locked || !armed || armedIndex < 0) return;
    const spanStart = placement?.startFrame ?? 0;
    const spanEnd = (placement?.endFrameExclusive ?? spanStart + 1) - 1;
    const nextFrame = Math.max(spanStart, Math.min(spanEnd, Math.round(frame)));
    updateLine(armedIndex, { revealFrame: nextFrame });
    onSeekReveal(nextFrame);
  };

  const pinArmedToPlayhead = () => {
    if (locked || !armed) return;
    setArmedFrame(playheadFrame);
    onPinPlayhead(playheadFrame);
  };

  const setRevealFromWord = (word: VisualPackageTranscriptWord) => {
    if (locked || !armed) return;
    const frame =
      word.startFrame != null && Number.isFinite(word.startFrame)
        ? Math.round(word.startFrame)
        : Math.round((word.startSec ?? 0) * fps);
    setArmedFrame(frame);
  };

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
      schedulePreview(next);
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
      schedulePreview(next);
      return next;
    });
  };

  const poster = assignmentPosterUrl(assignment?.posterUrl || null);
  const engineLabel =
    placement?.displayName ||
    placement?.engineId ||
    assignment?.displayName ||
    assignment?.engineId ||
    "—";
  const layoutLabel = assignment?.layoutId || null;
  const positionLabel =
    beatTotal > 0 && beatIndex >= 0
      ? `${beatIndex + 1} of ${beatTotal}`
      : beatTotal > 0
        ? `— of ${beatTotal}`
        : "—";

  const slotLabel = (slot: string, index: number) => {
    if (listSlot && slot.startsWith(`${listSlot}.`)) {
      const n = slot.slice(listSlot.length + 1);
      return `Bullet ${Number(n) + 1}`;
    }
    if (slot === "text" || slot === "title" || slot === "phrase" || slot === "thesis") {
      return "Title";
    }
    if (slot === "label") return "Label";
    if (slot === "detail") return "Detail";
    if (slot === "action") return "Action";
    if (slot === "prompt") return "Prompt";
    return slot || `Line ${index + 1}`;
  };

  return (
    <aside className="visual-package-placement-editor" aria-label="Placement craft panel">
      <header className="visual-package-placement-panel-head">
        <div className="visual-package-placement-panel-title-row">
          <h3 className="visual-package-placement-panel-title">
            Placement
            <span className="visual-package-placement-panel-beat">
              · beat {positionLabel}
            </span>
          </h3>
          <div className="visual-package-assignment-poster-wrap compact">
            {poster ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                className="visual-package-assignment-poster"
                src={poster}
                alt={engineLabel}
              />
            ) : (
              <div className="visual-package-assignment-poster-empty" aria-hidden>
                —
              </div>
            )}
          </div>
        </div>
        {selected && placement ? (
          <div className="visual-package-placement-panel-meta">
            {layoutLabel ? (
              <span className="visual-package-placement-layout-pill">
                {layoutLabel.replace(/-/g, " ")}
              </span>
            ) : null}
            <span className="visual-package-assignment-name">{engineLabel}</span>
            {locked ? (
              <span className="visual-package-assignment-source">Locked</span>
            ) : (
              <span className="visual-package-assignment-source muted">
                {livePreviewReady ? "Editing · live" : "Editing"}
              </span>
            )}
          </div>
        ) : null}
      </header>

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
            {draftLines.length === 0 ? (
              <p className="visual-package-layout-review-hint">
                Motion-only engine — no copy lines. Scrub live preview and Lock when ready.
              </p>
            ) : (
              draftLines.map((line, index) => {
                const isList = Boolean(listSlot && line.slot.startsWith(`${listSlot}.`));
                const isArmed = index === armedIndex;
                return (
                  <div
                    key={`${line.slot}-${index}`}
                    role="listitem"
                    className={[
                      "visual-package-placement-line-row",
                      isArmed ? "is-armed" : "",
                    ].join(" ")}
                    onClick={() => setArmedIndex(index)}
                  >
                    <span className="visual-package-placement-slot" title={line.slot}>
                      {slotLabel(line.slot, index)}
                    </span>
                    <input
                      className="visual-package-placement-text"
                      type="text"
                      value={line.text}
                      disabled={editDisabled}
                      onFocus={() => setArmedIndex(index)}
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
                        setArmedIndex(index);
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
            )}
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

          {/* Hero frame control for the armed line (mockup center control) */}
          <div className="visual-package-placement-frame-hero" aria-label="Reveal frame fine-tune">
            <span className="visual-package-placement-speech-label" style={{ width: "100%", textAlign: "center" }}>
              Reveal timing · {armed ? slotLabel(armed.slot, armedIndex) : "arm a line"}
              {previewBusy ? " · updating live preview…" : ""}
            </span>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={editDisabled || !armed}
              onClick={() => nudgeArmed(-10)}
            >
              ←10
            </button>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={editDisabled || !armed}
              onClick={() => nudgeArmed(-5)}
            >
              ←5
            </button>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={editDisabled || !armed}
              onClick={() => nudgeArmed(-1)}
            >
              ←1
            </button>
            <label className="visual-package-placement-frame-display">
              <span className="visual-package-placement-frame-prefix">f</span>
              <input
                type="number"
                value={armed?.revealFrame ?? ""}
                disabled={editDisabled || !armed}
                onChange={(e) => setArmedFrame(Number(e.target.value) || 0)}
                title="Reveal frame (absolute on locked cut) for the armed line"
              />
            </label>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={editDisabled || !armed}
              onClick={() => nudgeArmed(1)}
            >
              1→
            </button>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={editDisabled || !armed}
              onClick={() => nudgeArmed(5)}
            >
              5→
            </button>
            <button
              type="button"
              className="visual-package-placement-nudge"
              disabled={editDisabled || !armed}
              onClick={() => nudgeArmed(10)}
            >
              10→
            </button>
          </div>

          <div className="visual-package-placement-actions">
            <button
              type="button"
              className="workflow-action emphasized"
              disabled={busy || locked}
              onClick={() => onSave({ lines: draftLines, detail: "edit lines" })}
            >
              Save
            </button>
            {locked ? (
              <button
                type="button"
                className="workflow-action"
                disabled={busy}
                onClick={() => onSave({ locked: false, detail: "unlock" })}
              >
                Unlock
              </button>
            ) : (
              <button
                type="button"
                className="workflow-action visual-package-placement-lock"
                disabled={busy}
                onClick={() =>
                  onSave({ lines: draftLines, locked: true, detail: "lock" })
                }
              >
                Lock
              </button>
            )}
            <button
              type="button"
              className="workflow-action visual-package-placement-pin"
              disabled={editDisabled || !armed}
              title="Set armed line reveal to current playhead"
              onClick={pinArmedToPlayhead}
            >
              ↗ Pin to playhead
            </button>
          </div>

          <div className="visual-package-placement-speech" aria-label="Spoken words in this beat">
            <span className="visual-package-placement-speech-label">
              Spoken in this beat · click sets reveal on armed line
            </span>
            <div className="visual-package-placement-word-chips">
              {beatWords.length === 0 ? (
                <span className="muted" style={{ fontSize: 12 }}>
                  No word timing for this beat.
                </span>
              ) : (
                beatWords.map((word) => {
                  const frame =
                    word.startFrame != null && Number.isFinite(word.startFrame)
                      ? Math.round(word.startFrame)
                      : Math.round((word.startSec ?? 0) * fps);
                  const isReveal =
                    armed != null && Math.abs((armed.revealFrame || 0) - frame) <= 1;
                  return (
                    <button
                      key={word.id}
                      type="button"
                      className={[
                        "visual-package-placement-word-chip",
                        isReveal ? "is-reveal" : "",
                      ].join(" ")}
                      disabled={editDisabled || !armed}
                      title={`Set reveal · f ${frame} · ${frameToClock(frame, fps)}`}
                      onClick={() => setRevealFromWord(word)}
                    >
                      {word.text}
                    </button>
                  );
                })
              )}
            </div>
          </div>

          <p className="visual-package-layout-review-hint">
            {allLocked
              ? "All assigned beats locked — Final is ready in the rail."
              : "Click Title or a Bullet to arm it · type to edit · f #### shows its reveal · nudge ±1/5/10 or click a spoken word · Pin to playhead · Save."}
          </p>
        </>
      )}
    </aside>
  );
}
