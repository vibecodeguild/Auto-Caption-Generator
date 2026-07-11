"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  Gauge,
  Grid3X3,
  Headphones,
  Pause,
  Play,
  RotateCcw,
  Save,
  Scissors,
  Settings,
  Upload,
  Volume2,
  VolumeX,
  WandSparkles,
  X,
} from "lucide-react";
import type { Dispatch, MutableRefObject, ReactNode, RefObject, SetStateAction } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HexColorInput, HexColorPicker } from "react-colorful";
import {
  API_BASE,
  type AudioAnalysisResponse,
  type AudioOptionsResponse,
  type AudioPreviewResponse,
  type CaptionOptionsResponse,
  type CaptionPreviewGroup,
  type CaptionPreviewResponse,
  type CaptionPresetPayload,
  type CaptionStylePayload,
  type DynamicSplice,
  type EditorProjectResponse,
  type ProjectDocumentResponse,
  type RenderedCutPreviewResponse,
  type TranscriptionJobStatus,
  adjustSplice,
  analyzeBoundaries,
  analyzePauses,
  analyzeVideoAudio,
  audioOptions,
  audioPreviewUrl,
  audioSourceVideoUrl,
  captionOptions,
  captionSourceVideoUrl,
  chooseCaptionOutputFolder,
  chooseCaptionVideo,
  chooseAudioOutputFolder,
  chooseAudioVideo,
  chooseTranscriptVideo,
  deleteDeadSpace,
  deleteCaptionStyle,
  deleteTokens,
  exportCut,
  generateAudioPreview,
  generateCaptionVideo,
  getProjectDocument,
  getTranscriptionJob,
  getCurrentProject,
  normalizeVideoAudio,
  openProjectDialog,
  prepareCaptionPreview,
  restoreTokens,
  renderedCutPreviewUrl,
  renderCutPreview,
  reviewSplice,
  saveCaptionStyle,
  sourceVideoUrl,
  startTranscription,
  updateEditorSettings,
} from "../lib/api";

type PreviewState = {
  segments: [number, number][];
  index: number;
  loop: boolean;
};

type ActiveTab = "transcript" | "caption" | "audio";

type ExportProgressState = {
  status: "running" | "complete" | "failed";
  message: string;
  outputPath?: string;
};

type ProjectFileHandle = {
  name: string;
  createWritable: () => Promise<{
    write: (data: Blob) => Promise<void>;
    close: () => Promise<void>;
  }>;
};

type WindowWithSaveFilePicker = Window & {
  showSaveFilePicker?: (options: {
    suggestedName: string;
    types: Array<{
      description: string;
      accept: Record<string, string[]>;
    }>;
  }) => Promise<ProjectFileHandle>;
};

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
  const [showTranscriptSettings, setShowTranscriptSettings] = useState(false);
  const [activeWorkflowStage, setActiveWorkflowStage] = useState(1);
  const [previewAspect, setPreviewAspect] = useState(16 / 9);
  const [previewBox, setPreviewBox] = useState({ width: 400, height: 225 });
  const previewPanelRef = useRef<HTMLElement | null>(null);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const renderedCutVideoRef = useRef<HTMLVideoElement | null>(null);
  const previewState = useRef<PreviewState>({ segments: [], index: 0, loop: false });
  const previewFrameRef = useRef<number | null>(null);
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);
  const spliceMarkerRefs = useRef(new Map<string, HTMLButtonElement>());
  const projectFileHandleRef = useRef<ProjectFileHandle | null>(null);
  const [captionOptionsData, setCaptionOptionsData] = useState<CaptionOptionsResponse | null>(null);
  const [captionSource, setCaptionSource] = useState<string | null>(null);
  const [captionOutputFolder, setCaptionOutputFolder] = useState("");
  const [captionStyle, setCaptionStyle] = useState<CaptionStylePayload | null>(null);
  const [captionPreset, setCaptionPreset] = useState<CaptionPresetPayload | null>(null);
  const [captionStyleName, setCaptionStyleName] = useState("Magenta Pop");
  const [captionModel, setCaptionModel] = useState("Base - balanced");
  const [captionCompute, setCaptionCompute] = useState("CPU");
  const [captionPreview, setCaptionPreview] = useState<CaptionPreviewResponse | null>(null);
  const [transcriptSource, setTranscriptSource] = useState<string | null>(null);
  const [transcriptionProgress, setTranscriptionProgress] = useState<TranscriptionJobStatus | null>(null);
  const [exportProgress, setExportProgress] = useState<ExportProgressState | null>(null);
  const [previewRenderProgress, setPreviewRenderProgress] = useState<ExportProgressState | null>(null);
  const [renderedCutPreview, setRenderedCutPreview] = useState<RenderedCutPreviewResponse | null>(null);
  const [audioOptionsData, setAudioOptionsData] = useState<AudioOptionsResponse | null>(null);
  const [audioSource, setAudioSource] = useState<string | null>(null);
  const [audioOutputFolder, setAudioOutputFolder] = useState("");
  const [audioPresetId, setAudioPresetId] = useState("gentle");
  const [normalizeCutAudio, setNormalizeCutAudio] = useState(false);
  const [audioTargetI, setAudioTargetI] = useState(-14);
  const [audioTargetLra, setAudioTargetLra] = useState(7);
  const [audioTargetTp, setAudioTargetTp] = useState(-1.5);
  const [audioAnalysis, setAudioAnalysis] = useState<AudioAnalysisResponse | null>(null);
  const [audioPreview, setAudioPreview] = useState<AudioPreviewResponse | null>(null);
  const [audioStatus, setAudioStatus] = useState("Choose a video, then analyze its audio.");

  const deletedWordIds = useMemo(() => new Set(project?.deleted_word_ids ?? []), [project]);
  const deletedSilenceIds = useMemo(() => new Set(project?.deleted_silence_ids ?? []), [project]);
  const tokenIndex = useMemo(() => new Map(project?.tokens.map((token, index) => [token.id, index]) ?? []), [project]);
  const spliceByRightWord = useMemo(
    () => new Map(project?.splices.map((splice) => [splice.right_word_id, splice]) ?? []),
    [project],
  );
  const selectedSplice = project?.splices.find((splice) => splice.anchor_key === activeSplice) ?? project?.splices[0];
  const selectedSpliceIndex = project?.splices.findIndex((splice) => splice.anchor_key === selectedSplice?.anchor_key) ?? -1;
  const transcriptVideoKey = project?.project.source ?? transcriptSource ?? "";
  const renderedBoundaryByAnchor = useMemo(
    () => new Map(renderedCutPreview?.splices.map((splice) => [splice.anchor_key, splice]) ?? []),
    [renderedCutPreview],
  );
  const pendingPreviewFrames = project?.splices.reduce((total, splice) => {
    const rendered = renderedBoundaryByAnchor.get(splice.anchor_key);
    if (!rendered) return total + 1;
    return total + Math.abs(splice.left_out_frame - rendered.left_out_frame) + Math.abs(splice.right_in_frame - rendered.right_in_frame);
  }, 0) ?? 0;
  const renderedPreviewStale = !!renderedCutPreview
    && (renderedCutPreview.splices.length !== (project?.splices.length ?? 0) || pendingPreviewFrames > 0);

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
    let cancelled = false;
    audioOptions()
      .then((data) => {
        if (cancelled) return;
        setAudioOptionsData(data);
        setAudioSource(data.source);
        setAudioOutputFolder(data.output_folder);
        setAudioPresetId(data.defaults.preset_id);
        setAudioTargetI(data.defaults.target_i);
        setAudioTargetLra(data.defaults.target_lra);
        setAudioTargetTp(data.defaults.target_tp);
      })
      .catch((error) => setAudioStatus(error instanceof Error ? error.message : String(error)));
    return () => {
      cancelled = true;
    };
  }, []);

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
        projectFileHandleRef.current = null;
        applyProject(data);
        setTranscriptSource(data.project.source);
        setActiveWorkflowStage(data.pause_analysis_pending_count > 0 ? 2 : data.splices.length > 0 ? 3 : 1);
      },
    );
  };

  const handleChooseTranscriptVideo = () => {
    void run(
      () => chooseTranscriptVideo(),
      (data) => {
        setTranscriptSource(data.source);
        setProject(null);
        projectFileHandleRef.current = null;
        setSelected([]);
        setActiveSplice(null);
        setActiveWorkflowStage(1);
        setStatus(`Selected ${data.source}`);
      },
    );
  };

  const handleGenerateTranscript = () => {
    void run(
      async () => {
        const started = await startTranscription({ model_label: captionModel, compute_label: captionCompute });
        setTranscriptionProgress({
          status: "running",
          value: 0,
          message: "Starting transcription...",
          result: null,
          error: null,
        });
        try {
          return await pollTranscriptionJob(started.job_id, setTranscriptionProgress);
        } catch (error) {
          setTranscriptionProgress(null);
          throw error;
        }
      },
      (data) => {
        projectFileHandleRef.current = null;
        applyProject(data);
        setTranscriptSource(data.project.source);
        setActiveWorkflowStage(2);
        setTranscriptionProgress(null);
        setStatus(`Transcript ready: ${data.project.words.length} words`);
      },
    );
  };

  const handleExportCut = () => {
    setBusy(true);
    setExportProgress({
      status: "running",
      message: normalizeCutAudio
        ? "Exporting the cut, then analyzing and normalizing its audio..."
        : "Exporting edited video with FFmpeg...",
    });
    exportCut({
      normalize_audio: normalizeCutAudio,
      normalization_preset_id: audioPresetId,
      target_i: audioTargetI,
      target_lra: audioTargetLra,
      target_tp: audioTargetTp,
    })
      .then((result) => {
        setStatus(`Exported ${result.output_path}`);
        setExportProgress({
          status: "complete",
          message: result.normalized
            ? `Cut and normalized export finished. The original cut remains at ${result.cut_output_path}`
            : "Export finished.",
          outputPath: result.output_path,
        });
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        setStatus(message);
        setExportProgress({
          status: "failed",
          message,
        });
      })
      .finally(() => setBusy(false));
  };

  const handleChooseCaptionVideo = () => {
    void run(
      () => chooseCaptionVideo(),
      (data) => {
        setCaptionSource(data.source);
        setCaptionOutputFolder(data.output_folder);
        setCaptionPreview(null);
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

  const audioPayload = {
    input_video_path: audioSource,
    preset_id: audioPresetId,
    target_i: audioTargetI,
    target_lra: audioTargetLra,
    target_tp: audioTargetTp,
  };

  const handleChooseAudioVideo = () => {
    void run(
      () => chooseAudioVideo(),
      (data) => {
        setAudioSource(data.source);
        setAudioOutputFolder(data.output_folder);
        setAudioAnalysis(null);
        setAudioPreview(null);
        setAudioStatus("Video selected. Analyze the audio to see its current levels.");
      },
    );
  };

  const handleChooseAudioOutputFolder = () => {
    void run(
      () => chooseAudioOutputFolder(),
      (data) => {
        setAudioOutputFolder(data.output_folder);
        setAudioStatus(`Output folder: ${data.output_folder}`);
      },
    );
  };

  const handleAnalyzeAudio = () => {
    setAudioStatus("Analyzing the complete audio track...");
    void run(
      async () => {
        try {
          return await analyzeVideoAudio(audioPayload);
        } catch (error) {
          setAudioStatus(error instanceof Error ? error.message : String(error));
          throw error;
        }
      },
      (data) => {
        setAudioAnalysis(data);
        setAudioStatus("Analysis complete. Review the measurements, then export when ready.");
      },
    );
  };

  const handleNormalizeAudio = () => {
    setAudioStatus("Creating a new video with corrected audio...");
    void run(
      async () => {
        try {
          return await normalizeVideoAudio({ ...audioPayload, output_folder: audioOutputFolder });
        } catch (error) {
          setAudioStatus(error instanceof Error ? error.message : String(error));
          throw error;
        }
      },
      (data) => setAudioStatus(`Done. Exported ${data.output_path}`),
    );
  };

  const handleGenerateAudioPreview = (startSeconds: number) => {
    setAudioStatus("Analyzing settings and creating the 20-second A/B preview...");
    void run(
      async () => {
        try {
          return await generateAudioPreview({
            ...audioPayload,
            start_seconds: startSeconds,
            duration_seconds: 20,
          });
        } catch (error) {
          setAudioStatus(error instanceof Error ? error.message : String(error));
          throw error;
        }
      },
      (data) => {
        setAudioPreview(data);
        setAudioAnalysis({
          source: audioSource ?? "",
          measurement: data.measurement,
          target: data.target,
          hotspots: data.hotspots,
          hotspot_message: data.hotspot_message,
        });
        setAudioStatus("Preview ready. Switch between Original and Corrected while listening.");
      },
    );
  };

  const handlePrepareCaptionPreview = () => {
    if (!captionPreset) return;
    void run(
      () => prepareCaptionPreview({
        input_video_path: captionSource,
        preset: captionPreset,
        model_label: captionModel,
        compute_label: captionCompute,
      }),
      (data) => {
        setCaptionPreview(data);
        setCaptionStatus(`Live preview ready: ${data.word_count} words${data.used_project_transcript ? " from project transcript" : ""}`);
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

  const handleSaveProject = () => {
    void run(
      async () => {
        const projectDocument = await getProjectDocument();
        return saveProjectDocument(projectDocument, projectFileHandleRef);
      },
      (fileName) => setStatus(`Saved ${fileName}`),
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

  const handleRenderCutPreview = () => {
    if (!project) return;
    setBusy(true);
    setPreviewRenderProgress({ status: "running", message: "Rendering the complete edited video as a fast review draft..." });
    renderCutPreview()
      .then((result) => {
        setRenderedCutPreview(result);
        setStatus(`Rendered complete ${formatTime(result.duration_seconds)} cut preview with ${result.splices.length} splice markers`);
        setPreviewRenderProgress({ status: "complete", message: "The complete rendered cut is ready for final review." });
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        setStatus(message);
        setPreviewRenderProgress({ status: "failed", message });
      })
      .finally(() => setBusy(false));
  };

  const seekRenderedJoin = (splice: DynamicSplice, autoplay = true) => {
    const video = renderedCutVideoRef.current;
    const marker = renderedBoundaryByAnchor.get(splice.anchor_key);
    if (!video || !marker) return;
    video.currentTime = Math.max(0, marker.preview_time_seconds - 2);
    if (autoplay) void video.play().catch((error) => setStatus(`Preview failed: ${error.message}`));
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
      {transcriptionProgress && (
        <ProgressModal
          progress={transcriptionProgress}
        />
      )}
      {exportProgress && (
        <ExportProgressModal
          progress={exportProgress}
          onClose={() => setExportProgress(null)}
        />
      )}
      {previewRenderProgress && (
        <PreviewRenderModal progress={previewRenderProgress} onClose={() => setPreviewRenderProgress(null)} />
      )}
      {showTranscriptSettings && project && (
        <TranscriptSettingsModal
          busy={busy}
          project={project}
          close={() => setShowTranscriptSettings(false)}
          update={(threshold) => void run(
            () => updateEditorSettings(threshold),
            applyProject,
          )}
        />
      )}
      <header className="topbar modern-topbar">
        <div className="brand-block">
          <h1>VCG Content Command Center</h1>
          <p>Local web editor for transcript cuts and source-video splice review</p>
        </div>
        <div className="header-menu tools-menu">
          <button className="header-menu-trigger" aria-haspopup="menu">
            <Grid3X3 size={17} /> Tools <ChevronDown size={14} />
          </button>
          <div className="header-dropdown" role="menu">
            <button className={activeTab === "transcript" ? "active" : ""} onClick={() => setActiveTab("transcript")}>
              Transcript Edit
            </button>
            <button className={activeTab === "caption" ? "active" : ""} onClick={() => setActiveTab("caption")}>
              Caption Generator
            </button>
            <button className={activeTab === "audio" ? "active" : ""} onClick={() => setActiveTab("audio")}>
              Audio Normalizer
            </button>
          </div>
        </div>

        {activeTab === "transcript" ? (
          <nav className="workflow-rail" aria-label="Transcript workflow">
            <WorkflowStage stage={1} activeStage={activeWorkflowStage} setActiveStage={setActiveWorkflowStage}>
              <span className="workflow-stage-label">Source</span>
              <button className="workflow-action" onClick={handleChooseTranscriptVideo} disabled={busy}>
                <FolderOpen size={15} /> Open Video
              </button>
              <button className="workflow-action emphasized" onClick={handleGenerateTranscript} disabled={busy || !transcriptSource}>
                <Upload size={15} /> Generate Transcript
              </button>
            </WorkflowStage>
            <WorkflowStage stage={2} activeStage={activeWorkflowStage} setActiveStage={setActiveWorkflowStage}>
              <span className="workflow-stage-label">Pauses</span>
              <button
                className="workflow-action teal"
                onClick={() => void run(analyzePauses, (data) => {
                  applyProject(data);
                  const summary = data.pause_analysis_summary;
                  if (summary) setStatus(`Analyze Pauses: ${summary.candidates_checked} checked, ${summary.validated_long_pauses} validated, ${summary.rejected_candidates} rejected`);
                })}
                disabled={busy || !project || project.pause_analysis_pending_count === 0}
              >
                <Gauge size={15} /> Analyze Pauses
              </button>
              <button
                className="workflow-action"
                onClick={() => void run(deleteDeadSpace, applyProject)}
                disabled={busy || !project || project.dead_space_candidate_count === 0 || project.pause_analysis_pending_count > 0}
              >
                <Scissors size={15} /> Remove {project?.dead_space_candidate_count ?? 0} Long Pauses
              </button>
            </WorkflowStage>
            <WorkflowStage stage={3} activeStage={activeWorkflowStage} setActiveStage={setActiveWorkflowStage}>
              <span className="workflow-stage-label">Cuts</span>
              <button
                className="workflow-action emphasized"
                onClick={() => void run(analyzeBoundaries, (data) => {
                  applyProject(data);
                  const summary = data.fine_tune_summary;
                  if (summary) setStatus(`Fine Tune: ${summary.cuts_checked} cuts checked, ${summary.cuts_adjusted} adjusted, ${summary.cuts_unchanged} unchanged`);
                })}
                disabled={busy || !project || !project.splices.some((splice) => !splice.reviewed && splice.left_word_id)}
              >
                <WandSparkles size={15} /> Fine Tune
              </button>
              <span className="workflow-status">
                {project?.splices.filter((splice) => splice.reviewed).length ?? 0} / {project?.splices.length ?? 0} Reviewed
              </span>
            </WorkflowStage>
            <WorkflowStage stage={4} activeStage={activeWorkflowStage} setActiveStage={setActiveWorkflowStage}>
              <span className="workflow-stage-label">Preview</span>
              <button
                className="workflow-action teal"
                onClick={handleRenderCutPreview}
                disabled={busy || !project}
              >
                <Play size={15} /> {renderedCutPreview ? "Refresh Preview" : "Render Cut Preview"}
              </button>
            </WorkflowStage>
            <WorkflowStage stage={5} activeStage={activeWorkflowStage} setActiveStage={setActiveWorkflowStage}>
              <span className="workflow-stage-label">Output</span>
              <label className="workflow-toggle" title="Normalize the completed cut with the existing two-pass audio normalizer">
                <input
                  type="checkbox"
                  checked={normalizeCutAudio}
                  onChange={(event) => setNormalizeCutAudio(event.target.checked)}
                  disabled={busy}
                />
                Normalize audio
              </label>
              {normalizeCutAudio && (
                <select
                  className="workflow-select"
                  aria-label="Audio normalization preset"
                  value={audioPresetId}
                  onChange={(event) => setAudioPresetId(event.target.value)}
                  disabled={busy}
                >
                  {(audioOptionsData?.presets ?? []).map((preset) => (
                    <option key={preset.id} value={preset.id}>{preset.name}</option>
                  ))}
                </select>
              )}
              <button className="workflow-action emphasized" onClick={handleExportCut} disabled={busy || !project}>
                <Upload size={15} /> {normalizeCutAudio ? "Export Final" : "Export Cut"}
              </button>
            </WorkflowStage>
          </nav>
        ) : (
          <div className="contextual-tool-actions">
            {activeTab === "caption" ? (
              <>
                <button onClick={handleChooseCaptionVideo} disabled={busy}><FolderOpen size={16} /> Choose Video</button>
                <button className="outline-primary" onClick={handleGenerateCaptions} disabled={busy || !captionStyle || !captionPreset || !captionSource}><Upload size={16} /> Generate Captioned Video</button>
              </>
            ) : (
              <>
                <button onClick={handleChooseAudioVideo} disabled={busy}><FolderOpen size={16} /> Choose Video</button>
                <button onClick={handleAnalyzeAudio} disabled={busy || !audioSource}><Gauge size={16} /> Analyze Audio</button>
                <button className="outline-primary" onClick={handleNormalizeAudio} disabled={busy || !audioAnalysis}><WandSparkles size={16} /> Export Corrected Video</button>
              </>
            )}
          </div>
        )}

        <div className="header-utilities">
          <div className="header-menu project-menu">
            <button className="header-menu-trigger" aria-haspopup="menu"><FolderOpen size={17} /> Project <ChevronDown size={14} /></button>
            <div className="header-dropdown project-dropdown" role="menu">
              <button onClick={handleOpen} disabled={busy}><FolderOpen size={15} /> Open Project</button>
              <button onClick={handleSaveProject} disabled={busy || !project}><Save size={15} /> Save Project</button>
            </div>
          </div>
          <button className="header-icon-button" aria-label="Save project" title="Save project" onClick={handleSaveProject} disabled={busy || !project}><Save size={18} /></button>
          <button className="header-icon-button" aria-label="Transcript settings" title="Transcript settings" onClick={() => setShowTranscriptSettings(true)} disabled={busy || !project || activeTab !== "transcript"}><Settings size={18} /></button>
        </div>
      </header>

      {activeTab === "transcript" && activeWorkflowStage === 4 && renderedCutPreview && project ? (
        <RenderedCutPreviewWorkspace
          busy={busy}
          onRefresh={handleRenderCutPreview}
          pendingFrames={pendingPreviewFrames}
          preview={renderedCutPreview}
          project={project}
          reviewSpliceAndAdvance={reviewSpliceAndAdvance}
          seekRenderedJoin={seekRenderedJoin}
          selectSplice={(splice) => {
            setActiveSplice(splice.anchor_key);
            seekRenderedJoin(splice);
          }}
          selectedSplice={selectedSplice}
          selectedSpliceIndex={selectedSpliceIndex}
          stale={renderedPreviewStale}
          updateSplice={updateSplice}
          videoRef={renderedCutVideoRef}
        />
      ) : activeTab === "transcript" ? (
        <section className="workspace">
        <div className="left-stack">
          <section className="preview-panel" ref={previewPanelRef}>
            <div className="panel-title">
              <span className="eyebrow">Source Preview</span>
              <span>{project?.project.source ?? transcriptSource ?? "No video selected"}</span>
            </div>
            <div className="preview-media" style={previewBox}>
              <video
                ref={previewRef}
                key={transcriptVideoKey}
                controls
                preload="metadata"
                src={transcriptVideoKey ? `${sourceVideoUrl()}?source=${encodeURIComponent(transcriptVideoKey)}` : undefined}
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
      ) : activeTab === "caption" ? (
        <CaptionGenerator
          busy={busy}
          captionCompute={captionCompute}
          captionModel={captionModel}
          captionOptionsData={captionOptionsData}
          captionOutputFolder={captionOutputFolder}
          captionPreset={captionPreset}
          captionPreview={captionPreview}
          captionSource={captionSource}
          captionStatus={captionStatus}
          captionStyle={captionStyle}
          captionStyleName={captionStyleName}
          handleChooseCaptionOutputFolder={handleChooseCaptionOutputFolder}
          handleDeleteCaptionStyle={handleDeleteCaptionStyle}
          handlePrepareCaptionPreview={handlePrepareCaptionPreview}
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
      ) : (
        <AudioNormalizer
          analysis={audioAnalysis}
          busy={busy}
          options={audioOptionsData}
          outputFolder={audioOutputFolder}
          presetId={audioPresetId}
          preview={audioPreview}
          source={audioSource}
          status={audioStatus}
          targetI={audioTargetI}
          targetLra={audioTargetLra}
          targetTp={audioTargetTp}
          onChooseOutputFolder={handleChooseAudioOutputFolder}
          onClearPreview={() => setAudioPreview(null)}
          onGeneratePreview={handleGenerateAudioPreview}
          onPreviewHotspot={(startSeconds) => handleGenerateAudioPreview(startSeconds)}
          onPresetChange={(value) => {
            setAudioPresetId(value);
            setAudioAnalysis(null);
            setAudioPreview(null);
            setAudioStatus("Preset changed. Analyze again before exporting.");
          }}
          onOutputFolderChange={setAudioOutputFolder}
          onTargetIChange={(value) => {
            setAudioTargetI(value);
            setAudioAnalysis(null);
            setAudioPreview(null);
          }}
          onTargetLraChange={(value) => {
            setAudioTargetLra(value);
            setAudioAnalysis(null);
            setAudioPreview(null);
          }}
          onTargetTpChange={(value) => {
            setAudioTargetTp(value);
            setAudioAnalysis(null);
            setAudioPreview(null);
          }}
        />
      )}
    </main>
  );
}

function AudioNormalizer({
  analysis,
  busy,
  options,
  outputFolder,
  presetId,
  preview,
  source,
  status,
  targetI,
  targetLra,
  targetTp,
  onChooseOutputFolder,
  onClearPreview,
  onGeneratePreview,
  onPreviewHotspot,
  onOutputFolderChange,
  onPresetChange,
  onTargetIChange,
  onTargetLraChange,
  onTargetTpChange,
}: {
  analysis: AudioAnalysisResponse | null;
  busy: boolean;
  options: AudioOptionsResponse | null;
  outputFolder: string;
  presetId: string;
  preview: AudioPreviewResponse | null;
  source: string | null;
  status: string;
  targetI: number;
  targetLra: number;
  targetTp: number;
  onChooseOutputFolder: () => void;
  onClearPreview: () => void;
  onGeneratePreview: (startSeconds: number) => void;
  onPreviewHotspot: (startSeconds: number) => void;
  onOutputFolderChange: (value: string) => void;
  onPresetChange: (value: string) => void;
  onTargetIChange: (value: number) => void;
  onTargetLraChange: (value: number) => void;
  onTargetTpChange: (value: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playheadSeconds, setPlayheadSeconds] = useState(0);
  const [previewMode, setPreviewMode] = useState<"original" | "corrected">("corrected");
  const [previewCurrentSeconds, setPreviewCurrentSeconds] = useState(0);
  const [previewClipDuration, setPreviewClipDuration] = useState(20);
  const [sourceDuration, setSourceDuration] = useState(0);
  const [isPreviewPlaying, setIsPreviewPlaying] = useState(false);
  const [isPreviewMuted, setIsPreviewMuted] = useState(false);
  const switchTimeRef = useRef(0);
  const switchWasPlayingRef = useRef(false);

  useEffect(() => {
    setPreviewMode("corrected");
    setPreviewCurrentSeconds(0);
    setIsPreviewPlaying(false);
    switchTimeRef.current = 0;
  }, [preview?.preview_id]);

  const generatePreviewAtPlayhead = () => {
    const video = videoRef.current;
    const current = video?.currentTime ?? playheadSeconds;
    const duration = video?.duration;
    const latestStart = duration && Number.isFinite(duration) ? Math.max(0, duration - 20) : current;
    onGeneratePreview(Math.max(0, Math.min(current, latestStart)));
  };

  const switchPreviewMode = (mode: "original" | "corrected") => {
    switchTimeRef.current = videoRef.current?.currentTime ?? 0;
    switchWasPlayingRef.current = !(videoRef.current?.paused ?? true);
    setPreviewMode(mode);
  };

  const togglePreviewPlayback = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play();
    } else {
      video.pause();
    }
  };

  const seekPreviewSourceTime = (sourceTime: number) => {
    const video = videoRef.current;
    if (!video || !preview) return;
    const clipTime = Math.max(0, Math.min(sourceTime - preview.start_seconds, previewClipDuration));
    video.currentTime = clipTime;
    setPreviewCurrentSeconds(clipTime);
  };

  const playerSource = preview
    ? audioPreviewUrl(preview.preview_id, previewMode)
    : source
      ? `${audioSourceVideoUrl()}?source=${encodeURIComponent(source)}`
      : undefined;
  const hotspots = analysis?.hotspots ?? null;

  return (
    <section className="audio-workspace">
      <section className="audio-preview-panel">
        <div className="panel-title">
          <span className="eyebrow">Source Video</span>
          <span>{source ?? "No video selected"}</span>
        </div>
        <div className="audio-preview-media">
          {playerSource ? (
            <video
              ref={videoRef}
              key={preview ? `${preview.preview_id}-${previewMode}` : source}
              controls={!preview}
              preload="metadata"
              src={playerSource}
              onLoadedMetadata={(event) => {
                const video = event.currentTarget;
                if (preview) {
                  const duration = Number.isFinite(video.duration) ? video.duration : preview.duration_seconds;
                  setPreviewClipDuration(duration);
                  const restoredTime = Math.min(switchTimeRef.current, duration);
                  video.currentTime = restoredTime;
                  setPreviewCurrentSeconds(restoredTime);
                  video.muted = isPreviewMuted;
                  if (switchWasPlayingRef.current) {
                    switchWasPlayingRef.current = false;
                    void video.play();
                  }
                } else if (Number.isFinite(video.duration)) {
                  setSourceDuration(video.duration);
                }
              }}
              onTimeUpdate={(event) => {
                if (preview) {
                  setPreviewCurrentSeconds(event.currentTarget.currentTime);
                } else {
                  setPlayheadSeconds(event.currentTarget.currentTime);
                }
              }}
              onSeeked={(event) => {
                if (preview) {
                  setPreviewCurrentSeconds(event.currentTarget.currentTime);
                } else {
                  setPlayheadSeconds(event.currentTarget.currentTime);
                }
              }}
              onPlay={() => setIsPreviewPlaying(true)}
              onPause={() => setIsPreviewPlaying(false)}
              onEnded={() => setIsPreviewPlaying(false)}
            />
          ) : (
            <div className="empty preview-empty">Choose a video from the toolbar</div>
          )}
        </div>
        {preview && (
          <div className="source-time-controls">
            <button className="icon-control" onClick={togglePreviewPlayback} disabled={busy} title={isPreviewPlaying ? "Pause preview" : "Play preview"}>
              {isPreviewPlaying ? <Pause size={17} /> : <Play size={17} />}
            </button>
            <span className="source-time-current">{formatPreciseTime(preview.start_seconds + previewCurrentSeconds)}</span>
            <input
              aria-label="Preview position in source video"
              type="range"
              min={preview.start_seconds}
              max={preview.start_seconds + previewClipDuration}
              step={0.1}
              value={preview.start_seconds + previewCurrentSeconds}
              onChange={(event) => seekPreviewSourceTime(Number(event.target.value))}
            />
            <span className="source-time-end">{formatPreciseTime(preview.start_seconds + previewClipDuration)}</span>
            {sourceDuration > 0 && <span className="source-duration">of {formatTime(sourceDuration)}</span>}
            <button
              className="icon-control"
              onClick={() => {
                const muted = !isPreviewMuted;
                setIsPreviewMuted(muted);
                if (videoRef.current) videoRef.current.muted = muted;
              }}
              disabled={busy}
              title={isPreviewMuted ? "Unmute preview" : "Mute preview"}
            >
              {isPreviewMuted ? <VolumeX size={17} /> : <Volume2 size={17} />}
            </button>
          </div>
        )}
        {source && (
          <div className="audio-preview-controls">
            {preview ? (
              <>
                <div className="preview-mode-switch" aria-label="Preview audio version">
                  <button className={previewMode === "original" ? "active" : ""} onClick={() => switchPreviewMode("original")} disabled={busy}>
                    Original
                  </button>
                  <button className={previewMode === "corrected" ? "active" : ""} onClick={() => switchPreviewMode("corrected")} disabled={busy}>
                    Corrected
                  </button>
                </div>
                <span>Source range {formatPreciseTime(preview.start_seconds)}–{formatPreciseTime(preview.start_seconds + previewClipDuration)}</span>
                <button onClick={onClearPreview} disabled={busy}>Choose another section</button>
              </>
            ) : (
              <>
                <span>Move the video playhead to the section you want to compare.</span>
                <button className="preview-generate" onClick={generatePreviewAtPlayhead} disabled={busy}>
                  <Headphones size={16} /> Generate 20-Second Preview at {formatTime(playheadSeconds)}
                </button>
              </>
            )}
          </div>
        )}
        <div className="audio-status" aria-live="polite">
          <Volume2 size={18} />
          <span>{busy ? "Processing audio. This can take about the length of the video." : status}</span>
        </div>
        <div className="folder-row">
          <label>
            Output folder
            <input value={outputFolder} onChange={(event) => onOutputFolderChange(event.target.value)} />
          </label>
          <button onClick={onChooseOutputFolder} disabled={busy}>
            <FolderOpen size={16} /> Change
          </button>
        </div>
      </section>

      <section className="audio-controls">
        <SettingsCard title="Choose Correction Strength">
          <div className="audio-preset-list">
            {(options?.presets ?? []).map((preset) => (
              <button
                key={preset.id}
                className={preset.id === presetId ? "audio-preset active" : "audio-preset"}
                onClick={() => onPresetChange(preset.id)}
                disabled={busy}
              >
                <span>{preset.name}</span>
                <small>{preset.description}</small>
              </button>
            ))}
          </div>
          {presetId === "strong" && (
            <div className="audio-warning">
              Strong leveling may make room noise, breaths, and microphone hiss more noticeable.
            </div>
          )}
        </SettingsCard>

        <div className="audio-results-stack">
          <SettingsCard title="Audio Measurements">
            {analysis ? (
              <>
                {presetId !== "normalize" && (
                  <div className="measurement-note">
                    Measurements include the selected voice leveling and show the signal immediately before final loudness normalization.
                  </div>
                )}
                <div className="measurement-grid">
                  <Measurement label={presetId === "normalize" ? "Source loudness" : "After leveling"} value={`${analysis.measurement.input_i.toFixed(1)} LUFS`} />
                  <Measurement label="Target loudness" value={`${analysis.target.integrated_lufs.toFixed(1)} LUFS`} emphasized />
                  <Measurement label={presetId === "normalize" ? "Source true peak" : "Leveled true peak"} value={`${analysis.measurement.input_tp.toFixed(1)} dBTP`} />
                  <Measurement label="Peak ceiling" value={`${analysis.target.true_peak_dbtp.toFixed(1)} dBTP`} />
                  <Measurement label={presetId === "normalize" ? "Source loudness range" : "Leveled range"} value={`${analysis.measurement.input_lra.toFixed(1)} LU`} />
                  <Measurement label="Target loudness range" value={`${analysis.target.loudness_range_lu.toFixed(1)} LU`} />
                </div>
                {hotspots ? <div className="hotspot-grid">
                  <button className="hotspot-option loudest" onClick={() => onPreviewHotspot(hotspots.loudest.start_seconds)} disabled={busy}>
                    <span>Loudest speech</span>
                    <strong>{formatTime(hotspots.loudest.focus_seconds)}</strong>
                    <small>{hotspots.loudest.loudness_lufs.toFixed(1)} LUFS near this point</small>
                    <em>Preview the section most likely to be turned down</em>
                  </button>
                  <button className="hotspot-option quietest" onClick={() => onPreviewHotspot(hotspots.quietest_speech.start_seconds)} disabled={busy}>
                    <span>Quietest speech</span>
                    <strong>{formatTime(hotspots.quietest_speech.focus_seconds)}</strong>
                    <small>{hotspots.quietest_speech.loudness_lufs.toFixed(1)} LUFS near this point</small>
                    <em>Preview the section most likely to be raised</em>
                  </button>
                </div> : (
                  <div className="measurement-note">
                    {analysis.hotspot_message ?? "No speech sections were available for automatic loud and quiet previews."}
                  </div>
                )}
              </>
            ) : (
              <div className="analysis-empty">
                <Gauge size={28} />
                <strong>No measurements yet</strong>
                <span>Analyze the video to measure its full audio track before export.</span>
              </div>
            )}
          </SettingsCard>

          <SettingsCard title="Advanced Targets">
            <div className="advanced-copy">The defaults are tuned for spoken-word YouTube videos. Change these only when you have a specific delivery requirement.</div>
            <div className="audio-target-grid">
              <NumberField label="Integrated loudness (LUFS)" value={targetI} min={-24} max={-10} step={0.5} onChange={onTargetIChange} />
              <NumberField label="True peak ceiling (dBTP)" value={targetTp} min={-3} max={-1} step={0.1} onChange={onTargetTpChange} />
              <NumberField label="Loudness range (LU)" value={targetLra} min={1} max={20} step={0.5} onChange={onTargetLraChange} />
            </div>
          </SettingsCard>
        </div>
      </section>
    </section>
  );
}

function formatTime(seconds: number) {
  const wholeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(wholeSeconds / 60);
  const remainingSeconds = wholeSeconds % 60;
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

function formatPreciseTime(seconds: number) {
  const safeSeconds = Math.max(0, seconds);
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds - minutes * 60;
  return `${minutes}:${remainingSeconds.toFixed(1).padStart(4, "0")}`;
}

function Measurement({ label, value, emphasized = false }: { label: string; value: string; emphasized?: boolean }) {
  return (
    <div className={emphasized ? "measurement emphasized" : "measurement"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
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
                    .filter((silence) => {
                      const effectiveStartFrame = silence.measured_start_frame ?? silence.start_frame;
                      const effectiveEndFrame = silence.measured_end_frame ?? silence.end_frame;
                      return silence.start_frame === word.end_frame + 1
                        && (effectiveEndFrame - effectiveStartFrame + 1) / (project?.project.fps ?? 1)
                          >= (project?.settings.dead_space_min_seconds ?? Number.POSITIVE_INFINITY);
                    })
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
                        {silence.audio_analyzed ? "DEAD SPACE" : "PAUSE CANDIDATE"} {((silence.measured_end ?? silence.end) - (silence.measured_start ?? silence.start)).toFixed(2)}s
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
  captionPreview,
  captionSource,
  captionStatus,
  captionStyle,
  captionStyleName,
  handleChooseCaptionOutputFolder,
  handleDeleteCaptionStyle,
  handlePrepareCaptionPreview,
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
  captionPreview: CaptionPreviewResponse | null;
  captionSource: string | null;
  captionStatus: string;
  captionStyle: CaptionStylePayload | null;
  captionStyleName: string;
  handleChooseCaptionOutputFolder: () => void;
  handleDeleteCaptionStyle: () => void;
  handlePrepareCaptionPreview: () => void;
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
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const captionMediaRef = useRef<HTMLDivElement | null>(null);
  const [videoTime, setVideoTime] = useState(0);
  const [captionGeometry, setCaptionGeometry] = useState({
    left: 0,
    top: 0,
    width: 0,
    height: 0,
    scale: 1,
  });
  const captionVideoKey = captionSource ?? "";
  const livePreviewGroups = useMemo(
    () => captionPreview ? groupCaptionPreviewWords(captionPreview.words, captionPreset) : null,
    [captionPreset, captionPreview],
  );
  const activePreviewGroup = useMemo(
    () => livePreviewGroups?.find((group) => videoTime >= group.start && videoTime <= group.end) ?? null,
    [livePreviewGroups, videoTime],
  );
  const updateCaptionGeometry = useCallback(() => {
    const media = captionMediaRef.current;
    const video = videoRef.current;
    if (!media || !video || !video.videoWidth || !video.videoHeight) return;

    const containerWidth = media.clientWidth;
    const containerHeight = media.clientHeight;
    const videoAspect = video.videoWidth / video.videoHeight;
    const containerAspect = containerWidth / containerHeight;
    const width = containerAspect > videoAspect ? containerHeight * videoAspect : containerWidth;
    const height = containerAspect > videoAspect ? containerHeight : containerWidth / videoAspect;

    setCaptionGeometry({
      left: (containerWidth - width) / 2,
      top: (containerHeight - height) / 2,
      width,
      height,
      scale: width / video.videoWidth,
    });
  }, []);

  useEffect(() => {
    const media = captionMediaRef.current;
    if (!media) return;
    const observer = new ResizeObserver(updateCaptionGeometry);
    observer.observe(media);
    return () => observer.disconnect();
  }, [updateCaptionGeometry]);

  const selectStyle = (name: string) => {
    setCaptionStyleName(name);
    setCaptionStyle(captionOptionsData.styles[name] ?? captionOptionsData.default_style);
  };

  const selectPreset = (name: string) => {
    setCaptionPreset(captionOptionsData.presets[name] ?? captionPreset);
  };
  const previewScale = captionGeometry.scale;
  const horizontalMargin = Math.max(50, (videoRef.current?.videoWidth ?? 0) * 0.08) * previewScale;
  const verticalMargin = captionStyle.margin_v * previewScale;
  const captionPositionStyle = captionPreviewPositionStyle(
    captionStyle.position,
    captionGeometry,
    horizontalMargin,
    verticalMargin,
  );

  return (
    <section className="caption-workspace">
      <section className="caption-preview-panel">
        <div className="panel-title">
          <span className="eyebrow">Caption Preview</span>
          <span>{captionSource ?? "Choose a video to generate captions"}</span>
        </div>
        <div className="caption-preview-media" ref={captionMediaRef}>
          {captionSource ? (
            <video
              ref={videoRef}
              key={captionSource}
              controls
              preload="metadata"
              src={`${captionSourceVideoUrl()}?source=${encodeURIComponent(captionVideoKey)}`}
              onTimeUpdate={(event) => setVideoTime(event.currentTarget.currentTime)}
              onSeeked={(event) => setVideoTime(event.currentTarget.currentTime)}
              onLoadedMetadata={(event) => {
                setVideoTime(event.currentTarget.currentTime);
                updateCaptionGeometry();
              }}
            />
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
              ...captionPositionStyle,
              color: captionStyle.main_color,
              fontFamily: previewFontStack(captionStyle.font_family),
              fontSize: `${captionStyle.main_font_size * previewScale}px`,
              fontWeight: captionStyle.bold ? 700 : 400,
              textShadow: captionPreviewTextShadow(captionStyle, previewScale),
            }}
          >
            {activePreviewGroup ? (
              <LiveCaptionWords group={activePreviewGroup} previewScale={previewScale} style={captionStyle} videoTime={videoTime} />
            ) : captionPreview ? null : (
              <SampleCaptionWords preset={captionPreset} previewScale={previewScale} style={captionStyle} />
            )}
          </div>
        </div>
        <button onClick={handlePrepareCaptionPreview} disabled={busy || !captionSource || !captionPreset}>
          <Play size={16} /> Prepare Live Preview
        </button>
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

function LiveCaptionWords({ group, previewScale, style, videoTime }: { group: CaptionPreviewGroup; previewScale: number; style: CaptionStylePayload; videoTime: number }) {
  return (
    <>
      {group.words.map((word, wordIndex) => {
        const active = videoTime >= word.start && videoTime <= word.end;
        return (
          <CaptionWordSpan
            active={active}
            key={`${word.text}-${word.start}-${wordIndex}`}
            previewScale={previewScale}
            style={style}
            text={word.text}
            trailingSpace={wordIndex < group.words.length - 1}
          />
        );
      })}
    </>
  );
}

function SampleCaptionWords({ preset, previewScale, style }: { preset: CaptionPresetPayload; previewScale: number; style: CaptionStylePayload }) {
  const words = captionPreviewWords(preset);
  return (
    <>
      {words.map((word, wordIndex) => (
        <CaptionWordSpan
          active={wordIndex === Math.min(1, words.length - 1)}
          key={`${word}-${wordIndex}`}
          previewScale={previewScale}
          style={style}
          text={word}
          trailingSpace={wordIndex < words.length - 1}
        />
      ))}
    </>
  );
}

function CaptionWordSpan({
  active,
  previewScale,
  style,
  text,
  trailingSpace,
}: {
  active: boolean;
  previewScale: number;
  style: CaptionStylePayload;
  text: string;
  trailingSpace: boolean;
}) {
  return (
    <span
      style={active ? {
        color: style.active_color,
        fontSize: `${style.active_font_size * previewScale}px`,
        fontWeight: style.active_bold ? 700 : 400,
      } : undefined}
    >
      {text}
      {trailingSpace ? " " : ""}
    </span>
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

function captionPreviewTextShadow(style: CaptionStylePayload, previewScale: number) {
  const shadows = [];
  if (style.outline_enabled) {
    const width = Math.max(0.5, style.outline_width * previewScale);
    shadows.push(...outlineTextShadows(width, style.outline_color));
  }
  if (style.shadow_enabled) {
    const depth = style.shadow_depth * previewScale;
    shadows.push(`${depth}px ${depth}px 0 ${style.shadow_color}`);
  }
  if (style.glow_enabled) shadows.push(`0 0 ${Math.max(1, style.glow_strength * 1.8 * previewScale)}px ${style.glow_color}`);
  return shadows.join(", ");
}

function captionPreviewPositionStyle(
  position: string,
  geometry: { left: number; top: number; width: number; height: number },
  horizontalMargin: number,
  verticalMargin: number,
) {
  const base = {
    left: `${geometry.left + horizontalMargin}px`,
    right: "auto",
    width: `${Math.max(0, geometry.width - (horizontalMargin * 2))}px`,
    bottom: "auto",
  };
  if (position === "Middle") {
    return {
      ...base,
      top: `${geometry.top + (geometry.height / 2)}px`,
      transform: "translateY(-50%)",
    };
  }
  if (position === "Top") {
    return {
      ...base,
      top: `${geometry.top + verticalMargin}px`,
      transform: "none",
    };
  }
  return {
    ...base,
    top: `${geometry.top + geometry.height - verticalMargin}px`,
    transform: "translateY(-100%)",
  };
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

function groupCaptionPreviewWords(words: CaptionPreviewResponse["words"], preset: CaptionPresetPayload) {
  const groups: CaptionPreviewGroup[] = [];
  let current: CaptionPreviewResponse["words"] = [];

  for (const word of words) {
    const text = word.text.trim();
    if (!text || word.end <= word.start) continue;
    const normalized = { ...word, text };
    if (!current.length) {
      current = [normalized];
      continue;
    }

    const proposed = [...current, normalized];
    const proposedText = proposed.map((item) => item.text).join(" ");
    const proposedDuration = proposed[proposed.length - 1].end - proposed[0].start;
    const shouldBreak =
      proposed.length > preset.max_words ||
      proposedDuration > preset.max_duration ||
      proposedText.length > preset.max_chars ||
      current[current.length - 1].text.endsWith(".") ||
      current[current.length - 1].text.endsWith("?") ||
      current[current.length - 1].text.endsWith("!");

    if (shouldBreak) {
      groups.push({ start: current[0].start, end: current[current.length - 1].end, words: current });
      current = [normalized];
    } else {
      current = proposed;
    }
  }

  if (current.length) {
    groups.push({ start: current[0].start, end: current[current.length - 1].end, words: current });
  }
  return groups;
}

function outlineTextShadows(width: number, color: string) {
  const shadows: string[] = [];
  for (let offset = 0.5; offset <= width; offset += 0.5) {
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

async function pollTranscriptionJob(
  jobId: string,
  setProgress: Dispatch<SetStateAction<TranscriptionJobStatus | null>>,
) {
  for (;;) {
    await delay(400);
    const status = await getTranscriptionJob(jobId);
    setProgress(status);
    if (status.status === "complete" && status.result) {
      return status.result;
    }
    if (status.status === "failed") {
      throw new Error(status.error ?? status.message);
    }
  }
}

async function saveProjectDocument(
  projectDocument: ProjectDocumentResponse,
  fileHandleRef: MutableRefObject<ProjectFileHandle | null>,
) {
  const contents = `${JSON.stringify(projectDocument.document, null, 2)}\n`;
  const blob = new Blob([contents], { type: "application/json" });
  const picker = (window as WindowWithSaveFilePicker).showSaveFilePicker;

  if (picker) {
    const handle = fileHandleRef.current ?? await picker({
      suggestedName: projectDocument.filename,
      types: [
        {
          description: "VCG project",
          accept: { "application/json": [".vcg.json", ".json"] },
        },
      ],
    });
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    fileHandleRef.current = handle;
    return handle.name;
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = projectDocument.filename;
  link.click();
  URL.revokeObjectURL(url);
  return projectDocument.filename;
}

function delay(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function ProgressModal({ progress }: { progress: TranscriptionJobStatus }) {
  const determinate = progress.value >= 0;
  const clamped = Math.max(0, Math.min(100, progress.value));
  return (
    <div className="modal-backdrop" role="status" aria-live="polite">
      <div className="progress-modal">
        <span className="eyebrow">Transcript Generation</span>
        <h2>Generating transcript</h2>
        <p>{progress.message}</p>
        <div className={determinate ? "progress-track" : "progress-track indeterminate"}>
          <div className="progress-bar" style={determinate ? { width: `${clamped}%` } : undefined} />
        </div>
        <strong>{determinate ? `${clamped}%` : "Working..."}</strong>
      </div>
    </div>
  );
}

function ExportProgressModal({
  onClose,
  progress,
}: {
  onClose: () => void;
  progress: ExportProgressState;
}) {
  const running = progress.status === "running";
  const failed = progress.status === "failed";
  return (
    <div className="modal-backdrop" role="status" aria-live="polite">
      <div className={failed ? "progress-modal failed" : "progress-modal"}>
        <span className="eyebrow">Video Export</span>
        <h2>{running ? "Exporting cut" : failed ? "Export failed" : "Export complete"}</h2>
        <p>{progress.message}</p>
        {progress.outputPath && <p className="modal-path">{progress.outputPath}</p>}
        <div className={running ? "progress-track indeterminate" : "progress-track"}>
          <div className="progress-bar" style={running ? undefined : { width: "100%" }} />
        </div>
        {running ? (
          <strong>Working...</strong>
        ) : (
          <button className="modal-action" onClick={onClose}>
            OK
          </button>
        )}
      </div>
    </div>
  );
}

function PreviewRenderModal({
  onClose,
  progress,
}: {
  onClose: () => void;
  progress: ExportProgressState;
}) {
  const running = progress.status === "running";
  const failed = progress.status === "failed";
  return (
    <div className="modal-backdrop" role="status" aria-live="polite">
      <div className={failed ? "progress-modal failed" : "progress-modal"}>
        <span className="eyebrow">Stage 4 Preview</span>
        <h2>{running ? "Rendering complete cut" : failed ? "Preview render failed" : "Preview ready"}</h2>
        <p>{progress.message}</p>
        <div className={running ? "progress-track indeterminate" : "progress-track"}>
          <div className="progress-bar" style={running ? undefined : { width: "100%" }} />
        </div>
        {running ? <strong>Working...</strong> : <button className="modal-action" onClick={onClose}>{failed ? "Close" : "Open Preview"}</button>}
      </div>
    </div>
  );
}

function TranscriptSettingsModal({
  busy,
  close,
  project,
  update,
}: {
  busy: boolean;
  close: () => void;
  project: EditorProjectResponse;
  update: (threshold: number) => void;
}) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="transcript-settings-title">
      <section className="transcript-settings-modal">
        <div className="settings-modal-header">
          <div>
            <span className="eyebrow">Transcript Settings</span>
            <h2 id="transcript-settings-title">Transcript editing</h2>
          </div>
          <button className="icon-button" aria-label="Close settings" onClick={close}><X size={17} /></button>
        </div>
        <h3>Long pause removal</h3>
        <p>Only detected pauses at or above this duration are removed by the toolbar action. Shorter cadence pauses remain untouched.</p>
        <label>
          <span>Minimum long-pause duration</span>
          <select
            disabled={busy}
            value={project.settings.dead_space_min_seconds}
            onChange={(event) => update(Number(event.target.value))}
          >
            {[0.5, 0.7, 0.8, 1, 1.5, 2].map((seconds) => (
              <option key={seconds} value={seconds}>{seconds.toFixed(1)} seconds</option>
            ))}
          </select>
        </label>
        <strong>{project.dead_space_candidate_count} pauses currently qualify</strong>
      </section>
    </div>
  );
}

function WorkflowStage({
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
        aria-label={`Open workflow stage ${stage}`}
        aria-expanded={active}
        onClick={() => setActiveStage(stage)}
      >
        {stage}
      </button>
      {active && <div className="workflow-stage-content">{children}</div>}
    </div>
  );
}

function RenderedCutPreviewWorkspace({
  busy,
  onRefresh,
  pendingFrames,
  preview,
  project,
  reviewSpliceAndAdvance,
  seekRenderedJoin,
  selectSplice,
  selectedSplice,
  selectedSpliceIndex,
  stale,
  updateSplice,
  videoRef,
}: {
  busy: boolean;
  onRefresh: () => void;
  pendingFrames: number;
  preview: RenderedCutPreviewResponse;
  project: EditorProjectResponse;
  reviewSpliceAndAdvance: (splice: DynamicSplice) => void;
  seekRenderedJoin: (splice: DynamicSplice, autoplay?: boolean) => void;
  selectSplice: (splice: DynamicSplice) => void;
  selectedSplice: DynamicSplice | undefined;
  selectedSpliceIndex: number;
  stale: boolean;
  updateSplice: (operation: () => Promise<EditorProjectResponse>) => void;
  videoRef: RefObject<HTMLVideoElement | null>;
}) {
  const previewMarkerByAnchor = new Map(preview.splices.map((splice) => [splice.anchor_key, splice]));
  const move = (direction: -1 | 1) => {
    const next = project.splices[selectedSpliceIndex + direction];
    if (next) selectSplice(next);
  };
  const isFrontTrim = selectedSplice?.left_word_id === "";
  return (
    <section className="rendered-cut-workspace">
      <aside className="rendered-cut-sidebar">
        <div className="rendered-sidebar-heading">
          <div>
            <span className="eyebrow">Final Review</span>
            <h2>Splices</h2>
          </div>
          <strong>{project.splices.length}</strong>
        </div>
        <div className="rendered-splice-list">
          {project.splices.map((splice, index) => {
            const marker = previewMarkerByAnchor.get(splice.anchor_key);
            return (
              <button
                key={splice.anchor_key}
                className={["rendered-splice-entry", selectedSplice?.anchor_key === splice.anchor_key ? "active" : "", splice.reviewed ? "reviewed" : ""].join(" ")}
                onClick={() => selectSplice(splice)}
              >
                <span>{index + 1}</span>
                <div>
                  <strong>{formatTime(marker?.preview_time_seconds ?? 0)}</strong>
                  <p><small>Before</small>{marker?.left_section || "Start of source"}</p>
                  <p><small>After</small>{marker?.right_section || splice.right_context}</p>
                </div>
              </button>
            );
          })}
        </div>
        <div className="rendered-sidebar-footer">
          <span>{project.splices.filter((splice) => splice.reviewed).length} reviewed</span>
          <span>{formatTime(preview.duration_seconds)}</span>
        </div>
      </aside>

      <section className="rendered-cut-main">
        <div className="rendered-cut-heading">
          <div>
            <span className="eyebrow">Stage 4</span>
            <h2>Rendered Cut Preview</h2>
          </div>
          {stale ? (
            <span className="preview-stale"><Gauge size={15} /> Preview stale · {pendingFrames} frame adjustment{pendingFrames === 1 ? "" : "s"} pending</span>
          ) : (
            <span className="preview-current"><Check size={15} /> Preview current</span>
          )}
        </div>
        <div className="rendered-cut-video">
          <video
            key={preview.preview_id}
            ref={videoRef}
            controls
            preload="metadata"
            src={renderedCutPreviewUrl(preview.preview_id)}
            onLoadedMetadata={() => selectedSplice && seekRenderedJoin(selectedSplice, false)}
          />
        </div>
        <div className="rendered-timeline" aria-label="Rendered cut splice timeline">
          <div className="rendered-timeline-track" />
          {preview.splices.map((marker, index) => (
            <button
              key={marker.anchor_key}
              className={selectedSplice?.anchor_key === marker.anchor_key ? "active" : ""}
              style={{ left: `${Math.min(100, Math.max(0, marker.preview_time_seconds / Math.max(preview.duration_seconds, 0.001) * 100))}%` }}
              title={`Splice ${index + 1} at ${formatTime(marker.preview_time_seconds)}`}
              onClick={() => {
                const splice = project.splices.find((item) => item.anchor_key === marker.anchor_key);
                if (splice) selectSplice(splice);
              }}
            >
              <Scissors size={16} />
              <span>{index + 1}</span>
            </button>
          ))}
          <div className="rendered-timeline-labels"><span>00:00</span><span>{formatTime(preview.duration_seconds)}</span></div>
        </div>

        <section className="rendered-splice-controls">
          <div className="rendered-control-heading">
            <h3>{selectedSplice ? `Splice ${selectedSpliceIndex + 1} of ${project.splices.length}` : "No splice selected"}</h3>
            <div className="rendered-control-actions">
              <button onClick={() => selectedSplice && seekRenderedJoin(selectedSplice)} disabled={!selectedSplice}><RotateCcw size={15} /> Replay Join</button>
              <button className={selectedSplice?.reviewed ? "reviewed" : ""} onClick={() => selectedSplice && reviewSpliceAndAdvance(selectedSplice)} disabled={!selectedSplice}>
                <Check size={15} /> {selectedSplice?.reviewed ? "Reviewed" : "Mark Reviewed"}
              </button>
              <button onClick={() => move(-1)} disabled={selectedSpliceIndex <= 0}><ChevronLeft size={15} /> Previous</button>
              <button onClick={() => move(1)} disabled={selectedSpliceIndex < 0 || selectedSpliceIndex >= project.splices.length - 1}>Next <ChevronRight size={15} /></button>
            </div>
          </div>
          {selectedSplice && (
            <div className={isFrontTrim ? "rendered-frame-grid single" : "rendered-frame-grid"}>
              {!isFrontTrim && (
                <CutFrameCard
                  title="OUT frame"
                  frame={selectedSplice.left_out_frame}
                  fps={project.project.fps}
                  adjustment={selectedSplice.left_out_adjustment}
                  whisperFrame={selectedSplice.left_whisper_out_frame}
                  suggestedFrame={selectedSplice.left_suggested_out_frame}
                  maxFrame={selectedSplice.right_in_frame - 1}
                  onNudge={(delta) => updateSplice(() => adjustSplice(selectedSplice.anchor_key, delta, 0))}
                />
              )}
              <CutFrameCard
                title={isFrontTrim ? "START frame" : "IN frame"}
                frame={selectedSplice.right_in_frame}
                fps={project.project.fps}
                adjustment={selectedSplice.right_in_adjustment}
                whisperFrame={selectedSplice.right_in_frame - selectedSplice.right_in_adjustment}
                suggestedFrame={selectedSplice.right_in_frame - selectedSplice.right_in_adjustment}
                minFrame={isFrontTrim ? 0 : selectedSplice.left_out_frame + 1}
                onNudge={(delta) => updateSplice(() => adjustSplice(selectedSplice.anchor_key, 0, delta))}
              />
            </div>
          )}
          <button className="refresh-rendered-preview" onClick={onRefresh} disabled={busy || !stale}>
            <RotateCcw size={18} /> Apply Changes & Refresh Preview
          </button>
        </section>
      </section>
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
  const isFrontTrim = selectedSplice?.left_word_id === "";
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
        <div className={isFrontTrim ? "splice-review-body single" : "splice-review-body"}>
          {!isFrontTrim && (
            <CutFrameCard
              title="OUT frame"
              frame={selectedSplice.left_out_frame}
              fps={project?.project.fps ?? 30}
              adjustment={selectedSplice.left_out_adjustment}
              whisperFrame={selectedSplice.left_whisper_out_frame}
              suggestedFrame={selectedSplice.left_suggested_out_frame}
              maxFrame={selectedSplice.right_in_frame - 1}
              onNudge={(delta) => updateSplice(() => adjustSplice(selectedSplice.anchor_key, delta, 0))}
            />
          )}
          <CutFrameCard
            title={isFrontTrim ? "START frame" : "IN frame"}
            frame={selectedSplice.right_in_frame}
            fps={project?.project.fps ?? 30}
            adjustment={selectedSplice.right_in_adjustment}
            whisperFrame={selectedSplice.right_in_frame - selectedSplice.right_in_adjustment}
            suggestedFrame={selectedSplice.right_in_frame - selectedSplice.right_in_adjustment}
            minFrame={isFrontTrim ? 0 : selectedSplice.left_out_frame + 1}
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
  fps,
  adjustment,
  whisperFrame,
  suggestedFrame,
  minFrame,
  maxFrame,
  onNudge,
}: {
  title: string;
  frame: number;
  fps: number;
  adjustment: number;
  whisperFrame: number;
  suggestedFrame: number;
  minFrame?: number;
  maxFrame?: number;
  onNudge: (delta: number) => void;
}) {
  const allowedDelta = (requested: number) => {
    const requestedFrame = frame + requested;
    const boundedFrame = Math.min(maxFrame ?? Number.POSITIVE_INFINITY, Math.max(minFrame ?? 0, requestedFrame));
    return boundedFrame - frame;
  };
  const nudge = (requested: number) => {
    const delta = allowedDelta(requested);
    if (delta !== 0) onNudge(delta);
  };
  const buttonTitle = (requested: number) => {
    const delta = allowedDelta(requested);
    if (delta === 0) return requested > 0 ? "At the next IN-frame safety limit" : "At the earliest legal frame";
    if (delta !== requested) return `Move ${Math.abs(delta)} frame${Math.abs(delta) === 1 ? "" : "s"} to the safety limit`;
    return `Move ${Math.abs(delta)} frame${Math.abs(delta) === 1 ? "" : "s"}`;
  };
  return (
    <div className="cut-frame-card">
      <div className="cut-frame-header">
        <span>{title}<small>Whisper {formatFrameTimecode(whisperFrame, fps)} · frame {whisperFrame.toLocaleString()}</small></span>
        <strong>{formatFrameTimecode(frame, fps)}<small>Frame {frame.toLocaleString()} · {formatSignedFrames(adjustment)}</small></strong>
      </div>
      {suggestedFrame !== whisperFrame && (
        <div className="assisted-boundary-label">Assisted suggestion: {formatFrameTimecode(suggestedFrame, fps)} · frame {suggestedFrame.toLocaleString()} · +{suggestedFrame - whisperFrame}</div>
      )}
      {(frame === minFrame || frame === maxFrame) && (
        <div className="cut-boundary-limit">Safety boundary reached at frame {frame.toLocaleString()}</div>
      )}
      <div className="nudge-buttons" aria-label={`${title} nudges`}>
        <button disabled={allowedDelta(-10) === 0} title={buttonTitle(-10)} onClick={() => nudge(-10)}><ArrowLeft size={13} /> 10</button>
        <button disabled={allowedDelta(-5) === 0} title={buttonTitle(-5)} onClick={() => nudge(-5)}><ArrowLeft size={13} /> 5</button>
        <button disabled={allowedDelta(-1) === 0} title={buttonTitle(-1)} onClick={() => nudge(-1)}><ArrowLeft size={13} /> 1</button>
        <button disabled={allowedDelta(1) === 0} title={buttonTitle(1)} onClick={() => nudge(1)}>1 <ArrowRight size={13} /></button>
        <button disabled={allowedDelta(5) === 0} title={buttonTitle(5)} onClick={() => nudge(5)}>5 <ArrowRight size={13} /></button>
        <button disabled={allowedDelta(10) === 0} title={buttonTitle(10)} onClick={() => nudge(10)}>10 <ArrowRight size={13} /></button>
      </div>
    </div>
  );
}

function formatFrameTimecode(frame: number, fps: number) {
  const roundedFps = Math.max(1, Math.round(fps));
  const safeFrame = Math.max(0, frame);
  const frames = safeFrame % roundedFps;
  const totalSeconds = Math.floor(safeFrame / roundedFps);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  return [hours, minutes, seconds, frames].map((value) => String(value).padStart(2, "0")).join(":");
}

function formatSignedFrames(value: number) {
  if (value === 0) return "0 frames";
  return `${value > 0 ? "+" : ""}${value} frames`;
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
