"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  ClipboardCopy,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
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
  Trash2,
} from "lucide-react";
import type { Dispatch, KeyboardEvent as ReactKeyboardEvent, MutableRefObject, PointerEvent as ReactPointerEvent, ReactNode, RefObject, SetStateAction } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HexColorInput, HexColorPicker } from "react-colorful";
import CreatorProductionWorkspace from "./creator-production";
import GraphicsLibraryWorkspace from "./graphics-library";
import VisualPackageWorkspace, { VISUAL_PACKAGE_RAIL_HOST_ID } from "./visual-package";
import VisualProductionWorkspace from "./visual-production";
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
  type VideoProjectResponse,
  addManualCut,
  addVideoProjectClips,
  adjustManualCut,
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
  createVideoProject,
  deleteDeadSpace,
  deleteCaptionStyle,
  deleteTokens,
  cancelExportCut,
  exportCut,
  generateAudioPreview,
  generateCaptionVideo,
  getExportCutJob,
  getProjectDocument,
  getTranscriptionJob,
  getCurrentProject,
  getCurrentVideoProject,
  getVisualPlanPrompt,
  liveCutPreview,
  normalizeVideoAudio,
  openProjectDialog,
  openVideoProject,
  removeVideoProjectClip,
  removeSplice,
  reorderVideoProjectClips,
  prepareCaptionPreview,
  restoreTokens,
  renderedCutPreviewUrl,
  renderCutPreview,
  reviewSplice,
  saveCaptionStyle,
  saveProject,
  setFinalOutFrame,
  sourceVideoUrl,
  startTranscription,
  updateEditorSettings,
  createGraphicsLibrary,
  getGraphicsLibrary,
  openGraphicsLibraryDialog,
  type GraphicsLibrarySummary,
} from "../lib/api";
import {
  beginPreviewRequest,
  isCurrentPreviewRequest,
  playMediaAt,
} from "../lib/media-preview";

type PreviewState = {
  segments: [number, number][];
  index: number;
  loop: boolean;
};

type ActiveTab = "transcript" | "caption" | "audio" | "visual" | "creator" | "graphics" | "package";

const DEFAULT_WHISPER_MODEL = "Large v3 - best accuracy";
const DEFAULT_WHISPER_COMPUTE = "NVIDIA GPU";

type ExportProgressState = {
  status: "running" | "canceling" | "canceled" | "complete" | "failed";
  message: string;
  outputPath?: string;
  value?: number;
  jobId?: string;
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
  const [openHeaderMenu, setOpenHeaderMenu] = useState<"tools" | "project" | null>(null);
  const toolsMenuRef = useRef<HTMLDivElement | null>(null);
  const projectMenuRef = useRef<HTMLDivElement | null>(null);
  const [showAppSettings, setShowAppSettings] = useState(false);
  const [graphicsLibraryRefreshSignal, setGraphicsLibraryRefreshSignal] = useState(0);
  const [project, setProject] = useState<EditorProjectResponse | null>(null);
  const [videoProject, setVideoProject] = useState<VideoProjectResponse | null>(null);
  const [visualPrompt, setVisualPrompt] = useState<string | null>(null);
  const [showSourceSequence, setShowSourceSequence] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [anchorToken, setAnchorToken] = useState<string | null>(null);
  const [activeSplice, setActiveSplice] = useState<string | null>(null);
  const [loop, setLoop] = useState(false);
  const [status, setStatus] = useState(`API: ${API_BASE}`);
  const [captionStatus, setCaptionStatus] = useState("Caption generator ready");
  const [busy, setBusy] = useState(false);

  const [activeWorkflowStage, setActiveWorkflowStage] = useState(1);
  const [previewAspect, setPreviewAspect] = useState(16 / 9);
  const [previewBox, setPreviewBox] = useState({ width: 400, height: 225 });
  const previewPanelRef = useRef<HTMLElement | null>(null);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const renderedCutVideoRef = useRef<HTMLVideoElement | null>(null);
  const previewState = useRef<PreviewState>({ segments: [], index: 0, loop: false });
  const previewRequestRef = useRef(0);
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
  const [captionModel, setCaptionModel] = useState(DEFAULT_WHISPER_MODEL);
  const [captionCompute, setCaptionCompute] = useState(DEFAULT_WHISPER_COMPUTE);
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
  const [normalizeCutAudio, setNormalizeCutAudio] = useState(true);
  const [audioTargetI, setAudioTargetI] = useState(-14);
  const [audioTargetLra, setAudioTargetLra] = useState(7);
  const [audioTargetTp, setAudioTargetTp] = useState(-1.5);
  const [audioAnalysis, setAudioAnalysis] = useState<AudioAnalysisResponse | null>(null);
  const [audioPreview, setAudioPreview] = useState<AudioPreviewResponse | null>(null);
  const [audioStatus, setAudioStatus] = useState("Choose a video, then analyze its audio.");

  const deletedWordIds = useMemo(() => new Set(project?.deleted_word_ids ?? []), [project]);
  const repeatedWordIds = useMemo(() => new Set(project?.repeated_word_ids ?? []), [project]);
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
    if (data.video_project) setVideoProject(data.video_project);
    setActiveSplice((current) => {
      if (current && data.splices.some((splice) => splice.anchor_key === current)) return current;
      return data.splices[0]?.anchor_key ?? null;
    });
    setStatus(data.project_path ? `Opened ${data.project_path}` : "Project loaded");
  }, []);

  const applyVideoProject = useCallback(
    (data: {
      videoProject: VideoProjectResponse;
      editorProject: EditorProjectResponse | null;
      visualPlanWarning?: string | null;
    }) => {
    setVideoProject(data.videoProject);
    if (data.editorProject) {
      applyProject(data.editorProject);
      setTranscriptSource(data.editorProject.project.source);
    } else {
      setProject(null);
      setTranscriptSource(data.videoProject.resolvedPaths.sourceVideo ?? null);
      setSelected([]);
      setActiveSplice(null);
      setActiveWorkflowStage(1);
    }
    const warning = data.visualPlanWarning?.trim();
    setStatus(
      warning
        ? `Opened private project: ${data.videoProject.name}. ${warning}`
        : `Opened private project: ${data.videoProject.name}`,
    );
  },
  [applyProject],
);

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

  const closeHeaderMenus = useCallback(() => setOpenHeaderMenu(null), []);

  const selectToolTab = useCallback((tab: ActiveTab) => {
    setActiveTab(tab);
    setOpenHeaderMenu(null);
  }, []);

  useEffect(() => {
    if (!openHeaderMenu) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (openHeaderMenu === "tools" && toolsMenuRef.current?.contains(target)) return;
      if (openHeaderMenu === "project" && projectMenuRef.current?.contains(target)) return;
      setOpenHeaderMenu(null);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenHeaderMenu(null);
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [openHeaderMenu]);

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
    getCurrentVideoProject().then(setVideoProject).catch(() => {
      // A legacy transcript project may be open without a parent video project.
    });
  }, []);

  useEffect(() => {
    if (!videoProject) return;
    const source = videoProject.preferredSource;
    const output = videoProject.resolvedPaths.finalVideo?.replace(/[\\/][^\\/]+$/, "") ?? "";
    setTranscriptSource(videoProject.resolvedPaths.sourceVideo ?? null);
    setCaptionSource(source ?? null);
    setAudioSource(source ?? null);
    setCaptionOutputFolder(output);
    setAudioOutputFolder(output);
  }, [videoProject]);

  const applyCaptionOptions = useCallback((data: CaptionOptionsResponse) => {
    setCaptionOptionsData(data);
    setCaptionSource(data.source);
    setCaptionOutputFolder(data.output_folder);
    const styleName = data.styles[captionStyleName] ? captionStyleName : Object.keys(data.styles)[0] ?? "";
    setCaptionStyleName(styleName);
    setCaptionStyle(data.styles[styleName] ?? data.default_style);
    setCaptionPreset(data.presets.Creator ?? Object.values(data.presets)[0] ?? null);
    if (!data.models[captionModel]) {
      setCaptionModel(data.models[DEFAULT_WHISPER_MODEL] ? DEFAULT_WHISPER_MODEL : (Object.keys(data.models)[0] ?? DEFAULT_WHISPER_MODEL));
    }
    if (!data.compute[captionCompute]) {
      setCaptionCompute(data.compute[DEFAULT_WHISPER_COMPUTE] ? DEFAULT_WHISPER_COMPUTE : (Object.keys(data.compute)[0] ?? DEFAULT_WHISPER_COMPUTE));
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
      return result;
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
      return undefined;
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
        setVideoProject(data.videoProject);
        setTranscriptSource(data.source);
        setProject(null);
        projectFileHandleRef.current = null;
        setSelected([]);
        setActiveSplice(null);
        setActiveWorkflowStage(1);
        setStatus(`Created ${data.videoProject.name}. Source copied to ${data.source}`);
        setShowSourceSequence(true);
      },
    );
  };

  const handleCreateVideoProject = () => {
    void run(createVideoProject, (data) => {
      applyVideoProject(data);
      setShowSourceSequence(true);
    });
  };

  const handleOpenVideoProject = () => {
    void run(openVideoProject, applyVideoProject);
  };

  const handleCookVisualPlanPrompt = () => {
    void run(getVisualPlanPrompt, ({ prompt }) => {
      setVisualPrompt(prompt);
      void navigator.clipboard.writeText(prompt).then(
        () => setStatus("Cook Visual Plan prompt copied to the clipboard."),
        () => setStatus("Prompt generated. Use Copy Prompt in the dialog."),
      );
    });
  };

  const handleAddSourceClips = () => {
    void run(addVideoProjectClips, (data) => {
      applyVideoProject(data);
      setShowSourceSequence(true);
      setStatus("Source sequence rebuilt. Generate a new transcript when the clip order is final.");
    });
  };

  const handleMoveSourceClip = (clipId: string, direction: -1 | 1) => {
    if (!videoProject) return;
    const clips = [...(videoProject.manifest.sourceSequence ?? [])].sort((a, b) => a.order - b.order);
    const index = clips.findIndex((clip) => clip.id === clipId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= clips.length) return;
    [clips[index], clips[target]] = [clips[target], clips[index]];
    void run(() => reorderVideoProjectClips(clips.map((clip) => clip.id)), (data) => {
      applyVideoProject(data);
      setShowSourceSequence(true);
      setStatus("Source sequence reordered. Previous transcript and downstream outputs are now stale.");
    });
  };

  const handleRemoveSourceClip = (clipId: string) => {
    if (!window.confirm("Remove this clip from the sequence? The original file remains private, but the transcript and downstream outputs must be regenerated.")) return;
    void run(() => removeVideoProjectClip(clipId), (data) => {
      applyVideoProject(data);
      setShowSourceSequence(true);
      setStatus("Clip removed and source sequence rebuilt. Generate a new transcript.");
    });
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
      value: 0,
      message: normalizeCutAudio
        ? "Exporting the cut, then analyzing and normalizing its audio…"
        : "Exporting edited video with FFmpeg…",
    });
    void exportCut({
      normalize_audio: normalizeCutAudio,
      normalization_preset_id: audioPresetId,
      target_i: audioTargetI,
      target_lra: audioTargetLra,
      target_tp: audioTargetTp,
    })
      .then(async (started) => {
        const jobId = started.job.job_id;
        setExportProgress({
          status: "running",
          value: started.job.value,
          message: started.job.message || "Exporting…",
          jobId,
        });
        // Poll until terminal state.
        for (;;) {
          await new Promise((r) => window.setTimeout(r, 800));
          const job = await getExportCutJob(jobId);
          if (job.status === "running" || job.status === "canceling") {
            setExportProgress({
              status: job.status === "canceling" ? "canceling" : "running",
              value: job.value,
              message: job.message || "Exporting…",
              jobId,
            });
            continue;
          }
          if (job.status === "complete") {
            if (job.output_path) {
              setCaptionSource(job.output_path);
              setAudioSource(job.output_path);
              setStatus(`Exported ${job.output_path}`);
            }
            setExportProgress({
              status: "complete",
              value: 100,
              message: job.normalized
                ? `Cut and normalized export finished. The original cut remains at ${job.cut_output_path}`
                : "Export finished.",
              outputPath: job.output_path ?? undefined,
              jobId,
            });
            break;
          }
          if (job.status === "canceled") {
            setExportProgress({
              status: "canceled",
              value: job.value,
              message: "Export canceled.",
              jobId,
            });
            setStatus("Export canceled.");
            break;
          }
          setExportProgress({
            status: "failed",
            value: job.value,
            message: job.error || job.message || "Export failed.",
            jobId,
          });
          setStatus(job.error || job.message || "Export failed.");
          break;
        }
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        setStatus(message);
        setExportProgress({ status: "failed", message });
      })
      .finally(() => setBusy(false));
  };

  const handleCancelExport = () => {
    const jobId = exportProgress?.jobId;
    if (!jobId) return;
    setExportProgress((prev) =>
      prev
        ? { ...prev, status: "canceling", message: "Canceling export…" }
        : prev,
    );
    void cancelExportCut(jobId)
      .then((result) => {
        setExportProgress({
          status: result.job.status === "canceled" ? "canceled" : "canceling",
          value: result.job.value,
          message: result.job.message || "Canceling export…",
          jobId,
        });
      })
      .catch((error) => {
        setStatus(error instanceof Error ? error.message : "Could not cancel export.");
      });
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
      saveProject,
      ({ saved }) => setStatus(`Saved ${saved}`),
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

  const startPreviewMonitor = useCallback((requestId: number) => {
    if (!isCurrentPreviewRequest(previewRequestRef, requestId)) return;
    stopPreviewMonitor();
    const tick = () => {
      if (!isCurrentPreviewRequest(previewRequestRef, requestId)) {
        previewFrameRef.current = null;
        return;
      }
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
          void playMediaAt(video, state.segments[1][0]).catch((error) => {
            if (!isCurrentPreviewRequest(previewRequestRef, requestId)) return;
            stopPreviewMonitor();
            setStatus(`Preview failed: ${error instanceof Error ? error.message : String(error)}`);
          });
        } else if (state.loop) {
          state.index = 0;
          void playMediaAt(video, state.segments[0][0]).catch((error) => {
            if (!isCurrentPreviewRequest(previewRequestRef, requestId)) return;
            stopPreviewMonitor();
            setStatus(`Preview failed: ${error instanceof Error ? error.message : String(error)}`);
          });
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
    const requestId = beginPreviewRequest(previewRequestRef);
    previewState.current = { segments, index: 0, loop };
    setActiveSplice(splice.anchor_key);
    setStatus(`${splice.id}: preview ${seconds}s from source video`);
    stopPreviewMonitor();
    video.pause();
    void playMediaAt(video, segments[0][0])
      .then(() => startPreviewMonitor(requestId))
      .catch((error) => {
        if (!isCurrentPreviewRequest(previewRequestRef, requestId)) return;
        setStatus(`Preview failed: ${error instanceof Error ? error.message : String(error)}`);
      });
  };

  const playFinalCut = (seconds: 2 | 4 | 6) => {
    const video = previewRef.current;
    const finalCut = project?.final_cut;
    if (!video || !finalCut || !project) return;
    const endSeconds = (finalCut.out_frame + 1) / project.project.fps;
    const keptStartSeconds = finalCut.minimum_out_frame / project.project.fps;
    const startSeconds = Math.max(keptStartSeconds, endSeconds - seconds);
    // The shared monitor stops half a frame before a segment boundary, so offset
    // this preview boundary by half a frame to match the export's inclusive OUT.
    const monitoredEndSeconds = endSeconds + 0.5 / project.project.fps;
    const requestId = beginPreviewRequest(previewRequestRef);
    previewState.current = { segments: [[startSeconds, monitoredEndSeconds]], index: 0, loop: false };
    setStatus(`Previewing the final ${seconds}s through OUT frame ${finalCut.out_frame}`);
    stopPreviewMonitor();
    video.pause();
    void playMediaAt(video, startSeconds)
      .then(() => startPreviewMonitor(requestId))
      .catch((error) => {
        if (!isCurrentPreviewRequest(previewRequestRef, requestId)) return;
        setStatus(`Final preview failed: ${error instanceof Error ? error.message : String(error)}`);
      });
  };

  /** Stage 4 CapCut-style: instant EDL plan, no FFmpeg bake. */
  const handleLiveCutPreview = useCallback((options?: { quiet?: boolean }) => {
    if (!project) return;
    const quiet = Boolean(options?.quiet);
    if (!quiet) {
      setBusy(true);
      setPreviewRenderProgress({
        status: "running",
        message: "Building live cut timeline (no re-encode)…",
      });
    }
    liveCutPreview()
      .then((result) => {
        setRenderedCutPreview(result);
        if (!quiet) {
          setStatus(
            `Live cut ready · ${formatTime(result.duration_seconds)} · ${result.splices.length} splice markers · seek source (no bake)`,
          );
          setPreviewRenderProgress({
            status: "complete",
            message: "Live cut timeline ready. Edits update instantly; export encodes once.",
          });
        }
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        setStatus(message);
        if (!quiet) setPreviewRenderProgress({ status: "failed", message });
      })
      .finally(() => {
        if (!quiet) setBusy(false);
      });
  }, [project]);

  // Entering Stage 4 loads the live plan; splice/manual-cut edits quietly refresh it.
  const livePlanKey = project
    ? [
        project.splices.map((s) => `${s.anchor_key}:${s.left_out_frame}:${s.right_in_frame}`).join("|"),
        (project.deleted_word_ids || []).join(","),
        (project.deleted_silence_ids || []).join(","),
        project.final_cut?.out_frame ?? "",
      ].join("::")
    : "";
  useEffect(() => {
    if (activeTab !== "transcript" || activeWorkflowStage !== 4 || !project || !livePlanKey) return;
    handleLiveCutPreview({ quiet: Boolean(renderedCutPreview) });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only replan when EDL fingerprint changes
  }, [activeTab, activeWorkflowStage, livePlanKey]);

  const seekRenderedJoin = (splice: DynamicSplice, autoplay = true) => {
    const video = renderedCutVideoRef.current;
    const marker = renderedBoundaryByAnchor.get(splice.anchor_key);
    const fps = Math.max(project?.project.fps ?? 30, 1);
    const mappedSegment = renderedCutPreview?.segments.find(
      (segment) => segment.source_start_frame <= splice.left_out_frame && splice.left_out_frame <= segment.source_end_frame,
    );
    const previewTime = marker?.preview_time_seconds ?? (mappedSegment
      ? mappedSegment.preview_start_seconds + (splice.left_out_frame - mappedSegment.source_start_frame) / fps
      : null);
    if (!video || previewTime === null || !renderedCutPreview) return;
    const targetContinuous = Math.max(0, previewTime - 2);
    if (renderedCutPreview.mode === "live" || renderedCutPreview.preview_id.startsWith("live-")) {
      const segment = renderedCutPreview.segments.find(
        (item, index) =>
          targetContinuous >= item.preview_start_seconds
          && (targetContinuous < item.preview_end_seconds
            || (index === renderedCutPreview.segments.length - 1
              && targetContinuous <= item.preview_end_seconds)),
      );
      if (!segment) return;
      const sourceTime =
        segment.source_start_frame / fps
        + (targetContinuous - segment.preview_start_seconds);
      video.currentTime = sourceTime;
      if (autoplay) void video.play().catch((error) => setStatus(`Preview failed: ${error.message}`));
      return;
    }
    video.currentTime = targetContinuous;
    if (autoplay) void video.play().catch((error) => setStatus(`Preview failed: ${error.message}`));
  };

  const updateSplice = (
    operation: () => Promise<EditorProjectResponse>,
    afterApply?: (data: EditorProjectResponse) => void,
  ) => run(operation, (data) => {
    applyProject(data);
    afterApply?.(data);
  });

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
  const sourceBoundaryByWord = useMemo(() => {
    const boundaries = new Map<string, { name: string; startSec: number }>();
    if (!project || !videoProject) return boundaries;
    for (const clip of videoProject.manifest.sourceSequence ?? []) {
      const word = project.project.words.find((item) => item.start >= clip.startSec - 0.05);
      if (word) boundaries.set(word.id, { name: clip.name, startSec: clip.startSec });
    }
    return boundaries;
  }, [project, videoProject]);

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
          onCancel={handleCancelExport}
        />
      )}
      {previewRenderProgress && (
        <PreviewRenderModal progress={previewRenderProgress} onClose={() => setPreviewRenderProgress(null)} />
      )}
      {visualPrompt && (
        <div className="modal-backdrop" role="presentation">
          <section className="visual-prompt-modal" role="dialog" aria-modal="true" aria-labelledby="visual-prompt-title">
            <div className="visual-prompt-heading">
              <div><span className="eyebrow">Codex handoff</span><h2 id="visual-prompt-title">Cook a Visual Plan</h2></div>
              <button className="header-icon-button" aria-label="Close prompt" onClick={() => setVisualPrompt(null)}><X size={18} /></button>
            </div>
            <p>This includes the active project’s exact private paths and the VCG editorial rules. Paste it into a new Codex task.</p>
            <textarea readOnly value={visualPrompt} aria-label="Cook Visual Plan prompt" />
            <div className="visual-prompt-actions">
              <button onClick={() => setVisualPrompt(null)}>Close</button>
              <button className="primary" onClick={() => void navigator.clipboard.writeText(visualPrompt).then(() => setStatus("Cook Visual Plan prompt copied."))}><ClipboardCopy size={16} /> Copy Prompt</button>
            </div>
          </section>
        </div>
      )}
      {showSourceSequence && videoProject && (
        <div className="modal-backdrop" role="presentation">
          <section className="source-sequence-modal" role="dialog" aria-modal="true" aria-labelledby="source-sequence-title">
            <div className="visual-prompt-heading">
              <div><span className="eyebrow">Phase 1</span><h2 id="source-sequence-title">Source Sequence</h2></div>
              <button className="header-icon-button" aria-label="Close source sequence" onClick={() => setShowSourceSequence(false)}><X size={18} /></button>
            </div>
            <div className={`sequence-compatibility ${(videoProject.manifest.sequenceBuild?.compatible ?? true) ? "compatible" : "normalized"}`}>
              <Check size={17} />
              <span>{videoProject.manifest.sequenceBuild?.compatible
                ? `${videoProject.manifest.sourceSequence?.length ?? 0} clips compatible · combined without re-encoding`
                : `Compatibility differences found · standardized working copies were used`}</span>
            </div>
            {!!videoProject.manifest.sequenceBuild?.differences.length && (
              <ul className="sequence-differences">{videoProject.manifest.sequenceBuild.differences.map((difference) => <li key={difference}>{difference}</li>)}</ul>
            )}
            <div className="source-clip-list">
              {[...(videoProject.manifest.sourceSequence ?? [])].sort((a, b) => a.order - b.order).map((clip, index, clips) => (
                <article className="source-clip-row" key={clip.id}>
                  <span className="source-clip-index">{String(index + 1).padStart(2, "0")}</span>
                  <div className="source-clip-copy">
                    <strong>{clip.name}</strong>
                    <small>{formatTime(clip.durationSec)} · starts {formatTime(clip.startSec)} · {clip.metadata.width}×{clip.metadata.height} · {clip.metadata.frameRate} fps</small>
                  </div>
                  <div className="source-clip-actions">
                    <button aria-label={`Move ${clip.name} up`} disabled={busy || index === 0} onClick={() => handleMoveSourceClip(clip.id, -1)}><ChevronUp size={16} /></button>
                    <button aria-label={`Move ${clip.name} down`} disabled={busy || index === clips.length - 1} onClick={() => handleMoveSourceClip(clip.id, 1)}><ChevronDown size={16} /></button>
                    <button aria-label={`Remove ${clip.name}`} disabled={busy || clips.length === 1} onClick={() => handleRemoveSourceClip(clip.id)}><Trash2 size={16} /></button>
                  </div>
                </article>
              ))}
            </div>
            <div className="source-sequence-footer">
              <span>Total sequence: {formatTime(videoProject.manifest.sequenceBuild?.durationSec ?? 0)}</span>
              <div><button onClick={() => setShowSourceSequence(false)}>Done</button><button className="primary" onClick={handleAddSourceClips} disabled={busy}><Upload size={16} /> Add recordings</button></div>
            </div>
          </section>
        </div>
      )}
      {showAppSettings ? (
        <AppSettingsModal
          busy={busy}
          project={project}
          captionOutputFolder={captionOutputFolder}
          audioOutputFolder={audioOutputFolder}
          projectManaged={!!videoProject}
          close={() => setShowAppSettings(false)}
          onUpdatePauseThreshold={(threshold) =>
            void run(() => updateEditorSettings(threshold), applyProject)
          }
          onChooseCaptionOutputFolder={() =>
            void run(chooseCaptionOutputFolder, (data) => {
              setCaptionOutputFolder(data.output_folder);
              setStatus(`Caption output folder set to ${data.output_folder}`);
            })
          }
          onChooseAudioOutputFolder={() =>
            void run(chooseAudioOutputFolder, (data) => {
              setAudioOutputFolder(data.output_folder);
              setAudioStatus(`Output folder set to ${data.output_folder}`);
            })
          }
          onCaptionOutputFolderChange={setCaptionOutputFolder}
          onAudioOutputFolderChange={setAudioOutputFolder}
          onGraphicsLibraryChanged={() => setGraphicsLibraryRefreshSignal((value) => value + 1)}
        />
      ) : null}
      <header className="topbar modern-topbar">
        <div className="brand-block">
          <h1>VCG Content Command Center</h1>
          <p>{videoProject ? `${videoProject.name} · Private project` : "Create or open a private video project"}</p>
        </div>
        <div
          className={["header-menu", "tools-menu", openHeaderMenu === "tools" ? "is-open" : ""].join(" ")}
          ref={toolsMenuRef}
        >
          <button
            className="header-menu-trigger"
            type="button"
            aria-haspopup="menu"
            aria-expanded={openHeaderMenu === "tools"}
            onClick={() => setOpenHeaderMenu((current) => (current === "tools" ? null : "tools"))}
          >
            <Grid3X3 size={17} /> Tools <ChevronDown size={14} />
          </button>
          <div className="header-dropdown" role="menu">
            <button type="button" className={activeTab === "transcript" ? "active" : ""} onClick={() => selectToolTab("transcript")}>
              Transcript Edit
            </button>
            <button type="button" className={activeTab === "caption" ? "active" : ""} onClick={() => selectToolTab("caption")}>
              Caption Generator
            </button>
            <button type="button" className={activeTab === "audio" ? "active" : ""} onClick={() => selectToolTab("audio")}>
              Audio Normalizer
            </button>
            <button type="button" className={activeTab === "visual" ? "active" : ""} onClick={() => selectToolTab("visual")}>
              Visual Production
            </button>
            <button type="button" className={activeTab === "creator" ? "active" : ""} onClick={() => selectToolTab("creator")}>
              Creator Production
            </button>
            <button type="button" className={activeTab === "graphics" ? "active" : ""} onClick={() => selectToolTab("graphics")}>
              Graphics Library
            </button>
            <button type="button" className={activeTab === "package" ? "active" : ""} onClick={() => selectToolTab("package")}>
              Visual Package
            </button>
          </div>
        </div>

        {activeTab === "transcript" ? (
          <nav className="workflow-rail" aria-label="Transcript workflow">
            <WorkflowStage stage={1} activeStage={activeWorkflowStage} setActiveStage={setActiveWorkflowStage}>
              <span className="workflow-stage-label">Project</span>
              <button className="workflow-action" onClick={handleChooseTranscriptVideo} disabled={busy}>
                <FolderOpen size={15} /> New from Clips
              </button>
              {videoProject && <button className="workflow-action" onClick={() => setShowSourceSequence(true)} disabled={busy}>{videoProject.manifest.sourceSequence?.length ?? 1} Source Clips</button>}
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
              <span className="workflow-status">
                {renderedCutPreview
                  ? "Live EDL · encode only on Export"
                  : project
                    ? "Building live plan…"
                    : "Seek source cut · no bake"}
              </span>
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
        ) : activeTab === "package" ? (
          <div id={VISUAL_PACKAGE_RAIL_HOST_ID} className="workflow-rail-host" />
        ) : (
          <div className="contextual-tool-actions">
            {activeTab === "caption" ? (
              <>
                {!videoProject && <button onClick={handleChooseCaptionVideo} disabled={busy}><FolderOpen size={16} /> Choose Video</button>}
                {videoProject && <span className="workflow-status">Using active project cut</span>}
                <button className="outline-primary" onClick={handleGenerateCaptions} disabled={busy || !captionStyle || !captionPreset || !captionSource}><Upload size={16} /> Generate Captioned Video</button>
              </>
            ) : activeTab === "audio" ? (
              <>
                {!videoProject && <button onClick={handleChooseAudioVideo} disabled={busy}><FolderOpen size={16} /> Choose Video</button>}
                {videoProject && <span className="workflow-status">Using active project cut</span>}
                <button onClick={handleAnalyzeAudio} disabled={busy || !audioSource}><Gauge size={16} /> Analyze Audio</button>
                <button className="outline-primary" onClick={handleNormalizeAudio} disabled={busy || !audioAnalysis}><WandSparkles size={16} /> Export Corrected Video</button>
              </>
            ) : activeTab === "creator" ? (
              <span className="workflow-status">Creator Production pipeline (jobs)</span>
            ) : activeTab === "graphics" ? (
              <span className="workflow-status">Graphics Library (review samples & promote usages)</span>
            ) : (
              <span className="workflow-status">Private post-cut graphics, timeline, player, and rendering</span>
            )}
          </div>
        )}

        <div className="header-utilities">
          <div
            className={["header-menu", "project-menu", openHeaderMenu === "project" ? "is-open" : ""].join(" ")}
            ref={projectMenuRef}
          >
            <button
              className="header-menu-trigger"
              type="button"
              aria-haspopup="menu"
              aria-expanded={openHeaderMenu === "project"}
              onClick={() => setOpenHeaderMenu((current) => (current === "project" ? null : "project"))}
            >
              <FolderOpen size={17} /> Project <ChevronDown size={14} />
            </button>
            <div className="header-dropdown project-dropdown" role="menu">
              <button
                type="button"
                onClick={() => {
                  closeHeaderMenus();
                  handleCreateVideoProject();
                }}
                disabled={busy}
              >
                <Upload size={15} /> New Video Project
              </button>
              <button
                type="button"
                onClick={() => {
                  closeHeaderMenus();
                  handleOpenVideoProject();
                }}
                disabled={busy}
              >
                <FolderOpen size={15} /> Open Video Project
              </button>
              <button
                type="button"
                onClick={() => {
                  closeHeaderMenus();
                  setShowSourceSequence(true);
                }}
                disabled={busy || !videoProject}
              >
                <Scissors size={15} /> Manage Source Clips
              </button>
              <button
                type="button"
                onClick={() => {
                  closeHeaderMenus();
                  handleCookVisualPlanPrompt();
                }}
                disabled={busy || !videoProject}
              >
                <ClipboardCopy size={15} /> Cook Visual Plan Prompt
              </button>
              <button
                type="button"
                onClick={() => {
                  closeHeaderMenus();
                  handleOpen();
                }}
                disabled={busy}
              >
                <FolderOpen size={15} /> Open Legacy Transcript
              </button>
              <button
                type="button"
                onClick={() => {
                  closeHeaderMenus();
                  void handleSaveProject();
                }}
                disabled={busy || !project}
              >
                <Save size={15} /> Save Project
              </button>
            </div>
          </div>
          <button className="header-icon-button" aria-label="Save project" title="Save project" onClick={handleSaveProject} disabled={busy || !project}><Save size={18} /></button>
          <button
            className="header-icon-button"
            aria-label="Application settings"
            title="Application settings — graphics library folder, transcript, caption, and audio preferences"
            onClick={() => setShowAppSettings(true)}
            disabled={busy}
          >
            <Settings size={18} />
          </button>
        </div>
      </header>

      {activeTab === "transcript" && activeWorkflowStage === 4 && renderedCutPreview && project ? (
        <RenderedCutPreviewWorkspace
          busy={busy}
          pendingFrames={0}
          preview={renderedCutPreview}
          project={project}
          seekRenderedJoin={seekRenderedJoin}
          selectSplice={(splice) => {
            setActiveSplice(splice.anchor_key);
            seekRenderedJoin(splice, false);
          }}
          selectedSplice={selectedSplice}
          selectedSpliceIndex={selectedSpliceIndex}
          stale={false}
          sourceVideoSrc={
            transcriptVideoKey
              ? `${sourceVideoUrl()}?source=${encodeURIComponent(transcriptVideoKey)}`
              : undefined
          }
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
            playFinalCut={playFinalCut}
            playSplice={playSplice}
            project={project}
            reviewSpliceAndAdvance={reviewSpliceAndAdvance}
            selectedSplice={selectedSplice}
          selectedSpliceIndex={selectedSpliceIndex}
          setLoop={setLoop}
          sourceVideoRef={previewRef}
          updateSplice={updateSplice}
          />
        </div>

        <TranscriptContext
          activeSplice={activeSplice}
          deletedSilenceIds={deletedSilenceIds}
          deletedWordIds={deletedWordIds}
          project={project}
          repeatedWordIds={repeatedWordIds}
          selected={selected}
          sentenceGroups={sentenceGroups}
          selectToken={selectToken}
          selectedMarkerRef={selectedMarkerRef}
          selectSplice={selectSplice}
          spliceByRightWord={spliceByRightWord}
          sourceBoundaryByWord={sourceBoundaryByWord}
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
          projectManaged={!!videoProject}
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
      ) : activeTab === "audio" ? (
        <AudioNormalizer
          analysis={audioAnalysis}
          busy={busy}
          options={audioOptionsData}
          outputFolder={audioOutputFolder}
          presetId={audioPresetId}
          preview={audioPreview}
          source={audioSource}
          status={audioStatus}
          projectManaged={!!videoProject}
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
      ) : activeTab === "creator" ? (
        <CreatorProductionWorkspace />
      ) : activeTab === "graphics" ? (
        <GraphicsLibraryWorkspace refreshSignal={graphicsLibraryRefreshSignal} />
      ) : activeTab === "package" ? (
        <VisualPackageWorkspace
          hasVideoProject={Boolean(videoProject)}
          projectName={videoProject?.name}
        />
      ) : (
        <VisualProductionWorkspace />
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
  projectManaged,
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
  projectManaged: boolean;
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
            {projectManaged ? "Project output folder" : "Output folder"}
            <input value={outputFolder} readOnly={projectManaged} onChange={(event) => onOutputFolderChange(event.target.value)} />
          </label>
          <button onClick={onChooseOutputFolder} disabled={busy || projectManaged} title={projectManaged ? "Managed automatically by the active video project" : undefined}>
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
  repeatedWordIds,
  selected,
  sentenceGroups,
  selectToken,
  selectedMarkerRef,
  selectSplice,
  spliceByRightWord,
  sourceBoundaryByWord,
  status,
  transcriptScrollRef,
}: {
  activeSplice: string | null;
  deletedSilenceIds: Set<string>;
  deletedWordIds: Set<string>;
  project: EditorProjectResponse | null;
  repeatedWordIds: Set<string>;
  selected: string[];
  sentenceGroups: { sentenceId: number; words: EditorProjectResponse["project"]["words"] }[];
  selectToken: (tokenId: string, shiftKey: boolean) => void;
  selectedMarkerRef: (anchorKey: string) => (element: HTMLButtonElement | null) => void;
  selectSplice: (splice: DynamicSplice) => void;
  spliceByRightWord: Map<string, DynamicSplice>;
  sourceBoundaryByWord: Map<string, { name: string; startSec: number }>;
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
              const sourceBoundary = sourceBoundaryByWord.get(word.id);
              const deleted = deletedWordIds.has(word.id);
              const repeated = repeatedWordIds.has(word.id) && !deleted;
              const selectedToken = selected.includes(word.id);
              return (
                <span key={word.id} className="word-wrap">
                  {sourceBoundary && <span className="source-boundary-marker">CLIP · {sourceBoundary.name} · {formatTime(sourceBoundary.startSec)}</span>}
                  {splice && (
                    <SpliceMarker
                      active={activeSplice === splice.anchor_key}
                      markerRef={selectedMarkerRef(splice.anchor_key)}
                      splice={splice}
                      onSelect={selectSplice}
                    />
                  )}
                  <button
                    className={["token", deleted ? "deleted" : "", repeated ? "repeated" : "", selectedToken ? "selected" : ""].join(" ")}
                    onClick={(event) => selectToken(word.id, event.shiftKey)}
                    title={repeated ? "Likely earlier take repeated below" : undefined}
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
  projectManaged,
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
  projectManaged: boolean;
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
            {projectManaged ? "Project output folder" : "Output folder"}
            <input value={captionOutputFolder} readOnly={projectManaged} onChange={(event) => setCaptionOutputFolder(event.target.value)} />
          </label>
          <button onClick={handleChooseCaptionOutputFolder} disabled={busy || projectManaged} title={projectManaged ? "Managed automatically by the active video project" : undefined}>
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
  const normalized = normalizeHexColor(value) ?? "#FFFFFF";
  const [draft, setDraft] = useState(normalized);

  useEffect(() => {
    setDraft(normalized);
  }, [normalized]);

  useEffect(() => {
    if (!normalizeHexColor(value)) onChange(normalized);
  }, [normalized, onChange, value]);

  const handlePickerChange = (nextColor: string) => {
    const next = normalizeHexColor(nextColor);
    if (!next) return;
    setDraft(next);
    onChange(next);
  };

  const handleInputChange = (nextColor: string) => {
    setDraft(nextColor);
    const next = normalizeSixDigitHexColor(nextColor);
    if (next) onChange(next);
  };

  const commitDraft = () => {
    const next = normalizeHexColor(draft) ?? normalized;
    setDraft(next);
    onChange(next);
  };

  return (
    <div className={compact ? "color-field compact" : "color-field"}>
      {!compact && <span>{label}</span>}
      <button className="color-trigger" type="button" onClick={() => setOpen((current) => !current)}>
        <span className="hex-swatch" style={{ backgroundColor: normalized }} />
        <span>{normalized}</span>
      </button>
      {open && (
        <div className="color-popover">
          <HexColorPicker color={normalized} onChange={handlePickerChange} onChangeEnd={() => setOpen(false)} />
          <HexColorInput className="hex-input" color={draft} onBlur={commitDraft} onChange={handleInputChange} prefixed />
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

function normalizeSixDigitHexColor(value: string) {
  const hex = value.trim().toUpperCase();
  return /^#[0-9A-F]{6}$/.test(hex) ? hex : null;
}

function normalizeHexColor(value: string) {
  const hex = value.trim().toUpperCase();
  const complete = normalizeSixDigitHexColor(hex);
  if (complete) return complete;
  const shorthand = /^#([0-9A-F]{3})$/.exec(hex);
  return shorthand ? `#${[...shorthand[1]].map((character) => character.repeat(2)).join("")}` : null;
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
  onCancel,
  progress,
}: {
  onClose: () => void;
  onCancel?: () => void;
  progress: ExportProgressState;
}) {
  const running = progress.status === "running" || progress.status === "canceling";
  const failed = progress.status === "failed";
  const canceled = progress.status === "canceled";
  const value = Math.max(0, Math.min(100, Math.round(progress.value ?? 0)));
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-live="polite">
      <div className={failed ? "progress-modal failed" : "progress-modal"}>
        <span className="eyebrow">Video Export</span>
        <h2>
          {progress.status === "canceling"
            ? "Canceling export…"
            : running
              ? "Exporting cut"
              : failed
                ? "Export failed"
                : canceled
                  ? "Export canceled"
                  : "Export complete"}
        </h2>
        <p>{progress.message}</p>
        {progress.outputPath && <p className="modal-path">{progress.outputPath}</p>}
        <div className={running && value < 2 ? "progress-track indeterminate" : "progress-track"}>
          <div
            className="progress-bar"
            style={running && value < 2 ? undefined : { width: `${running ? value : failed || canceled ? value : 100}%` }}
          />
        </div>
        {running ? (
          <div className="placement-final-progress-actions">
            <strong>{value > 0 ? `${value}%` : "Working…"}</strong>
            {onCancel && progress.status === "running" ? (
              <button type="button" className="modal-action" onClick={onCancel}>
                Cancel
              </button>
            ) : null}
          </div>
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

function AppSettingsModal({
  busy,
  close,
  project,
  captionOutputFolder,
  audioOutputFolder,
  projectManaged,
  onUpdatePauseThreshold,
  onChooseCaptionOutputFolder,
  onChooseAudioOutputFolder,
  onCaptionOutputFolderChange,
  onAudioOutputFolderChange,
  onGraphicsLibraryChanged,
}: {
  busy: boolean;
  close: () => void;
  project: EditorProjectResponse | null;
  captionOutputFolder: string;
  audioOutputFolder: string;
  projectManaged: boolean;
  onUpdatePauseThreshold: (threshold: number) => void;
  onChooseCaptionOutputFolder: () => void;
  onChooseAudioOutputFolder: () => void;
  onCaptionOutputFolderChange: (value: string) => void;
  onAudioOutputFolderChange: (value: string) => void;
  onGraphicsLibraryChanged: () => void;
}) {
  const [graphics, setGraphics] = useState<GraphicsLibrarySummary | null>(null);
  const [graphicsBusy, setGraphicsBusy] = useState(false);
  const [graphicsMessage, setGraphicsMessage] = useState("");

  const loadGraphics = useCallback(async () => {
    try {
      const data = await getGraphicsLibrary();
      setGraphics(data);
      setGraphicsMessage("");
    } catch (error) {
      setGraphicsMessage(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    void loadGraphics();
  }, [loadGraphics]);

  const runGraphics = async (action: () => Promise<GraphicsLibrarySummary>, success: string) => {
    setGraphicsBusy(true);
    setGraphicsMessage("");
    try {
      const data = await action();
      setGraphics(data);
      setGraphicsMessage(success);
      onGraphicsLibraryChanged();
    } catch (error) {
      setGraphicsMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setGraphicsBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="app-settings-title">
      <section className="app-settings-modal">
        <div className="settings-modal-header">
          <div>
            <span className="eyebrow">Application</span>
            <h2 id="app-settings-title">Settings</h2>
          </div>
          <button className="icon-button" aria-label="Close settings" onClick={close}>
            <X size={17} />
          </button>
        </div>

        <div className="app-settings-sections">
          <section className="app-settings-section">
            <h3>Graphics Library</h3>
            <p>
              Private Graphics Library folder on this machine. Sample clips and ratings stay local and are never
              published with the app.
            </p>
            <label>
              <span>Library folder</span>
              <input
                readOnly
                value={graphics?.root || ""}
                placeholder={graphicsBusy ? "Loading…" : "No folder connected yet"}
              />
            </label>
            <div className="app-settings-row">
              <button
                disabled={busy || graphicsBusy}
                onClick={() => void runGraphics(openGraphicsLibraryDialog, "Graphics library folder updated.")}
              >
                <FolderOpen size={15} /> Change folder…
              </button>
              {!graphics?.exists ? (
                <button
                  className="primary"
                  disabled={busy || graphicsBusy}
                  onClick={() => void runGraphics(createGraphicsLibrary, "Default Graphics Library folder created.")}
                >
                  Create default library
                </button>
              ) : null}
            </div>
            {graphics?.exists ? (
              <small className="app-settings-meta">
                {graphics.entryCount} graphics · {graphics.withSample} with samples
              </small>
            ) : (
              <small className="app-settings-meta">Not connected — create a default library or choose a folder.</small>
            )}
            {graphicsMessage ? <strong className="app-settings-feedback">{graphicsMessage}</strong> : null}
          </section>

          <section className="app-settings-section">
            <h3>Transcript Edit</h3>
            <p>
              Only detected pauses at or above this duration are removed by Remove Long Pauses. Shorter cadence
              pauses stay untouched.
            </p>
            {project ? (
              <>
                <label>
                  <span>Minimum long-pause duration</span>
                  <select
                    disabled={busy}
                    value={project.settings.dead_space_min_seconds}
                    onChange={(event) => onUpdatePauseThreshold(Number(event.target.value))}
                  >
                    {[0.5, 0.7, 0.8, 1, 1.5, 2].map((seconds) => (
                      <option key={seconds} value={seconds}>
                        {seconds.toFixed(1)} seconds
                      </option>
                    ))}
                  </select>
                </label>
                <small className="app-settings-meta">
                  {project.dead_space_candidate_count} pauses currently qualify in the active project
                </small>
              </>
            ) : (
              <small className="app-settings-meta">Open a transcript project to edit pause settings.</small>
            )}
          </section>

          <section className="app-settings-section">
            <h3>Caption Generator</h3>
            <p>Default folder for generated captioned videos when you are not inside a managed video project.</p>
            <label>
              <span>Caption output folder</span>
              <div className="app-settings-path-row">
                <input
                  value={captionOutputFolder}
                  readOnly={projectManaged}
                  onChange={(event) => onCaptionOutputFolderChange(event.target.value)}
                  placeholder="Choose a folder…"
                />
                <button
                  disabled={busy || projectManaged}
                  onClick={onChooseCaptionOutputFolder}
                  title={projectManaged ? "Managed automatically by the active video project" : "Choose caption output folder"}
                >
                  <FolderOpen size={15} /> Browse…
                </button>
              </div>
            </label>
            {projectManaged ? (
              <small className="app-settings-meta">Managed by the active video project.</small>
            ) : null}
          </section>

          <section className="app-settings-section">
            <h3>Audio Normalizer</h3>
            <p>Default folder for corrected audio exports when you are not inside a managed video project.</p>
            <label>
              <span>Audio output folder</span>
              <div className="app-settings-path-row">
                <input
                  value={audioOutputFolder}
                  readOnly={projectManaged}
                  onChange={(event) => onAudioOutputFolderChange(event.target.value)}
                  placeholder="Choose a folder…"
                />
                <button
                  disabled={busy || projectManaged}
                  onClick={onChooseAudioOutputFolder}
                  title={projectManaged ? "Managed automatically by the active video project" : "Choose audio output folder"}
                >
                  <FolderOpen size={15} /> Browse…
                </button>
              </div>
            </label>
            {projectManaged ? (
              <small className="app-settings-meta">Managed by the active video project.</small>
            ) : null}
          </section>
        </div>

        <div className="app-settings-footer">
          <button className="primary" onClick={close}>
            Done
          </button>
        </div>
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
  pendingFrames,
  preview,
  project,
  seekRenderedJoin,
  selectSplice,
  selectedSplice,
  selectedSpliceIndex,
  stale,
  sourceVideoSrc,
  updateSplice,
  videoRef,
}: {
  busy: boolean;
  pendingFrames: number;
  preview: RenderedCutPreviewResponse;
  project: EditorProjectResponse;
  seekRenderedJoin: (splice: DynamicSplice, autoplay?: boolean) => void;
  selectSplice: (splice: DynamicSplice) => void;
  selectedSplice: DynamicSplice | undefined;
  selectedSpliceIndex: number;
  stale: boolean;
  sourceVideoSrc?: string;
  updateSplice: (
    operation: () => Promise<EditorProjectResponse>,
    afterApply?: (data: EditorProjectResponse) => void,
  ) => Promise<EditorProjectResponse | undefined>;
  videoRef: RefObject<HTMLVideoElement | null>;
}) {
  const isLive = preview.mode === "live" || preview.preview_id.startsWith("live-");
  const fps = Math.max(project.project.fps, 1);
  const [manualOutTime, setManualOutTime] = useState("");
  const [manualInTime, setManualInTime] = useState("");
  const [manualCutError, setManualCutError] = useState("");
  const [manualDraftBaseFrames, setManualDraftBaseFrames] = useState<{ outFrame: number; inFrame: number } | null>(null);
  const [renderedPlayheadSeconds, setRenderedPlayheadSeconds] = useState(0);
  const [timelineZoom, setTimelineZoom] = useState(1);
  const [timelineScrubbing, setTimelineScrubbing] = useState(false);
  const [timelinePlaying, setTimelinePlaying] = useState(false);
  const [manualPreviewSeconds, setManualPreviewSeconds] = useState<2 | 4 | 6 | null>(null);
  const timelineViewportRef = useRef<HTMLDivElement | null>(null);
  const timelineContentRef = useRef<HTMLDivElement | null>(null);
  const timelinePlayheadRef = useRef<HTMLDivElement | null>(null);
  const cutControlsRef = useRef<HTMLElement | null>(null);
  const cutVideoPanelRef = useRef<HTMLElement | null>(null);
  const timelineScrubbingRef = useRef(false);
  const renderedPlayheadSecondsRef = useRef(0);
  const timelinePlaybackFrameRef = useRef<number | null>(null);
  const manualPreviewRef = useRef<{
    segments: [[number, number], [number, number]];
    index: number;
    /** Base-timeline continuous times for playhead (pre-roll start, IN start). */
    baseContinuous?: [number, number];
  } | null>(null);
  const previewMarkerByAnchor = new Map(preview.splices.map((splice) => [splice.anchor_key, splice]));
  const isFrontTrim = selectedSplice?.kind === "front_trim";
  type CutSegment = RenderedCutPreviewResponse["segments"][number];

  // Keep the left controls card the same height as the video card (video defines height).
  useEffect(() => {
    const controls = cutControlsRef.current;
    const videoPanel = cutVideoPanelRef.current;
    if (!controls || !videoPanel) return;
    const syncHeight = () => {
      const next = Math.round(videoPanel.getBoundingClientRect().height);
      if (next > 0) controls.style.height = `${next}px`;
    };
    syncHeight();
    const observer = new ResizeObserver(syncHeight);
    observer.observe(videoPanel);
    const video = videoRef.current;
    video?.addEventListener("loadedmetadata", syncHeight);
    return () => {
      observer.disconnect();
      video?.removeEventListener("loadedmetadata", syncHeight);
    };
  }, [preview.preview_id, videoRef]);

  /** Split base keep-segments at a draft manual cut (same rules as server _apply_manual_cuts). */
  const segmentsWithDraftCut = (
    base: CutSegment[],
    outFrame: number,
    inFrame: number,
  ): CutSegment[] => {
    const next: Array<{ source_start_frame: number; source_end_frame: number }> = [];
    for (const segment of base) {
      if (segment.source_start_frame <= outFrame && inFrame <= segment.source_end_frame) {
        if (outFrame >= segment.source_start_frame) {
          next.push({
            source_start_frame: segment.source_start_frame,
            source_end_frame: outFrame,
          });
        }
        if (inFrame <= segment.source_end_frame) {
          next.push({
            source_start_frame: inFrame,
            source_end_frame: segment.source_end_frame,
          });
        }
      } else {
        next.push({
          source_start_frame: segment.source_start_frame,
          source_end_frame: segment.source_end_frame,
        });
      }
    }
    // Rebuild continuous preview times from source frame spans.
    let elapsedFrames = 0;
    return next
      .filter((item) => item.source_end_frame >= item.source_start_frame)
      .map((item) => {
        const frameCount = item.source_end_frame - item.source_start_frame + 1;
        const built = {
          source_start_frame: item.source_start_frame,
          source_end_frame: item.source_end_frame,
          preview_start_seconds: elapsedFrames / fps,
          preview_end_seconds: (elapsedFrames + frameCount) / fps,
        };
        elapsedFrames += frameCount;
        return built;
      });
  };

  // Draft OUT/IN (valid, not yet accepted) are applied to playback immediately so
  // fine-tune can hear/see the join before Accept commits the cut to the project.
  const draftCutForPlayback = (() => {
    if (!isLive) return null;
    // Prefer nudged frames when present (set after Set IN / frame cards).
    if (manualDraftBaseFrames) {
      const { outFrame, inFrame } = manualDraftBaseFrames;
      if (
        inFrame >= outFrame + 2
        && preview.segments.some(
          (item) => item.source_start_frame <= outFrame && inFrame <= item.source_end_frame,
        )
      ) {
        return { outFrame, inFrame };
      }
    }
    if (!manualOutTime.trim() || !manualInTime.trim()) return null;
    const outSeconds = parsePreviewTimecode(manualOutTime, fps);
    const inSeconds = parsePreviewTimecode(manualInTime, fps);
    if (outSeconds === null || inSeconds === null) return null;
    // Live: times are source clock. Baked: continuous compressed plan times.
    const mapFrame = (seconds: number) => {
      if (isLive) {
        const frame = Math.round(seconds * fps);
        const segment = preview.segments.find(
          (item) => item.source_start_frame <= frame && frame <= item.source_end_frame,
        );
        if (!segment) return null;
        return Math.min(segment.source_end_frame, Math.max(segment.source_start_frame, frame));
      }
      const segment = preview.segments.find(
        (item, index) =>
          seconds >= item.preview_start_seconds
          && (seconds < item.preview_end_seconds
            || (index === preview.segments.length - 1 && seconds <= item.preview_end_seconds)),
      );
      if (!segment) return null;
      const offset = Math.floor((seconds - segment.preview_start_seconds) * fps);
      return Math.min(
        segment.source_end_frame,
        Math.max(segment.source_start_frame, segment.source_start_frame + offset),
      );
    };
    const outFrame = mapFrame(outSeconds);
    const inFrame = mapFrame(inSeconds);
    if (outFrame === null || inFrame === null || inFrame < outFrame + 2) return null;
    const sameSection = preview.segments.some(
      (item) => item.source_start_frame <= outFrame && inFrame <= item.source_end_frame,
    );
    if (!sameSection) return null;
    return { outFrame, inFrame };
  })();

  const playSegments: CutSegment[] = draftCutForPlayback
    ? segmentsWithDraftCut(
        preview.segments,
        draftCutForPlayback.outFrame,
        draftCutForPlayback.inFrame,
      )
    : preview.segments;

  const segmentAtContinuous = (currentTime: number, segments: CutSegment[] = playSegments) =>
    segments.find(
      (item, index) =>
        currentTime >= item.preview_start_seconds
        && (currentTime < item.preview_end_seconds
          || (index === segments.length - 1 && currentTime <= item.preview_end_seconds)),
    );
  /** Map continuous draft-entry times (base plan) for OUT/IN capture — always base segments. */
  const sourceFrameAtPreviewTime = (currentTime: number) => {
    const segment = segmentAtContinuous(currentTime, preview.segments);
    if (!segment) return null;
    const offset = Math.floor((currentTime - segment.preview_start_seconds) * fps);
    return Math.min(segment.source_end_frame, Math.max(segment.source_start_frame, segment.source_start_frame + offset));
  };
  const previewTimeAtSourceFrame = (frame: number, segments: CutSegment[] = playSegments) => {
    const segment = segments.find(
      (item) => item.source_start_frame <= frame && frame <= item.source_end_frame,
    );
    return segment
      ? segment.preview_start_seconds + (frame - segment.source_start_frame) / fps
      : null;
  };
  const sourceSecondsFromContinuous = (currentTime: number, segments: CutSegment[] = playSegments) => {
    const segment = segmentAtContinuous(currentTime, segments);
    if (!segment) return null;
    return segment.source_start_frame / fps + (currentTime - segment.preview_start_seconds);
  };
  const continuousFromSourceSeconds = (sourceTime: number, segments: CutSegment[] = playSegments) => {
    for (let index = 0; index < segments.length; index += 1) {
      const segment = segments[index];
      const start = segment.source_start_frame / fps;
      const end = (segment.source_end_frame + 1) / fps;
      if (sourceTime + 1e-4 >= start && (sourceTime < end - 1e-4 || index === segments.length - 1)) {
        return segment.preview_start_seconds + Math.max(0, sourceTime - start);
      }
    }
    return null;
  };
  /** Source-timeline duration so cut gaps render with real removed length. */
  const sourceTimelineSeconds = (() => {
    let maxFrame = 0;
    for (const segment of preview.segments) {
      maxFrame = Math.max(maxFrame, segment.source_end_frame + 1);
    }
    for (const splice of project.splices) {
      maxFrame = Math.max(maxFrame, splice.left_out_frame + 1, splice.right_in_frame + 1);
    }
    for (const word of project.project.words) {
      maxFrame = Math.max(maxFrame, word.end_frame ?? 0);
    }
    if (project.final_cut?.out_frame != null) {
      maxFrame = Math.max(maxFrame, project.final_cut.out_frame + 1);
    }
    if (draftCutForPlayback) {
      maxFrame = Math.max(maxFrame, draftCutForPlayback.inFrame + 1, draftCutForPlayback.outFrame + 1);
    }
    const mediaFrames = Number.isFinite(videoRef.current?.duration)
      ? Math.ceil((videoRef.current?.duration ?? 0) * fps)
      : 0;
    maxFrame = Math.max(maxFrame, mediaFrames);
    return Math.max(preview.duration_seconds, maxFrame / fps);
  })();
  /** Live uses full source clock (gaps = chopped sections). Baked stays compressed. */
  const timelineDurationSeconds = isLive ? sourceTimelineSeconds : preview.duration_seconds;
  const timelinePct = (seconds: number) =>
    `${Math.min(100, Math.max(0, seconds / Math.max(timelineDurationSeconds, 0.001) * 100))}%`;
  const sourceTimeForFrame = (frame: number) => frame / fps;
  /** Keep bands drawn on the source timeline (accepted plan + draft skip). */
  const timelineKeepRanges = playSegments.map((segment) => ({
    start: sourceTimeForFrame(segment.source_start_frame),
    end: sourceTimeForFrame(segment.source_end_frame + 1),
  }));
  /**
   * Cut-output duration (kept length after accepted cuts + draft skip when active).
   * Not source/unedited length — that is timelineDurationSeconds in live mode.
   */
  const cutDurationSeconds =
    playSegments.length > 0
      ? playSegments[playSegments.length - 1].preview_end_seconds
      : preview.duration_seconds;
  /** Live playlist: source ranges that implement continuous cut playback. */
  const livePlaylistRef = useRef<
    | {
        ranges: Array<{ sourceStart: number; sourceEnd: number; continuousStart: number }>;
        index: number;
      }
    | null
  >(null);
  const maximumTimelineZoom = () => {
    const viewportWidth = Math.max(1, timelineViewportRef.current?.clientWidth ?? 1);
    const frameCount = Math.max(1, Math.ceil(timelineDurationSeconds * fps));
    return Math.max(1, Math.min(500, frameCount * 10 / viewportWidth));
  };
  const changeTimelineZoom = (requestedZoom: number, anchorX?: number) => {
    const viewport = timelineViewportRef.current;
    const nextZoom = Math.min(maximumTimelineZoom(), Math.max(1, requestedZoom));
    if (!viewport || Math.abs(nextZoom - timelineZoom) < 0.001) return;
    const anchor = Math.min(viewport.clientWidth, Math.max(0, anchorX ?? viewport.clientWidth / 2));
    const timelineRatio = (viewport.scrollLeft + anchor) / Math.max(1, viewport.scrollWidth);
    setTimelineZoom(nextZoom);
    requestAnimationFrame(() => {
      viewport.scrollLeft = timelineRatio * viewport.scrollWidth - anchor;
    });
  };
  useEffect(() => {
    const viewport = timelineViewportRef.current;
    if (!viewport) return;
    const zoomWithWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      const pointerX = event.clientX - viewport.getBoundingClientRect().left;
      const deltaScale = event.deltaMode === 1 ? 0.06 : 0.002;
      changeTimelineZoom(timelineZoom * Math.exp(-event.deltaY * deltaScale), pointerX);
    };
    viewport.addEventListener("wheel", zoomWithWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", zoomWithWheel);
  }, [timelineZoom, timelineDurationSeconds, fps]);
  const positionTimelinePlayhead = useCallback((seconds: number) => {
    const clamped = Math.min(timelineDurationSeconds, Math.max(0, seconds));
    renderedPlayheadSecondsRef.current = clamped;
    if (timelinePlayheadRef.current) {
      timelinePlayheadRef.current.style.left = `${clamped / Math.max(timelineDurationSeconds, 0.001) * 100}%`;
    }
    return clamped;
  }, [timelineDurationSeconds]);

  const commitPlayhead = useCallback(
    (seconds: number) => {
      const clamped = positionTimelinePlayhead(seconds);
      setRenderedPlayheadSeconds(clamped);
      return clamped;
    },
    [positionTimelinePlayhead],
  );

  /** Nearest keep-edge source time for a scrub inside a removed gap. */
  const snapSourcePlaybackTime = (sourceTime: number) => {
    const frame = Math.round(sourceTime * fps);
    if (draftCutForPlayback && frame > draftCutForPlayback.outFrame && frame < draftCutForPlayback.inFrame) {
      return draftCutForPlayback.inFrame / fps;
    }
    for (const segment of playSegments) {
      if (frame >= segment.source_start_frame && frame <= segment.source_end_frame) {
        return sourceTime;
      }
    }
    // In a chopped gap: park the video on the following IN (or previous OUT).
    let nextIn: number | null = null;
    let prevOut: number | null = null;
    for (const segment of playSegments) {
      const start = segment.source_start_frame / fps;
      const end = (segment.source_end_frame + 1) / fps;
      if (end <= sourceTime) prevOut = end;
      if (start >= sourceTime && nextIn == null) nextIn = start;
    }
    if (nextIn != null) return nextIn;
    if (prevOut != null) return Math.max(0, prevOut - 1 / fps);
    return sourceTime;
  };

  /**
   * Play position in the *cut* timeline (after removals), not source footage time.
   * Live UI playhead is source-based; map through playSegments for the output clock.
   */
  const cutPlayheadSeconds = (() => {
    if (!isLive) {
      return Math.min(cutDurationSeconds, Math.max(0, renderedPlayheadSeconds));
    }
    const sourceTime = snapSourcePlaybackTime(renderedPlayheadSeconds);
    const continuous = continuousFromSourceSeconds(sourceTime, playSegments);
    return Math.min(cutDurationSeconds, Math.max(0, continuous ?? 0));
  })();

  const stopTimelinePlaybackMonitor = useCallback(() => {
    if (timelinePlaybackFrameRef.current !== null) {
      cancelAnimationFrame(timelinePlaybackFrameRef.current);
      timelinePlaybackFrameRef.current = null;
    }
  }, []);
  const startTimelinePlaybackMonitor = useCallback(() => {
    stopTimelinePlaybackMonitor();
    const tick = () => {
      const video = videoRef.current;
      if (!video || video.paused || video.ended) {
        timelinePlaybackFrameRef.current = null;
        return;
      }
      const frameGuard = 1 / fps;
      const manualPreview = manualPreviewRef.current;
      if (manualPreview) {
        const segment = manualPreview.segments[manualPreview.index];
        if (segment && video.currentTime >= segment[1] - frameGuard / 2) {
          if (manualPreview.index === 0) {
            manualPreview.index = 1;
            video.currentTime = manualPreview.segments[1][0];
            commitPlayhead(manualPreview.segments[1][0]);
          } else {
            commitPlayhead(Math.min(timelineDurationSeconds, segment[1]));
            manualPreviewRef.current = null;
            setManualPreviewSeconds(null);
            video.pause();
            timelinePlaybackFrameRef.current = null;
            return;
          }
        } else {
          // Live join preview: playhead follows source clock (jumps OUT→IN with the seek).
          commitPlayhead(Math.min(timelineDurationSeconds, Math.max(0, video.currentTime)));
        }
      } else if (isLive && livePlaylistRef.current) {
        const playlist = livePlaylistRef.current;
        const range = playlist.ranges[playlist.index];
        if (!range) {
          video.pause();
          timelinePlaybackFrameRef.current = null;
          return;
        }
        // Source-timeline playhead: jumps across cut gaps when the playlist seeks.
        commitPlayhead(Math.min(timelineDurationSeconds, Math.max(0, video.currentTime)));
        if (video.currentTime >= range.sourceEnd - frameGuard / 2) {
          if (playlist.index + 1 < playlist.ranges.length) {
            playlist.index += 1;
            const next = playlist.ranges[playlist.index];
            video.currentTime = next.sourceStart;
            commitPlayhead(next.sourceStart);
          } else {
            commitPlayhead(Math.min(timelineDurationSeconds, range.sourceEnd));
            livePlaylistRef.current = null;
            video.pause();
            timelinePlaybackFrameRef.current = null;
            return;
          }
        }
      } else if (isLive) {
        commitPlayhead(Math.min(timelineDurationSeconds, Math.max(0, video.currentTime)));
      } else {
        commitPlayhead(video.currentTime);
      }
      timelinePlaybackFrameRef.current = requestAnimationFrame(tick);
    };
    timelinePlaybackFrameRef.current = requestAnimationFrame(tick);
  }, [
    commitPlayhead,
    fps,
    isLive,
    stopTimelinePlaybackMonitor,
    timelineDurationSeconds,
    videoRef,
  ]);
  useEffect(() => stopTimelinePlaybackMonitor, [stopTimelinePlaybackMonitor]);
  const timelineTimeAtPointer = (clientX: number) => {
    const timeline = timelineContentRef.current;
    if (!timeline) return null;
    const bounds = timeline.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - bounds.left) / Math.max(1, bounds.width)));
    const totalFrames = Math.max(1, Math.round(timelineDurationSeconds * fps));
    return Math.min(timelineDurationSeconds, Math.round(ratio * totalFrames) / fps);
  };
  const scrubTimelineToPointer = (clientX: number, commitState = false) => {
    const time = timelineTimeAtPointer(clientX);
    const video = videoRef.current;
    if (time === null || !video) return null;
    livePlaylistRef.current = null;
    if (isLive) {
      // Playhead can sit inside a chopped gap; video parks on the nearest keep edge.
      const playbackTime = snapSourcePlaybackTime(time);
      video.currentTime = playbackTime;
      positionTimelinePlayhead(time);
      if (commitState) setRenderedPlayheadSeconds(time);
      return time;
    }
    video.currentTime = time;
    positionTimelinePlayhead(time);
    if (commitState) setRenderedPlayheadSeconds(time);
    return time;
  };

  const playLiveFromContinuous = (fromTimelineSeconds: number) => {
    const video = videoRef.current;
    if (!video || !isLive) return;
    // Timeline is source clock in live mode.
    let startSource = fromTimelineSeconds;
    startSource = snapSourcePlaybackTime(startSource);
    // Source playlist from playSegments (accepted cuts + draft skip).
    const ranges: Array<{ sourceStart: number; sourceEnd: number; continuousStart: number }> = [];
    for (const segment of playSegments) {
      const segStart = segment.source_start_frame / fps;
      const segEnd = (segment.source_end_frame + 1) / fps;
      if (segEnd <= startSource + 1e-6) continue;
      const sourceStart = Math.max(startSource, segStart);
      ranges.push({
        sourceStart,
        sourceEnd: segEnd,
        continuousStart: 0,
      });
    }
    if (!ranges.length) return;
    livePlaylistRef.current = { ranges, index: 0 };
    manualPreviewRef.current = null;
    setManualPreviewSeconds(null);
    video.currentTime = ranges[0].sourceStart;
    commitPlayhead(ranges[0].sourceStart);
    void video.play().catch(() => undefined);
    startTimelinePlaybackMonitor();
  };
  const cancelManualDraftPreview = () => {
    manualPreviewRef.current = null;
    setManualPreviewSeconds(null);
  };
  const beginTimelineScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    cancelManualDraftPreview();
    videoRef.current?.pause();
    timelineScrubbingRef.current = true;
    setTimelineScrubbing(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    scrubTimelineToPointer(event.clientX);
  };
  /** Click / drag anywhere on the timeline body (not cut buttons) to move the playhead. */
  const beginTimelineAreaSeek = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest(".rendered-timeline-playhead, .timeline-cut-markers, button")) return;
    beginTimelineScrub(event);
  };
  const moveTimelineScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!timelineScrubbingRef.current) return;
    scrubTimelineToPointer(event.clientX);
  };
  const finishTimelineScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!timelineScrubbingRef.current) return;
    scrubTimelineToPointer(event.clientX, true);
    timelineScrubbingRef.current = false;
    setTimelineScrubbing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };
  const cancelTimelineScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    timelineScrubbingRef.current = false;
    setTimelineScrubbing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setRenderedPlayheadSeconds(renderedPlayheadSecondsRef.current);
  };
  const handleTimelinePlayheadKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      cancelManualDraftPreview();
      livePlaylistRef.current = null;
      videoRef.current?.pause();
      const direction = event.key === "ArrowLeft" ? -1 : 1;
      const next = positionTimelinePlayhead(renderedPlayheadSecondsRef.current + direction / fps);
      if (videoRef.current) {
        if (isLive) {
          videoRef.current.currentTime = snapSourcePlaybackTime(next);
        } else {
          videoRef.current.currentTime = next;
        }
      }
      setRenderedPlayheadSeconds(next);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (isLive) playLiveFromContinuous(renderedPlayheadSecondsRef.current);
      else void videoRef.current?.play().catch(() => undefined);
    }
  };
  const sourceFrameAtSourceTime = (sourceSeconds: number) => {
    const frame = Math.round(sourceSeconds * fps);
    const segment = preview.segments.find(
      (item) => item.source_start_frame <= frame && frame <= item.source_end_frame,
    );
    if (!segment) return null;
    return Math.min(segment.source_end_frame, Math.max(segment.source_start_frame, frame));
  };
  const resolveManualCutDraft = (outValue: string, inValue: string): {
    cut: { outSeconds: number; inSeconds: number; outFrame: number; inFrame: number } | null;
    error: string;
  } => {
    const outSeconds = parsePreviewTimecode(outValue, project.project.fps);
    const inSeconds = parsePreviewTimecode(inValue, project.project.fps);
    if (outSeconds === null || inSeconds === null) {
      return { cut: null, error: "Enter times as SS, MM:SS, HH:MM:SS, or HH:MM:SS:FF." };
    }
    const maxTime = isLive ? timelineDurationSeconds : preview.duration_seconds;
    if (outSeconds < 0 || inSeconds < 0 || outSeconds > maxTime || inSeconds > maxTime) {
      return { cut: null, error: `Times must stay within this ${formatTime(maxTime)} timeline.` };
    }
    // Live timeline is source clock; baked preview stays continuous compressed time.
    const outFrame = isLive ? sourceFrameAtSourceTime(outSeconds) : sourceFrameAtPreviewTime(outSeconds);
    const inFrame = isLive ? sourceFrameAtSourceTime(inSeconds) : sourceFrameAtPreviewTime(inSeconds);
    if (outFrame === null || inFrame === null) {
      return { cut: null, error: "One of those times does not map to a kept section of this preview." };
    }
    const outSegment = preview.segments.find((item) => item.source_start_frame <= outFrame && outFrame <= item.source_end_frame);
    const inSegment = preview.segments.find((item) => item.source_start_frame <= inFrame && inFrame <= item.source_end_frame);
    if (outSegment !== inSegment) {
      return { cut: null, error: "A manual cut cannot cross an existing cut marker. Add it on one side of that marker." };
    }
    if (inFrame < outFrame + 2) {
      return { cut: null, error: "IN must be at least two frames after OUT so the cut removes a complete frame." };
    }
    return { cut: { outSeconds, inSeconds, outFrame, inFrame }, error: "" };
  };
  const parsedManualOutSeconds = parsePreviewTimecode(manualOutTime, project.project.fps);
  const manualOutReady = parsedManualOutSeconds !== null
    && parsedManualOutSeconds >= 0
    && parsedManualOutSeconds <= (isLive ? timelineDurationSeconds : preview.duration_seconds)
    && (isLive
      ? sourceFrameAtSourceTime(parsedManualOutSeconds) !== null
      : sourceFrameAtPreviewTime(parsedManualOutSeconds) !== null);
  const resolvedManualDraft = manualInTime.trim()
    ? resolveManualCutDraft(manualOutTime, manualInTime).cut
    : null;
  const manualDraftFrames = resolvedManualDraft
    ? (manualDraftBaseFrames ?? { outFrame: resolvedManualDraft.outFrame, inFrame: resolvedManualDraft.inFrame })
    : null;
  const manualDraftSegment = resolvedManualDraft
    ? preview.segments.find(
      (item) => item.source_start_frame <= resolvedManualDraft.outFrame
        && resolvedManualDraft.inFrame <= item.source_end_frame,
    )
    : null;
  const manualDraftTimeText = (frame: number) => {
    // Live: source clock. Baked: continuous base plan.
    const seconds = isLive
      ? sourceTimeForFrame(frame)
      : previewTimeAtSourceFrame(frame, preview.segments);
    if (seconds === null) return null;
    const timecode = formatPreviewTimecode(seconds, fps);
    if (isLive) return timecode;
    const parsed = parsePreviewTimecode(timecode, fps);
    if (parsed !== null && sourceFrameAtPreviewTime(parsed) === frame) return timecode;
    return (seconds + 0.25 / fps).toFixed(6);
  };
  const nudgeManualDraft = (outDelta: number, inDelta: number) => {
    if (!resolvedManualDraft || !manualDraftSegment) return;
    const baseOut = manualDraftBaseFrames?.outFrame ?? resolvedManualDraft.outFrame;
    const baseIn = manualDraftBaseFrames?.inFrame ?? resolvedManualDraft.inFrame;
    const nextOutFrame = baseOut + outDelta;
    const nextInFrame = baseIn + inDelta;
    if (
      nextOutFrame < manualDraftSegment.source_start_frame
      || nextInFrame > manualDraftSegment.source_end_frame
      || nextInFrame < nextOutFrame + 2
    ) return;
    const nextOutTime = manualDraftTimeText(nextOutFrame);
    const nextInTime = manualDraftTimeText(nextInFrame);
    if (!nextOutTime || !nextInTime) {
      setManualCutError("That nudge falls outside the working preview.");
      return;
    }
    cancelManualDraftPreview();
    livePlaylistRef.current = null;
    videoRef.current?.pause();
    setManualOutTime(nextOutTime);
    setManualInTime(nextInTime);
    setManualDraftBaseFrames({ outFrame: nextOutFrame, inFrame: nextInFrame });
    setManualCutError("");
  };
  /** Timeline clock under the playhead for OUT/IN entry (source in live mode). */
  const timelineTimeFromPlayhead = () => {
    if (isLive) {
      // Prefer the white playhead so scrubbing a gap still sets OUT/IN to that source time
      // when the pointer is on a keep; otherwise use the parked video clock.
      return renderedPlayheadSecondsRef.current;
    }
    return renderedPlayheadSecondsRef.current;
  };
  const setManualOutFromPlayhead = () => {
    cancelManualDraftPreview();
    livePlaylistRef.current = null;
    videoRef.current?.pause();
    setManualOutTime(formatPreviewTimecode(timelineTimeFromPlayhead(), fps));
    setManualInTime("");
    setManualDraftBaseFrames(null);
    setManualCutError("");
  };
  const setManualInFromPlayhead = () => {
    if (!manualOutReady) {
      setManualCutError("Set a valid OUT point before setting IN.");
      return;
    }
    const candidate = formatPreviewTimecode(timelineTimeFromPlayhead(), fps);
    const resolved = resolveManualCutDraft(manualOutTime, candidate);
    if (!resolved.cut) {
      setManualCutError(resolved.error);
      return;
    }
    cancelManualDraftPreview();
    livePlaylistRef.current = null;
    videoRef.current?.pause();
    setManualInTime(candidate);
    setManualDraftBaseFrames({ outFrame: resolved.cut.outFrame, inFrame: resolved.cut.inFrame });
    setManualCutError("");
  };
  /** Half-math join preview: N/2 before OUT, N/2 after IN (draft manual cut or selected splice). */
  const playJoinPreview = (seconds: 2 | 4 | 6) => {
    const video = videoRef.current;
    if (!video) {
      setManualCutError("The cut preview is not ready.");
      return;
    }

    let segments: [[number, number], [number, number]] | null = null;

    // Prefer an in-progress draft OUT/IN when both sides are set.
    const draftResolved = manualOutTime.trim() && manualInTime.trim()
      ? resolveManualCutDraft(manualOutTime, manualInTime)
      : null;
    if (draftResolved?.cut) {
      const outFrame = manualDraftBaseFrames?.outFrame ?? draftResolved.cut.outFrame;
      const inFrame = manualDraftBaseFrames?.inFrame ?? draftResolved.cut.inFrame;
      const section = preview.segments.find(
        (item) => item.source_start_frame <= outFrame && inFrame <= item.source_end_frame,
      );
      if (!section) {
        setManualCutError("That manual cut no longer sits inside one kept section.");
        return;
      }
      const halfSeconds = seconds / 2;
      const sectionSourceStart = section.source_start_frame / fps;
      const sectionSourceEnd = (section.source_end_frame + 1) / fps;
      const outEndSource = (outFrame + 1) / fps;
      const inStartSource = inFrame / fps;
      const preRollStart = Math.max(sectionSourceStart, outEndSource - halfSeconds);
      const postRollEnd = Math.min(sectionSourceEnd, inStartSource + halfSeconds);
      if (outEndSource - preRollStart < 1 / fps || postRollEnd - inStartSource < 1 / fps) {
        setManualCutError("Not enough room around OUT/IN for that join preview length.");
        return;
      }
      segments = [
        [preRollStart, outEndSource],
        [inStartSource, postRollEnd],
      ];
    } else if (selectedSplice) {
      // Accepted splices: use server-built source pre/post rolls (same half-math).
      const key = `preview_segments_${seconds}s` as const;
      const prepared = selectedSplice[key];
      if (prepared?.length >= 2) {
        segments = [
          [prepared[0][0], prepared[0][1]],
          [prepared[1][0], prepared[1][1]],
        ];
      } else {
        // Fallback if preview segments are missing from the project payload.
        const halfSeconds = seconds / 2;
        const outEndSource = (selectedSplice.left_out_frame + 1) / fps;
        const inStartSource = selectedSplice.right_in_frame / fps;
        segments = [
          [Math.max(0, outEndSource - halfSeconds), outEndSource],
          [inStartSource, inStartSource + halfSeconds],
        ];
      }
      setManualCutError("");
    } else {
      setManualCutError(draftResolved?.error || "Select a splice or set draft OUT/IN to preview a join.");
      return;
    }

    video.pause();
    livePlaylistRef.current = null;
    manualPreviewRef.current = {
      segments,
      index: 0,
    };
    setManualPreviewSeconds(seconds);
    setManualCutError("");
    // Source-timeline playhead follows the media clock across the OUT→IN jump.
    commitPlayhead(segments[0][0]);
    void playMediaAt(video, segments[0][0])
      .then(() => startTimelinePlaybackMonitor())
      .catch((error) => {
        manualPreviewRef.current = null;
        setManualPreviewSeconds(null);
        setManualCutError(`Preview failed: ${error instanceof Error ? error.message : String(error)}`);
      });
  };
  const finishManualCut = async () => {
    const resolved = resolveManualCutDraft(manualOutTime, manualInTime);
    if (!resolved.cut) {
      setManualCutError(resolved.error);
      return;
    }
    const { outFrame, inFrame } = resolved.cut;
    const existingManualCutIds = new Set(
      project.splices.filter((splice) => splice.kind === "manual").map((splice) => splice.manual_cut_id),
    );
    cancelManualDraftPreview();
    videoRef.current?.pause();
    const result = await updateSplice(
      () => addManualCut(outFrame, inFrame),
      (data) => {
        const createdCut = data.splices.find(
          (splice) => splice.kind === "manual" && !existingManualCutIds.has(splice.manual_cut_id),
        );
        if (createdCut) selectSplice(createdCut);
      },
    );
    if (result) {
      setManualOutTime("");
      setManualInTime("");
      setManualDraftBaseFrames(null);
      setManualCutError("");
    }
  };
  const clearManualDraft = () => {
    cancelManualDraftPreview();
    livePlaylistRef.current = null;
    videoRef.current?.pause();
    setManualOutTime("");
    setManualInTime("");
    setManualDraftBaseFrames(null);
    setManualCutError("");
    setManualPreviewSeconds(null);
  };
  /** Clear draft OUT/IN, or remove the selected accepted splice (manual or transcript). */
  const clearOrRemoveCut = async () => {
    const hasDraft = Boolean(manualOutTime.trim() || manualInTime.trim() || manualDraftBaseFrames);
    if (hasDraft) {
      clearManualDraft();
      return;
    }
    if (!selectedSplice) {
      setManualCutError("Select a splice to remove, or set a draft OUT/IN to clear.");
      return;
    }
    cancelManualDraftPreview();
    videoRef.current?.pause();
    const removedKey = selectedSplice.anchor_key;
    const nextKey =
      project.splices[selectedSpliceIndex + 1]?.anchor_key
      ?? project.splices[selectedSpliceIndex - 1]?.anchor_key
      ?? null;
    const result = await updateSplice(
      () => removeSplice(selectedSplice.anchor_key),
      (data) => {
        const stillThere = data.splices.some((splice) => splice.anchor_key === removedKey);
        if (stillThere) return;
        const preferred = nextKey && data.splices.some((splice) => splice.anchor_key === nextKey)
          ? nextKey
          : data.splices[0]?.anchor_key ?? null;
        if (preferred) {
          const next = data.splices.find((splice) => splice.anchor_key === preferred);
          if (next) selectSplice(next);
        }
      },
    );
    if (result) setManualCutError("");
  };
  const canClearOrRemove = Boolean(
    manualOutTime.trim()
    || manualInTime.trim()
    || manualDraftBaseFrames
    || selectedSplice,
  );
  return (
    <section className="rendered-cut-workspace">
      {/* Former left splice transcript list (Before/After) — restore if needed.
      <aside className="rendered-cut-sidebar">…</aside>
      */}

      {/* Left: all Stage 4 controls (transport, manual cut, timeline, nudges). */}
      <section className="rendered-cut-controls" ref={cutControlsRef}>
        {!isLive && stale ? (
          <div className="rendered-cut-heading">
            <span className="preview-stale"><Gauge size={15} /> Working preview · {pendingFrames} pending change{pendingFrames === 1 ? "" : "s"}</span>
          </div>
        ) : null}

        <section className="rendered-splice-controls">
          <div className="rendered-control-heading">
            {resolvedManualDraft ? (
              <h3 className="rendered-control-heading-label">Manual cut draft · not yet accepted</h3>
            ) : project.splices.length > 0 ? (
              <label className="splice-picker">
                <span className="sr-only">Select splice</span>
                <select
                  value={selectedSplice?.anchor_key ?? ""}
                  onChange={(event) => {
                    const next = project.splices.find((splice) => splice.anchor_key === event.target.value);
                    if (next) selectSplice(next);
                  }}
                  disabled={busy}
                  aria-label="Select splice"
                >
                  {project.splices.map((splice, index) => (
                    <option key={splice.anchor_key} value={splice.anchor_key}>
                      {`Splice ${index + 1} of ${project.splices.length}${
                        splice.kind === "manual" ? " · Manual" : splice.kind === "front_trim" ? " · Front trim" : ""
                      }`}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <h3 className="rendered-control-heading-label">No splice selected</h3>
            )}
          </div>
          {resolvedManualDraft && manualDraftFrames && manualDraftSegment ? (
            <div className="rendered-frame-grid">
              <CutFrameCard
                title="Draft OUT frame"
                frame={manualDraftFrames.outFrame}
                fps={project.project.fps}
                adjustment={manualDraftFrames.outFrame - resolvedManualDraft.outFrame}
                whisperFrame={resolvedManualDraft.outFrame}
                suggestedFrame={resolvedManualDraft.outFrame}
                minFrame={manualDraftSegment.source_start_frame}
                maxFrame={manualDraftFrames.inFrame - 2}
                sourceLabel="Set"
                onNudge={(delta) => nudgeManualDraft(delta, 0)}
              />
              <CutFrameCard
                title="Draft IN frame"
                frame={manualDraftFrames.inFrame}
                fps={project.project.fps}
                adjustment={manualDraftFrames.inFrame - resolvedManualDraft.inFrame}
                whisperFrame={resolvedManualDraft.inFrame}
                suggestedFrame={resolvedManualDraft.inFrame}
                minFrame={manualDraftFrames.outFrame + 2}
                maxFrame={manualDraftSegment.source_end_frame}
                sourceLabel="Set"
                onNudge={(delta) => nudgeManualDraft(0, delta)}
              />
            </div>
          ) : selectedSplice && (
            <div className={isFrontTrim ? "rendered-frame-grid single" : "rendered-frame-grid"}>
              {!isFrontTrim && (
                <CutFrameCard
                  title="OUT frame"
                  frame={selectedSplice.left_out_frame}
                  fps={project.project.fps}
                  adjustment={selectedSplice.left_out_adjustment}
                  whisperFrame={selectedSplice.left_whisper_out_frame}
                  suggestedFrame={selectedSplice.left_suggested_out_frame}
                  maxFrame={selectedSplice.right_in_frame - (selectedSplice.kind === "manual" ? 2 : 1)}
                  sourceLabel={selectedSplice.kind === "manual" ? "Initial" : "Whisper"}
                  onNudge={(delta) => void updateSplice(() => selectedSplice.kind === "manual"
                    ? adjustManualCut(selectedSplice.manual_cut_id, delta, 0)
                    : adjustSplice(selectedSplice.anchor_key, delta, 0))}
                />
              )}
              <CutFrameCard
                title={isFrontTrim ? "START frame" : "IN frame"}
                frame={selectedSplice.right_in_frame}
                fps={project.project.fps}
                adjustment={selectedSplice.right_in_adjustment}
                whisperFrame={selectedSplice.right_in_frame - selectedSplice.right_in_adjustment}
                suggestedFrame={selectedSplice.right_in_frame - selectedSplice.right_in_adjustment}
                minFrame={isFrontTrim ? 0 : selectedSplice.left_out_frame + (selectedSplice.kind === "manual" ? 2 : 1)}
                sourceLabel={selectedSplice.kind === "manual" ? "Initial" : "Whisper"}
                onNudge={(delta) => void updateSplice(() => selectedSplice.kind === "manual"
                  ? adjustManualCut(selectedSplice.manual_cut_id, 0, delta)
                  : adjustSplice(selectedSplice.anchor_key, 0, delta))}
              />
            </div>
          )}
        </section>
        <div className="rendered-timeline-shell">
          <div className="rendered-timeline-toolbar">
            <span className="rendered-timeline-toolbar-label">
              <strong>Cut timeline</strong>
            </span>
            <div className="rendered-timeline-transport" aria-label="Cut transport">
              <button
                type="button"
                className="rendered-timeline-play-toggle"
                title={timelinePlaying ? "Pause" : isLive ? "Play cut" : "Play"}
                aria-label={timelinePlaying ? "Pause" : isLive ? "Play cut" : "Play"}
                disabled={busy}
                onClick={() => {
                  if (timelinePlaying) {
                    videoRef.current?.pause();
                    livePlaylistRef.current = null;
                    return;
                  }
                  if (isLive) playLiveFromContinuous(renderedPlayheadSecondsRef.current);
                  else void videoRef.current?.play().catch(() => undefined);
                }}
              >
                {timelinePlaying ? <Pause size={15} /> : <Play size={15} />}
              </button>
              <div className="manual-cut-preview-controls timeline-join-preview" aria-label="Join preview duration">
                {([2, 4, 6] as const).map((seconds) => (
                  <button
                    key={seconds}
                    type="button"
                    className={manualPreviewSeconds === seconds ? "active" : ""}
                    onClick={() => playJoinPreview(seconds)}
                    disabled={
                      busy
                      || !(
                        selectedSplice
                        || (manualOutReady && Boolean(manualInTime.trim()))
                      )
                    }
                    title={`Preview ${seconds}s join (${seconds / 2}s before OUT, ${seconds / 2}s after IN)`}
                  >{seconds}s</button>
                ))}
              </div>
            </div>
            <div className="rendered-timeline-zoom-controls" aria-label="Timeline zoom controls">
              <button title="Zoom timeline out" onClick={() => changeTimelineZoom(timelineZoom / 1.5)} disabled={timelineZoom <= 1.001}>−</button>
              <button title="Reset timeline zoom" onClick={() => changeTimelineZoom(1)}>{timelineZoom < 10 ? timelineZoom.toFixed(1) : timelineZoom.toFixed(0)}×</button>
              <button title="Zoom timeline in" onClick={() => changeTimelineZoom(timelineZoom * 1.5)} disabled={timelineZoom >= maximumTimelineZoom() - 0.001}>+</button>
            </div>
          </div>
          <div
            className="rendered-timeline-viewport"
            ref={timelineViewportRef}
          >
            <div
              className="rendered-timeline"
              ref={timelineContentRef}
              aria-label="Rendered cut splice timeline"
              style={{ width: `${timelineZoom * 100}%` }}
              onPointerDown={beginTimelineAreaSeek}
              onPointerMove={moveTimelineScrub}
              onPointerUp={finishTimelineScrub}
              onPointerCancel={cancelTimelineScrub}
              onLostPointerCapture={() => {
                timelineScrubbingRef.current = false;
                setTimelineScrubbing(false);
              }}
            >
              <div className="rendered-timeline-track" />
              {isLive && timelineKeepRanges.map((range, index) => (
                <div
                  key={`keep-${index}`}
                  className="timeline-keep-range"
                  style={{
                    left: timelinePct(range.start),
                    width: `${Math.max(0, (range.end - range.start) / Math.max(timelineDurationSeconds, 0.001) * 100)}%`,
                  }}
                />
              ))}
              {project.splices.map((splice, index) => {
                const marker = previewMarkerByAnchor.get(splice.anchor_key);
                const pending = !marker;
                const isFrontTrimCut = splice.kind === "front_trim";
                const outTime = isLive
                  ? sourceTimeForFrame(splice.left_out_frame)
                  : (marker?.preview_time_seconds ?? previewTimeAtSourceFrame(splice.left_out_frame) ?? 0);
                const inTime = isLive
                  ? sourceTimeForFrame(splice.right_in_frame)
                  : (marker?.preview_time_seconds ?? previewTimeAtSourceFrame(splice.right_in_frame) ?? outTime);
                const rangeStart = Math.min(outTime, inTime);
                const rangeEnd = Math.max(outTime, inTime);
                const rangeWidth = Math.max(rangeEnd - rangeStart, 1 / fps);
                const label = splice.kind === "manual"
                  ? "Manual cut"
                  : isFrontTrimCut
                    ? "Front trim"
                    : `Splice ${index + 1}`;
                const removedSeconds = Math.max(0, (splice.right_in_frame - splice.left_out_frame) / fps);
                return (
                  <button
                    key={splice.anchor_key}
                    type="button"
                    className={[
                      "timeline-cut-markers",
                      selectedSplice?.anchor_key === splice.anchor_key ? "active" : "",
                      splice.kind === "manual" ? "manual" : "",
                      pending ? "pending" : "",
                      splice.reviewed ? "reviewed" : "",
                      isFrontTrimCut ? "front-trim" : "",
                    ].join(" ")}
                    style={{
                      left: timelinePct(rangeStart),
                      width: `${Math.max(0.15, rangeWidth / Math.max(timelineDurationSeconds, 0.001) * 100)}%`,
                    }}
                    title={`${label} · remove ${formatTime(removedSeconds)} · OUT ${formatPreviewTimecode(outTime, fps)} → IN ${formatPreviewTimecode(inTime, fps)}${pending ? " · accepted, not yet in the working video" : ""}`}
                    aria-label={`${label}, removes ${formatTime(removedSeconds)}`}
                    onClick={() => selectSplice(splice)}
                  >
                    <span className="timeline-cut-range" aria-hidden="true" />
                    {!isFrontTrimCut && (
                      <span className="manual-draft-boundary out" aria-hidden="true" />
                    )}
                    <span className="manual-draft-boundary in" aria-hidden="true" />
                  </button>
                );
              })}
              {manualOutReady && parsedManualOutSeconds !== null && !resolvedManualDraft && (
                <div
                  className="manual-draft-boundary out"
                  style={{ left: timelinePct(parsedManualOutSeconds) }}
                  title={`Draft OUT ${formatPreviewTimecode(parsedManualOutSeconds, project.project.fps)}`}
                />
              )}
              {resolvedManualDraft && manualDraftFrames && (
                <>
                  <div
                    className="manual-draft-cut-range"
                    style={{
                      left: timelinePct(
                        isLive
                          ? sourceTimeForFrame(manualDraftFrames.outFrame)
                          : resolvedManualDraft.outSeconds,
                      ),
                      width: `${Math.max(
                        0.15,
                        (
                          (isLive
                            ? sourceTimeForFrame(manualDraftFrames.inFrame) - sourceTimeForFrame(manualDraftFrames.outFrame)
                            : resolvedManualDraft.inSeconds - resolvedManualDraft.outSeconds)
                          / Math.max(timelineDurationSeconds, 0.001)
                        ) * 100,
                      )}%`,
                    }}
                  />
                  <div
                    className="manual-draft-boundary out"
                    style={{
                      left: timelinePct(
                        isLive
                          ? sourceTimeForFrame(manualDraftFrames.outFrame)
                          : resolvedManualDraft.outSeconds,
                      ),
                    }}
                    title={`Draft OUT ${formatPreviewTimecode(
                      isLive ? sourceTimeForFrame(manualDraftFrames.outFrame) : resolvedManualDraft.outSeconds,
                      project.project.fps,
                    )}`}
                  />
                  <div
                    className="manual-draft-boundary in"
                    style={{
                      left: timelinePct(
                        isLive
                          ? sourceTimeForFrame(manualDraftFrames.inFrame)
                          : resolvedManualDraft.inSeconds,
                      ),
                    }}
                    title={`Draft IN ${formatPreviewTimecode(
                      isLive ? sourceTimeForFrame(manualDraftFrames.inFrame) : resolvedManualDraft.inSeconds,
                      project.project.fps,
                    )}`}
                  />
                </>
              )}
              <div
                ref={timelinePlayheadRef}
                className={["rendered-timeline-playhead", timelineScrubbing ? "scrubbing" : ""].join(" ")}
                style={{ left: timelinePct(renderedPlayheadSeconds) }}
                role="slider"
                tabIndex={0}
                aria-label="Preview playhead"
                aria-valuemin={0}
                aria-valuemax={timelineDurationSeconds}
                aria-valuenow={renderedPlayheadSeconds}
                aria-valuetext={formatPreviewTimecode(renderedPlayheadSeconds, project.project.fps)}
                title={`${formatPreviewTimecode(renderedPlayheadSeconds, project.project.fps)} · drag to scrub, release to hold`}
                onPointerDown={beginTimelineScrub}
                onPointerMove={moveTimelineScrub}
                onPointerUp={finishTimelineScrub}
                onPointerCancel={cancelTimelineScrub}
                onLostPointerCapture={() => {
                  timelineScrubbingRef.current = false;
                  setTimelineScrubbing(false);
                }}
                onKeyDown={handleTimelinePlayheadKey}
              >
                <span />
              </div>
            </div>
          </div>
          <div className="manual-cut-actions" aria-label="Manual cut actions">
            <strong className="manual-cut-actions-label">Manual Cut</strong>
            <button type="button" onClick={setManualOutFromPlayhead} disabled={busy}>
              Set OUT
            </button>
            <button type="button" onClick={setManualInFromPlayhead} disabled={busy || !manualOutReady}>
              Set IN
            </button>
            <button
              type="button"
              className="manual-cut-confirm"
              onClick={() => void finishManualCut()}
              disabled={busy || !manualOutTime.trim() || !manualInTime.trim()}
            >
              Accept
            </button>
            <button
              type="button"
              className="danger"
              onClick={() => void clearOrRemoveCut()}
              disabled={busy || !canClearOrRemove}
              title={
                manualOutTime.trim() || manualInTime.trim() || manualDraftBaseFrames
                  ? "Clear draft OUT/IN"
                  : selectedSplice
                    ? "Remove this cut and restore the removed section"
                    : "Nothing to clear"
              }
            >
              <Trash2 size={14} />
              {manualOutTime.trim() || manualInTime.trim() || manualDraftBaseFrames
                ? "Clear"
                : "Remove"}
            </button>
          </div>
          {manualCutError ? <p className="manual-cut-error" role="alert">{manualCutError}</p> : null}
          <div
            className="timeline-cut-clock"
            title="Play position in the cut / total length after cuts (not source footage length)"
            aria-label={`Cut time ${formatTime(cutPlayheadSeconds)} of ${formatTime(cutDurationSeconds)}`}
          >
            <span className="timeline-cut-clock-current">{formatTime(cutPlayheadSeconds)}</span>
            <span className="timeline-cut-clock-sep" aria-hidden="true">/</span>
            <span className="timeline-cut-clock-total">{formatTime(cutDurationSeconds)}</span>
          </div>
        </div>

      </section>

      {/* Right: large video preview only (no transport or edit chrome). */}
      <section className="rendered-cut-video-panel" ref={cutVideoPanelRef} aria-label="Cut video preview">
        <div className="rendered-cut-video">
          <video
            key={preview.preview_id}
            ref={videoRef}
            controls={false}
            preload="metadata"
            playsInline
            src={
              isLive
                ? sourceVideoSrc
                : renderedCutPreviewUrl(preview.preview_id)
            }
            onLoadedMetadata={() => {
              if (selectedSplice) seekRenderedJoin(selectedSplice, false);
              else if (isLive && preview.segments[0]) {
                const first = preview.segments[0];
                const startSource = first.source_start_frame / fps;
                if (videoRef.current) {
                  videoRef.current.currentTime = startSource;
                }
                positionTimelinePlayhead(startSource);
                setRenderedPlayheadSeconds(startSource);
              } else {
                const currentTime = positionTimelinePlayhead(videoRef.current?.currentTime ?? 0);
                setRenderedPlayheadSeconds(currentTime);
              }
            }}
            onTimeUpdate={(event) => {
              if (isLive) {
                // Source-timeline playhead tracks the media clock (jumps across cut gaps).
                commitPlayhead(event.currentTarget.currentTime);
                return;
              }
              commitPlayhead(event.currentTarget.currentTime);
            }}
            onPlay={() => {
              setTimelinePlaying(true);
              if (isLive && !livePlaylistRef.current && !manualPreviewRef.current) {
                // Native play without playlist: build from current source playhead.
                playLiveFromContinuous(renderedPlayheadSecondsRef.current);
                return;
              }
              startTimelinePlaybackMonitor();
            }}
            onPause={() => {
              setTimelinePlaying(false);
              stopTimelinePlaybackMonitor();
              livePlaylistRef.current = null;
            }}
            onEnded={() => {
              setTimelinePlaying(false);
              stopTimelinePlaybackMonitor();
            }}
          />
        </div>
      </section>
    </section>
  );
}

function SpliceReviewPanel({
  loop,
  moveSpliceSelection,
  playSplice,
  playFinalCut,
  project,
  reviewSpliceAndAdvance,
  selectedSplice,
  selectedSpliceIndex,
  setLoop,
  sourceVideoRef,
  updateSplice,
}: {
  loop: boolean;
  moveSpliceSelection: (direction: -1 | 1) => void;
  playSplice: (splice: DynamicSplice, seconds: 2 | 4 | 6) => void;
  playFinalCut: (seconds: 2 | 4 | 6) => void;
  project: EditorProjectResponse | null;
  reviewSpliceAndAdvance: (splice: DynamicSplice) => void;
  selectedSplice: DynamicSplice | undefined;
  selectedSpliceIndex: number;
  setLoop: Dispatch<SetStateAction<boolean>>;
  sourceVideoRef: RefObject<HTMLVideoElement | null>;
  updateSplice: (operation: () => Promise<EditorProjectResponse>) => void;
}) {
  const count = project?.splices.length ?? 0;
  const isFrontTrim = selectedSplice?.left_word_id === "";
  const finalCut = project?.final_cut ?? null;
  const [finalCutExpanded, setFinalCutExpanded] = useState(false);
  const [finalOutDraft, setFinalOutDraft] = useState(finalCut ? String(finalCut.out_frame) : "");
  useEffect(() => {
    setFinalOutDraft(finalCut ? String(finalCut.out_frame) : "");
  }, [finalCut?.out_frame]);
  const sourceVideo = sourceVideoRef.current;
  const sourceMaximumOutFrame = sourceVideo && Number.isFinite(sourceVideo.duration)
    ? Math.max(0, Math.ceil(sourceVideo.duration * (project?.project.fps ?? 30)) - 1)
    : null;
  const maximumOutFrame = finalCut?.maximum_out_frame === null
    ? sourceMaximumOutFrame
    : sourceMaximumOutFrame === null
      ? finalCut?.maximum_out_frame
      : Math.min(finalCut?.maximum_out_frame ?? sourceMaximumOutFrame, sourceMaximumOutFrame);
  const parsedFinalOutDraft = Number(finalOutDraft);
  const finalOutDraftValid = !!finalCut
    && finalOutDraft.trim() !== ""
    && Number.isInteger(parsedFinalOutDraft)
    && parsedFinalOutDraft >= finalCut.minimum_out_frame
    && (maximumOutFrame === null || maximumOutFrame === undefined || parsedFinalOutDraft <= maximumOutFrame);
  const setFinalFromPlayhead = () => {
    if (!finalCut || !sourceVideo || !Number.isFinite(sourceVideo.currentTime)) return;
    const requestedFrame = Math.max(0, Math.round(sourceVideo.currentTime * (project?.project.fps ?? 30)));
    const frame = maximumOutFrame === null || maximumOutFrame === undefined
      ? requestedFrame
      : Math.min(maximumOutFrame, requestedFrame);
    setFinalOutDraft(String(frame));
    updateSplice(() => setFinalOutFrame(frame));
  };
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
      <div className="splice-review-content">
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
        {finalCut && (
          <div className={finalCutExpanded ? "final-cut-control expanded" : "final-cut-control collapsed"}>
            <div className="final-cut-heading">
              <button
                type="button"
                className="final-cut-toggle"
                aria-expanded={finalCutExpanded}
                aria-controls="final-cut-details"
                onClick={() => setFinalCutExpanded((expanded) => !expanded)}
              >
                <span>
                  <strong>Final endpoint</strong>
                  <small>
                    {finalCutExpanded
                      ? "Seek the source preview to the end of the final word, then set its exact frame."
                      : `FINAL OUT ${formatFrameTimecode(finalCut.out_frame, project?.project.fps ?? 30)} · frame ${finalCut.out_frame.toLocaleString()}`}
                  </small>
                </span>
                {finalCutExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {finalCutExpanded && finalCut.custom && <button onClick={() => updateSplice(() => setFinalOutFrame(null))}>Reset to transcript</button>}
            </div>
            {finalCutExpanded && (
              <div className="final-cut-details" id="final-cut-details">
                <CutFrameCard
                  title="FINAL OUT frame"
                  frame={finalCut.out_frame}
                  fps={project?.project.fps ?? 30}
                  adjustment={finalCut.adjustment}
                  whisperFrame={finalCut.suggested_out_frame}
                  suggestedFrame={finalCut.suggested_out_frame}
                  minFrame={finalCut.minimum_out_frame}
                  maxFrame={maximumOutFrame ?? undefined}
                  sourceLabel="Transcript"
                  onNudge={(delta) => updateSplice(() => setFinalOutFrame(finalCut.out_frame + delta))}
                />
                <div className="review-playbar final-cut-playbar">
                  <span>Preview final</span>
                  {([2, 4, 6] as const).map((seconds) => (
                    <button key={seconds} onClick={() => playFinalCut(seconds)}><Play size={13} /> {seconds}s</button>
                  ))}
                  <small>Plays the retained source and stops on FINAL OUT.</small>
                </div>
                <div className="final-cut-actions">
                  <label>
                    Exact frame
                    <input
                      type="number"
                      min={finalCut.minimum_out_frame}
                      max={maximumOutFrame ?? undefined}
                      step={1}
                      value={finalOutDraft}
                      onChange={(event) => setFinalOutDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && finalOutDraftValid) {
                          updateSplice(() => setFinalOutFrame(parsedFinalOutDraft));
                        }
                      }}
                    />
                  </label>
                  <button disabled={!finalOutDraftValid || parsedFinalOutDraft === finalCut.out_frame} onClick={() => updateSplice(() => setFinalOutFrame(parsedFinalOutDraft))}>Set frame</button>
                  <button onClick={setFinalFromPlayhead} disabled={!sourceVideo}>Set from playhead</button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function CutFrameCard({
  title,
  frame,
  fps,
  minFrame,
  maxFrame,
  onNudge,
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
  /** Kept for call-site compatibility; Whisper/source label chrome removed. */
  sourceLabel?: string;
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
        <span className="cut-frame-title">{title}</span>
        <span className="cut-frame-timecode">{formatFrameTimecode(frame, fps)}</span>
        <span className="cut-frame-number">{frame.toLocaleString()}</span>
      </div>
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

function formatPreviewTimecode(seconds: number, fps: number) {
  return formatFrameTimecode(Math.max(0, Math.round(seconds * fps)), fps);
}

function parsePreviewTimecode(value: string, fps: number): number | null {
  const clean = value.trim();
  if (!clean) return null;
  const parts = clean.split(":");
  const numeric = parts.map((part) => Number(part));
  if (numeric.some((part) => !Number.isFinite(part) || part < 0)) return null;
  if (parts.length === 1) return numeric[0];
  if (parts.length === 2) {
    if (numeric[1] >= 60) return null;
    return numeric[0] * 60 + numeric[1];
  }
  if (parts.length === 3) {
    if (numeric[1] >= 60 || numeric[2] >= 60) return null;
    return numeric[0] * 3600 + numeric[1] * 60 + numeric[2];
  }
  if (parts.length === 4) {
    const roundedFps = Math.max(1, Math.round(fps));
    if (numeric.some((part) => !Number.isInteger(part)) || numeric[1] >= 60 || numeric[2] >= 60 || numeric[3] >= roundedFps) return null;
    return numeric[0] * 3600 + numeric[1] * 60 + numeric[2] + numeric[3] / roundedFps;
  }
  return null;
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
