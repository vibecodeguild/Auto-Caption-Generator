"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  Play,
  RotateCcw,
  Save,
  Scissors,
  Upload,
} from "lucide-react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE,
  type DynamicSplice,
  type EditorProjectResponse,
  adjustSplice,
  deleteDeadSpace,
  deleteTokens,
  exportCut,
  frameImageUrl,
  getCurrentProject,
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
  const [project, setProject] = useState<EditorProjectResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [anchorToken, setAnchorToken] = useState<string | null>(null);
  const [activeSplice, setActiveSplice] = useState<string | null>(null);
  const [loop, setLoop] = useState(false);
  const [status, setStatus] = useState(`API: ${API_BASE}`);
  const [busy, setBusy] = useState(false);
  const [previewAspect, setPreviewAspect] = useState(16 / 9);
  const [previewBox, setPreviewBox] = useState({ width: 400, height: 225 });
  const previewPanelRef = useRef<HTMLElement | null>(null);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const previewState = useRef<PreviewState>({ segments: [], index: 0, loop: false });
  const previewFrameRef = useRef<number | null>(null);
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);
  const spliceMarkerRefs = useRef(new Map<string, HTMLButtonElement>());

  const deletedWordIds = useMemo(() => new Set(project?.deleted_word_ids ?? []), [project]);
  const deletedSilenceIds = useMemo(() => new Set(project?.deleted_silence_ids ?? []), [project]);
  const tokenIndex = useMemo(() => new Map(project?.tokens.map((token, index) => [token.id, index]) ?? []), [project]);
  const spliceByRightWord = useMemo(
    () => new Map(project?.splices.map((splice) => [splice.right_word_id, splice]) ?? []),
    [project],
  );
  const selectedSplice = project?.splices.find((splice) => splice.anchor_key === activeSplice) ?? project?.splices[0];
  const selectedSpliceIndex = project?.splices.findIndex((splice) => splice.anchor_key === selectedSplice?.anchor_key) ?? -1;

  const applyProject = useCallback((data: EditorProjectResponse) => {
    setProject(data);
    setActiveSplice((current) => {
      if (current && data.splices.some((splice) => splice.anchor_key === current)) return current;
      return data.splices[0]?.anchor_key ?? null;
    });
    setStatus(data.project_path ? `Opened ${data.project_path}` : "Project loaded");
  }, []);

  const updatePreviewBox = useCallback((aspect = previewAspect) => {
    const panelWidth = previewPanelRef.current?.clientWidth ?? 420;
    const availableWidth = Math.max(220, Math.min(420, panelWidth - 20));
    const maxHeight = 236;
    let width = availableWidth;
    let height = width / aspect;

    if (height > maxHeight) {
      height = maxHeight;
      width = height * aspect;
    }

    setPreviewBox({
      width: Math.round(width),
      height: Math.round(height),
    });
  }, [previewAspect]);

  useEffect(() => {
    let cancelled = false;
    getCurrentProject()
      .then((data) => {
        if (!cancelled) applyProject(data);
      })
      .catch(() => {
        // No project is loaded in the local API yet.
      });
    return () => {
      cancelled = true;
    };
  }, [applyProject]);

  useEffect(() => {
    updatePreviewBox();
    const handleResize = () => updatePreviewBox();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [updatePreviewBox]);

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
      () => openProjectDialog(),
      (data) => {
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

  const updateSplice = (operation: () => Promise<EditorProjectResponse>) => {
    void run(operation, applyProject);
  };

  const reviewSpliceAndAdvance = (splice: DynamicSplice) => {
    const shouldAdvance = !splice.reviewed && !!project && selectedSpliceIndex < project.splices.length - 1;
    const nextAnchorKey = shouldAdvance ? project?.splices[selectedSpliceIndex + 1]?.anchor_key : null;
    void run(
      () => reviewSplice(splice.anchor_key, !splice.reviewed),
      (data) => {
        applyProject(data);
        if (nextAnchorKey) {
          setActiveSplice(nextAnchorKey);
        }
      },
    );
  };

  const selectSplice = (splice: DynamicSplice) => {
    setActiveSplice(splice.anchor_key);
    setStatus(`${splice.id}: OUT ${splice.left_out_frame}, IN ${splice.right_in_frame}`);
  };

  const moveSpliceSelection = (direction: -1 | 1) => {
    if (!project?.splices.length || selectedSpliceIndex < 0) return;
    const nextIndex = Math.min(project.splices.length - 1, Math.max(0, selectedSpliceIndex + direction));
    selectSplice(project.splices[nextIndex]);
  };

  const selectedMarkerRef = useCallback(
    (anchorKey: string) => (element: HTMLButtonElement | null) => {
      if (element) {
        spliceMarkerRefs.current.set(anchorKey, element);
      } else {
        spliceMarkerRefs.current.delete(anchorKey);
      }
    },
    [],
  );

  useEffect(() => {
    if (!selectedSplice?.anchor_key) return;
    spliceMarkerRefs.current.get(selectedSplice.anchor_key)?.scrollIntoView({
      block: "center",
      inline: "center",
      behavior: "smooth",
    });
  }, [selectedSplice?.anchor_key]);

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
        <div className="top-actions">
          <button onClick={handleOpen} disabled={busy}>
            <FolderOpen size={16} /> Open Project
          </button>
          <button onClick={() => void run(saveProject, (result) => setStatus(`Saved ${result.saved}`))} disabled={busy || !project}>
            <Save size={16} /> Save Project
          </button>
          <button onClick={() => void run(deleteDeadSpace, applyProject)} disabled={busy || !project}>
            <Scissors size={16} /> Delete Dead Space
          </button>
          <button
            className="primary"
            onClick={() => void run(exportCut, (result) => setStatus(`Exported ${result.output_path}`))}
            disabled={busy || !project}
          >
            <Upload size={16} /> Export Cut
          </button>
        </div>
      </header>

      <section className="workspace">
        <div className="left-stack">
          <section className="preview-panel" ref={previewPanelRef}>
            <div className="panel-title">
              <span className="eyebrow">Source Preview</span>
              <span>{project?.project.source ?? "No project loaded"}</span>
            </div>
            <div className="preview-media" style={previewBox}>
              <video
                ref={previewRef}
                controls
                preload="metadata"
                src={project ? sourceVideoUrl() : undefined}
                onLoadedMetadata={(event) => {
                  const video = event.currentTarget;
                  if (video.videoWidth && video.videoHeight) {
                    const aspect = video.videoWidth / video.videoHeight;
                    setPreviewAspect(aspect);
                    updatePreviewBox(aspect);
                  }
                }}
              />
            </div>
          </section>

          <SpliceReviewPanel
            loop={loop}
            moveSpliceSelection={moveSpliceSelection}
            playSplice={playSplice}
            project={project}
            reviewSpliceAndAdvance={reviewSpliceAndAdvance}
            selectedSplice={selectedSplice}
            selectedSpliceIndex={selectedSpliceIndex}
            setLoop={setLoop}
            updateSplice={updateSplice}
          />
        </div>

        <TranscriptContext
          activeSplice={activeSplice}
          deletedSilenceIds={deletedSilenceIds}
          deletedWordIds={deletedWordIds}
          project={project}
          selected={selected}
          sentenceGroups={sentenceGroups}
          selectToken={selectToken}
          selectedMarkerRef={selectedMarkerRef}
          selectSplice={selectSplice}
          spliceByRightWord={spliceByRightWord}
          status={status}
          transcriptScrollRef={transcriptScrollRef}
        />
      </section>
    </main>
  );
}

function TranscriptContext({
  activeSplice,
  deletedSilenceIds,
  deletedWordIds,
  project,
  selected,
  sentenceGroups,
  selectToken,
  selectedMarkerRef,
  selectSplice,
  spliceByRightWord,
  status,
  transcriptScrollRef,
}: {
  activeSplice: string | null;
  deletedSilenceIds: Set<string>;
  deletedWordIds: Set<string>;
  project: EditorProjectResponse | null;
  selected: string[];
  sentenceGroups: { sentenceId: number; words: EditorProjectResponse["project"]["words"] }[];
  selectToken: (tokenId: string, shiftKey: boolean) => void;
  selectedMarkerRef: (anchorKey: string) => (element: HTMLButtonElement | null) => void;
  selectSplice: (splice: DynamicSplice) => void;
  spliceByRightWord: Map<string, DynamicSplice>;
  status: string;
  transcriptScrollRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <section className="transcript-context-panel">
      <div className="panel-title">
        <span className="eyebrow">Transcript Context</span>
        <span>{selected.length ? `${selected.length} selected` : status}</span>
      </div>
      <div className="transcript-scroll" ref={transcriptScrollRef}>
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
                    <SpliceMarker
                      active={activeSplice === splice.anchor_key}
                      markerRef={selectedMarkerRef(splice.anchor_key)}
                      splice={splice}
                      onSelect={selectSplice}
                    />
                  )}
                  <button
                    className={["token", deleted ? "deleted" : "", selectedToken ? "selected" : ""].join(" ")}
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
  );
}

function SpliceReviewPanel({
  loop,
  moveSpliceSelection,
  playSplice,
  project,
  reviewSpliceAndAdvance,
  selectedSplice,
  selectedSpliceIndex,
  setLoop,
  updateSplice,
}: {
  loop: boolean;
  moveSpliceSelection: (direction: -1 | 1) => void;
  playSplice: (splice: DynamicSplice, seconds: 2 | 4 | 6) => void;
  project: EditorProjectResponse | null;
  reviewSpliceAndAdvance: (splice: DynamicSplice) => void;
  selectedSplice: DynamicSplice | undefined;
  selectedSpliceIndex: number;
  setLoop: Dispatch<SetStateAction<boolean>>;
  updateSplice: (operation: () => Promise<EditorProjectResponse>) => void;
}) {
  const count = project?.splices.length ?? 0;
  return (
    <section className="splice-review-panel">
      <div className="splice-review-header">
        <div>
          <span className="eyebrow">Splice Review</span>
          <span className="splice-count-label">
            {selectedSplice ? `Splice ${selectedSpliceIndex + 1} of ${count}` : "No splice selected"}
          </span>
        </div>
        <div className="review-nav">
          <button onClick={() => moveSpliceSelection(-1)} disabled={!selectedSplice || selectedSpliceIndex <= 0}>
            <ChevronLeft size={16} /> Previous
          </button>
          <button
            onClick={() => selectedSplice && reviewSpliceAndAdvance(selectedSplice)}
            disabled={!selectedSplice}
            className={selectedSplice?.reviewed ? "review-toggle reviewed" : "review-toggle"}
          >
            {selectedSplice?.reviewed ? <Check size={14} /> : <Scissors size={14} />}
            {selectedSplice?.reviewed ? "Reviewed" : "Needs review"}
          </button>
          <button onClick={() => moveSpliceSelection(1)} disabled={!selectedSplice || selectedSpliceIndex >= count - 1}>
            Next <ChevronRight size={16} />
          </button>
        </div>
        {selectedSplice && (
          <div className="review-playbar">
            <span>Play</span>
            <button onClick={() => playSplice(selectedSplice, 2)}><Play size={13} /> 2</button>
            <button onClick={() => playSplice(selectedSplice, 4)}><Play size={13} /> 4</button>
            <button onClick={() => playSplice(selectedSplice, 6)}><Play size={13} /> 6</button>
            <button className={loop ? "toggle on" : "toggle"} onClick={() => setLoop((value) => !value)}>
              <RotateCcw size={13} /> Loop
            </button>
          </div>
        )}
      </div>
      {selectedSplice ? (
        <div className="splice-review-body">
          <CutFrameCard
            title="OUT frame"
            frame={selectedSplice.left_out_frame}
            onNudge={(delta) => updateSplice(() => adjustSplice(selectedSplice.anchor_key, delta, 0))}
          />
          <CutFrameCard
            title="IN frame"
            frame={selectedSplice.right_in_frame}
            onNudge={(delta) => updateSplice(() => adjustSplice(selectedSplice.anchor_key, 0, delta))}
          />
        </div>
      ) : (
        <p className="muted">Delete content to create splice points for review.</p>
      )}
    </section>
  );
}

function CutFrameCard({
  title,
  frame,
  onNudge,
}: {
  title: string;
  frame: number;
  onNudge: (delta: number) => void;
}) {
  return (
    <div className="cut-frame-card">
      <div className="cut-frame-header">
        <span>{title}</span>
        <strong>{frame}</strong>
      </div>
      <img src={frameImageUrl(frame)} alt={`${title} ${frame}`} />
      <div className="nudge-buttons" aria-label={`${title} nudges`}>
        <button onClick={() => onNudge(-10)}><ArrowLeft size={13} /> 10</button>
        <button onClick={() => onNudge(-5)}><ArrowLeft size={13} /> 5</button>
        <button onClick={() => onNudge(-1)}><ArrowLeft size={13} /> 1</button>
        <button onClick={() => onNudge(1)}>1 <ArrowRight size={13} /></button>
        <button onClick={() => onNudge(5)}>5 <ArrowRight size={13} /></button>
        <button onClick={() => onNudge(10)}>10 <ArrowRight size={13} /></button>
      </div>
    </div>
  );
}

function SpliceMarker({
  splice,
  active,
  markerRef,
  onSelect,
}: {
  splice: DynamicSplice;
  active: boolean;
  markerRef: (element: HTMLButtonElement | null) => void;
  onSelect: (splice: DynamicSplice) => void;
}) {
  return (
    <button
      ref={markerRef}
      className={["splice-marker", active ? "active" : "", splice.reviewed ? "reviewed" : ""].join(" ")}
      onClick={() => onSelect(splice)}
    >
      <span>{splice.id.replace("_", " ")}</span>
      <strong>{splice.reviewed ? "Reviewed" : "Needs review"}</strong>
    </button>
  );
}
