"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";

export function formatFrameTimecode(frame: number, fps: number) {
  const roundedFps = Math.max(1, Math.round(fps));
  const safeFrame = Math.max(0, frame);
  const frames = safeFrame % roundedFps;
  const totalSeconds = Math.floor(safeFrame / roundedFps);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  return [hours, minutes, seconds, frames].map((value) => String(value).padStart(2, "0")).join(":");
}

export function CutFrameCard({
  title,
  frame,
  fps,
  minFrame,
  maxFrame,
  onNudge,
  resolveDelta,
}: {
  title: string;
  frame: number;
  fps: number;
  /** Kept for call-site compatibility; adjustment chrome removed. */
  adjustment?: number;
  /** Kept for call-site compatibility; Whisper/source label chrome removed. */
  whisperFrame?: number;
  /** Kept for call-site compatibility; assisted-suggestion chrome removed. */
  suggestedFrame?: number;
  minFrame?: number;
  maxFrame?: number;
  onNudge: (delta: number) => void;
  /** Override linear min/max (e.g. skip illegal insert T frames). */
  resolveDelta?: (requested: number) => number;
  /** Kept for call-site compatibility; Whisper/source label chrome removed. */
  sourceLabel?: string;
}) {
  const allowedDelta = (requested: number) => {
    if (resolveDelta) return resolveDelta(requested);
    const requestedFrame = frame + requested;
    const boundedFrame = Math.min(
      maxFrame ?? Number.POSITIVE_INFINITY,
      Math.max(minFrame ?? 0, requestedFrame),
    );
    return boundedFrame - frame;
  };
  const nudge = (requested: number) => {
    const delta = allowedDelta(requested);
    if (delta !== 0) onNudge(delta);
  };
  const buttonTitle = (requested: number) => {
    const delta = allowedDelta(requested);
    if (delta === 0) {
      return requested > 0 ? "At the next IN-frame safety limit" : "At the earliest legal frame";
    }
    if (delta !== requested) {
      return `Move ${Math.abs(delta)} frame${Math.abs(delta) === 1 ? "" : "s"} to the safety limit`;
    }
    return `Move ${Math.abs(delta)} frame${Math.abs(delta) === 1 ? "" : "s"}`;
  };
  return (
    <div className="cut-frame-card">
      <div className="cut-frame-header">
        <span className="cut-frame-title">{title}</span>
        <span className="cut-frame-timecode">{formatFrameTimecode(frame, fps)}</span>
        <span className="cut-frame-number">{frame.toLocaleString()}</span>
      </div>
      {(frame === minFrame || frame === maxFrame) && (
        <div className="cut-boundary-limit">Safety boundary reached at frame {frame.toLocaleString()}</div>
      )}
      <div className="nudge-buttons" aria-label={`${title} nudges`}>
        <button disabled={allowedDelta(-10) === 0} title={buttonTitle(-10)} onClick={() => nudge(-10)}>
          <ArrowLeft size={13} /> 10
        </button>
        <button disabled={allowedDelta(-5) === 0} title={buttonTitle(-5)} onClick={() => nudge(-5)}>
          <ArrowLeft size={13} /> 5
        </button>
        <button disabled={allowedDelta(-1) === 0} title={buttonTitle(-1)} onClick={() => nudge(-1)}>
          <ArrowLeft size={13} /> 1
        </button>
        <button disabled={allowedDelta(1) === 0} title={buttonTitle(1)} onClick={() => nudge(1)}>
          1 <ArrowRight size={13} />
        </button>
        <button disabled={allowedDelta(5) === 0} title={buttonTitle(5)} onClick={() => nudge(5)}>
          5 <ArrowRight size={13} />
        </button>
        <button disabled={allowedDelta(10) === 0} title={buttonTitle(10)} onClick={() => nudge(10)}>
          10 <ArrowRight size={13} />
        </button>
      </div>
    </div>
  );
}
