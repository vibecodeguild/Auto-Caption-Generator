"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  FolderOpen,
  Play,
  RotateCcw,
  Save,
  Scissors,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE,
  type DynamicSplice,
  type EditorProjectResponse,
  adjustSplice,
  deleteTokens,
  exportCut,
  frameImageUrl,
  openProject,
  openProjectDialog,
  restoreTokens,
  reviewSplice,
  saveProject,
  sourceVideoUrl,
} from "../lib/api";

type PreviewState = {
  segments: [number, number][];
  index: number;
  loop: boolean;
};

export default function Home() {
  const [projectPath, setProjectPath] = useState("");
  const [project, setProject] = useState<EditorProjectResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [anchorToken, setAnchorToken] = useState<string | null>(null);
  const [activeSplice, setActiveSplice] = useState<string | null>(null);
  const [loop, setLoop] = useState(false);
  const [status, setStatus] = useState(`API: ${API_BASE}`);
  const [busy, setBusy] = useState(false);
  const [previewWidth, setPreviewWidth] = useState(340);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const previewState = useRef<PreviewState>({ segments: [], index: 0, loop: false });
  const previewFrameRef = useRef<number | null>(null);

  const deletedWordIds = useMemo(() => new Set(project?.deleted_word_ids ?? []), [project]);
  const deletedSilenceIds = useMemo(() => new Set(project?.deleted_silence_ids ?? []), [project]);
  const tokenIndex = useMemo(() => new Map(project?.tokens.map((token, index) => [token.id, index]) ?? []), [project]);
  const spliceByRightWord = useMemo(
    () => new Map(project?.splices.map((splice) => [splice.right_word_id, splice]) ?? []),
    [project],
  );
  const selectedSplice = project?.splices.find((splice) => splice.anchor_key === activeSplice) ?? project?.splices[0];

  const applyProject = useCallback((data: EditorProjectResponse) => {
    setProject(data);
    setStatus(data.project_path ? `Opened ${data.project_path}` : "Project loaded");
  }, []);

  const run = useCallback(async <T,>(operation: () => Promise<T>, done?: (result: T) => void) => {
    setBusy(true);
    try {
      const result = await operation();
      done?.(result);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }, []);

  const handleOpen = () => {
    void run(
      () => (projectPath.trim() ? openProject(projectPath.trim()) : openProjectDialog()),
      (data) => {
        setProjectPath(data.project_path ?? "");
        applyProject(data);
      },
    );
  };

  const tokenRange = (from: string, to: string) => {
    const start = tokenIndex.get(from);
    const end = tokenIndex.get(to);
    if (start === undefined || end === undefined || !project) return [to];
    const low = Math.min(start, end);
    const high = Math.max(start, end);
    return project.tokens.slice(low, high + 1).map((token) => token.id);
  };

  const selectToken = (tokenId: string, shiftKey: boolean) => {
    if (shiftKey && anchorToken) {
      setSelected(tokenRange(anchorToken, tokenId));
      return;
    }
    setAnchorToken(tokenId);
    setSelected([tokenId]);
  };

  const deleteSelection = useCallback(() => {
    if (!selected.length) return;
    void run(() => deleteTokens(selected), applyProject);
  }, [applyProject, run, selected]);

  const restoreSelection = useCallback(() => {
    if (!selected.length) return;
    void run(() => restoreTokens(selected), applyProject);
  }, [applyProject, run, selected]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA") return;
      if (event.key.toLowerCase() === "d" || event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelection();
      }
      if (event.key.toLowerCase() === "r") {
        event.preventDefault();
        restoreSelection();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteSelection, restoreSelection]);

  const stopPreviewMonitor = useCallback(() => {
    if (previewFrameRef.current !== null) {
      cancelAnimationFrame(previewFrameRef.current);
      previewFrameRef.current = null;
    }
  }, []);

  const seekPreview = (video: HTMLVideoElement, time: number) =>
    new Promise<void>((resolve) => {
      if (Math.abs(video.currentTime - time) < 0.001) {
        resolve();
        return;
      }
      const done = () => {
        video.removeEventListener("seeked", done);
        resolve();
      };
      video.addEventListener("seeked", done, { once: true });
      video.currentTime = time;
    });

  const startPreviewMonitor = useCallback(() => {
    stopPreviewMonitor();
    const tick = () => {
      const video = previewRef.current;
      const state = previewState.current;
      const segment = state.segments[state.index];
      if (!video || !segment) {
        previewFrameRef.current = null;
        return;
      }
      const frameGuardSeconds = 1 / Math.max(project?.project.fps ?? 30, 1);
      if (video.currentTime >= segment[1] - frameGuardSeconds / 2) {
        if (state.index === 0 && state.segments[1]) {
          state.index = 1;
          void seekPreview(video, state.segments[1][0]).then(() => video.play());
        } else if (state.loop) {
          state.index = 0;
          void seekPreview(video, state.segments[0][0]).then(() => video.play());
        } else {
          video.pause();
          previewState.current = { segments: [], index: 0, loop: state.loop };
          previewFrameRef.current = null;
          return;
        }
      }
      previewFrameRef.current = requestAnimationFrame(tick);
    };
    previewFrameRef.current = requestAnimationFrame(tick);
  }, [project?.project.fps, stopPreviewMonitor]);

  useEffect(() => stopPreviewMonitor, [stopPreviewMonitor]);

  const playSplice = (splice: DynamicSplice, seconds: 2 | 4 | 6) => {
    const video = previewRef.current;
    if (!video) return;
    const segments = splice[`preview_segments_${seconds}s`];
    previewState.current = { segments, index: 0, loop };
    setActiveSplice(splice.anchor_key);
    setStatus(`${splice.id}: preview ${seconds}s from source video`);
    stopPreviewMonitor();
    video.pause();
    void seekPreview(video, segments[0][0])
      .then(() => video.play())
      .then(startPreviewMonitor)
      .catch((error) => setStatus(`Preview failed: ${error.message}`));
  };

  const onTimeUpdate = () => {
    const video = previewRef.current;
    const state = previewState.current;
    if (!video || !state.segments.length) return;
    const segment = state.segments[state.index];
    if (!segment || video.currentTime < segment[1]) return;
    if (state.index === 0) {
      state.index = 1;
      video.currentTime = state.segments[1][0];
      void video.play();
      return;
    }
    if (state.loop) {
      state.index = 0;
      video.currentTime = state.segments[0][0];
      void video.play();
      return;
    }
    video.pause();
    previewState.current = { segments: [], index: 0, loop: state.loop };
  };

  const updateSplice = (operation: () => Promise<EditorProjectResponse>) => {
    void run(operation, applyProject);
  };

  const selectSplice = (splice: DynamicSplice) => {
    setActiveSplice(splice.anchor_key);
    setStatus(`${splice.id}: OUT ${splice.left_out_frame}, IN ${splice.right_in_frame}`);
  };

  const sentenceGroups = useMemo(() => {
    if (!project) return [];
    const currentProject = project.project;
    const groups = new Map<number, typeof project.project.words>();
    for (const word of currentProject.words) {
      const group = groups.get(word.sentence_id) ?? [];
      group.push(word);
      groups.set(word.sentence_id, group);
    }
    return [...groups.entries()].map(([sentenceId, words]) => ({ sentenceId, words }));
  }, [project]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>VCG AutoCaption</h1>
          <p>Local web editor for transcript cuts and source-video splice review</p>
        </div>
        <nav>
          <button className="tab active">Transcript Edit</button>
          <button className="tab">Caption Generator</button>
        </nav>
      </header>

      <section className="workspace">
        <aside className="action-rail">
          <label>
            Project path
            <input
              value={projectPath}
              onChange={(event) => setProjectPath(event.target.value)}
              placeholder="Optional path or use picker"
            />
          </label>
          <button onClick={handleOpen} disabled={busy}>
            <FolderOpen size={16} /> Open Project
          </button>
          <button onClick={() => void run(saveProject, (result) => setStatus(`Saved ${result.saved}`))} disabled={busy || !project}>
            <Save size={16} /> Save Project
          </button>
          <button
            className="primary"
            onClick={() => void run(exportCut, (result) => setStatus(`Exported ${result.output_path}`))}
            disabled={busy || !project}
          >
            <Upload size={16} /> Export Cut
          </button>
          <div className="hint">
            Select words or dead space. Press D to delete and R to restore.
          </div>
        </aside>

        <section className="preview-panel" style={{ width: previewWidth }}>
          <div className="panel-title">
            <span>Source Preview</span>
            <span>{project?.project.source ?? "No project loaded"}</span>
          </div>
          <div className="preview-media">
            <video
              ref={previewRef}
              controls
              src={project ? sourceVideoUrl() : undefined}
              onLoadedMetadata={(event) => {
                const video = event.currentTarget;
                if (video.videoWidth && video.videoHeight) {
                  const aspect = video.videoWidth / video.videoHeight;
                  setPreviewWidth(Math.round(Math.min(420, Math.max(220, aspect * 170 + 28))));
                }
              }}
              onTimeUpdate={onTimeUpdate}
            />
          </div>
        </section>

        <section className="splice-detail">
          <div className="panel-title">
            <span>{selectedSplice?.id.replace("_", " ") ?? "Selected Splice"}</span>
            <span>{project ? `${project.splices.length} dynamic splices` : "No project"}</span>
          </div>
          {selectedSplice ? (
            <div className="splice-detail-body">
              <div className="frame-preview-grid">
                <FrameStrip
                  title="OUT frame"
                  frame={selectedSplice.left_out_frame}
                  offsets={[-4, -3, -2, -1, 0]}
                  onMinus={() => updateSplice(() => adjustSplice(selectedSplice.anchor_key, -1, 0))}
                  onPlus={() => updateSplice(() => adjustSplice(selectedSplice.anchor_key, 1, 0))}
                />
                <FrameStrip
                  title="IN frame"
                  frame={selectedSplice.right_in_frame}
                  offsets={[0, 1, 2, 3, 4]}
                  onMinus={() => updateSplice(() => adjustSplice(selectedSplice.anchor_key, 0, -1))}
                  onPlus={() => updateSplice(() => adjustSplice(selectedSplice.anchor_key, 0, 1))}
                />
              </div>
              <div className="detail-actions" aria-label="Selected splice actions">
                <span className="splice-mini-context">{selectedSplice.left_context} -&gt; {selectedSplice.right_context}</span>
                <span>Play</span>
                <button onClick={() => playSplice(selectedSplice, 2)}><Play size={13} /> 2</button>
                <button onClick={() => playSplice(selectedSplice, 4)}><Play size={13} /> 4</button>
                <button onClick={() => playSplice(selectedSplice, 6)}><Play size={13} /> 6</button>
                <button className={loop ? "toggle on" : "toggle"} onClick={() => setLoop((value) => !value)}>
                  <RotateCcw size={13} /> Loop
                </button>
                <button
                  className={selectedSplice.reviewed ? "review-toggle reviewed" : "review-toggle"}
                  onClick={() => updateSplice(() => reviewSplice(selectedSplice.anchor_key, !selectedSplice.reviewed))}
                >
                  {selectedSplice.reviewed ? <Check size={14} /> : <Scissors size={14} />}
                  {selectedSplice.reviewed ? "Reviewed" : "Needs review"}
                </button>
              </div>
            </div>
          ) : (
            <p className="muted">Delete content to create a splice.</p>
          )}
        </section>
      </section>

      <section className="transcript-panel">
        <div className="panel-title">
          <span>Transcript Edit</span>
          <span>{selected.length ? `${selected.length} selected` : status}</span>
        </div>
        <div className="transcript-scroll">
          {!project && <div className="empty">Open a `.vcg.json` editor project to start testing the web editor.</div>}
          {sentenceGroups.map((group) => (
            <div className="sentence" key={group.sentenceId}>
              {group.words.map((word) => {
                const splice = spliceByRightWord.get(word.id);
                const deleted = deletedWordIds.has(word.id);
                const selectedToken = selected.includes(word.id);
                return (
                  <span key={word.id} className="word-wrap">
                    {splice && (
                      <SpliceControl
                        splice={splice}
                        active={activeSplice === splice.anchor_key}
                        loop={loop}
                        onSelect={selectSplice}
                        onPlay={playSplice}
                        onLoop={() => setLoop((value) => !value)}
                        onOut={(delta) => updateSplice(() => adjustSplice(splice.anchor_key, delta, 0))}
                        onIn={(delta) => updateSplice(() => adjustSplice(splice.anchor_key, 0, delta))}
                        onReview={() => updateSplice(() => reviewSplice(splice.anchor_key, !splice.reviewed))}
                      />
                    )}
                    <button
                      className={[
                        "token",
                        deleted ? "deleted" : "",
                        selectedToken ? "selected" : "",
                      ].join(" ")}
                      onClick={(event) => selectToken(word.id, event.shiftKey)}
                    >
                      {word.text}
                    </button>
                    {(project?.project.silence_ranges ?? [])
                      .filter((silence) => silence.start_frame === word.end_frame + 1)
                      .map((silence) => (
                        <button
                          key={silence.id}
                          className={[
                            "silence",
                            deletedSilenceIds.has(silence.id) ? "deleted" : "",
                            selected.includes(silence.id) ? "selected" : "",
                          ].join(" ")}
                          onClick={(event) => selectToken(silence.id, event.shiftKey)}
                        >
                          DEAD SPACE {(silence.end - silence.start).toFixed(1)}s
                        </button>
                      ))}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function FrameStrip({
  title,
  frame,
  offsets,
  onMinus,
  onPlus,
}: {
  title: string;
  frame: number;
  offsets: number[];
  onMinus: () => void;
  onPlus: () => void;
}) {
  const frames = offsets.map((offset) => Math.max(0, frame + offset));
  return (
    <div className="frame-strip">
      <div className="frame-strip-header">
        <span>{title}</span>
        <strong>{frame}</strong>
        <button onClick={onMinus}><ArrowLeft size={13} /></button>
        <button onClick={onPlus}><ArrowRight size={13} /></button>
      </div>
      <div className="frame-strip-images">
        {frames.map((item, index) => (
          <figure className={item === frame ? "frame-thumb active" : "frame-thumb"} key={`${title}-${item}-${index}`}>
            <img src={frameImageUrl(item)} alt={`${title} ${item}`} />
            <figcaption>{item === frame ? "CUT" : item}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}

function SpliceControl({
  splice,
  active,
  loop,
  onPlay,
  onSelect,
  onLoop,
  onOut,
  onIn,
  onReview,
}: {
  splice: DynamicSplice;
  active: boolean;
  loop: boolean;
  onPlay: (splice: DynamicSplice, seconds: 2 | 4 | 6) => void;
  onSelect: (splice: DynamicSplice) => void;
  onLoop: () => void;
  onOut: (delta: number) => void;
  onIn: (delta: number) => void;
  onReview: () => void;
}) {
  return (
    <span className={active ? "splice-control active" : "splice-control"}>
      <button className="splice-label" onClick={() => onSelect(splice)}>{splice.id.replace("_", " ")}</button>
      <button className="splice-context" onClick={() => onSelect(splice)}>{splice.left_context} -&gt; {splice.right_context}</button>
      <span>Play</span>
      <button onClick={() => onPlay(splice, 2)}>2</button>
      <button onClick={() => onPlay(splice, 4)}>4</button>
      <button onClick={() => onPlay(splice, 6)}>6</button>
      <button className={loop ? "on" : ""} onClick={onLoop}>Loop</button>
      <span>Out</span>
      <button onClick={() => onOut(-1)}><ArrowLeft size={12} /></button>
      <button onClick={() => onOut(1)}><ArrowRight size={12} /></button>
      <span>In</span>
      <button onClick={() => onIn(-1)}><ArrowLeft size={12} /></button>
      <button onClick={() => onIn(1)}><ArrowRight size={12} /></button>
      <button onClick={onReview}>{splice.reviewed ? <Check size={12} /> : <Scissors size={12} />} Review</button>
    </span>
  );
}
