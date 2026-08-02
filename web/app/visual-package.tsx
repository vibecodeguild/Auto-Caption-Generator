"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronUp, Loader2, Pause, Play, RefreshCw, SkipBack } from "lucide-react";
import {
  getVisualPackageStatus,
  runMasterbeater,
  visualPackageSourceVideoUrl,
  type MasterbeaterBeat,
  type MasterbeaterResult,
  type VisualPackageStatus,
} from "../lib/api";

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

export default function VisualPackageWorkspace({
  hasVideoProject,
  projectName,
}: {
  hasVideoProject: boolean;
  projectName?: string | null;
}) {
  const [activeStage, setActiveStage] = useState(1);
  const [status, setStatus] = useState<VisualPackageStatus | null>(null);
  const [result, setResult] = useState<MasterbeaterResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [railHost, setRailHost] = useState<HTMLElement | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loopBeat, setLoopBeat] = useState(true);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const fps = result?.fps || status?.fps || 30;
  const videoUrl = hasVideoProject ? visualPackageSourceVideoUrl() : null;

  const refresh = useCallback(async () => {
    if (!hasVideoProject) {
      setStatus(null);
      setResult(null);
      return;
    }
    const data = await getVisualPackageStatus();
    setStatus(data);
    setResult(data.result);
  }, [hasVideoProject]);

  useEffect(() => {
    void refresh().catch((error: Error) => {
      setMessage(error.message || "Could not load Visual Package status.");
      setStatus(null);
      setResult(null);
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

  const beats = result?.beats ?? [];
  const filtered = useMemo(() => {
    if (typeFilter === "all") return beats;
    return beats.filter((beat) => beat.beatType === typeFilter);
  }, [beats, typeFilter]);

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const beat of beats) {
      counts.set(beat.beatType, (counts.get(beat.beatType) ?? 0) + 1);
    }
    return counts;
  }, [beats]);

  const selected = useMemo(
    () => beats.find((beat) => beat.id === selectedId) ?? null,
    [beats, selectedId]
  );

  // Auto-select first beat when results load
  useEffect(() => {
    if (!selectedId && filtered.length > 0) {
      setSelectedId(filtered[0].id);
    }
    if (selectedId && !beats.some((b) => b.id === selectedId) && filtered.length > 0) {
      setSelectedId(filtered[0].id);
    }
  }, [beats, filtered, selectedId]);

  const seekToBeat = useCallback(
    (beat: MasterbeaterBeat, autoplay: boolean) => {
      const video = videoRef.current;
      if (!video) return;
      const start = beatStartSec(beat, fps);
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
    [fps]
  );

  const selectBeat = useCallback(
    (beat: MasterbeaterBeat, autoplay = true) => {
      setSelectedId(beat.id);
      seekToBeat(beat, autoplay);
      // Scroll card into view
      const node = listRef.current?.querySelector(`[data-beat-id="${beat.id}"]`);
      node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
    [seekToBeat]
  );

  const onTimeUpdate = () => {
    const video = videoRef.current;
    if (!video || !selected) return;
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
    const video = videoRef.current;
    if (!video || !selected) return;
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

  const stepBeat = (delta: number) => {
    if (!filtered.length) return;
    const index = Math.max(
      0,
      filtered.findIndex((b) => b.id === selectedId)
    );
    const next = filtered[Math.min(filtered.length - 1, Math.max(0, index + delta))];
    if (next) selectBeat(next, true);
  };

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
          title="Experimental in-app Grok CLI run"
        >
          {busy ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
          {busy ? "Running…" : "API run"}
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
        <span className="workflow-stage-label">Graphic pass</span>
        <span className="workflow-status">Next — assign golden graphics</span>
      </PackageWorkflowStage>
      <PackageWorkflowStage stage={3} activeStage={activeStage} setActiveStage={setActiveStage}>
        <span className="workflow-stage-label">Build</span>
        <span className="workflow-status">Later stage</span>
      </PackageWorkflowStage>
    </nav>
  );

  if (!hasVideoProject) {
    return (
      <div className="visual-package-workspace">
        {railHost ? createPortal(rail, railHost) : null}
        <header className="visual-package-hero">
          <div>
            <span className="eyebrow">Visual Package</span>
            <h2>Open a private video project</h2>
            <p>Review Masterbeater beats against the locked cut.</p>
          </div>
        </header>
      </div>
    );
  }

  return (
    <div className="visual-package-workspace">
      {railHost ? createPortal(rail, railHost) : null}
      {!railHost ? <div className="visual-package-rail-fallback">{rail}</div> : null}

      <header className="visual-package-hero">
        <div>
          <span className="eyebrow">Visual Package · Stage 1 review</span>
          <h2>{projectName || "Active project"}</h2>
          <p>Select a beat to inspect exact words, frames, and play that section of the cut.</p>
        </div>
        <div className="visual-package-meta">
          <span className={status?.transcriptExists ? "pill ok" : "pill warn"}>
            {status?.transcriptExists ? "Transcript ready" : "Transcript missing"}
          </span>
          <span className={status?.reviewVideoExists ? "pill ok" : "pill warn"}>
            {status?.reviewVideoExists
              ? `Video: ${status.reviewVideoKind || "source"}`
              : "Review video missing"}
          </span>
          <span className={status?.outputExists ? "pill ok" : "pill muted"}>
            {status?.outputExists ? `${status.beatCount || 0} beats` : "No beats file"}
          </span>
        </div>
      </header>

      {message ? <p className="visual-package-message">{message}</p> : null}

      {activeStage !== 1 ? (
        <section className="visual-package-stage-body">
          <div className="visual-package-empty-state">
            <h3>Stage {activeStage} not built yet</h3>
            <p>Finish reviewing Masterbeater beats first.</p>
          </div>
        </section>
      ) : !result || !(result.beatCount || beats.length) ? (
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
        <section className="visual-package-review">
          <div className="visual-package-player-panel">
            <div className="visual-package-player-frame">
              {status?.reviewVideoExists && videoUrl ? (
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
            </div>

            <div className="visual-package-player-controls">
              <button type="button" className="workflow-action" onClick={() => stepBeat(-1)} disabled={!filtered.length}>
                <ChevronUp size={16} /> Prev
              </button>
              <button
                type="button"
                className="workflow-action emphasized"
                onClick={togglePlay}
                disabled={!selected || !status?.reviewVideoExists}
              >
                {playing ? <Pause size={16} /> : <Play size={16} />}
                {playing ? "Pause" : "Play beat"}
              </button>
              <button
                type="button"
                className="workflow-action"
                onClick={() => selected && seekToBeat(selected, false)}
                disabled={!selected}
              >
                <SkipBack size={16} /> Reset
              </button>
              <button type="button" className="workflow-action" onClick={() => stepBeat(1)} disabled={!filtered.length}>
                Next <ChevronDown size={16} />
              </button>
              <label className="visual-package-loop">
                <input
                  type="checkbox"
                  checked={loopBeat}
                  onChange={(event) => setLoopBeat(event.target.checked)}
                />
                Loop beat
              </label>
            </div>

            {selected ? (
              <div className="visual-package-selection">
                <div className="visual-package-selection-header">
                  <span className={`beat-type-badge type-${selected.beatType}`}>{selected.beatType}</span>
                  <span className="beat-id">{selected.id}</span>
                </div>
                <dl className="visual-package-facts">
                  <div>
                    <dt>Frames</dt>
                    <dd>
                      {selected.startFrame != null && endFrameExclusive(selected) != null
                        ? `${selected.startFrame} → ${endFrameExclusive(selected)} (end exclusive)`
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Clock (info)</dt>
                    <dd>
                      {formatClock(beatStartSec(selected, fps))} – {formatClock(beatEndSec(selected, fps))}
                      {fps ? ` · ${fps} fps` : ""}
                    </dd>
                  </div>
                  <div>
                    <dt>Word IDs</dt>
                    <dd>
                      {selected.startWordId && selected.endWordId
                        ? `${selected.startWordId} → ${selected.endWordId}`
                        : "—"}
                      {selected.wordIds?.length ? ` · ${selected.wordIds.length} words` : ""}
                    </dd>
                  </div>
                </dl>
                <div className="visual-package-words-block">
                  <h3>Exact words</h3>
                  <p className="visual-package-words-text">
                    {selected.wordsText || selected.span || selected.label || "—"}
                  </p>
                </div>
                {selected.label &&
                selected.wordsText &&
                selected.label !== selected.wordsText ? (
                  <div className="visual-package-words-block secondary">
                    <h3>Label</h3>
                    <p>{selected.label}</p>
                  </div>
                ) : null}
                <div className="visual-package-words-block secondary">
                  <h3>Why this type</h3>
                  <p>{selected.rationale}</p>
                </div>
              </div>
            ) : (
              <p className="visual-package-empty">Select a beat from the list.</p>
            )}
          </div>

          <div className="visual-package-list-panel">
            <div className="visual-package-summary compact">
              <div>
                <strong>{result.beatCount ?? beats.length}</strong>
                <span>beats</span>
              </div>
              <div>
                <strong>{result.mode || "—"}</strong>
                <span>mode</span>
              </div>
              <div>
                <strong>{result.timingAuthority || "frames"}</strong>
                <span>timing</span>
              </div>
              <div className="visual-package-filters">
                <label>
                  Filter
                  <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                    <option value="all">All types</option>
                    {BEAT_TYPE_ORDER.filter((type) => typeCounts.has(type)).map((type) => (
                      <option key={type} value={type}>
                        {type} ({typeCounts.get(type)})
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            {(result.gaps || []).length > 0 ? (
              <details className="visual-package-gaps">
                <summary>Gaps ({result.gaps?.length})</summary>
                <ul>
                  {(result.gaps || []).map((gap, index) => (
                    <li key={`gap-${index}`}>{gap}</li>
                  ))}
                </ul>
              </details>
            ) : null}

            <div className="visual-package-beat-list" role="listbox" aria-label="Beats" ref={listRef}>
              {filtered.map((beat, index) => {
                const words = beat.wordsText || beat.span || beat.label || "—";
                const endEx = endFrameExclusive(beat);
                const active = beat.id === selectedId;
                return (
                  <button
                    key={beat.id}
                    type="button"
                    role="option"
                    aria-selected={active}
                    data-beat-id={beat.id}
                    className={["visual-package-beat-card", "selectable", active ? "is-selected" : ""].join(" ")}
                    onClick={() => selectBeat(beat, true)}
                  >
                    <header>
                      <span className="beat-index">{index + 1}</span>
                      <span className={`beat-type-badge type-${beat.beatType}`}>{beat.beatType}</span>
                      {beat.startFrame != null && endEx != null ? (
                        <span className="beat-frames">
                          f {beat.startFrame}–{endEx}
                        </span>
                      ) : null}
                      <span className="beat-time">
                        {formatClock(beatStartSec(beat, fps))}–{formatClock(beatEndSec(beat, fps))}
                      </span>
                    </header>
                    <p className="beat-span">{words}</p>
                  </button>
                );
              })}
            </div>
            {filtered.length === 0 ? <p className="visual-package-empty">No beats match this filter.</p> : null}
          </div>
        </section>
      )}
    </div>
  );
}
