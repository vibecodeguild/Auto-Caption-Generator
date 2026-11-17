"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, FileUp, Play, Plus, RefreshCw, X } from "lucide-react";
import { captionOptions, type CaptionOptionsResponse } from "../lib/api";
import {
  type Short,
  type ShortJob,
  type ShortSettings,
  type ShortsState,
  type PostingDrafts,
  loadShorts,
  candidateBrief,
  importShorts,
  createShort,
  saveShort,
  startShortJob,
  getShortJob,
  cancelShortJob,
  shortPostingBrief,
  importShortPosting,
  shortPostingPackage,
  shortsSourceUrl,
  shortMediaUrl,
  downloadShortsJson,
} from "../lib/shorts-api";
import { playMediaAt } from "../lib/media-preview";
import "./shorts.css";

export const SHORTS_RAIL_HOST_ID = "shorts-rail-host";
type Step = "edit" | "captions" | "posting" | "export";
type Boundary = { index: number; edge: "in" | "out" };
const running = (job: ShortJob | null) =>
  job?.status === "running" || job?.status === "canceling";
const clock = (sec: number) =>
  `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
function frameClock(frame: number, fps: number) {
  const whole = Math.floor(frame / fps);
  return `${String(Math.floor(whole / 3600)).padStart(2, "0")}:${String(Math.floor(whole / 60) % 60).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}:${String(Math.round(frame - Math.floor(whole * fps))).padStart(2, "0")}`;
}

export default function ShortsWorkspace({
  hasVideoProject,
}: {
  hasVideoProject: boolean;
}) {
  const [data, setData] = useState<ShortsState | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [step, setStep] = useState<Step>("edit");
  const [status, setStatus] = useState("Loading Shorts…");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [job, setJob] = useState<ShortJob | null>(null);
  const [title, setTitle] = useState("");
  const [settings, setSettings] = useState<ShortSettings | null>(null);
  const [options, setOptions] = useState<CaptionOptionsResponse | null>(null);
  const [styleName, setStyleName] = useState("");
  const [posting, setPosting] = useState<PostingDrafts>({});
  const [platform, setPlatform] = useState("YouTube");
  const [boundary, setBoundary] = useState<Boundary>({ index: 0, edge: "in" });
  const [previewTime, setPreviewTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [sourcePreview, setSourcePreview] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newIn, setNewIn] = useState(0);
  const [newOut, setNewOut] = useState(0);
  const [railHost, setRailHost] = useState<HTMLElement | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const sourceVideo = useRef<HTMLVideoElement>(null);
  const createDialog = useRef<HTMLElement>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const postingInput = useRef<HTMLInputElement>(null);
  const auditionStop = useRef<number | null>(null);
  const auditionNext = useRef<{ seek: number; stop: number } | null>(null);
  const refreshRequest = useRef(0);
  const short = data?.shorts.find((s) => s.id === selectedId) ?? null;
  const busy = saving || (job?.shortId === selectedId && running(job));
  const activeBoundary = short?.sections[boundary.index] ?? short?.sections[0];
  const fps = short?.source.fps ?? data?.source?.fps ?? 30;
  const boundaryFrame = activeBoundary
    ? boundary.edge === "in"
      ? activeBoundary.startFrame
      : activeBoundary.endFrameExclusive - 1
    : 0;

  const accept = useCallback((state: ShortsState) => {
    setData(state);
    setStatus(
      state.ready
        ? state.shorts.length
          ? "Shorts loaded."
          : "Ready to create your first short."
        : (state.reason ?? "Open a private video project to create Shorts."),
    );
    setSelectedId((current) =>
      state.shorts.some((s) => s.id === current)
        ? current
        : (state.shorts[0]?.id ?? ""),
    );
  }, []);
  const refresh = useCallback(async () => {
    const request = ++refreshRequest.current;
    try {
      const state = await loadShorts();
      if (request === refreshRequest.current) accept(state);
    } catch (e) {
      if (request === refreshRequest.current) setError((e as Error).message);
    }
  }, [accept]);

  useEffect(() => {
    void refresh();
    void captionOptions()
      .then(setOptions)
      .catch((e) => setError(e.message));
    setRailHost(document.getElementById(SHORTS_RAIL_HOST_ID));
    return () => {
      refreshRequest.current++;
    };
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setJob(null);
      return;
    }
    let alive = true,
      completed = "";
    const poll = async () => {
      try {
        const result = await getShortJob(selectedId);
        if (!alive) return;
        setJob(result.job);
        if (result.job && !running(result.job) && completed !== result.job.id) {
          completed = result.job.id;
          setStatus(result.job.message);
          if (result.job.status === "failed")
            setError(result.job.error ?? result.job.message);
          await refresh();
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 1500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [selectedId, refresh]);

  useEffect(() => {
    if (!short) return;
    setTitle(short.title);
    setSettings(short.settings);
    setPosting(short.posting);
  }, [short?.id, short?.revision]); // Saved decisions are authoritative after each operation.

  useEffect(() => {
    setBoundary({ index: 0, edge: "in" });
    setPreviewTime(0);
    setSourcePreview(false);
    auditionStop.current = null;
    auditionNext.current = null;
    if (video.current) {
      video.current.pause();
      video.current.onloadedmetadata = null;
    }
    setStyleName("");
    setError("");
  }, [selectedId]);

  useEffect(() => {
    let animation = 0;
    const tick = () => {
      const player = video.current;
      if (player && !player.paused && !player.seeking) {
        setPreviewTime(player.currentTime);
        if (
          auditionStop.current !== null &&
          player.currentTime + 0.5 / fps >= auditionStop.current
        ) {
          const next = auditionNext.current;
          if (next) {
            auditionNext.current = null;
            auditionStop.current = next.stop;
            player.currentTime = next.seek;
            void player.play().catch((e) => setError(e.message));
          } else {
            player.pause();
            player.currentTime = Math.max(0, auditionStop.current - 1 / fps);
            auditionStop.current = null;
          }
        }
      }
      animation = requestAnimationFrame(tick);
    };
    animation = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animation);
  }, [fps, selectedId]);

  useEffect(() => {
    if (!showCreate) return;
    const previous = document.activeElement as HTMLElement | null;
    createDialog.current?.querySelector<HTMLInputElement>("input")?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        sourceVideo.current?.pause();
        setShowCreate(false);
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(
        createDialog.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input:not(:disabled),video[controls]",
        ) ?? [],
      );
      const first = controls[0],
        last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      previous?.focus();
    };
  }, [showCreate]);

  async function action<T>(
    work: () => Promise<T>,
    success?: (value: T) => void,
  ) {
    setSaving(true);
    setError("");
    try {
      const value = await work();
      success?.(value);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const save = (changes: Record<string, unknown>) =>
    short &&
    action(
      () => saveShort(short.id, { revision: short.revision, ...changes }),
      (result) => {
        accept(result);
        setStatus("Short saved.");
      },
    );
  const start = (operation: "assemble" | "captions" | "export") =>
    short &&
    action(
      () => startShortJob(short.id, operation),
      (result) => {
        setJob(result);
        setStatus(result.message);
        setSourcePreview(false);
      },
    );

  async function importFile(file: File | undefined, kind: "plan" | "posting") {
    if (!file) return;
    if (file.size > 2_000_000) {
      setError("Choose a Shorts JSON file smaller than 2 MB.");
      return;
    }
    await action(
      async () => {
        const plan: unknown = JSON.parse(await file.text());
        return kind === "posting" && short
          ? importShortPosting(short.id, plan)
          : importShorts(plan);
      },
      (result) => {
        accept(result);
        setStatus(
          kind === "plan"
            ? "Candidate plan imported. Review each short."
            : "Posting drafts imported. Review before posting.",
        );
      },
    );
  }

  function nudge(delta: number) {
    if (!short || !activeBoundary || !data?.durationFrames) return;
    const sections = short.sections.map((s) => ({ ...s }));
    const section = sections[boundary.index];
    if (boundary.edge === "in")
      section.startFrame = Math.max(
        0,
        Math.min(section.endFrameExclusive - 1, section.startFrame + delta),
      );
    else
      section.endFrameExclusive = Math.max(
        section.startFrame + 1,
        Math.min(data.durationFrames, section.endFrameExclusive + delta),
      );
    seekSourceFrame(
      boundary.edge === "in"
        ? section.startFrame
        : section.endFrameExclusive - 1,
    );
    void save({ sections });
  }

  function withSourcePlayer(ready: (player: HTMLVideoElement) => void) {
    const player = video.current;
    if (!player) return;
    player.pause();
    setSourcePreview(true);
    auditionStop.current = null;
    auditionNext.current = null;
    if (
      player.currentSrc !== shortsSourceUrl(data?.source) ||
      player.readyState < 1
    ) {
      player.onloadedmetadata = () => {
        player.onloadedmetadata = null;
        ready(player);
      };
    } else ready(player);
  }

  function seekSourceFrame(frame: number) {
    withSourcePlayer((player) => {
      player.currentTime = frame / fps;
      setPreviewTime(frame / fps);
    });
  }

  async function playAt(seconds: number) {
    if (!video.current) return;
    try {
      await playMediaAt(video.current, seconds);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function audition(duration: number) {
    if (!short || !activeBoundary) return;
    const index = boundary.index;
    // A join is an OUT followed by the next section IN (or an IN preceded by OUT).
    const joinLeft = boundary.edge === "out" ? index : index - 1;
    const player = video.current;
    if (!player) return;
    const begin = async () => {
      if (joinLeft >= 0 && joinLeft < short.sections.length - 1) {
        const left = short.sections[joinLeft],
          right = short.sections[joinLeft + 1];
        auditionStop.current = left.endFrameExclusive / fps;
        auditionNext.current = {
          seek: right.startFrame / fps,
          stop: Math.min(
            right.endFrameExclusive / fps,
            right.startFrame / fps + duration,
          ),
        };
        await playAt(
          Math.max(
            left.startFrame / fps,
            left.endFrameExclusive / fps - duration,
          ),
        );
      } else {
        const start = activeBoundary.startFrame / fps,
          end = activeBoundary.endFrameExclusive / fps;
        auditionStop.current =
          boundary.edge === "in" ? Math.min(end, start + duration) : end;
        auditionNext.current = null;
        await playAt(
          boundary.edge === "in" ? start : Math.max(start, end - duration),
        );
      }
    };
    withSourcePlayer(() => void begin());
  }

  const rail = (
    <nav className="shorts-steps" aria-label="Shorts workflow">
      <strong>Shorts</strong>
      {(["edit", "captions", "posting", "export"] as Step[]).map((s, i) => (
        <button
          type="button"
          key={s}
          className={step === s ? "selected" : ""}
          onClick={() => setStep(s)}
        >
          {i + 1} {s[0].toUpperCase() + s.slice(1)}
        </button>
      ))}
      <button
        type="button"
        onClick={() => void refresh()}
        disabled={busy}
        aria-label="Refresh Shorts"
      >
        <RefreshCw size={15} />
      </button>
    </nav>
  );
  const currentGroup =
    !sourcePreview && short?.captionCurrent
      ? short.groups.find((g) => g.start <= previewTime && previewTime < g.end)
      : null;
  const activeWordIndex = currentGroup
    ? currentGroup.words.reduce(
        (active, word, index) => (word.start <= previewTime ? index : active),
        -1,
      )
    : -1;
  const activeStyle = short?.settings.style;
  const readySource = Boolean(data?.ready && data.source);
  const previewUrl =
    sourcePreview || !short?.assemblyCurrent
      ? shortsSourceUrl(data?.source)
      : shortMediaUrl(short, "assembly");
  const layout = data?.layout;

  return (
    <section className="shorts-workspace">
      {railHost ? createPortal(rail, railHost) : rail}
      <input
        ref={importInput}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={(e) => {
          void importFile(e.target.files?.[0], "plan");
          e.target.value = "";
        }}
      />
      <input
        ref={postingInput}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={(e) => {
          void importFile(e.target.files?.[0], "posting");
          e.target.value = "";
        }}
      />
      {!hasVideoProject || !data?.ready ? (
        <div className="shorts-empty">
          <h2>Shorts</h2>
          <p>
            {!hasVideoProject
              ? "Open a private video project to create Shorts."
              : (data?.reason ?? "Checking the locked cut…")}
          </p>
          <p>
            Use a talking-head locked cut and its matching final transcript.
          </p>
          <button onClick={() => void refresh()}>Check readiness</button>
        </div>
      ) : (
        <div className="shorts-columns">
          <aside className="shorts-library">
            <h2>Your shorts</h2>
            {data.shorts.map((s) => (
              <button
                type="button"
                key={s.id}
                className={`shorts-candidate ${s.id === selectedId ? "selected" : ""}`}
                onClick={() => setSelectedId(s.id)}
              >
                <strong>{s.title}</strong>
                <span>
                  {clock(Math.round(s.durationSec))} · {s.sections.length}{" "}
                  {s.sections.length === 1 ? "section" : "sections"}
                </span>
                <small>
                  {!s.sourceCurrent
                    ? "Source changed"
                    : s.deliveryCurrent
                      ? "Exported"
                      : s.captionCurrent
                        ? "Captions ready"
                        : "Needs captions"}
                </small>
              </button>
            ))}
            <div className="shorts-actions">
              <button
                onClick={() => {
                  video.current?.pause();
                  setShowCreate(true);
                }}
                disabled={busy}
              >
                <Plus size={14} /> New short
              </button>
              <button
                onClick={() => importInput.current?.click()}
                disabled={busy}
              >
                <FileUp size={14} /> Import plan
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void action(candidateBrief, (v) => {
                    downloadShortsJson(v, "shorts-candidate-brief.json");
                    setStatus(
                      "Brief downloaded. Give it to your agent to select candidates, then import the returned plan.",
                    );
                  })
                }
              >
                <Download size={14} /> Candidate brief
              </button>
            </div>
            <p className="shorts-note">
              The candidate brief contains your private final transcript. Keep
              it with your private project.
            </p>
            {short && (
              <>
                <p className="shorts-note">{short.rationale}</p>
                {short.concerns && (
                  <p className="shorts-warning">{short.concerns}</p>
                )}
                {short.warnings.map((w) => (
                  <p className="shorts-warning" key={w}>
                    {w}
                  </p>
                ))}
              </>
            )}
          </aside>
          {short ? (
            <>
              <section className="shorts-preview">
                <div className="shorts-preview-label">
                  <span>
                    {sourcePreview || !short.assemblyCurrent
                      ? "Source boundary review"
                      : "Assembled short"}
                  </span>
                  <span>9:16 · Before graphics</span>
                </div>
                <div
                  className="shorts-canvas"
                  style={{ containerType: "inline-size" }}
                >
                  <div
                    className="shorts-title"
                    style={{
                      top: `${(layout?.titleY ?? 250) / 19.2}%`,
                      fontSize: `${(layout?.titleSize ?? 80) / 10.8}cqw`,
                      fontFamily: layout?.titleFont ?? "Inter",
                    }}
                  >
                    {short.titleLines.map((line, i) => (
                      <span key={i}>{line}</span>
                    ))}
                  </div>
                  <div
                    className="shorts-picture"
                    style={{
                      top: `${(layout?.videoY ?? 500) / 19.2}%`,
                      height: `${(layout?.videoHeight ?? 608) / 19.2}%`,
                    }}
                  >
                    <video
                      ref={video}
                      src={previewUrl}
                      preload="metadata"
                      playsInline
                      onPlay={() => setIsPlaying(true)}
                      onPause={() => setIsPlaying(false)}
                      onLoadedData={(e) =>
                        setPreviewTime(e.currentTarget.currentTime)
                      }
                      onTimeUpdate={(e) => {
                        const player = e.currentTarget;
                        setPreviewTime(player.currentTime);
                      }}
                      onError={() =>
                        setError(
                          "Video could not load. Check that the source or assembled short is current.",
                        )
                      }
                    />
                  </div>
                  {currentGroup && activeStyle && (
                    <div
                      className="shorts-caption-overlay"
                      style={{
                        top: `${(layout?.captionY ?? 1200) / 19.2}%`,
                        fontFamily: activeStyle.font_family,
                        fontSize: `${activeStyle.main_font_size / 10.8}cqw`,
                        color: activeStyle.main_color,
                        fontWeight: activeStyle.bold ? 700 : 400,
                        WebkitTextStroke: activeStyle.outline_enabled
                          ? `${activeStyle.outline_width / 10.8}cqw ${activeStyle.outline_color}`
                          : undefined,
                        paintOrder: "stroke fill",
                        textShadow: activeStyle.shadow_enabled
                          ? `${activeStyle.shadow_depth / 10.8}cqw ${activeStyle.shadow_depth / 10.8}cqw ${activeStyle.shadow_depth / 10.8}cqw ${activeStyle.shadow_color}`
                          : undefined,
                      }}
                    >
                      {currentGroup.words.map((word, i) => (
                        <span
                          key={i}
                          style={
                            i === activeWordIndex
                              ? {
                                  color: activeStyle.active_color,
                                  fontWeight: activeStyle.active_bold
                                    ? 700
                                    : 400,
                                  fontSize: `${activeStyle.active_font_size / 10.8}cqw`,
                                }
                              : undefined
                          }
                        >
                          {word.text}{" "}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="shorts-playback">
                  <button
                    disabled={!short.sourceCurrent}
                    onClick={() => {
                      auditionStop.current = null;
                      auditionNext.current = null;
                      if (video.current?.paused)
                        void playAt(video.current.currentTime);
                      else video.current?.pause();
                    }}
                  >
                    <Play size={15} /> {isPlaying ? "Pause" : "Play"}
                  </button>
                  <span>
                    {clock(previewTime)} /{" "}
                    {clock(
                      sourcePreview || !short.assemblyCurrent
                        ? (data.durationSec ?? 0)
                        : short.durationSec,
                    )}
                  </span>
                </div>
                <input
                  aria-label="Short preview playhead"
                  type="range"
                  min="0"
                  step={1 / fps}
                  max={
                    sourcePreview || !short.assemblyCurrent
                      ? (data.durationSec ?? 0)
                      : short.durationSec
                  }
                  value={Math.min(
                    previewTime,
                    sourcePreview || !short.assemblyCurrent
                      ? (data.durationSec ?? 0)
                      : short.durationSec,
                  )}
                  onChange={(e) => {
                    if (video.current) {
                      video.current.pause();
                      auditionStop.current = null;
                      auditionNext.current = null;
                      video.current.currentTime = Number(e.target.value);
                      setPreviewTime(Number(e.target.value));
                    }
                  }}
                />
                <div className="shorts-actions">
                  <button
                    disabled={busy || !short.sourceCurrent}
                    onClick={() => void start("assemble")}
                  >
                    {short.assemblyCurrent
                      ? "Review assembled preview"
                      : "Build assembled preview"}
                  </button>
                  {short.assemblyCurrent && (
                    <button
                      onClick={() => {
                        video.current?.pause();
                        setSourcePreview(false);
                        auditionStop.current = null;
                        auditionNext.current = null;
                      }}
                    >
                      Show assembled short
                    </button>
                  )}
                </div>
                {!short.captionCurrent && (
                  <p className="shorts-note">
                    {short.caption
                      ? "Captions need regeneration after editing."
                      : "Prepare this short's captions after reviewing its edit."}
                  </p>
                )}
              </section>
              <aside className="shorts-inspector">
                {step === "edit" && (
                  <>
                    <h2>Review the short</h2>
                    <label>
                      On-video title
                      <textarea
                        maxLength={100}
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        disabled={busy}
                      />
                    </label>
                    <button
                      disabled={busy || title === short.title}
                      onClick={() => void save({ title })}
                    >
                      Save title
                    </button>
                    <h3>Source sections</h3>
                    {short.sections.map((section, i) => (
                      <div className="shorts-source-section" key={section.id}>
                        <strong>{i + 1} · Source section</strong>
                        <span>
                          {frameClock(section.startFrame, fps)} →{" "}
                          {frameClock(section.endFrameExclusive - 1, fps)}
                        </span>
                        <div className="shorts-actions">
                          <button
                            className={
                              boundary.index === i && boundary.edge === "in"
                                ? "selected"
                                : ""
                            }
                            onClick={() => {
                              setBoundary({ index: i, edge: "in" });
                              seekSourceFrame(section.startFrame);
                            }}
                          >
                            IN
                          </button>
                          <button
                            className={
                              boundary.index === i && boundary.edge === "out"
                                ? "selected"
                                : ""
                            }
                            onClick={() => {
                              setBoundary({ index: i, edge: "out" });
                              seekSourceFrame(section.endFrameExclusive - 1);
                            }}
                          >
                            OUT
                          </button>
                        </div>
                      </div>
                    ))}
                    <p className="shorts-note">
                      Section {boundary.index + 1} ·{" "}
                      {boundary.edge.toUpperCase()} · source frame{" "}
                      {boundaryFrame}
                    </p>
                    <div className="shorts-frame">
                      {frameClock(boundaryFrame, fps)}
                    </div>
                    <div className="shorts-nudges">
                      {[-10, -5, -1, 1, 5, 10].map((n) => (
                        <button
                          key={n}
                          disabled={
                            busy ||
                            !short.sourceCurrent ||
                            (boundary.edge === "in"
                              ? n < 0
                                ? boundaryFrame <= 0
                                : boundaryFrame >=
                                  (activeBoundary?.endFrameExclusive ?? 0) - 1
                              : n < 0
                                ? boundaryFrame <=
                                  (activeBoundary?.startFrame ?? 0)
                                : boundaryFrame >=
                                  (data.durationFrames ?? 0) - 1)
                          }
                          onClick={() => nudge(n)}
                        >
                          {n > 0 ? "+" : ""}
                          {n} frames
                        </button>
                      ))}
                    </div>
                    <div className="shorts-actions">
                      {[2, 4, 6].map((d) => (
                        <button
                          key={d}
                          disabled={busy || !short.sourceCurrent}
                          onClick={() => void audition(d)}
                        >
                          Audition {d}s
                        </button>
                      ))}
                    </div>
                  </>
                )}
                {step === "captions" && settings && (
                  <>
                    <h2>Captions for this short</h2>
                    <label>
                      Saved style
                      <select
                        value={styleName}
                        disabled={busy}
                        onChange={(e) => {
                          const name = e.target.value;
                          setStyleName(name);
                          const style = options?.styles[name];
                          if (style)
                            setSettings({
                              ...settings,
                              style: {
                                ...style,
                                main_font_size: settings.style.main_font_size,
                                active_font_size:
                                  settings.style.active_font_size,
                                position: "Top",
                                margin_v: 1200,
                              },
                            });
                        }}
                      >
                        <option value="">Current short style</option>
                        {Object.keys(options?.styles ?? {}).map((name) => (
                          <option key={name}>{name}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Font
                      <select
                        value={settings.style.font_family}
                        disabled={busy}
                        onChange={(e) =>
                          setSettings({
                            ...settings,
                            style: {
                              ...settings.style,
                              font_family: e.target.value,
                            },
                          })
                        }
                      >
                        {[
                          ...new Set([
                            settings.style.font_family,
                            "Inter",
                            "Montserrat",
                            "Open Sans",
                            "Anton",
                            "Poppins",
                            "Roboto",
                          ]),
                        ].map((name) => (
                          <option key={name}>{name}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Font size
                      <input
                        type="number"
                        min={24}
                        max={96}
                        value={settings.style.main_font_size}
                        disabled={busy}
                        onChange={(e) =>
                          setSettings({
                            ...settings,
                            style: {
                              ...settings.style,
                              main_font_size: Number(e.target.value),
                              active_font_size: Math.min(
                                110,
                                Number(e.target.value) + 6,
                              ),
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      Active word color
                      <input
                        type="color"
                        value={settings.style.active_color}
                        disabled={busy}
                        onChange={(e) =>
                          setSettings({
                            ...settings,
                            style: {
                              ...settings.style,
                              active_color: e.target.value,
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      Grouping
                      <select
                        value={settings.preset.name}
                        disabled={busy}
                        onChange={(e) => {
                          const preset = Object.values(
                            options?.presets ?? {},
                          ).find((p) => p.name === e.target.value);
                          if (preset) setSettings({ ...settings, preset });
                        }}
                      >
                        {Object.values(options?.presets ?? {}).map((p) => (
                          <option key={p.name}>{p.name}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Transcription model
                      <select
                        value={settings.modelLabel}
                        disabled={busy}
                        onChange={(e) =>
                          setSettings({
                            ...settings,
                            modelLabel: e.target.value,
                          })
                        }
                      >
                        {Object.keys(options?.models ?? {}).map((name) => (
                          <option key={name}>{name}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Compute
                      <select
                        value={settings.computeLabel}
                        disabled={busy}
                        onChange={(e) =>
                          setSettings({
                            ...settings,
                            computeLabel: e.target.value,
                          })
                        }
                      >
                        {Object.keys(options?.compute ?? {}).map((name) => (
                          <option key={name}>{name}</option>
                        ))}
                      </select>
                    </label>
                    <div className="shorts-actions">
                      <button
                        disabled={
                          busy ||
                          JSON.stringify(settings) ===
                            JSON.stringify(short.settings)
                        }
                        onClick={() => void save({ settings })}
                      >
                        Save caption settings
                      </button>
                      <button
                        className="outline-primary"
                        disabled={
                          busy ||
                          !short.sourceCurrent ||
                          JSON.stringify(settings) !==
                            JSON.stringify(short.settings)
                        }
                        onClick={() => void start("captions")}
                      >
                        {short.caption
                          ? "Regenerate captions"
                          : "Prepare captions"}
                      </button>
                    </div>
                    <p className="shorts-note">
                      Transcribes the assembled short's audio. Preview and
                      export share its saved transcript. Save changed settings
                      before preparing captions.
                    </p>
                  </>
                )}
                {step === "posting" && (
                  <>
                    <h2>Posting copy</h2>
                    <label>
                      Destination
                      <select
                        value={platform}
                        onChange={(e) => setPlatform(e.target.value)}
                      >
                        {data.platforms?.map((p) => (
                          <option key={p}>{p}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Platform title
                      <input
                        maxLength={12000}
                        value={posting[platform]?.title ?? ""}
                        disabled={busy}
                        onChange={(e) =>
                          setPosting({
                            ...posting,
                            [platform]: {
                              ...posting[platform],
                              title: e.target.value,
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      Post text
                      <textarea
                        rows={7}
                        maxLength={12000}
                        value={posting[platform]?.text ?? ""}
                        disabled={busy}
                        onChange={(e) =>
                          setPosting({
                            ...posting,
                            [platform]: {
                              ...posting[platform],
                              text: e.target.value,
                            },
                          })
                        }
                      />
                    </label>
                    <div className="shorts-actions">
                      <button
                        disabled={busy}
                        onClick={() => void save({ posting })}
                      >
                        Save drafts
                      </button>
                      <button
                        disabled={busy || !short.captionCurrent}
                        onClick={() =>
                          void save({ posting, reviewPosting: true })
                        }
                      >
                        Mark reviewed
                      </button>
                      <button
                        onClick={() =>
                          void action(
                            async () => {
                              await navigator.clipboard.writeText(
                                [
                                  posting[platform]?.title,
                                  posting[platform]?.text,
                                ]
                                  .filter(Boolean)
                                  .join("\n\n"),
                              );
                            },
                            () => setStatus("Posting text copied."),
                          )
                        }
                      >
                        Copy text
                      </button>
                    </div>
                    <div className="shorts-platform-guidance">
                      <strong>
                        {short.platformGuidance[platform]?.status}
                      </strong>
                      {short.platformGuidance[platform]?.issues.map((issue) => (
                        <p className="shorts-warning" key={issue}>
                          {issue}
                        </p>
                      ))}
                      <p className="shorts-note">
                        {short.platformGuidance[platform]?.note}
                      </p>
                      <a
                        href={short.platformGuidance[platform]?.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Platform guidance
                      </a>
                    </div>
                    <h3>Generate with your agent</h3>
                    <p className="shorts-note">
                      Download the brief, ask your agent for platform-specific
                      drafts, then import its JSON response. No CTA is
                      requested.
                    </p>
                    <div className="shorts-actions">
                      <button
                        disabled={busy || !short.captionCurrent}
                        onClick={() =>
                          void action(
                            () => shortPostingBrief(short.id),
                            (v) =>
                              downloadShortsJson(
                                v,
                                `${short.id}-posting-brief.json`,
                              ),
                          )
                        }
                      >
                        Posting brief
                      </button>
                      <button
                        disabled={busy || !short.captionCurrent}
                        onClick={() => postingInput.current?.click()}
                      >
                        Import copy
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          void action(
                            () => shortPostingPackage(short.id),
                            (v) =>
                              downloadShortsJson(v, `${short.id}-posting.json`),
                          )
                        }
                      >
                        Download drafts
                      </button>
                    </div>
                    <p className="shorts-note">
                      {short.postingCurrent
                        ? "Copy reviewed against this edit."
                        : "Draft copy · Review against the current short."}
                    </p>
                  </>
                )}
                {step === "export" && (
                  <>
                    <h2>Export short</h2>
                    <div className="shorts-source-section">
                      <strong>Vertical video</strong>
                      <span>1080 × 1920 · H.264 MP4</span>
                      <span>
                        Title · complete widescreen picture · captions
                      </span>
                      <span>Black background</span>
                    </div>
                    <p className="shorts-note">
                      {short.captionCurrent
                        ? "Caption transcript matches this edit."
                        : "Prepare current captions before exporting."}
                    </p>
                    <p className="shorts-note">
                      {short.postingCurrent
                        ? "Posting copy reviewed."
                        : "Posting package contains unreviewed drafts. Review before publishing."}
                    </p>
                    <button
                      className="outline-primary"
                      disabled={
                        busy || !short.captionCurrent || !short.sourceCurrent
                      }
                      onClick={() => void start("export")}
                    >
                      Export short
                    </button>
                    {short.deliveryCurrent && (
                      <div className="shorts-result">
                        <a
                          href={shortMediaUrl(short, "delivery")}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open exported video
                        </a>
                        <p>
                          Saved directly in exports/shorts/ with a title-based
                          filename and matching posting files. Repeat exports
                          keep earlier versions with a numbered suffix.
                        </p>
                      </div>
                    )}
                    <p className="shorts-note">
                      The original and all long-form outputs stay intact.
                    </p>
                  </>
                )}
              </aside>
            </>
          ) : (
            <div className="shorts-empty shorts-start">
              <h2>Create your first short</h2>
              <p>
                Choose a source IN and OUT, or give the candidate brief to your
                agent and import its suggestions.
              </p>
              <button
                onClick={() => {
                  video.current?.pause();
                  setShowCreate(true);
                }}
              >
                <Plus size={15} /> New short
              </button>
            </div>
          )}
        </div>
      )}
      <footer className="shorts-status">
        <span role="status" aria-live="polite">
          {job?.shortId === selectedId && running(job) ? job.message : status}
        </span>
        {job?.shortId === selectedId && running(job) && (
          <>
            <progress
              value={job.value}
              max="100"
              aria-label="Shorts operation progress"
            />
            <button
              disabled={job.status === "canceling"}
              onClick={() =>
                void action(() => cancelShortJob(selectedId, job.id), setJob)
              }
            >
              Cancel
            </button>
          </>
        )}
        {job?.shortId === selectedId &&
          job.status === "complete" &&
          short?.deliveryCurrent &&
          job.result?.outputPath && <span>{job.result.outputPath}</span>}
      </footer>
      {error && (
        <div className="shorts-error" role="alert">
          {error}
          <button
            aria-label="Dismiss Shorts error"
            onClick={() => setError("")}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {showCreate && readySource && (
        <div className="shorts-dialog-backdrop">
          <section
            ref={createDialog}
            role="dialog"
            aria-modal="true"
            aria-label="New short"
            className="shorts-dialog"
          >
            <header>
              <h2>New short</h2>
              <button
                aria-label="Close new short"
                onClick={() => {
                  sourceVideo.current?.pause();
                  setShowCreate(false);
                }}
              >
                <X size={17} />
              </button>
            </header>
            <video
              ref={sourceVideo}
              src={shortsSourceUrl(data?.source)}
              controls
              preload="metadata"
            />
            <label>
              On-video title
              <input
                maxLength={100}
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
            </label>
            <div className="shorts-create-range">
              <label>
                Source IN (seconds)
                <input
                  type="number"
                  min={0}
                  step={1 / fps}
                  value={newIn}
                  onChange={(e) => setNewIn(Number(e.target.value))}
                />
              </label>
              <button
                onClick={() =>
                  setNewIn(
                    Math.floor((sourceVideo.current?.currentTime ?? 0) * fps) /
                      fps,
                  )
                }
              >
                Set IN
              </button>
              <label>
                Source OUT (seconds, exclusive)
                <input
                  type="number"
                  min={0}
                  step={1 / fps}
                  value={newOut}
                  onChange={(e) => setNewOut(Number(e.target.value))}
                />
              </label>
              <button
                onClick={() =>
                  setNewOut(
                    Math.min(
                      data?.durationFrames ?? 0,
                      Math.floor(
                        (sourceVideo.current?.currentTime ?? 0) * fps,
                      ) + 1,
                    ) / fps,
                  )
                }
              >
                Set OUT
              </button>
            </div>
            <p className="shorts-note">
              Use the source player to mark a complete thought. Frame
              adjustments are available after creation.
            </p>
            <button
              disabled={busy || !newTitle.trim() || newOut <= newIn}
              onClick={() =>
                void action(
                  () =>
                    createShort({
                      schemaVersion: 1,
                      source: data?.source,
                      shorts: [
                        {
                          id: `short-${crypto.randomUUID().slice(0, 8)}`,
                          title: newTitle,
                          sections: [
                            {
                              id: "section-1",
                              startFrame: Math.round(newIn * fps),
                              endFrameExclusive: Math.round(newOut * fps),
                            },
                          ],
                        },
                      ],
                    }),
                  (result) => {
                    sourceVideo.current?.pause();
                    accept(result);
                    setSelectedId(result.shorts[result.shorts.length - 1].id);
                    setShowCreate(false);
                    setNewTitle("");
                    setStatus(
                      "Short created. Review its boundaries, then build the assembled preview.",
                    );
                  },
                )
              }
            >
              Create short
            </button>
          </section>
        </div>
      )}
    </section>
  );
}
