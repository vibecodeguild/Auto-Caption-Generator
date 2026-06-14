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
import type { Dispatch, ReactNode, RefObject, SetStateAction } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HexColorInput, HexColorPicker } from "react-colorful";
import {
  API_BASE,
  type CaptionOptionsResponse,
  type CaptionPresetPayload,
  type CaptionStylePayload,
  type DynamicSplice,
  type EditorProjectResponse,
  adjustSplice,
  captionOptions,
  captionSourceVideoUrl,
  chooseCaptionOutputFolder,
  chooseCaptionVideo,
  deleteDeadSpace,
  deleteCaptionStyle,
  deleteTokens,
  exportCut,
  frameImageUrl,
  generateCaptionVideo,
  getCurrentProject,
  openProjectDialog,
  restoreTokens,
  reviewSplice,
  saveCaptionStyle,
  saveProject,
  sourceVideoUrl,
} from "../lib/api";

type PreviewState = {
  segments: [number, number][];
  index: number;
  loop: boolean;
};

type ActiveTab = "transcript" | "caption";

export default function Home() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("transcript");
  const [project, setProject] = useState<EditorProjectResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [anchorToken, setAnchorToken] = useState<string | null>(null);
  const [activeSplice, setActiveSplice] = useState<string | null>(null);
  const [loop, setLoop] = useState(false);
  const [status, setStatus] = useState(`API: ${API_BASE}`);
  const [captionStatus, setCaptionStatus] = useState("Caption generator ready");
  const [busy, setBusy] = useState(false);
  const [previewAspect, setPreviewAspect] = useState(16 / 9);
  const [previewBox, setPreviewBox] = useState({ width: 400, height: 225 });
  const previewPanelRef = useRef<HTMLElement | null>(null);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const previewState = useRef<PreviewState>({ segments: [], index: 0, loop: false });
  const previewFrameRef = useRef<number | null>(null);
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);
  const spliceMarkerRefs = useRef(new Map<string, HTMLButtonElement>());
  const [captionOptionsData, setCaptionOptionsData] = useState<CaptionOptionsResponse | null>(null);
  const [captionSource, setCaptionSource] = useState<string | null>(null);
  const [captionOutputFolder, setCaptionOutputFolder] = useState("");
  const [captionStyle, setCaptionStyle] = useState<CaptionStylePayload | null>(null);
  const [captionPreset, setCaptionPreset] = useState<CaptionPresetPayload | null>(null);
  const [captionStyleName, setCaptionStyleName] = useState("Magenta Pop");
  const [captionModel, setCaptionModel] = useState("Base - balanced");
  const [captionCompute, setCaptionCompute] = useState("CPU");

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

  const applyCaptionOptions = useCallback((data: CaptionOptionsResponse) => {
    setCaptionOptionsData(data);
    setCaptionSource(data.source);
    setCaptionOutputFolder(data.output_folder);
    const styleName = data.styles[captionStyleName] ? captionStyleName : Object.keys(data.styles)[0] ?? "";
    setCaptionStyleName(styleName);
    setCaptionStyle(data.styles[styleName] ?? data.default_style);
    setCaptionPreset(data.presets.Creator ?? Object.values(data.presets)[0] ?? null);
    if (!data.models[captionModel]) {
      setCaptionModel(Object.keys(data.models)[0] ?? "Base - balanced");
    }
    if (!data.compute[captionCompute]) {
      setCaptionCompute(Object.keys(data.compute)[0] ?? "CPU");
    }
  }, [captionCompute, captionModel, captionStyleName]);

  useEffect(() => {
    let cancelled = false;
    captionOptions()
      .then((data) => {
        if (!cancelled) applyCaptionOptions(data);
      })
      .catch((error) => setCaptionStatus(error instanceof Error ? error.message : String(error)));
    return () => {
      cancelled = true;
    };
  }, [applyCaptionOptions]);

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

  const handleChooseCaptionVideo = () => {
    void run(
      () => chooseCaptionVideo(),
      (data) => {
        setCaptionSource(data.source);
        setCaptionOutputFolder(data.output_folder);
        setCaptionStatus(`Selected ${data.source}`);
      },
    );
  };

  const handleChooseCaptionOutputFolder = () => {
    void run(
      () => chooseCaptionOutputFolder(),
      (data) => {
        setCaptionOutputFolder(data.output_folder);
        setCaptionStatus(`Output folder: ${data.output_folder}`);
      },
    );
  };

  const updateCaptionStyle = (patch: Partial<CaptionStylePayload>) => {
    setCaptionStyle((current) => current ? { ...current, ...patch } : current);
  };

  const updateCaptionPreset = (patch: Partial<CaptionPresetPayload>) => {
    setCaptionPreset((current) => current ? { ...current, ...patch } : current);
  };

  const handleGenerateCaptions = () => {
    if (!captionStyle || !captionPreset) return;
    void run(
      () => generateCaptionVideo({
        input_video_path: captionSource,
        output_folder: captionOutputFolder,
        style: captionStyle,
        preset: captionPreset,
        model_label: captionModel,
        compute_label: captionCompute,
      }),
      (result) => {
        const finalProgress = result.progress.at(-1);
        setCaptionStatus(`${finalProgress?.message ?? "Done."} Exported ${result.output_path}`);
      },
    );
  };

  const handleSaveCaptionStyle = () => {
    if (!captionStyle) return;
    const name = window.prompt("Style name:", captionStyleName);
    if (!name) return;
    void run(
      () => saveCaptionStyle(name, captionStyle),
      (data) => {
        applyCaptionOptions(data);
        setCaptionStyleName(name.trim());
        setCaptionStatus(`Saved style ${name.trim()}`);
      },
    );
  };

  const handleDeleteCaptionStyle = () => {
    if (!captionStyleName) return;
    void run(
      () => deleteCaptionStyle(captionStyleName),
      (data) => {
        applyCaptionOptions(data);
        setCaptionStatus(`Deleted style ${captionStyleName}`);
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
          <h1>VCG Content Command Center</h1>
          <p>Local web editor for transcript cuts and source-video splice review</p>
        </div>
        <nav>
          <button className={activeTab === "transcript" ? "tab active" : "tab"} onClick={() => setActiveTab("transcript")}>
            Transcript Edit
          </button>
          <button className={activeTab === "caption" ? "tab active" : "tab"} onClick={() => setActiveTab("caption")}>
            Caption Generator
          </button>
        </nav>
        <div className="top-actions">
          {activeTab === "transcript" ? (
            <>
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
            </>
          ) : (
            <>
              <button onClick={handleChooseCaptionVideo} disabled={busy}>
                <FolderOpen size={16} /> Choose Video
              </button>
              <button className="primary" onClick={handleGenerateCaptions} disabled={busy || !captionStyle || !captionPreset || !captionSource}>
                <Upload size={16} /> Generate Captioned Video
              </button>
            </>
          )}
        </div>
      </header>

      {activeTab === "transcript" ? (
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
      ) : (
        <CaptionGenerator
          busy={busy}
          captionCompute={captionCompute}
          captionModel={captionModel}
          captionOptionsData={captionOptionsData}
          captionOutputFolder={captionOutputFolder}
          captionPreset={captionPreset}
          captionSource={captionSource}
          captionStatus={captionStatus}
          captionStyle={captionStyle}
          captionStyleName={captionStyleName}
          handleChooseCaptionOutputFolder={handleChooseCaptionOutputFolder}
          handleDeleteCaptionStyle={handleDeleteCaptionStyle}
          handleSaveCaptionStyle={handleSaveCaptionStyle}
          setCaptionCompute={setCaptionCompute}
          setCaptionModel={setCaptionModel}
          setCaptionOutputFolder={setCaptionOutputFolder}
          setCaptionPreset={setCaptionPreset}
          setCaptionStyle={setCaptionStyle}
          setCaptionStyleName={setCaptionStyleName}
          updateCaptionPreset={updateCaptionPreset}
          updateCaptionStyle={updateCaptionStyle}
        />
      )}
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

function CaptionGenerator({
  busy,
  captionCompute,
  captionModel,
  captionOptionsData,
  captionOutputFolder,
  captionPreset,
  captionSource,
  captionStatus,
  captionStyle,
  captionStyleName,
  handleChooseCaptionOutputFolder,
  handleDeleteCaptionStyle,
  handleSaveCaptionStyle,
  setCaptionCompute,
  setCaptionModel,
  setCaptionOutputFolder,
  setCaptionPreset,
  setCaptionStyle,
  setCaptionStyleName,
  updateCaptionPreset,
  updateCaptionStyle,
}: {
  busy: boolean;
  captionCompute: string;
  captionModel: string;
  captionOptionsData: CaptionOptionsResponse | null;
  captionOutputFolder: string;
  captionPreset: CaptionPresetPayload | null;
  captionSource: string | null;
  captionStatus: string;
  captionStyle: CaptionStylePayload | null;
  captionStyleName: string;
  handleChooseCaptionOutputFolder: () => void;
  handleDeleteCaptionStyle: () => void;
  handleSaveCaptionStyle: () => void;
  setCaptionCompute: Dispatch<SetStateAction<string>>;
  setCaptionModel: Dispatch<SetStateAction<string>>;
  setCaptionOutputFolder: Dispatch<SetStateAction<string>>;
  setCaptionPreset: Dispatch<SetStateAction<CaptionPresetPayload | null>>;
  setCaptionStyle: Dispatch<SetStateAction<CaptionStylePayload | null>>;
  setCaptionStyleName: Dispatch<SetStateAction<string>>;
  updateCaptionPreset: (patch: Partial<CaptionPresetPayload>) => void;
  updateCaptionStyle: (patch: Partial<CaptionStylePayload>) => void;
}) {
  if (!captionOptionsData || !captionStyle || !captionPreset) {
    return (
      <section className="caption-workspace">
        <div className="empty">Loading caption generator...</div>
      </section>
    );
  }

  const styleNames = Object.keys(captionOptionsData.styles);

  const selectStyle = (name: string) => {
    setCaptionStyleName(name);
    setCaptionStyle(captionOptionsData.styles[name] ?? captionOptionsData.default_style);
  };

  const selectPreset = (name: string) => {
    setCaptionPreset(captionOptionsData.presets[name] ?? captionPreset);
  };

  return (
    <section className="caption-workspace">
      <section className="caption-preview-panel">
        <div className="panel-title">
          <span className="eyebrow">Caption Preview</span>
          <span>{captionSource ?? "Choose a video to generate captions"}</span>
        </div>
        <div className="caption-preview-media">
          {captionSource ? (
            <video controls preload="metadata" src={captionSourceVideoUrl()} />
          ) : (
            <div className="empty preview-empty">No video selected</div>
          )}
          <div
            className={[
              "caption-sample",
              captionStyle.position.toLowerCase(),
              captionStyle.outline_enabled ? "with-outline" : "",
              captionStyle.shadow_enabled ? "with-shadow" : "",
              captionStyle.glow_enabled ? "with-glow" : "",
            ].join(" ")}
            style={{
              color: captionStyle.main_color,
              fontFamily: previewFontStack(captionStyle.font_family),
              fontSize: `${Math.max(18, Math.round(captionStyle.main_font_size / 3))}px`,
              fontWeight: captionStyle.bold ? 900 : 400,
              textShadow: captionPreviewTextShadow(captionStyle),
            }}
          >
            {captionPreviewWords(captionPreset).map((word, wordIndex, words) => {
              const active = wordIndex === Math.min(1, words.length - 1);
              return (
                <span
                  key={`${word}-${wordIndex}`}
                  style={active ? {
                    color: captionStyle.active_color,
                    fontSize: `${Math.max(20, Math.round(captionStyle.active_font_size / 3))}px`,
                    fontWeight: captionStyle.active_bold ? 900 : 400,
                  } : undefined}
                >
                  {word}
                  {wordIndex < words.length - 1 ? " " : ""}
                </span>
              );
            })}
          </div>
        </div>
        <div className="folder-row">
          <label>
            Output folder
            <input value={captionOutputFolder} onChange={(event) => setCaptionOutputFolder(event.target.value)} />
          </label>
          <button onClick={handleChooseCaptionOutputFolder} disabled={busy}>
            <FolderOpen size={16} /> Change
          </button>
        </div>
      </section>

      <section className="caption-settings-grid">
        <SettingsCard title="Caption Setup">
          <label>
            Preset
            <select value={captionPreset.name} onChange={(event) => selectPreset(event.target.value)}>
              {Object.keys(captionOptionsData.presets).map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
          <label>
            Whisper model
            <select value={captionModel} onChange={(event) => setCaptionModel(event.target.value)}>
              {Object.keys(captionOptionsData.models).map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
          <label>
            Compute device
            <select value={captionCompute} onChange={(event) => setCaptionCompute(event.target.value)}>
              {Object.keys(captionOptionsData.compute).map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
        </SettingsCard>

        <SettingsCard title="Grouping">
          <NumberField label="Max words" value={captionPreset.max_words} min={1} max={12} step={1} onChange={(value) => updateCaptionPreset({ max_words: value })} />
          <NumberField label="Max seconds" value={captionPreset.max_duration} min={0.5} max={8} step={0.1} onChange={(value) => updateCaptionPreset({ max_duration: value })} />
          <NumberField label="Max characters" value={captionPreset.max_chars} min={10} max={120} step={1} onChange={(value) => updateCaptionPreset({ max_chars: value })} />
        </SettingsCard>

        <SettingsCard title="Caption Style">
          <label>
            Font
            <select value={captionStyle.font_family} onChange={(event) => updateCaptionStyle({ font_family: event.target.value })}>
              {["Montserrat", "Open Sans", "Poppins", "Inter", "Anton", "Oswald", "Roboto", "Lato", "Arial"].map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
          <NumberField label="Main size" value={captionStyle.main_font_size} min={24} max={160} step={1} onChange={(value) => updateCaptionStyle({ main_font_size: value })} />
          <NumberField label="Active size" value={captionStyle.active_font_size} min={24} max={180} step={1} onChange={(value) => updateCaptionStyle({ active_font_size: value })} />
          <div className="paired-row">
            <ColorField label="Text color" value={captionStyle.main_color} onChange={(value) => updateCaptionStyle({ main_color: value })} />
            <ColorField label="Active color" value={captionStyle.active_color} onChange={(value) => updateCaptionStyle({ active_color: value })} />
          </div>
          <ToggleField label="Bold" checked={captionStyle.bold} onChange={(value) => updateCaptionStyle({ bold: value })} />
          <ToggleField label="Active word bold" checked={captionStyle.active_bold} onChange={(value) => updateCaptionStyle({ active_bold: value })} />
        </SettingsCard>

        <SettingsCard title="Effects">
          <EffectRow
            label="Outline"
            checked={captionStyle.outline_enabled}
            color={captionStyle.outline_color}
            size={captionStyle.outline_width}
            onToggle={(value) => updateCaptionStyle({ outline_enabled: value })}
            onColor={(value) => updateCaptionStyle({ outline_color: value })}
            onSize={(value) => updateCaptionStyle({ outline_width: value })}
          />
          <EffectRow
            label="Shadow"
            checked={captionStyle.shadow_enabled}
            color={captionStyle.shadow_color}
            size={captionStyle.shadow_depth}
            onToggle={(value) => updateCaptionStyle({ shadow_enabled: value, shadow_depth: value && captionStyle.shadow_depth === 0 ? 5 : captionStyle.shadow_depth })}
            onColor={(value) => updateCaptionStyle({ shadow_color: value })}
            onSize={(value) => updateCaptionStyle({ shadow_depth: value })}
          />
          <EffectRow
            label="Glow"
            checked={captionStyle.glow_enabled}
            color={captionStyle.glow_color}
            size={captionStyle.glow_strength}
            onToggle={(value) => updateCaptionStyle({ glow_enabled: value, glow_strength: value && captionStyle.glow_strength === 0 ? 5 : captionStyle.glow_strength })}
            onColor={(value) => updateCaptionStyle({ glow_color: value })}
            onSize={(value) => updateCaptionStyle({ glow_strength: value })}
          />
        </SettingsCard>

        <SettingsCard title="Position">
          <label>
            Placement
            <select value={captionStyle.position} onChange={(event) => updateCaptionStyle({ position: event.target.value })}>
              {["Bottom", "Middle", "Top"].map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
          <NumberField label="Offset" value={captionStyle.margin_v} min={0} max={600} step={10} onChange={(value) => updateCaptionStyle({ margin_v: value })} />
        </SettingsCard>

        <SettingsCard title="Style Library">
          <label>
            Style
            <select value={captionStyleName} onChange={(event) => selectStyle(event.target.value)}>
              {styleNames.map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
          <div className="button-row">
            <button onClick={handleSaveCaptionStyle}>Save</button>
            <button onClick={handleDeleteCaptionStyle}>Delete</button>
          </div>
        </SettingsCard>
      </section>
    </section>
  );
}

function SettingsCard({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="settings-card">
      <span className="eyebrow">{title}</span>
      {children}
    </section>
  );
}

function NumberField({ label, max, min, onChange, step, value }: { label: string; max: number; min: number; onChange: (value: number) => void; step: number; value: number }) {
  return (
    <label>
      {label}
      <input min={min} max={max} step={step} type="number" value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function EffectRow({
  checked,
  color,
  label,
  onColor,
  onSize,
  onToggle,
  size,
}: {
  checked: boolean;
  color: string;
  label: string;
  onColor: (value: string) => void;
  onSize: (value: number) => void;
  onToggle: (value: boolean) => void;
  size: number;
}) {
  return (
    <div className="effect-row">
      <ToggleField label={label} checked={checked} onChange={onToggle} />
      <ColorField label={`${label} color`} value={color} onChange={onColor} compact />
      <input
        aria-label={`${label} size`}
        min={0}
        max={20}
        step={1}
        type="number"
        value={size}
        onChange={(event) => onSize(Number(event.target.value))}
      />
    </div>
  );
}

function ColorField({ compact = false, label, onChange, value }: { compact?: boolean; label: string; onChange: (value: string) => void; value: string }) {
  const [open, setOpen] = useState(false);
  const normalized = completeHexOrFallback(value);
  return (
    <div className={compact ? "color-field compact" : "color-field"}>
      {!compact && <span>{label}</span>}
      <button className="color-trigger" type="button" onClick={() => setOpen((current) => !current)}>
        <span className="hex-swatch" style={{ backgroundColor: normalized }} />
        <span>{normalized}</span>
      </button>
      {open && (
        <div className="color-popover">
          <HexColorPicker color={normalized} onChange={onChange} onChangeEnd={() => setOpen(false)} />
          <HexColorInput className="hex-input" color={normalized} onChange={onChange} prefixed />
        </div>
      )}
    </div>
  );
}

function ToggleField({ checked, label, onChange }: { checked: boolean; label: string; onChange: (value: boolean) => void }) {
  return (
    <button className={checked ? "switch-field on" : "switch-field"} onClick={() => onChange(!checked)}>
      <span />
      {label}
    </button>
  );
}

function captionPreviewTextShadow(style: CaptionStylePayload) {
  const shadows = [];
  if (style.outline_enabled) {
    const width = Math.max(1, Math.round(style.outline_width / 3));
    shadows.push(...outlineTextShadows(width, style.outline_color));
  }
  if (style.shadow_enabled) shadows.push(`${style.shadow_depth}px ${style.shadow_depth}px 0 ${style.shadow_color}`);
  if (style.glow_enabled) shadows.push(`0 0 ${Math.max(2, style.glow_strength * 2)}px ${style.glow_color}`);
  return shadows.join(", ");
}

function captionPreviewWords(preset: CaptionPresetPayload) {
  const words = ["Build", "fast.", "Skip", "the", "syntax.", "Ship", "useful", "tools.", "Review", "every", "splice."];
  const preview: string[] = [];
  let currentChars = 0;
  const maxWords = Math.max(1, preset.max_words);
  const maxChars = Math.max(8, preset.max_chars);

  for (const word of words) {
    const nextChars = currentChars + word.length + (preview.length ? 1 : 0);
    if (preview.length > 0 && (preview.length >= maxWords || nextChars > maxChars)) break;
    preview.push(word);
    currentChars = nextChars;
  }
  return preview;
}

function outlineTextShadows(width: number, color: string) {
  const shadows: string[] = [];
  for (let offset = 1; offset <= width; offset += 1) {
    shadows.push(
      `${offset}px 0 0 ${color}`,
      `${-offset}px 0 0 ${color}`,
      `0 ${offset}px 0 ${color}`,
      `0 ${-offset}px 0 ${color}`,
      `${offset}px ${offset}px 0 ${color}`,
      `${-offset}px ${offset}px 0 ${color}`,
      `${offset}px ${-offset}px 0 ${color}`,
      `${-offset}px ${-offset}px 0 ${color}`,
    );
  }
  return shadows;
}

function completeHexOrFallback(value: string) {
  const hex = value.trim().toUpperCase();
  return /^#[0-9A-F]{6}$/.test(hex) ? hex : "#FFFFFF";
}

function previewFontStack(fontFamily: string) {
  const stacks: Record<string, string> = {
    Montserrat: 'Montserrat, "Arial Black", "Segoe UI", sans-serif',
    "Open Sans": '"Open Sans", "Segoe UI", Arial, sans-serif',
    Poppins: 'Poppins, "Trebuchet MS", "Segoe UI", sans-serif',
    Inter: 'Inter, "Segoe UI", Arial, sans-serif',
    Anton: 'Anton, Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif',
    Oswald: 'Oswald, "Arial Narrow", "Roboto Condensed", Arial, sans-serif',
    Roboto: 'Roboto, Arial, "Segoe UI", sans-serif',
    Lato: 'Lato, "Gill Sans", "Segoe UI", sans-serif',
    Arial: 'Arial, Helvetica, sans-serif',
  };
  return stacks[fontFamily] ?? `${fontFamily}, "Segoe UI", Arial, sans-serif`;
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
