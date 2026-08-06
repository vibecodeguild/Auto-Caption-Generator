"use client";

import {
  Check,
  ChevronDown,
  Clapperboard,
  Copy,
  Film,
  FolderOpen,
  Image as ImageIcon,
  Maximize2,
  Minimize2,
  Play,
  Plus,
  Save,
  RefreshCw,
  Shield,
  Trash2,
  Type,
  Upload,
  Search,
  SkipForward,
  Sparkles,
} from "lucide-react";
import { createElement, useCallback, useEffect, useRef, useState } from "react";
import {
  type VisualAsset,
  type VisualCue,
  type VisualCueParameters,
  type VisualPlan,
  type VisualProjectResponse,
  type VisualRenderJob,
  type CreatorAsset,
  type VisualSuggestion,
  type VisualSuggestionCoverage,
  type StockCandidate,
  type VisualReviewRecord,
  type VisualRecipe,
  type VisualCatalogModule,
  type VisualTreatment,
  createRecipeSuggestion,
  ensureVisualProject,
  getCurrentVisualProject,
  getActiveVisualRenderJob,
  getVisualRenderJob,
  importVisualAsset,
  openVisualProject,
  saveVisualProject,
  startVisualRender,
  visualFinalVideoUrl,
  visualRenderVideoUrl,
  visualRuntimeCompositionUrl,
  visualRuntimePlayerUrl,
  verifyVisualDeliveryReopened,
  approveVisualFullReview,
  approveVisualRepresentative,
  getCreatorLibrary,
  getPexelsSettings,
  getVisualSuggestions,
  getVisualCredits,
  getVisualCatalog,
  getVisualReviewPrompt,
  importCreatorAsset,
  savePexelsKey,
  searchSuggestionStock,
  selectSuggestionStock,
  updateCreatorAsset,
  updateVisualSuggestion,
  useCreatorAsset,
  buildVisualSuggestion,
  decideVisualSuggestion,
  prepareVisualSuggestionEvidence,
  creatorAssetMediaUrl,
  visualRecipePreviewUrl,
  visualSourceFrameUrl,
  visualSuggestionApprovalFrameUrl,
  visualTreatmentPreviewUrl,
  visualTreatmentMotionPreviewUrl,
  updateVisualTreatment,
} from "../lib/api";

const MODULES: Array<{ id: NonNullable<VisualCue["moduleId"]>; name: string; description: string }> = [
  { id: "punchline-reveal", name: "Punchline reveal", description: "Land text with the spoken phrase" },
  { id: "progress-scale", name: "Progress scale", description: "Full white journey stage with speaker in an upper-right window" },
  { id: "dependency-stack", name: "Dependency stack", description: "Title + sequential stack; talking head docks right" },
];

type LibraryTab = "generated" | "creator" | "imported" | "curate";

function cueLabel(cue: VisualCue, assets: VisualAsset[]) {
  if (cue.parameters.reviewLabel) return cue.parameters.reviewLabel;
  if (cue.kind === "module") return MODULES.find((module) => module.id === cue.moduleId)?.name ?? cue.moduleId ?? "Graphic";
  if (cue.kind === "composition") return cue.sceneId ?? "Custom composition";
  return assets.find((asset) => asset.id === cue.assetId)?.name ?? "Imported media";
}

function newId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function semanticParameterEntries(moduleId: VisualCue["moduleId"], parameters: VisualCueParameters): Array<[string, string]> {
  if (!moduleId) return [];
  const entries: Array<[string, string]> = [];
  const scalarKeys = moduleId === "progress-scale"
    ? ["kicker", "text", "startLabel", "targetLabel"] as const
    : ["kicker", "text"] as const;
  for (const key of scalarKeys) {
    const value = parameters[key];
    if (typeof value === "string" && value.trim()) entries.push([`parameters.${key}`, value]);
  }
  const listKeys = moduleId === "dependency-stack" ? ["nodes"] as const : [];
  for (const key of listKeys) {
    const values = parameters[key];
    if (Array.isArray(values)) values.forEach((value, index) => entries.push([`parameters.${key}.${index}`, value]));
  }
  return entries;
}

function defaultModuleCue(moduleId: NonNullable<VisualCue["moduleId"]>, at: number, duration: number): VisualCue {
  const cueDuration = Math.min(6, Math.max(2, duration - at));
  const common: VisualCueParameters = {
    opacity: 1,
    transitionIn: "editorial-snap",
    transitionOut: "fade",
  };
  const parameters: VisualCueParameters = moduleId === "dependency-stack"
    ? { ...common, text: "WHAT YOU NEED", nodes: ["Transcript", "Locked cut", "Graphics kit"] }
    : moduleId === "progress-scale"
      ? { ...common, text: "ANIMATE TOWARD THE TARGET", kicker: "VCG / VISUAL", startLabel: "START", targetLabel: "TARGET", accentColor: "#FF00CE" }
      : { ...common, text: "EDIT THIS MESSAGE", kicker: "VCG / VISUAL", accentColor: "#FF00CE" };
  const startSec = Math.min(at, Math.max(0, duration - cueDuration));
  const endSec = Math.min(duration, at + cueDuration);
  const semanticEntries = semanticParameterEntries(moduleId, parameters);
  return {
    id: newId("cue"),
    kind: "module",
    moduleId,
    startSec,
    endSec,
    enabled: true,
    parameters,
    semanticItems: semanticEntries.map(([parameterPath, text], index) => ({
      id: `semantic-${index + 1}`,
      label: parameterPath.split(".").at(-1) ?? `item-${index + 1}`,
      text,
      parameterPath,
      phrase: "",
      anchorType: "unanchored",
      spokenStartSec: startSec,
      fullyVisibleSec: Math.min(endSec, startSec + 0.5),
    })),
  };
}

function defaultAssetCue(asset: VisualAsset, at: number, duration: number): VisualCue {
  const cueDuration = Math.min(asset.durationSec ?? 5, Math.max(1, duration - at));
  return {
    id: newId("asset"),
    kind: "asset",
    assetId: asset.id,
    startSec: Math.min(at, Math.max(0, duration - cueDuration)),
    endSec: Math.min(duration, at + cueDuration),
    enabled: true,
    parameters: {
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      opacity: 1,
      scale: 1,
      rotation: 0,
      fit: "cover",
      muted: true,
      volume: 1,
      sourceStartSec: 0,
      playbackRate: 1,
      loop: false,
      transitionIn: "fade",
      transitionOut: "fade",
    },
    semanticItems: [],
  };
}

type HyperFramesPlayerElement = HTMLElement & {
  currentTime: number;
  duration: number;
  paused: boolean;
  ready: boolean;
  play: () => void;
  pause: () => void;
  seek: (time: number) => void;
};

export default function VisualProductionWorkspace() {
  const [project, setProject] = useState<VisualProjectResponse | null>(null);
  const [selectedCueId, setSelectedCueId] = useState<string | null>(null);
  const [libraryTab, setLibraryTab] = useState<LibraryTab>("generated");
  const [playhead, setPlayhead] = useState(0);
  const [status, setStatus] = useState("Export the locked cut, then initialize Visual Production from the active project.");
  const [busy, setBusy] = useState(false);
  const [renderJob, setRenderJob] = useState<VisualRenderJob | null>(null);
  const [renderVideo, setRenderVideo] = useState<string | null>(null);
  const [previewMode, setPreviewMode] = useState<"runtime" | "render">("runtime");
  const [runtimeScriptReady, setRuntimeScriptReady] = useState(false);
  const [runtimeReady, setRuntimeReady] = useState(false);
  const [creatorAssets, setCreatorAssets] = useState<CreatorAsset[]>([]);
  const [creatorQuery, setCreatorQuery] = useState("");
  const [suggestions, setSuggestions] = useState<VisualSuggestion[]>([]);
  const [suggestionCoverage, setSuggestionCoverage] = useState<VisualSuggestionCoverage | null>(null);
  const [recipes, setRecipes] = useState<VisualRecipe[]>([]);
  const [catalogModules, setCatalogModules] = useState<VisualCatalogModule[]>([]);
  const [hoveredRecipeId, setHoveredRecipeId] = useState<string | null>(null);
  const [selectedSuggestionId, setSelectedSuggestionId] = useState<string | null>(null);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [reviewMode, setReviewMode] = useState(false);
  const [pexelsConfigured, setPexelsConfigured] = useState(false);
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const [previewFullscreen, setPreviewFullscreen] = useState(false);
  const [decisionNote, setDecisionNote] = useState("");
  const renderedVideoRef = useRef<HTMLVideoElement | null>(null);
  const runtimePlayerRef = useRef<HyperFramesPlayerElement | null>(null);
  const previewStageRef = useRef<HTMLDivElement | null>(null);
  const playheadRef = useRef(0);
  const reviewPlaybackEndRef = useRef<number | null>(null);
  const reviewPlaybackTargetRef = useRef<{ itemType: "cue" | "suggestion"; itemId: string } | null>(null);
  const reopenVerificationRef = useRef<string | null>(null);
  const stockPrepStarted = useRef(new Set<string>());
  const saveRevisionRef = useRef(0);
  const lastSavedRevisionRef = useRef(0);
  const [saveRevision, setSaveRevision] = useState(0);

  const plan = project?.plan ?? null;
  const duration = plan?.composition.durationSec ?? 0;
  const selectedCue = plan?.cues.find((cue) => cue.id === selectedCueId) ?? null;
  const selectedCompositionCue = selectedCue?.kind === "composition";
  const selectedSuggestion = suggestions.find((item) => item.id === selectedSuggestionId) ?? null;
  const graphicReviewSuggestions = suggestions.filter((item) => item.category === "graphic");
  const reviewSuggestion = graphicReviewSuggestions[reviewIndex] ?? null;
  const treatments: VisualTreatment[] = [...catalogModules, ...recipes];
  const selectedTreatmentId = reviewSuggestion?.decision?.selectedTreatmentId
    ?? reviewSuggestion?.moduleId
    ?? reviewSuggestion?.recipeId
    ?? null;
  const selectedTreatment = treatments.find((item) => item.id === selectedTreatmentId) ?? null;
  const reviewNeedsTreatment = Boolean(reviewSuggestion && (reviewSuggestion.timelineLane === "graphics" || reviewSuggestion.category === "graphic"));
  const reviewEvidenceReady = Boolean(
    !reviewNeedsTreatment
    || (
      reviewSuggestion?.approvalEvidence
      && ["historical-ready", "sample-ready"].includes(reviewSuggestion.approvalEvidence.status)
      && reviewSuggestion.approvalEvidence.selectedTreatmentId === selectedTreatmentId
    ),
  );
  const reviewSpeakerSafe = Boolean(!reviewNeedsTreatment || reviewSuggestion?.speakerSafety?.checked);
  const graphicApprovalsRemaining = graphicReviewSuggestions.filter((item) => item.decision?.status !== "approved").length;
  const graphicDecisionsPending = graphicReviewSuggestions.filter((item) => !item.decision || item.decision.status === "pending").length;
  const selectedReviewTarget = selectedCue
    ? { itemType: "cue" as const, itemId: selectedCue.id, startSec: selectedCue.startSec, endSec: selectedCue.endSec, label: cueLabel(selectedCue, plan?.assets ?? []) }
    : selectedSuggestion
      ? { itemType: "suggestion" as const, itemId: selectedSuggestion.id, startSec: selectedSuggestion.startSec, endSec: selectedSuggestion.endSec, label: selectedSuggestion.moduleId ?? selectedSuggestion.recipeId ?? selectedSuggestion.category.replace("-", " ") }
      : null;
  const activeReview = selectedReviewTarget
    ? plan?.reviews?.find((item) => item.itemType === selectedReviewTarget.itemType && item.itemId === selectedReviewTarget.itemId) ?? null
    : null;
  const activeReviewQueue = plan?.reviews?.filter((item) => item.note.trim()) ?? [];
  const orderedRecipes = [...recipes].sort((left, right) => Number(Boolean(right.previewAvailable)) - Number(Boolean(left.previewAvailable)) || left.name.localeCompare(right.name));
  const plannedBRollCount = suggestions.filter((item) => item.status !== "rejected" && (item.timelineLane === "b-roll" || item.category === "stock")).length;
  const plannedGraphicCount = suggestions.filter((item) => item.status !== "rejected" && (item.timelineLane === "graphics" || item.category === "graphic")).length;
  const reusedTreatmentCount = (suggestionCoverage?.reuseAudit.reusedModuleIds.length ?? 0)
    + (suggestionCoverage?.reuseAudit.reusedRecipeIds.length ?? 0)
    + (suggestionCoverage?.reuseAudit.creatorLibraryQueries.length ?? 0);
  const auditedGraphicCount = suggestions.filter((item) => item.status !== "rejected" && (item.timelineLane === "graphics" || item.category === "graphic") && item.speakerSafety?.checked && (item.candidateTreatmentIds?.length ?? 0) >= 3 && item.visualFamily).length;
  const plannedVisualFamilies = new Set(suggestions.filter((item) => item.status !== "rejected" && (item.timelineLane === "graphics" || item.category === "graphic")).map((item) => item.visualFamily).filter(Boolean)).size;
  const reuseAuditHealthy = Boolean((suggestionCoverage?.reuseAudit.contractVersion ?? 0) >= 2 && suggestionCoverage?.reuseAudit.reviewed && (plannedGraphicCount === 0 || (reusedTreatmentCount > 0 && auditedGraphicCount === plannedGraphicCount)));
  const decisionCounts = suggestionCoverage?.decisionCounts;
  const unresolvedSuggestionCount = decisionCounts?.unresolvedApprovals
    ?? suggestions.filter((item) => item.status !== "rejected" && item.decision?.status !== "approved").length;
  const approvalCount = Math.max(0, (decisionCounts?.timelineDecisions ?? suggestions.length) - unresolvedSuggestionCount);
  // Treatments this video introduced, reported by the delivery harvest. Rating everything the
  // project touched buries the handful that are actually new, and an unrated library cannot rank
  // candidates for the next Cook.
  const introducedTreatmentIds = project?.libraryCuration?.introducedTreatmentIds ?? [];
  const curatedTreatmentIds = introducedTreatmentIds.length ? introducedTreatmentIds : [...new Set(
    suggestions
      .filter((item) => item.status === "built" || item.decision?.status === "approved")
      .map((item) => item.decision?.selectedTreatmentId ?? item.moduleId ?? item.recipeId)
      .filter((value): value is string => Boolean(value)),
  )];
  const unratedIntroducedIds = introducedTreatmentIds.filter(
    (id) => !(treatments.find((item) => item.id === id)?.creatorRating),
  );

  const updatePlayheadFromPlayback = useCallback((next: number) => {
    playheadRef.current = next;
    setPlayhead(next);
    const reviewEnd = reviewPlaybackEndRef.current;
    if (reviewEnd !== null && next >= reviewEnd - 0.5 / Math.max(plan?.composition.fps ?? 30, 1)) {
      reviewPlaybackEndRef.current = null;
      reviewPlaybackTargetRef.current = null;
      runtimePlayerRef.current?.pause();
      renderedVideoRef.current?.pause();
      setPreviewPlaying(false);
    }
  }, [plan?.composition.fps]);

  const applyProject = useCallback((response: VisualProjectResponse) => {
    const normalized = { ...response, plan: { ...response.plan, reviews: response.plan.reviews ?? [], reviewHistory: response.plan.reviewHistory ?? [] } };
    setProject(normalized);
    setSelectedCueId((current) => normalized.plan.cues.some((cue) => cue.id === current) ? current : null);
    const revisionName = response.finalVideo?.revisionName;
    setStatus(revisionName ? `Active visual revision: ${revisionName}` : `Private project: ${response.plan.project.name}`);
    setRenderVideo(response.finalVideo?.available ? visualFinalVideoUrl(response.finalVideo.cacheKey) : null);
    lastSavedRevisionRef.current = saveRevisionRef.current;
  }, []);

  useEffect(() => {
    if (customElements.get("hyperframes-player")) {
      setRuntimeScriptReady(true);
      return;
    }
    const existing = document.querySelector<HTMLScriptElement>('script[data-vcg-hyperframes-player="true"]');
    const script = existing ?? document.createElement("script");
    const onReady = () => setRuntimeScriptReady(true);
    script.addEventListener("load", onReady);
    if (!existing) {
      script.src = visualRuntimePlayerUrl();
      script.async = true;
      script.dataset.vcgHyperframesPlayer = "true";
      document.head.appendChild(script);
    }
    return () => script.removeEventListener("load", onReady);
  }, []);

  useEffect(() => {
    setRuntimeReady(false);
    const player = runtimePlayerRef.current;
    if (!player || !runtimeScriptReady) return;
    const onReady = () => {
      setRuntimeReady(true);
      player.seek(playheadRef.current);
    };
    const onTimeUpdate = (event: Event) => {
      const currentTime = (event as CustomEvent<{ currentTime?: number }>).detail?.currentTime;
      const next = Number.isFinite(currentTime) ? Number(currentTime) : player.currentTime;
      if (!player.paused) setPreviewPlaying(true);
      updatePlayheadFromPlayback(next);
    };
    const onPlay = () => setPreviewPlaying(true);
    const onPause = () => setPreviewPlaying(false);
    const onEnded = () => {
      reviewPlaybackEndRef.current = null;
      reviewPlaybackTargetRef.current = null;
      setPreviewPlaying(false);
      updatePlayheadFromPlayback(duration);
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
  }, [duration, previewMode, project?.runtimePreview.cacheKey, runtimeScriptReady, updatePlayheadFromPlayback]);

  useEffect(() => {
    const onFullscreenChange = () => setPreviewFullscreen(document.fullscreenElement === previewStageRef.current);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  useEffect(() => {
    if (!previewPlaying || !plan) return;
    if (reviewPlaybackTargetRef.current) return;
    const activeCue = plan.cues
      .map((cue, index) => ({ cue, index }))
      .filter(({ cue }) => cue.enabled && playhead >= cue.startSec && playhead < cue.endSec)
      .sort((left, right) => right.cue.startSec - left.cue.startSec
        || (left.cue.endSec - left.cue.startSec) - (right.cue.endSec - right.cue.startSec)
        || right.index - left.index)
      .at(0)?.cue;
    const nextId = activeCue?.id ?? null;
    setSelectedCueId((current) => current === nextId ? current : nextId);
    if (nextId) setSelectedSuggestionId(null);
  }, [plan, playhead, previewPlaying]);

  useEffect(() => {
    const revision = project?.activeRevision;
    const production = project?.production;
    if (!runtimeReady || !revision || !production || revision.status !== "delivered" || production.deliveryReopenVerified) return;
    const verificationKey = `${revision.number}:${production.planHash}`;
    if (reopenVerificationRef.current === verificationKey) return;
    reopenVerificationRef.current = verificationKey;
    verifyVisualDeliveryReopened(revision.number, production.planHash)
      .then(applyProject)
      .catch((error: Error) => {
        reopenVerificationRef.current = null;
        setStatus(`Delivered revision is visible, but reopen verification failed: ${error.message}`);
      });
  }, [applyProject, project?.activeRevision, project?.production, runtimeReady]);

  const refreshStoryAssets = useCallback(() => {
    void getCreatorLibrary().then((data) => setCreatorAssets(data.assets)).catch(() => undefined);
    void getPexelsSettings().then((data) => setPexelsConfigured(data.configured)).catch(() => undefined);
    void getVisualSuggestions().then((data) => {
      setSuggestions(data.suggestions);
      setSuggestionCoverage(data.coverage ?? null);
    }).catch((error: Error) => {
      setSuggestions([]);
      setSuggestionCoverage(null);
      setStatus(`Could not load visual suggestions: ${error.message}`);
    });
  }, []);

  useEffect(() => {
    getVisualCatalog().then((data) => {
      setCatalogModules(data.modules);
      setRecipes(data.recipes);
    }).catch(() => {
      setCatalogModules([]);
      setRecipes([]);
    });
    getCurrentVisualProject().then((response) => {
      applyProject(response);
      refreshStoryAssets();
      return getActiveVisualRenderJob();
    }).then(({ job }) => {
      if (!job) return;
      setRenderJob(job);
      setStatus(job.status === "running" ? `Reconnected to export: ${job.message}` : job.message);
    }).catch(() => undefined);
  }, [applyProject, refreshStoryAssets]);

  useEffect(() => {
    if (!project || saveRevision === 0 || saveRevision === lastSavedRevisionRef.current) return;
    const revision = saveRevision;
    const snapshot = project.plan;
    const timer = window.setTimeout(() => {
      saveVisualProject(snapshot)
        .then((response) => {
          if (saveRevisionRef.current === revision) {
            setProject({ ...response, plan: { ...response.plan, reviews: response.plan.reviews ?? [], reviewHistory: response.plan.reviewHistory ?? [] } });
            lastSavedRevisionRef.current = revision;
            setStatus("All visual changes saved privately.");
          }
        })
        .catch((error: Error) => setStatus(`Automatic save failed: ${error.message}`));
    }, 650);
    return () => window.clearTimeout(timer);
  }, [project, saveRevision]);

  useEffect(() => {
    const reloadOnFocus = () => {
      if (saveRevisionRef.current !== lastSavedRevisionRef.current) return;
      getCurrentVisualProject().then(applyProject).then(refreshStoryAssets).catch(() => undefined);
    };
    window.addEventListener("focus", reloadOnFocus);
    return () => window.removeEventListener("focus", reloadOnFocus);
  }, [applyProject, refreshStoryAssets]);

  useEffect(() => {
    if (!renderJob || renderJob.status !== "running") return;
    const timer = window.setInterval(() => {
      getVisualRenderJob(renderJob.job_id)
        .then((job) => {
          setRenderJob(job);
          setStatus(job.message);
          if (job.status === "complete") {
            const renderedUrl = visualRenderVideoUrl(job.job_id);
            getCurrentVisualProject()
              .then((response) => {
                applyProject(response);
                setRenderVideo(renderedUrl);
                setPreviewMode(response.activeRevision?.status === "delivered" ? "runtime" : "render");
              })
              .catch(() => {
                setRenderVideo(renderedUrl);
                setPreviewMode("render");
              });
          } else if (job.status === "failed") {
            setStatus(job.error ?? job.message);
          }
        })
        .catch((error: Error) => setStatus(error.message));
    }, 800);
    return () => window.clearInterval(timer);
  }, [applyProject, renderJob]);

  useEffect(() => {
    if (!pexelsConfigured) return;
    for (const suggestion of suggestions.filter((item) => item.category === "stock" && !item.candidates?.length && item.status !== "built" && item.status !== "rejected")) {
      if (stockPrepStarted.current.has(suggestion.id)) continue;
      stockPrepStarted.current.add(suggestion.id);
      searchSuggestionStock(suggestion.id)
        .then((result) => setSuggestions((current) => current.map((item) => item.id === suggestion.id ? { ...item, status: "prepared", candidates: result.candidates } : item)))
        .catch(() => stockPrepStarted.current.delete(suggestion.id));
    }
  }, [pexelsConfigured, suggestions]);

  useEffect(() => {
    if (!reviewMode || !reviewSuggestion) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === "ArrowLeft") setReviewIndex((index) => Math.max(0, index - 1));
      else if (event.key === "ArrowRight") setReviewIndex((index) => Math.min(graphicReviewSuggestions.length - 1, index + 1));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [reviewMode, reviewSuggestion, graphicReviewSuggestions.length]);

  useEffect(() => {
    if (!reviewMode || !reviewSuggestion) return;
    setDecisionNote(reviewSuggestion.decision?.notes ?? "");
    setSelectedCueId(null);
    setSelectedSuggestionId(reviewSuggestion.id);
    const next = reviewSuggestion.startSec;
    playheadRef.current = next;
    setPlayhead(next);
    runtimePlayerRef.current?.seek(next);
    if (renderedVideoRef.current) renderedVideoRef.current.currentTime = next;
  }, [reviewMode, reviewSuggestion]);

  function updatePlan(updater: (current: VisualPlan) => VisualPlan) {
    setProject((current) => current ? { ...current, plan: updater(current.plan) } : current);
    saveRevisionRef.current += 1;
    setSaveRevision(saveRevisionRef.current);
  }

  async function reloadFromDisk() {
    if (saveRevisionRef.current !== lastSavedRevisionRef.current) {
      setStatus("Waiting for the current automatic save before reloading.");
      return;
    }
    setBusy(true);
    try {
      const response = await getCurrentVisualProject();
      applyProject(response);
      refreshStoryAssets();
      setStatus("Reloaded the latest plan and suggestions from the private project files.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  function selectCue(cue: VisualCue) {
    setSelectedSuggestionId(null);
    setSelectedCueId(cue.id);
    seek(cue.startSec);
  }

  function selectSuggestion(suggestion: VisualSuggestion) {
    setSelectedCueId(null);
    setSelectedSuggestionId(suggestion.id);
    setReviewIndex(Math.max(0, suggestions.findIndex((item) => item.id === suggestion.id)));
    seek(suggestion.startSec);
  }

  function updateReview(updates: Partial<Pick<VisualReviewRecord, "note" | "directive">>) {
    if (!selectedReviewTarget) return;
    const now = new Date().toISOString();
    updatePlan((current) => {
      const existing = current.reviews.find((item) => item.itemType === selectedReviewTarget.itemType && item.itemId === selectedReviewTarget.itemId);
      const next: VisualReviewRecord = existing
        ? {
            ...existing,
            ...updates,
            startSec: selectedReviewTarget.startSec,
            endSec: selectedReviewTarget.endSec,
            status: "changes-requested",
            updatedAt: now,
          }
        : {
            id: newId("review"),
            itemId: selectedReviewTarget.itemId,
            itemType: selectedReviewTarget.itemType,
            startSec: selectedReviewTarget.startSec,
            endSec: selectedReviewTarget.endSec,
            note: updates.note ?? "",
            directive: updates.directive ?? "targeted",
            status: "changes-requested",
            createdAt: now,
            updatedAt: now,
          };
      return { ...current, reviews: existing ? current.reviews.map((item) => item.id === existing.id ? next : item) : [...current.reviews, next] };
    });
  }

  function acceptReview() {
    if (!activeReview) return;
    const accepted = { ...activeReview, acceptedAt: new Date().toISOString() };
    updatePlan((current) => ({
      ...current,
      reviews: current.reviews.filter((item) => item.id !== activeReview.id),
      reviewHistory: [...current.reviewHistory, accepted],
    }));
    setStatus(`Accepted ${selectedReviewTarget?.label ?? "visual item"}; its note was archived in review history.`);
  }

  function jumpToNextReview() {
    if (!plan || !activeReviewQueue.length) return;
    const ordered = [...activeReviewQueue].sort((left, right) => Number(right.status === "ready-for-review") - Number(left.status === "ready-for-review") || left.startSec - right.startSec);
    const currentIndex = activeReview ? ordered.findIndex((item) => item.id === activeReview.id) : -1;
    const next = ordered[(currentIndex + 1) % ordered.length];
    if (next.itemType === "cue") {
      const cue = plan.cues.find((item) => item.id === next.itemId);
      if (cue) selectCue(cue);
    } else {
      const suggestion = suggestions.find((item) => item.id === next.itemId);
      if (suggestion) selectSuggestion(suggestion);
    }
    const playing = playReviewRange(next.startSec, next.endSec, { itemType: next.itemType, itemId: next.itemId });
    setStatus(`${next.status === "ready-for-review" ? "Ready for review" : "Changes requested"}: ${playing ? "playing" : "selected"} ${formatTime(next.startSec)} - ${formatTime(next.endSec)}.`);
  }

  async function copyAllNotes() {
    if (!plan) return;
    const noteCount = plan.reviews.filter((item) => item.note.trim()).length;
    if (!noteCount) {
      setStatus("Add at least one review note before copying the handoff prompt.");
      return;
    }
    setBusy(true);
    try {
      const saved = await saveVisualProject(plan);
      applyProject(saved);
      setRenderVideo(null);
      const response = await getVisualReviewPrompt();
      if (!response.prompt || !response.noteCount) throw new Error("No non-empty review notes were found.");
      await navigator.clipboard.writeText(response.prompt);
      applyProject(response);
      setStatus(`Copied ${response.noteCount} review note${response.noteCount === 1 ? "" : "s"} with exact IDs and timestamps.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function requestRecipe(recipe: VisualRecipe) {
    if (!plan) return;
    setBusy(true);
    try {
      const end = Math.min(duration, playhead + 6);
      const suggestion = await createRecipeSuggestion(recipe.id, Math.min(playhead, Math.max(0, duration - 0.01)), Math.max(Math.min(duration, playhead + 0.01), end));
      const now = new Date().toISOString();
      const review: VisualReviewRecord = {
        id: newId("review"),
        itemId: suggestion.id,
        itemType: "suggestion",
        startSec: suggestion.startSec,
        endSec: suggestion.endSec,
        note: `Reuse and adapt the existing ${recipe.name} treatment for this scene. Start from its established VCG layout and motion grammar, match the exact transcript and spoken reveal beats, keep the speaker visible, and write the finished result back into this visual project. Do not replace it with a bespoke treatment unless the recipe cannot satisfy this beat.`,
        directive: "targeted",
        status: "changes-requested",
        createdAt: now,
        updatedAt: now,
      };
      const saved = await saveVisualProject({ ...plan, reviews: [...plan.reviews, review] });
      setSuggestions((current) => [...current, suggestion]);
      applyProject(saved);
      setSelectedCueId(null);
      setSelectedSuggestionId(suggestion.id);
      setReviewIndex(suggestions.length);
      const promptResponse = await getVisualReviewPrompt([review.id]);
      await navigator.clipboard.writeText(promptResponse.prompt);
      applyProject(promptResponse);
      setSelectedCueId(null);
      setSelectedSuggestionId(suggestion.id);
      setStatus(`${recipe.name} build prompt copied for ${formatTime(suggestion.startSec)}. Paste it into Codex.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  function updateCue(updates: Partial<VisualCue>, parameterUpdates?: Partial<VisualCueParameters>) {
    if (!selectedCue) return;
    updatePlan((current) => {
      const nextCue = { ...selectedCue, ...updates, parameters: { ...selectedCue.parameters, ...(parameterUpdates ?? {}) } };
      if (nextCue.kind === "module") {
        const previousByPath = new Map(selectedCue.semanticItems.map((item) => [item.parameterPath, item]));
        nextCue.semanticItems = semanticParameterEntries(nextCue.moduleId, nextCue.parameters).map(([parameterPath, text], index) => {
          const previous = previousByPath.get(parameterPath);
          const spokenStartSec = Math.max(nextCue.startSec, Math.min(nextCue.endSec, previous?.spokenStartSec ?? nextCue.startSec));
          return {
            id: previous?.id ?? `semantic-${index + 1}`,
            label: previous?.label ?? parameterPath.split(".").at(-1) ?? `item-${index + 1}`,
            text,
            parameterPath,
            phrase: previous?.phrase ?? "",
            anchorType: previous?.anchorType ?? "unanchored",
            spokenStartSec,
            fullyVisibleSec: Math.max(spokenStartSec, Math.min(nextCue.endSec, previous?.fullyVisibleSec ?? spokenStartSec + 0.5)),
          };
        });
      }
      return {
        ...current,
        cues: current.cues.map((cue) => cue.id === selectedCue.id ? nextCue : cue),
        protectedFootage: current.protectedFootage,
      };
    });
  }

  async function run(action: () => Promise<VisualProjectResponse>, success: string) {
    setBusy(true);
    try {
      const response = await action();
      applyProject(response);
      setStatus(success);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!plan) return;
    await run(() => saveVisualProject(plan), "Visual plan saved privately.");
  }

  function addModule(moduleId: NonNullable<VisualCue["moduleId"]>) {
    if (!plan) return;
    const cue = defaultModuleCue(moduleId, playhead, duration);
    updatePlan((current) => ({
      ...current,
      cues: [...current.cues, cue],
    }));
    setSelectedSuggestionId(null);
    setSelectedCueId(cue.id);
    setStatus(`${cueLabel(cue, plan.assets)} added at ${cue.startSec.toFixed(2)}s.`);
  }

  async function importAsset() {
    if (!plan) return;
    setBusy(true);
    try {
      const response = await importVisualAsset();
      const asset = response.importedAsset;
      if (!asset) throw new Error("The imported asset was not returned by the API.");
      const cue = defaultAssetCue(asset, playhead, response.plan.composition.durationSec);
      const next = { ...response, plan: { ...response.plan, cues: [...response.plan.cues, cue] } };
      const saved = await saveVisualProject(next.plan);
      applyProject(saved);
      setSelectedSuggestionId(null);
      setSelectedCueId(cue.id);
      setLibraryTab("imported");
      setStatus(`${asset.name} copied into the private project and added to the timeline.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function importReusableAsset() {
    setBusy(true);
    try {
      const response = await importCreatorAsset();
      let asset = response.asset;
      if (!response.duplicate) {
        const name = window.prompt("Reusable asset name:", asset.name)?.trim();
        const tags = window.prompt("Search tags, separated by commas:", asset.tags.join(", "));
        const series = window.prompt("Callback series (optional):", asset.series)?.trim();
        const updated = await updateCreatorAsset(asset.id, {
          ...(name ? { name } : {}),
          ...(tags !== null ? { tags: tags.split(",").map((item) => item.trim()).filter(Boolean) } : {}),
          ...(series ? { series } : {}),
        });
        asset = updated.asset;
        setCreatorAssets(updated.assets);
      } else {
        setCreatorAssets(response.assets);
      }
      setLibraryTab("creator");
      setStatus(response.duplicate ? `${asset.name} was already in the Creator Library.` : `${asset.name} saved to the private Creator Library.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function placeCreatorAsset(asset: CreatorAsset, start = playhead, end?: number, suggestion?: VisualSuggestion) {
    if (!plan) return;
    const duration = Math.min(asset.durationSec ?? 5, Math.max(1, plan.composition.durationSec - start));
    setBusy(true);
    try {
      const response = await useCreatorAsset(asset.id, start, end ?? Math.min(plan.composition.durationSec, start + duration));
      applyProject(response);
      if (suggestion) {
        await updateVisualSuggestion(suggestion.id, { status: "built" });
        setSuggestions((current) => current.map((item) => item.id === suggestion.id ? { ...item, status: "built" } : item));
      }
      setStatus(`${asset.name} frozen into this project and added to the timeline.`);
      refreshStoryAssets();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function configurePexels() {
    const key = window.prompt("Paste your free Pexels API key. It stays in private local settings:");
    if (!key) return;
    setBusy(true);
    try {
      await savePexelsKey(key);
      setPexelsConfigured(true);
      setStatus("Pexels connected. The key was saved in private local settings.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function copyCredits() {
    try {
      const response = await getVisualCredits();
      if (!response.credits) throw new Error("No selected stock footage needs credits yet.");
      await navigator.clipboard.writeText(response.credits);
      setStatus("Stock credits copied for the YouTube description.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function searchStock(suggestion: VisualSuggestion) {
    setBusy(true);
    try {
      const result = await searchSuggestionStock(suggestion.id);
      setSuggestions((current) => current.map((item) => item.id === suggestion.id ? { ...item, status: "prepared", candidates: result.candidates } : item));
      setStatus(`${result.candidates.length} Pexels candidates prepared.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function chooseStock(suggestion: VisualSuggestion, candidate: StockCandidate) {
    setBusy(true);
    try {
      const response = await selectSuggestionStock(suggestion.id, candidate);
      applyProject(response);
      setSuggestions((current) => current.map((item) => item.id === suggestion.id ? { ...item, status: "built", selectedCandidate: candidate.id } : item));
      setStatus("Pexels footage downloaded privately, licensed in the ledger, and added to the timeline.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function setSuggestionStatus(suggestion: VisualSuggestion, status: VisualSuggestion["status"], category?: VisualSuggestion["category"]) {
    try {
      const updated = await updateVisualSuggestion(suggestion.id, { status, ...(category ? { category } : {}) });
      setSuggestions((current) => current.map((item) => item.id === updated.id ? updated : item));
      if (status === "approved" && category === "clean-speaker") {
        const response = await buildVisualSuggestion(suggestion.id);
        applyProject(response);
        setSuggestions((current) => current.map((item) => item.id === updated.id ? { ...updated, status: "built" } : item));
      }
      setStatus(`Suggestion marked ${status}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function approveSuggestion(suggestion: VisualSuggestion) {
    if (["graphic", "clean-speaker", "protected-footage"].includes(suggestion.category)) {
      setBusy(true);
      try {
        const response = await buildVisualSuggestion(suggestion.id);
        applyProject(response);
        setSuggestions((current) => current.map((item) => item.id === suggestion.id ? { ...item, status: "built" } : item));
        setStatus("Suggestion built as an editable timeline cue.");
      } catch (error) {
        setStatus(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
      return;
    }
    await setSuggestionStatus(suggestion, "approved");
  }

  async function selectRankedTreatment(suggestion: VisualSuggestion, treatment: VisualTreatment) {
    setBusy(true);
    try {
      const updated = await updateVisualSuggestion(suggestion.id, {
        moduleId: treatment.kind === "module" ? treatment.id : null,
        recipeId: treatment.kind === "recipe" ? treatment.id : null,
        visualFamily: treatment.family,
        decision: {
          status: "pending",
          selectedTreatmentId: treatment.id,
          notes: decisionNote,
        },
      });
      setSuggestions((current) => current.map((item) => item.id === suggestion.id ? {
        ...updated,
        ...(treatment.kind === "module" ? { recipeId: undefined } : { moduleId: undefined }),
      } : item));
      setStatus(`${treatment.name ?? treatment.id} selected. Approve it or add a rejection note.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function prepareApprovalEvidence(suggestion: VisualSuggestion) {
    setBusy(true);
    try {
      const response = await prepareVisualSuggestionEvidence(suggestion.id);
      setSuggestions(response.suggestions);
      setSuggestionCoverage(response.coverage ?? null);
      setStatus(response.suggestion.approvalEvidence?.status === "historical-ready"
        ? "Historical treatment evidence is ready for approval."
        : "Exact one-frame treatment sample rendered and bound to this proposal.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function makePlanningDecision(
    suggestion: VisualSuggestion,
    action: "approve" | "reject" | "request-another" | "approve-series",
  ) {
    setBusy(true);
    try {
      const response = await decideVisualSuggestion(suggestion.id, action, decisionNote);
      applyProject(response);
      setSuggestions(response.suggestions);
      setSuggestionCoverage(response.coverage ?? null);
      const accepted = action === "approve" || action === "approve-series";
      setStatus(accepted
        ? `${action === "approve-series" ? "Intentional series" : "Scene"} approved before production.`
        : "Change request saved and routed to the producer with your note.");
      jumpToNextPendingGraphic(response.suggestions, suggestion.id);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  function openGraphicReview() {
    const firstPending = graphicReviewSuggestions.findIndex((item) => !item.decision || item.decision.status === "pending");
    setReviewIndex(firstPending >= 0 ? firstPending : 0);
    setReviewMode(true);
  }

  function jumpToNextPendingGraphic(source = suggestions, currentId = reviewSuggestion?.id) {
    const graphics = source.filter((item) => item.category === "graphic");
    if (!graphics.length) return;
    const currentIndex = Math.max(0, graphics.findIndex((item) => item.id === currentId));
    const pending = graphics
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => !item.decision || item.decision.status === "pending");
    if (!pending.length) {
      setStatus("Every current graphic proposal has been reviewed.");
      return;
    }
    const next = pending.find(({ index }) => index > currentIndex) ?? pending[0];
    setReviewIndex(next.index);
  }

  async function curateTreatment(treatment: VisualTreatment, updates: Partial<VisualTreatment>) {
    setBusy(true);
    try {
      const updated = await updateVisualTreatment(treatment.id, updates);
      if (updated.kind === "module") {
        setCatalogModules((current) => current.map((item) => item.id === updated.id ? updated as VisualCatalogModule : item));
      } else {
        setRecipes((current) => current.map((item) => item.id === updated.id ? updated as VisualRecipe : item));
      }
      setStatus(`${treatment.name ?? treatment.id} library preference saved.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  function duplicateCue() {
    if (!selectedCue || !plan || selectedCue.kind === "composition") return;
    const length = selectedCue.endSec - selectedCue.startSec;
    const start = Math.min(duration - length, selectedCue.endSec + 0.2);
    const copyCue = {
      ...selectedCue,
      id: newId("cue"),
      startSec: Math.max(0, start),
      endSec: Math.min(duration, Math.max(0, start) + length),
      parameters: { ...selectedCue.parameters },
      semanticItems: selectedCue.semanticItems.map((item, index) => ({ ...item, id: `semantic-${index + 1}`, spokenStartSec: Math.max(0, start), fullyVisibleSec: Math.min(duration, Math.max(0, start) + 0.5) })),
    };
    updatePlan((current) => ({
      ...current,
      cues: [...current.cues, copyCue],
    }));
    setSelectedCueId(copyCue.id);
  }

  function deleteCue() {
    if (!selectedCue) return;
    updatePlan((current) => ({
      ...current,
      cues: current.cues.filter((cue) => cue.id !== selectedCue.id),
      protectedFootage: current.protectedFootage.filter((range) => range.cueId !== selectedCue.id),
      reviews: current.reviews.filter((review) => review.itemType !== "cue" || review.itemId !== selectedCue.id),
    }));
    setSelectedCueId(null);
  }

  async function runRender(purpose: "review" | "final", startedMessage: string) {
    if (!plan) return;
    setBusy(true);
    setRenderVideo(null);
    try {
      setStatus("Saving the latest visual plan before rendering...");
      const saved = await saveVisualProject(plan);
      applyProject(saved);
      const result = await startVisualRender({ quality: purpose === "final" ? "high" : "standard", purpose });
      const active = await getVisualRenderJob(result.job_id);
      setRenderJob(active);
      setStatus(result.reused ? `${startedMessage} already running. Reconnected to its progress.` : active.message);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  const exportFinal = () => runRender("final", "Export");
  const renderReview = () => runRender("review", "Review render");

  /** Loop B sign-off: the creator watched the review render against the full cut and accepted it. */
  async function approveFullReview() {
    setBusy(true);
    try {
      applyProject(await approveVisualFullReview());
      setStatus("Full review approved. The final export is now unblocked.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function markRepresentativeScene() {
    if (!selectedCue) return;
    setBusy(true);
    try {
      applyProject(await approveVisualRepresentative(selectedCue.id));
      setStatus("Recorded as the representative scene for this revision.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  function seek(value: number) {
    reviewPlaybackEndRef.current = null;
    reviewPlaybackTargetRef.current = null;
    const next = Math.max(0, Math.min(duration, value));
    playheadRef.current = next;
    setPlayhead(next);
    runtimePlayerRef.current?.seek(next);
    if (renderedVideoRef.current) renderedVideoRef.current.currentTime = next;
  }

  function playPreview() {
    if (previewMode === "render") {
      const video = renderedVideoRef.current;
      if (!video) return false;
      void video.play();
    } else {
      const player = runtimePlayerRef.current;
      if (!player) return false;
      player.play();
    }
    setPreviewPlaying(true);
    return true;
  }

  function pausePreview() {
    runtimePlayerRef.current?.pause();
    renderedVideoRef.current?.pause();
    setPreviewPlaying(false);
  }

  function togglePreviewPlayback() {
    if (previewPlaying) pausePreview(); else playPreview();
  }

  function playReviewRange(startSec: number, endSec: number, target: { itemType: "cue" | "suggestion"; itemId: string }) {
    seek(startSec);
    reviewPlaybackEndRef.current = endSec;
    reviewPlaybackTargetRef.current = target;
    const playing = playPreview();
    if (!playing) {
      reviewPlaybackEndRef.current = null;
      reviewPlaybackTargetRef.current = null;
    }
    return playing;
  }

  function switchPreviewMode(mode: "runtime" | "render") {
    pausePreview();
    reviewPlaybackEndRef.current = null;
    reviewPlaybackTargetRef.current = null;
    setPreviewMode(mode);
  }

  async function togglePreviewFullscreen() {
    try {
      if (document.fullscreenElement === previewStageRef.current) {
        await document.exitFullscreen();
      } else {
        await previewStageRef.current?.requestFullscreen();
      }
    } catch (error) {
      setStatus(`Could not change preview fullscreen mode: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  if (!plan || !project) {
    return (
      <section className="visual-empty-state">
        <div>
          <span className="visual-private-chip"><Shield size={15} /> Private workspace</span>
          <h2>Visual Production</h2>
          <p>This workspace uses the active video project’s locked cut, transcript, assets, previews, and final export paths automatically.</p>
          <div className="visual-empty-actions">
            <button className="visual-primary" onClick={() => void run(ensureVisualProject, "Visual Production initialized from the active project.")} disabled={busy}><Plus size={17} /> Start from active project</button>
            <button onClick={() => void run(openVisualProject, "Legacy private visual plan opened.")} disabled={busy}><FolderOpen size={17} /> Open legacy visual plan</button>
          </div>
          <p className="visual-status">{status}</p>
        </div>
      </section>
    );
  }

  const selectedAsset = selectedCue?.kind === "asset" ? plan.assets.find((asset) => asset.id === selectedCue.assetId) : null;
  const creatorTerms = creatorQuery.toLowerCase().split(/\s+/).filter(Boolean);
  const visibleCreatorAssets = creatorAssets.filter((asset) => !creatorTerms.length || creatorTerms.some((term) => [asset.name, asset.description, asset.series, ...asset.tags].join(" ").toLowerCase().includes(term)));

  return (
    <section className={`visual-production-workspace ${reviewMode ? "visual-graphic-review-mode" : ""}`}>
      <div className="visual-commandbar">
        <div className="visual-project-heading">
          <span className="visual-private-chip"><Shield size={14} /> Private</span>
          <div>
            <strong>{reviewMode ? "Graphic approvals" : plan.project.name}</strong>
            <span>{reviewMode ? `${graphicReviewSuggestions.length} proposed graphic treatments · ${graphicApprovalsRemaining} unresolved` : project?.finalVideo?.revisionName ? `${project.finalVideo.revisionName} · ${project.projectRoot}` : project?.projectRoot ?? ""}</span>
          </div>
        </div>
        <div className="visual-command-actions">
          {reviewMode ? (
            <button onClick={() => setReviewMode(false)}>Back to workspace</button>
          ) : (
            <>
              <button className="visual-review-entry" onClick={openGraphicReview} disabled={!graphicReviewSuggestions.length}><Check size={15} /> Review graphics {graphicReviewSuggestions.length ? `(${graphicDecisionsPending} new)` : ""}</button>
              <button onClick={() => void run(openVisualProject, "Private visual project opened.")} disabled={busy}><FolderOpen size={15} /> Open</button>
              <button onClick={() => void save()} disabled={busy}><Save size={15} /> Save</button>
              <button onClick={() => void reloadFromDisk()} disabled={busy}><RefreshCw size={15} /> Reload files</button>
              <button onClick={() => void importAsset()} disabled={busy}><ImageIcon size={15} /> Import image/video</button>
              <button onClick={() => void copyAllNotes()} disabled={busy || !plan.reviews.some((item) => item.note.trim())}><Copy size={15} /> Copy all notes</button>
              <button onClick={() => void configurePexels()} disabled={busy}><Search size={15} /> {pexelsConfigured ? "Pexels connected" : "Connect Pexels"}</button>
              <button onClick={() => void copyCredits()} disabled={busy}><Copy size={15} /> Copy credits</button>
              <button
                onClick={() => void renderReview()}
                disabled={busy || renderJob?.status === "running" || !project.production.canRenderReview}
                title={project.production.canRenderReview ? "Render the full cut for review without exporting it" : project.production.messages.join(" ")}
              ><Play size={15} /> Render review</button>
              <button
                onClick={() => void approveFullReview()}
                disabled={busy || !project.production.reviewRenderAvailable || project.production.fullReviewApproved || project.production.activeReviewCount > 0}
                title={project.production.activeReviewCount > 0 ? "Resolve the active review notes first" : "Approve the review render against the full cut"}
              ><Check size={15} /> {project.production.fullReviewApproved ? "Review approved" : "Approve review"}</button>
              <button className="visual-primary" onClick={() => void exportFinal()} disabled={busy || renderJob?.status === "running" || !project.production.canExportFinal}><Upload size={15} /> {renderJob?.status === "running" ? `Exporting ${Math.round(renderJob.value)}%` : "Export final"}</button>
            </>
          )}
        </div>
      </div>

      {reviewMode ? (
        <main className="visual-graphic-review">
          {!reviewSuggestion ? (
            <div className="visual-graphic-review-empty">
              <ImageIcon size={28} />
              <strong>No graphic treatments are ready to review.</strong>
              <span>Cook Visual Plan must save proposed graphic treatments before this approval pass begins.</span>
            </div>
          ) : (
            <>
              <header className="visual-graphic-review-header">
                <div className="visual-graphic-review-identity">
                  <span>Graphic {reviewIndex + 1} of {graphicReviewSuggestions.length}</span>
                  <h2>{selectedTreatment?.name ?? selectedTreatmentId ?? reviewSuggestion.id}</h2>
                  <p>{reviewSuggestion.id} · {reviewSuggestion.visualFamily ?? "Visual family not recorded"}</p>
                </div>
                <div className="visual-graphic-review-time">
                  <span>On screen</span>
                  <strong>{formatTime(reviewSuggestion.startSec)}–{formatTime(reviewSuggestion.endSec)}</strong>
                  <em>{formatDuration(reviewSuggestion.endSec - reviewSuggestion.startSec)}</em>
                </div>
              </header>

              <section className="visual-graphic-review-timeline" aria-label="Graphic treatment timeline">
                <div className="visual-graphic-review-timeline-heading">
                  <span>Graphic map</span>
                  <strong>{formatTime(0)}–{formatTime(duration)}</strong>
                </div>
                <div className="visual-graphic-review-timeline-track">
                  {graphicReviewSuggestions.map((suggestion, index) => {
                    const treatmentId = suggestion.decision?.selectedTreatmentId ?? suggestion.moduleId ?? suggestion.recipeId ?? suggestion.id;
                    return (
                      <button
                        key={suggestion.id}
                        className={index === reviewIndex ? "current" : ""}
                        style={{
                          left: `${duration ? suggestion.startSec / duration * 100 : 0}%`,
                          width: `${duration ? (suggestion.endSec - suggestion.startSec) / duration * 100 : 0}%`,
                        }}
                        onClick={() => setReviewIndex(index)}
                        aria-current={index === reviewIndex ? "true" : undefined}
                        aria-label={`Graphic ${index + 1}: ${treatmentId}, ${formatTime(suggestion.startSec)} to ${formatTime(suggestion.endSec)}`}
                        title={`${index + 1}. ${treatmentId} · ${formatTime(suggestion.startSec)}–${formatTime(suggestion.endSec)}`}
                      >
                        <span>{index + 1}</span>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="visual-approval-frame-grid" aria-label="Graphic approval evidence">
                <figure>
                  <div className="visual-approval-frame-label">
                    <span>Actual locked video</span>
                    <strong>{formatTime(reviewSuggestion.approvalEvidence?.sourceFrameTimeSec ?? reviewSuggestion.scenePacket?.screenshotTimeSec ?? reviewSuggestion.startSec)}</strong>
                  </div>
                  <img
                    src={visualSourceFrameUrl(reviewSuggestion.approvalEvidence?.sourceFrameTimeSec ?? reviewSuggestion.scenePacket?.screenshotTimeSec ?? reviewSuggestion.startSec)}
                    alt={`Actual locked-video frame at ${formatTime(reviewSuggestion.approvalEvidence?.sourceFrameTimeSec ?? reviewSuggestion.scenePacket?.screenshotTimeSec ?? reviewSuggestion.startSec)}`}
                  />
                  <figcaption>Speaker and protected geometry are evaluated against this scene.</figcaption>
                </figure>
                <figure>
                  <div className="visual-approval-frame-label">
                    <span>{reviewSuggestion.approvalEvidence?.status === "historical-ready" ? "Historical VCG example" : "Proposed design sample"}</span>
                    <strong>{reviewSuggestion.approvalEvidence?.status?.replace("-", " ") ?? "Evidence required"}</strong>
                  </div>
                  {reviewSuggestion.approvalEvidence?.status === "historical-ready" && selectedTreatment?.previewAvailable
                    ? <img src={visualTreatmentPreviewUrl(selectedTreatment.id)} alt={`${selectedTreatment.name ?? selectedTreatment.id} historical VCG treatment example`} />
                    : reviewSuggestion.approvalEvidence?.status === "sample-ready"
                      ? <img src={visualSuggestionApprovalFrameUrl(reviewSuggestion.id)} alt={`Proposed one-frame design for ${selectedTreatment?.name ?? selectedTreatmentId ?? reviewSuggestion.id}`} />
                      : <div className="visual-approval-frame-missing"><ImageIcon size={28} /><strong>Approval evidence is not ready.</strong><span>The proposed design cannot be approved until its exact representative frame exists.</span></div>}
                  <figcaption>{reviewSuggestion.approvalEvidence?.representativeState ?? "Maximum-occupancy representative state"}{reviewSuggestion.approvalEvidence?.representativeTimeSec !== undefined ? ` · ${formatTime(reviewSuggestion.approvalEvidence.representativeTimeSec)}` : ""}</figcaption>
                </figure>
              </section>

              <section className="visual-graphic-review-decision">
                <div className={`visual-approval-status ${reviewSuggestion.decision?.status ?? "pending"}`}>
                  <strong>{reviewSuggestion.decision?.status === "approved" ? "Approved" : reviewSuggestion.decision?.status === "revision-requested" ? "Changes requested" : "Awaiting your decision"}</strong>
                  <span>{reviewSpeakerSafe ? "Speaker-safety record passed" : "Speaker-safety record missing"} · {reviewEvidenceReady ? "Evidence ready" : "Evidence missing"}</span>
                </div>
                <label>
                  Notes for this graphic
                  <textarea value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} placeholder="Describe exactly what should change. Leave blank when approving." />
                </label>
                <div className="visual-graphic-review-actions">
                  {!reviewEvidenceReady && selectedTreatmentId && <button onClick={() => void prepareApprovalEvidence(reviewSuggestion)} disabled={busy}><ImageIcon size={15} /> Prepare exact sample</button>}
                  <button onClick={() => void makePlanningDecision(reviewSuggestion, "reject")} disabled={busy || !decisionNote.trim()}>Request changes & next</button>
                  <button className="visual-primary" onClick={() => void makePlanningDecision(reviewSuggestion, "approve")} disabled={busy || !selectedTreatmentId || !reviewEvidenceReady || !reviewSpeakerSafe}><Check size={15} /> Approve & next</button>
                </div>
              </section>

              <section className="visual-graphic-review-context">
                <div>
                  <span>Editorial intent</span>
                  <p>{reviewSuggestion.editorialPurpose ?? "No editorial rationale supplied."}</p>
                </div>
                <div>
                  <span>Spoken context</span>
                  <p>“{reviewSuggestion.transcriptContext ?? "Transcript context not supplied"}”</p>
                </div>
              </section>

              {(reviewSuggestion.rankedCandidates?.length ?? 0) > 1 && (
                <details className="visual-graphic-review-alternatives">
                  <summary>Compare ranked alternatives</summary>
                  <div className="visual-ranked-candidates">
                    {[...(reviewSuggestion.rankedCandidates ?? [])].sort((left, right) => left.rank - right.rank).map((candidate) => {
                      const treatment = treatments.find((item) => item.id === candidate.treatmentId);
                      if (!treatment) return null;
                      const selected = candidate.treatmentId === selectedTreatmentId;
                      return <button key={candidate.treatmentId} className={selected ? "selected" : ""} onClick={() => void selectRankedTreatment(reviewSuggestion, treatment)} disabled={busy}>
                        <em>#{candidate.rank}</em>
                        <span><strong>{treatment.name ?? treatment.id}{treatment.lockedDefault ? " · LOCKED" : ""}</strong><small>{candidate.fitReason}</small><small>{treatment.creatorRating ? `${treatment.creatorRating}/5 creator rating · ` : ""}{candidate.limitations || "No noted limitation"}</small></span>
                      </button>;
                    })}
                  </div>
                </details>
              )}

              <nav className="visual-graphic-review-navigation" aria-label="Graphic review navigation">
                <button disabled={reviewIndex === 0} onClick={() => setReviewIndex((index) => Math.max(0, index - 1))}>Previous graphic</button>
                <span>{graphicApprovalsRemaining} unresolved · {graphicDecisionsPending} not yet reviewed</span>
                <button onClick={() => jumpToNextPendingGraphic()} disabled={!graphicDecisionsPending}>Next pending</button>
                <button disabled={reviewIndex >= graphicReviewSuggestions.length - 1} onClick={() => setReviewIndex((index) => Math.min(graphicReviewSuggestions.length - 1, index + 1))}>Next graphic</button>
              </nav>
            </>
          )}
        </main>
      ) : (
        <>
      <div className="visual-main-grid">
        <aside className="visual-library">
          <div className="visual-panel-title"><span>Visual Library</span><button onClick={() => void importAsset()} disabled={busy} title="Import image or video"><Plus size={16} /> Import</button></div>
          <div className="visual-coverage-summary">
            <strong>Reuse-first plan</strong>
            <span className={reuseAuditHealthy ? "complete" : "missing"}>{suggestionCoverage?.reuseAudit.reviewed ? (reusedTreatmentCount ? `${reusedTreatmentCount} reusable source${reusedTreatmentCount === 1 ? "" : "s"} selected` : plannedGraphicCount ? `0 reused · ${suggestionCoverage.reuseAudit.bespokeRationales.length} bespoke exception${suggestionCoverage.reuseAudit.bespokeRationales.length === 1 ? "" : "s"}` : "Reuse reviewed: no treatment needed") : "Library audit missing"}</span>
            {plannedGraphicCount > 0 && <span className={auditedGraphicCount === plannedGraphicCount ? "complete" : "missing"}>{auditedGraphicCount}/{plannedGraphicCount} graphics face-safe and library-compared · {plannedVisualFamilies} visual families</span>}
            {suggestionCoverage?.reuseAudit.contractVersion === 3 && <span className={unresolvedSuggestionCount === 0 ? "complete" : "missing"}>{approvalCount}/{decisionCounts?.timelineDecisions ?? suggestions.length} timeline decisions approved before production</span>}
            {decisionCounts && <span className="complete">{decisionCounts.timelineDecisions} timeline decisions · {decisionCounts.graphicTreatments} graphics · {decisionCounts.cleanPerformanceHolds} clean holds · {decisionCounts.protectedFootageDecisions} protected · {decisionCounts.bRollDecisions} B-roll</span>}
            {suggestionCoverage?.cadenceAudit && <span className={suggestionCoverage.cadenceAudit.completeCoverage && suggestionCoverage.cadenceAudit.violations.length === 0 ? "complete" : "missing"}>{suggestionCoverage.cadenceAudit.meaningfulChangeCount} meaningful changes · longest non-hold gap {suggestionCoverage.cadenceAudit.maxObservedGapSec.toFixed(1)}s · {suggestionCoverage.cadenceAudit.violations.length} cadence/coverage violations</span>}
            {suggestionCoverage?.variationAudit?.reviewed && <span className={suggestionCoverage.variationAudit.warnings.length ? "missing" : "complete"}>{Object.keys(suggestionCoverage.variationAudit.familyCounts).length} families tracked · {suggestionCoverage.variationAudit.warnings.length} variation warnings</span>}
            <span className={suggestionCoverage?.bRollAudit.reviewed ? "complete" : "missing"}>{suggestionCoverage?.bRollAudit.reviewed ? (suggestionCoverage.bRollAudit.decision === "planned" ? `${plannedBRollCount} B-roll moment${plannedBRollCount === 1 ? "" : "s"} planned` : "B-roll reviewed: not suitable") : "B-roll audit missing"}</span>
            {suggestionCoverage?.bRollAudit.reviewed && <small>{suggestionCoverage.bRollAudit.rationale}</small>}
          </div>
          <div className="visual-tabs">
            <button className={libraryTab === "generated" ? "active" : ""} onClick={() => setLibraryTab("generated")}>Treatments</button>
            <button className={libraryTab === "creator" ? "active" : ""} onClick={() => setLibraryTab("creator")}>Library</button>
            <button className={libraryTab === "imported" ? "active" : ""} onClick={() => setLibraryTab("imported")}>Project</button>
            <button className={libraryTab === "curate" ? "active" : ""} onClick={() => setLibraryTab("curate")}>Rate</button>
          </div>
          {libraryTab === "generated" ? (
            <div className="visual-library-list">
              <div className="visual-library-section"><strong>Registered modules</strong><span>Reuse these content-neutral VCG building blocks first</span></div>
              {MODULES.map((module) => (
                <button key={module.id} className="visual-library-item" onClick={() => addModule(module.id)}>
                  {module.id === "punchline-reveal" ? <Type size={17} /> : <Clapperboard size={17} />}
                  <span><strong>{module.name}</strong><small>{module.description}</small></span>
                </button>
              ))}
              <div className="visual-library-section needs-build"><strong>Proven VCG recipes</strong><span>Adapt an existing treatment before proposing a bespoke scene</span></div>
              {orderedRecipes.map((recipe) => (
                <article key={recipe.id} className="visual-recipe-card" onMouseEnter={() => setHoveredRecipeId(recipe.id)} onMouseLeave={() => setHoveredRecipeId(null)} onFocus={() => setHoveredRecipeId(recipe.id)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setHoveredRecipeId(null); }}>
                  <div className="visual-library-item visual-recipe-item">
                    <Sparkles size={17} />
                    <span><strong>{recipe.name}</strong><small>{recipe.description}</small><em>{recipe.previewAvailable ? "Prior VCG usage" : "Reusable recipe"} · {recipe.speakerMode}</em></span>
                  </div>
                  <button className="visual-recipe-build" onClick={() => void requestRecipe(recipe)} disabled={busy}>Reuse with Codex</button>
                </article>
              ))}
            </div>
          ) : libraryTab === "creator" ? (
            <div className="visual-library-list">
              <label className="creator-search"><Search size={15} /><input value={creatorQuery} onChange={(event) => setCreatorQuery(event.target.value)} placeholder="Search callbacks and AI footage" /></label>
              {visibleCreatorAssets.map((asset) => (
                <button key={asset.id} className="visual-library-item" onClick={() => void placeCreatorAsset(asset)}>
                  {asset.mediaType === "video" ? <video className="creator-library-thumb" src={creatorAssetMediaUrl(asset.id)} muted preload="metadata" /> : <img className="creator-library-thumb" src={creatorAssetMediaUrl(asset.id)} alt="" />}
                  <span><strong>{asset.name}</strong><small>{asset.series ? `${asset.series} · ` : ""}{asset.usageCount} prior uses</small></span>
                </button>
              ))}
              {!visibleCreatorAssets.length && <p className="visual-library-empty">No reusable footage matches this search.</p>}
              <button className="visual-import-button" onClick={() => void importReusableAsset()} disabled={busy}><Sparkles size={16} /> Import reusable AI footage</button>
            </div>
          ) : libraryTab === "imported" ? (
            <div className="visual-library-list">
              {plan.assets.map((asset) => (
                <button key={asset.id} className="visual-library-item" onClick={() => {
                  const cue = defaultAssetCue(asset, playhead, duration);
                  updatePlan((current) => ({ ...current, cues: [...current.cues, cue] }));
                  setSelectedCueId(cue.id);
                }}>
                  {asset.mediaType === "video" ? <Film size={17} /> : <ImageIcon size={17} />}
                  <span><strong>{asset.name}</strong><small>{asset.durationSec ? `${asset.durationSec.toFixed(1)} seconds` : asset.mediaType}</small></span>
                </button>
              ))}
              <button className="visual-import-button" onClick={() => void importAsset()} disabled={busy}><Plus size={16} /> Import animation or image</button>
            </div>
          ) : libraryTab === "curate" ? (
            <div className="visual-library-list visual-curation-list">
              <div className="visual-library-section"><strong>Strengthen the library</strong><span>Rate each unique treatment used in this video and explicitly lock your defaults</span></div>
              {!curatedTreatmentIds.length && <div className="visual-library-empty"><strong>Nothing to rate yet.</strong><span>After a final export, the treatments this video introduced appear here.</span></div>}
              {!!introducedTreatmentIds.length && <p className="visual-muted">Showing the {introducedTreatmentIds.length} treatment{introducedTreatmentIds.length === 1 ? "" : "s"} this video introduced.</p>}
              {curatedTreatmentIds.map((id) => treatments.find((item) => item.id === id)).filter((item): item is VisualTreatment => Boolean(item)).map((treatment) => (
                <article key={treatment.id} className={`visual-curation-card ${treatment.lockedDefault ? "locked" : ""}`}>
                  {treatment.motionPreviewAvailable
                    ? <video className="visual-curation-preview" src={visualTreatmentMotionPreviewUrl(treatment.id)} muted loop controls preload="metadata" />
                    : treatment.previewAvailable && <img className="visual-curation-preview" src={visualTreatmentPreviewUrl(treatment.id)} alt={`${treatment.name ?? treatment.id} preview`} />}
                  <div>
                    <strong>{treatment.name ?? treatment.id}</strong>
                    <span>{treatment.family} · {treatment.allowedLayouts.map((layout) => layout.replaceAll("-", " ")).join(", ")}</span>
                    <small>{treatment.motionProfile}</small>
                  </div>
                  <div className="visual-rating" aria-label={`Rate ${treatment.name ?? treatment.id}`}>
                    {[1, 2, 3, 4, 5].map((rating) => <button key={rating} className={rating <= treatment.creatorRating ? "active" : ""} onClick={() => void curateTreatment(treatment, { creatorRating: rating })} disabled={busy} title={`${rating} of 5`}>★</button>)}
                  </div>
                  <button className={treatment.lockedDefault ? "visual-primary" : ""} onClick={() => void curateTreatment(treatment, { lockedDefault: !treatment.lockedDefault })} disabled={busy}>{treatment.lockedDefault ? "Locked as default" : "Lock as default"}</button>
                </article>
              ))}
            </div>
          ) : (
            <div className="visual-review-panel">
              {!reviewSuggestion ? (
                <div className="visual-library-empty"><strong>No suggestions loaded.</strong><span>Run Project → Cook Visual Plan Prompt, let Codex save visual-suggestions.json, then reopen this workspace.</span></div>
              ) : (
                <>
                  <div className="review-progress"><span>{reviewIndex + 1} / {suggestions.length}</span><strong>{reviewSuggestion.category.replace("-", " ")}</strong></div>
                  <p className="review-transcript">“{reviewSuggestion.transcriptContext ?? "Transcript context not supplied"}”</p>
                  <p className="review-purpose">{reviewSuggestion.editorialPurpose ?? "No editorial rationale supplied."}</p>
                  {suggestionCoverage?.reuseAudit.contractVersion === 3 && reviewSuggestion.scenePacket && (
                    <>
                      <div className="visual-scene-packet">
                        <strong>{reviewSuggestion.scenePacket.layout.replaceAll("-", " ")}</strong>
                        <span>{reviewSuggestion.scenePacket.contentDensity} · {reviewSuggestion.scenePacket.motionOpportunities.length} motion opportunities</span>
                        <small>{reviewSuggestion.scenePacket.protectedRegions.length ? `Protected: ${reviewSuggestion.scenePacket.protectedRegions.map((region) => region.label).join(", ")}` : "No additional protected screen regions"}</small>
                      </div>
                      {(reviewSuggestion.timelineLane === "graphics" || reviewSuggestion.category === "graphic") && (
                        <>
                          <div className="visual-treatment-comparison">
                            <figure>
                              <img src={visualSourceFrameUrl(reviewSuggestion.scenePacket.screenshotTimeSec)} alt={`Video frame at ${formatTime(reviewSuggestion.scenePacket.screenshotTimeSec)}`} />
                              <figcaption>Actual video · {formatTime(reviewSuggestion.scenePacket.screenshotTimeSec)}</figcaption>
                            </figure>
                            <figure>
                              {reviewSuggestion.approvalEvidence?.status === "historical-ready" && selectedTreatment?.previewAvailable
                                ? <img src={visualTreatmentPreviewUrl(selectedTreatment.id)} alt={`${selectedTreatment.name ?? selectedTreatment.id} library example`} />
                                : reviewSuggestion.approvalEvidence?.status === "sample-ready"
                                  ? <img src={visualSuggestionApprovalFrameUrl(reviewSuggestion.id)} alt={`Exact sample of ${selectedTreatment?.name ?? selectedTreatmentId ?? "selected treatment"}`} />
                                  : <div className="visual-treatment-empty">{selectedTreatment ? "Exact sample frame required" : "Choose a treatment"}</div>}
                              <figcaption>{selectedTreatment ? `${selectedTreatment.name ?? selectedTreatment.id}${selectedTreatment.lockedDefault ? " · Locked default" : ""} · ${reviewSuggestion.approvalEvidence?.status?.replace("-", " ") ?? "evidence missing"}` : "Selected treatment evidence"}</figcaption>
                            </figure>
                          </div>
                          {reviewSuggestion.approvalEvidence?.representativeState && <small className="visual-evidence-state">Representative state: {reviewSuggestion.approvalEvidence.representativeState} at {formatTime(reviewSuggestion.approvalEvidence.representativeTimeSec)}</small>}
                          {!reviewEvidenceReady && selectedTreatmentId && <button className="review-wide" onClick={() => void prepareApprovalEvidence(reviewSuggestion)} disabled={busy}><ImageIcon size={15} /> Prepare exact one-frame sample</button>}
                          {(reviewSuggestion.meaningfulChanges?.length ?? 0) > 0 && <div className="visual-scene-packet"><strong>{reviewSuggestion.meaningfulChanges?.length} internal meaningful changes</strong><span>{reviewSuggestion.meaningfulChanges?.map((change) => `${formatTime(change.timeSec)} ${change.description}`).join(" · ")}</span></div>}
                          <div className="visual-ranked-candidates">
                            {[...(reviewSuggestion.rankedCandidates ?? [])].sort((left, right) => left.rank - right.rank).map((candidate) => {
                              const treatment = treatments.find((item) => item.id === candidate.treatmentId);
                              if (!treatment) return null;
                              const selected = candidate.treatmentId === selectedTreatmentId;
                              return <button key={candidate.treatmentId} className={selected ? "selected" : ""} onClick={() => void selectRankedTreatment(reviewSuggestion, treatment)} disabled={busy}>
                                <em>#{candidate.rank}</em>
                                <span><strong>{treatment.name ?? treatment.id}{treatment.lockedDefault ? " · LOCKED" : ""}</strong><small>{candidate.fitReason}</small><small>{treatment.creatorRating ? `${treatment.creatorRating}/5 creator rating · ` : ""}{candidate.limitations || "No noted limitation"}</small></span>
                              </button>;
                            })}
                          </div>
                          <label className="visual-decision-note">Decision note
                            <textarea value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} placeholder="Required when rejecting; optional when approving." />
                          </label>
                          <div className={`visual-planning-decision ${reviewSuggestion.decision?.status ?? "pending"}`}>
                            <strong>{reviewSuggestion.decision?.status === "approved" ? "Approved before production" : reviewSuggestion.decision?.status === "revision-requested" ? "Revision requested" : "Awaiting your decision"}</strong>
                            <span>{reviewSuggestion.rejectionHistory?.length ?? 0} prior rejections</span>
                          </div>
                        </>
                      )}
                    </>
                  )}
                  {reviewSuggestion.category === "stock" && (
                    <>
                      <div className="stock-candidates">
                        {(reviewSuggestion.candidates ?? []).map((candidate, index) => (
                          <button key={candidate.id} className="stock-candidate" onClick={() => void chooseStock(reviewSuggestion, candidate)} disabled={busy}>
                            {candidate.previewUrl ? <img src={candidate.previewUrl} alt="" /> : <span className="stock-placeholder">Pexels</span>}
                            <span><strong>Option {index + 1}</strong><small>{candidate.durationSec.toFixed(1)}s · {candidate.width}×{candidate.height}</small><small>{candidate.creator}</small></span>
                          </button>
                        ))}
                      </div>
                      <button className="visual-primary review-wide" onClick={() => void searchStock(reviewSuggestion)} disabled={busy || !pexelsConfigured}><Search size={15} /> {(reviewSuggestion.candidates?.length ?? 0) ? "Search again" : "Prepare 3–5 Pexels options"}</button>
                    </>
                  )}
                  {reviewSuggestion.category === "creator-library" && (
                    <div className="visual-library-list">
                      {creatorAssets.filter((asset) => !reviewSuggestion.libraryQuery || [asset.name, asset.description, asset.series, ...asset.tags].join(" ").toLowerCase().includes(reviewSuggestion.libraryQuery.toLowerCase())).slice(0, 5).map((asset) => (
                        <button key={asset.id} className="visual-library-item" onClick={() => void placeCreatorAsset(asset, reviewSuggestion.startSec, reviewSuggestion.endSec, reviewSuggestion)}><Film size={16} /><span><strong>{asset.name}</strong><small>{asset.usageCount} prior uses</small></span></button>
                      ))}
                    </div>
                  )}
                  {reviewSuggestion.category === "ai-brief" && <><pre className="generation-brief">{typeof reviewSuggestion.generationBrief === "string" ? reviewSuggestion.generationBrief : JSON.stringify(reviewSuggestion.generationBrief ?? {}, null, 2)}</pre><button onClick={() => void navigator.clipboard.writeText(typeof reviewSuggestion.generationBrief === "string" ? reviewSuggestion.generationBrief : JSON.stringify(reviewSuggestion.generationBrief ?? {}, null, 2)).then(() => setStatus("AI footage brief copied."))}><Copy size={15} /> Copy generation brief</button></>}
                  {suggestionCoverage?.reuseAudit.contractVersion === 3 ? (
                    <div className="review-treatment-actions visual-planning-actions">
                      <button className="visual-primary" onClick={() => void makePlanningDecision(reviewSuggestion, "approve")} disabled={busy || (reviewNeedsTreatment && (!selectedTreatmentId || !reviewEvidenceReady || !reviewSpeakerSafe))}><Check size={15} /> Approve choice</button>
                      {reviewSuggestion.seriesId && <button onClick={() => void makePlanningDecision(reviewSuggestion, "approve-series")} disabled={busy || (reviewNeedsTreatment && (!selectedTreatmentId || !reviewEvidenceReady || !reviewSpeakerSafe))}>Approve series</button>}
                      <button onClick={() => void makePlanningDecision(reviewSuggestion, "reject")} disabled={busy || !decisionNote.trim()}><Trash2 size={15} /> Reject with note</button>
                      <button onClick={() => void makePlanningDecision(reviewSuggestion, "request-another")} disabled={busy || !decisionNote.trim()}>Request another</button>
                    </div>
                  ) : (
                    <div className="review-treatment-actions">
                      <button onClick={() => void approveSuggestion(reviewSuggestion)}><Check size={15} /> Approve</button>
                      <button onClick={() => void setSuggestionStatus(reviewSuggestion, "approved", "clean-speaker")}>Keep speaker</button>
                      <button onClick={() => void setSuggestionStatus(reviewSuggestion, "needs-alternatives", "graphic")}>Use graphic</button>
                      <button onClick={() => void setSuggestionStatus(reviewSuggestion, "needs-alternatives", "creator-library")}>Creator Library</button>
                      <button onClick={() => void setSuggestionStatus(reviewSuggestion, "needs-alternatives", "ai-brief")}>AI brief</button>
                      <button onClick={() => void setSuggestionStatus(reviewSuggestion, "rejected")}><Trash2 size={15} /> Reject</button>
                    </div>
                  )}
                  <div className="review-navigation"><button disabled={reviewIndex === 0} onClick={() => setReviewIndex((index) => Math.max(0, index - 1))}>Previous</button>{suggestionCoverage?.reuseAudit.contractVersion === 3 && <button onClick={() => jumpToNextPendingGraphic()} disabled={!graphicDecisionsPending}>Next pending ({graphicDecisionsPending})</button>}<button disabled={reviewIndex >= graphicReviewSuggestions.length - 1} onClick={() => setReviewIndex((index) => Math.min(graphicReviewSuggestions.length - 1, index + 1))}>Next</button></div>
                </>
              )}
            </div>
          )}
        </aside>

        {hoveredRecipeId && (() => {
          const recipe = recipes.find((item) => item.id === hoveredRecipeId);
          return recipe ? <RecipeHoverPreview recipe={recipe} /> : null;
        })()}

        <div className="visual-preview-column">
          <div className="visual-preview-switcher">
            <button className={previewMode === "runtime" ? "active" : ""} onClick={() => switchPreviewMode("runtime")}>Live preview</button>
            <button className={previewMode === "render" ? "active" : ""} onClick={() => switchPreviewMode("render")} disabled={!renderVideo}>Exported video</button>
            <span>{runtimeReady ? "Runtime ready" : "Loading runtime…"}</span>
          </div>
          <div className="visual-preview-stage" ref={previewStageRef}>
            <button className="visual-fullscreen-control" onClick={() => void togglePreviewFullscreen()} title={previewFullscreen ? "Exit fullscreen" : "View preview fullscreen"}>{previewFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}<span>{previewFullscreen ? "Exit fullscreen" : "Fullscreen"}</span></button>
            {previewMode === "render" && renderVideo ? (
              <video
                ref={renderedVideoRef}
                className="visual-main-video"
                src={renderVideo}
                controls
                onLoadedMetadata={(event) => { event.currentTarget.currentTime = playhead; }}
                onPlay={() => setPreviewPlaying(true)}
                onPause={() => setPreviewPlaying(false)}
                onTimeUpdate={(event) => updatePlayheadFromPlayback(event.currentTarget.currentTime)}
                onEnded={() => { reviewPlaybackEndRef.current = null; reviewPlaybackTargetRef.current = null; setPreviewPlaying(false); updatePlayheadFromPlayback(duration); }}
              />
            ) : runtimeScriptReady && project.runtimePreview.available ? createElement("hyperframes-player", {
              key: project.runtimePreview.cacheKey,
              ref: (element: HyperFramesPlayerElement | null) => { runtimePlayerRef.current = element; },
              className: "visual-hyperframes-player",
              src: visualRuntimeCompositionUrl(project.runtimePreview.cacheKey),
              controls: true,
              width: plan.composition.width,
              height: plan.composition.height,
            }) : <div className="visual-runtime-loading">Preparing the registered HyperFrames composition…</div>}
          </div>
          <div className="visual-transport">
            <button className="visual-icon-button" onClick={() => seek(playhead - 1 / plan.composition.fps)}><ChevronDown className="visual-rotate-90" size={17} /></button>
            <button className="visual-play-button" onClick={togglePreviewPlayback}><Play size={18} /> {previewPlaying ? "Pause" : "Play"}</button>
            <button className="visual-icon-button" onClick={() => seek(playhead + 1 / plan.composition.fps)}><ChevronDown className="visual-rotate-minus-90" size={17} /></button>
            <code>{formatTime(playhead)} / {formatTime(duration)}</code>
          </div>
          <div className="visual-production-gates">
            <span className={project.production.activeReviewCount === 0 ? "passed" : "blocked"}>Review notes {project.production.activeReviewCount === 0 ? "resolved" : `${project.production.activeReviewCount} active`}</span>
            <span className={project.production.timingAnchored ? "passed" : "blocked"}>Voice timing {project.production.timingAnchored ? "anchored" : `${project.production.unanchoredCount} missing`}</span>
            <span className={project.production.noBlanketOverflow ? "passed" : "blocked"}>Composition {project.production.noBlanketOverflow ? "ready" : "blocked"}</span>
            <span className={project.production.planningApprovalPassed ? "passed" : "blocked"}>Scene choices {project.production.planningApprovalPassed ? "approved" : `${project.production.planningApprovalIssues.length} unresolved`}</span>
            <span className={project.production.lockedCutMatches ? "passed" : "blocked"}>Locked cut {project.production.lockedCutMatches ? "matches" : "changed"}</span>
            <span className={project.production.fullReviewApproved ? "passed" : "blocked"}>Full review {project.production.fullReviewApproved ? "approved" : project.production.reviewRenderAvailable ? "awaiting approval" : "not rendered"}</span>
            <span className={project.production.layoutInspectionPassed ? "passed" : ""}>Automated checks {project.production.layoutInspectionPassed ? "last passed" : "run on export"}</span>
          </div>
          {!!project.production.messages.length && <div className="visual-gate-message">{project.production.messages.join(" ")}</div>}
          {project.libraryCuration?.status === "failed" && <div className="visual-gate-message blocked">
            The Creator Library harvest failed, so this video taught the library nothing. {project.libraryCuration.error}
          </div>}
          {!!unratedIntroducedIds.length && <div className="visual-gate-message">
            <strong>{unratedIntroducedIds.length} new treatment{unratedIntroducedIds.length === 1 ? "" : "s"} to rate.</strong>{" "}
            This video introduced {unratedIntroducedIds.join(", ")}. Ratings are what the next Cook ranks candidates by.{" "}
            <button onClick={() => setLibraryTab("curate")}>Rate them now</button>
          </div>}
          {renderJob && <div className={`visual-render-status ${renderJob.status}`}>
            <div><strong>{Math.round(renderJob.value)}% · {renderStageLabel(renderJob.stage)}</strong><span>{renderJob.message}</span><small>{formatRenderTiming(renderJob.elapsed_seconds, renderJob.eta_seconds, renderJob.status)}</small>{renderJob.output_path && <code>{renderJob.output_path}</code>}</div>
            <progress max={100} value={renderJob.value} />
          </div>}
        </div>

        <aside className="visual-inspector">
          <div className="visual-panel-title"><span>Inspector</span>{selectedCue && !selectedCompositionCue && <div><button className="visual-icon-button" onClick={() => void markRepresentativeScene()} disabled={busy} title="Mark as the representative scene for this revision"><Check size={15} /></button><button className="visual-icon-button" onClick={duplicateCue} title="Duplicate"><Copy size={15} /></button><button className="visual-icon-button danger" onClick={deleteCue} title="Delete"><Trash2 size={15} /></button></div>}</div>
          {selectedCue ? (
            <div className="visual-inspector-fields">
              <div className="visual-selection-name"><Check size={15} /> {cueLabel(selectedCue, plan.assets)}</div>
              {selectedCompositionCue
                ? <><div className="visual-render-ownership renderable"><strong>Plan-backed custom composition</strong><span>This scene is played from the same registered HyperFrames source used for review and final rendering. Notes retain its stable cue and scene IDs.</span></div><div className="visual-suggestion-summary"><strong>{formatTime(selectedCue.startSec)} - {formatTime(selectedCue.endSec)}</strong><span>{selectedCue.parameters.editorialPurpose ?? selectedCue.notes ?? "Custom HyperFrames scene"}</span><small>{selectedCue.sceneId} · {selectedCue.parameters.recipeId ?? "custom HyperFrames treatment"}</small></div><div className="visual-semantic-timing"><strong>Voice-synced reveals ({selectedCue.semanticItems.length})</strong>{selectedCue.semanticItems.map((item) => <span key={item.id}><em>{formatTime(item.spokenStartSec)}</em>{item.label}<small>{item.anchorType === "spoken" ? `“${item.phrase}”` : "scene-relative"}</small></span>)}</div></>
                : <div className="visual-render-ownership renderable"><strong>Plan-backed · Renderable</strong><span>Inspector changes save to visual-plan.json; the exact HyperFrames runtime above is also used for review and final rendering.</span></div>}
              <fieldset className="visual-cue-controls" disabled={selectedCompositionCue}>
              <label>Enabled<input type="checkbox" checked={selectedCue.enabled} onChange={(event) => updateCue({ enabled: event.target.checked })} /></label>
              {selectedCue.kind === "module" && <><label>Text<textarea value={selectedCue.parameters.text ?? ""} onChange={(event) => updateCue({}, { text: event.target.value })} /></label><label>Kicker<input value={selectedCue.parameters.kicker ?? ""} onChange={(event) => updateCue({}, { kicker: event.target.value })} /></label>{(selectedCue.moduleId === "punchline-reveal") && <label>Accent color<input type="color" value={selectedCue.parameters.accentColor ?? "#FF00CE"} onChange={(event) => updateCue({}, { accentColor: event.target.value })} /></label>}</>}
              <div className="visual-field-row"><label>Start<input type="number" min={0} max={duration} step={0.01} value={selectedCue.startSec} onChange={(event) => updateCue({ startSec: Math.min(Number(event.target.value), selectedCue.endSec - .01) })} /></label><label>End<input type="number" min={0} max={duration} step={0.01} value={selectedCue.endSec} onChange={(event) => updateCue({ endSec: Math.max(Number(event.target.value), selectedCue.startSec + .01) })} /></label></div>
              {selectedCue.kind === "asset" && <>
                <div className="visual-field-row"><label>X %<input type="number" min={0} max={100} value={selectedCue.parameters.x ?? 0} onChange={(event) => updateCue({}, { x: Number(event.target.value) })} /></label><label>Y %<input type="number" min={0} max={100} value={selectedCue.parameters.y ?? 0} onChange={(event) => updateCue({}, { y: Number(event.target.value) })} /></label></div>
                <div className="visual-field-row"><label>Width %<input type="number" min={1} max={100} value={selectedCue.parameters.width ?? 100} onChange={(event) => updateCue({}, { width: Number(event.target.value) })} /></label><label>Height %<input type="number" min={1} max={100} value={selectedCue.parameters.height ?? 100} onChange={(event) => updateCue({}, { height: Number(event.target.value) })} /></label></div>
                <label>Opacity <span>{Math.round((selectedCue.parameters.opacity ?? 1) * 100)}%</span><input type="range" min={0} max={1} step={0.01} value={selectedCue.parameters.opacity ?? 1} onChange={(event) => updateCue({}, { opacity: Number(event.target.value) })} /></label>
                <label>Fit<select value={selectedCue.parameters.fit ?? "cover"} onChange={(event) => updateCue({}, { fit: event.target.value as "cover" | "contain" | "fill" })}><option value="cover">Cover</option><option value="contain">Contain</option><option value="fill">Fill</option></select></label>
                <label>Source trim<input type="number" min={0} step={0.01} value={selectedCue.parameters.sourceStartSec ?? 0} onChange={(event) => updateCue({}, { sourceStartSec: Number(event.target.value) })} /></label>
                <label className="visual-switch"><input type="checkbox" checked={selectedCue.parameters.muted ?? true} onChange={(event) => updateCue({}, { muted: event.target.checked })} /> Imported media muted</label>
                <p className="visual-muted">{selectedAsset?.hasTransparency ? "Transparency-capable asset" : "Standard composited asset"}</p>
              </>}
              <div className="visual-field-row"><label>Transition in<select value={selectedCue.parameters.transitionIn ?? "fade"} onChange={(event) => updateCue({}, { transitionIn: event.target.value })}><option value="editorial-snap">Editorial snap</option><option value="fade">Fade</option><option value="slide">Slide</option><option value="none">None</option></select></label><label>Transition out<select value={selectedCue.parameters.transitionOut ?? "fade"} onChange={(event) => updateCue({}, { transitionOut: event.target.value })}><option value="fade">Fade</option><option value="slide">Slide</option><option value="none">None</option></select></label></div>
              </fieldset>
            </div>
          ) : selectedSuggestion ? (
            <div className="visual-inspector-fields">
              <div className="visual-selection-name"><Sparkles size={15} /> {selectedSuggestion.moduleId ?? selectedSuggestion.recipeId ?? selectedSuggestion.category.replace("-", " ")}</div>
              <div className="visual-render-ownership planning"><strong>Planning only · Not rendered</strong><span>This item needs a registered module, composition cue, or imported overlay before it can appear in the rendered video.</span></div>
              <div className="visual-suggestion-summary"><strong>{formatTime(selectedSuggestion.startSec)} - {formatTime(selectedSuggestion.endSec)}</strong><span>{selectedSuggestion.editorialPurpose ?? "Planning item"}</span><small>{selectedSuggestion.status.replace("-", " ")}</small></div>
              {(selectedSuggestion.timelineLane === "graphics" || selectedSuggestion.category === "graphic") && <div className="visual-suggestion-summary"><strong>{selectedSuggestion.speakerSafety?.checked ? "Speaker-safe geometry checked" : "Speaker-safety check missing"}</strong><span>{selectedSuggestion.visualFamily ? `Visual family: ${selectedSuggestion.visualFamily}` : "Visual family missing"}</span><small>{selectedSuggestion.candidateTreatmentIds?.length ?? 0} library treatments compared{selectedSuggestion.speakerSafety ? ` · ${selectedSuggestion.speakerSafety.mode}` : ""}</small></div>}
            </div>
          ) : <p className="visual-muted">Select a timeline clip or planning item to edit or review it.</p>}
          {(selectedReviewTarget || activeReviewQueue.length > 0) && (
            <section className={`visual-note-dock ${activeReview?.status ?? ""}`}>
              <div className="visual-note-heading"><div><strong>Review note</strong><span>{activeReview?.note.trim() ? activeReview.status.replaceAll("-", " ") : selectedReviewTarget ? "No active note" : "Choose next review"}</span></div><div className="visual-note-actions">{activeReview?.status === "ready-for-review" && <button className="visual-primary" onClick={acceptReview}><Check size={14} /> Accept</button>}<button onClick={jumpToNextReview} disabled={busy || !activeReviewQueue.length}><SkipForward size={14} /> Next review ({activeReviewQueue.length})</button></div></div>
              {selectedReviewTarget ? <>
                <label>What should change?
                  <textarea value={activeReview?.note ?? ""} onChange={(event) => updateReview({ note: event.target.value })} placeholder="Add a precise note for this scene..." />
                </label>
                <label className="visual-review-option"><input type="checkbox" checked={activeReview?.directive === "leave-everything-else"} onChange={(event) => updateReview({ directive: event.target.checked ? "leave-everything-else" : "targeted" })} /> Leave everything else</label>
                <label className="visual-review-option"><input type="checkbox" checked={activeReview?.directive === "replace-all"} onChange={(event) => updateReview({ directive: event.target.checked ? "replace-all" : "targeted" })} /> Replace all of it</label>
                <small>Only non-empty notes are included by Copy All Notes. Accepted notes stay in project history.</small>
              </> : <small>Next review selects the item and automatically plays only its timestamped section.</small>}
              {plan.reviewHistory.length > 0 && <details className="visual-review-history"><summary>Accepted note history ({plan.reviewHistory.length})</summary><div>{[...plan.reviewHistory].reverse().map((item) => <article key={`${item.id}-${item.acceptedAt}`}><strong>{formatTime(item.startSec)} - {formatTime(item.endSec)}</strong><span>{item.note}</span><small>{item.itemType} {item.itemId}</small></article>)}</div></details>}
            </section>
          )}
        </aside>
      </div>

      <div className="visual-timeline-area">
        <div className="visual-timeline-toolbar"><span>{status}</span><div><strong>{project.activeRevision ? `${project.activeRevision.name} · ${project.activeRevision.status}` : "No rendered revision"}</strong></div></div>
        <input className="visual-scrubber" type="range" min={0} max={duration} step={1 / plan.composition.fps} value={playhead} onChange={(event) => seek(Number(event.target.value))} />
        <div className="visual-timeline-grid">
          <TimelineRow label="Main video"><div className="visual-main-track">Locked video + verified locked-cut audio</div></TimelineRow>
          <TimelineRow label="Graphics">
            {plan.cues.filter((cue) => cue.kind === "module").map((cue) => <TimelineClip key={cue.id} cue={cue} duration={duration} selected={cue.id === selectedCueId} reviewStatus={plan.reviews.find((item) => item.itemType === "cue" && item.itemId === cue.id && item.note.trim())?.status} label={cueLabel(cue, plan.assets)} onSelect={() => selectCue(cue)} />)}
            {suggestions.filter((item) => item.category === "graphic" && item.status !== "built" && item.status !== "rejected").map((item) => <SuggestionClip key={item.id} suggestion={item} duration={duration} selected={item.id === selectedSuggestionId} reviewStatus={plan.reviews.find((review) => review.itemType === "suggestion" && review.itemId === item.id && review.note.trim())?.status} kind="graphic" onSelect={() => selectSuggestion(item)} />)}
          </TimelineRow>
          <TimelineRow label="Active revision">{plan.cues.filter((cue) => cue.kind === "composition").map((cue) => <TimelineClip key={cue.id} cue={cue} duration={duration} selected={cue.id === selectedCueId} reviewStatus={plan.reviews.find((item) => item.itemType === "cue" && item.itemId === cue.id && item.note.trim())?.status} label={cueLabel(cue, plan.assets)} onSelect={() => selectCue(cue)} />)}</TimelineRow>
          <TimelineRow label="B-roll">{suggestions.filter((item) => item.timelineLane === "b-roll" || item.category === "stock").map((item) => <SuggestionClip key={item.id} suggestion={item} duration={duration} selected={item.id === selectedSuggestionId} reviewStatus={plan.reviews.find((review) => review.itemType === "suggestion" && review.itemId === item.id && review.note.trim())?.status} kind="b-roll" onSelect={() => selectSuggestion(item)} />)}</TimelineRow>
          <TimelineRow label="AI footage">{suggestions.filter((item) => item.timelineLane === "ai-footage" || item.category === "ai-brief").map((item) => <SuggestionClip key={item.id} suggestion={item} duration={duration} selected={item.id === selectedSuggestionId} reviewStatus={plan.reviews.find((review) => review.itemType === "suggestion" && review.itemId === item.id && review.note.trim())?.status} kind="ai" onSelect={() => selectSuggestion(item)} />)}</TimelineRow>
          <TimelineRow label="Imported">{plan.cues.filter((cue) => cue.kind === "asset").map((cue) => <TimelineClip key={cue.id} cue={cue} duration={duration} selected={cue.id === selectedCueId} reviewStatus={plan.reviews.find((item) => item.itemType === "cue" && item.itemId === cue.id && item.note.trim())?.status} label={cueLabel(cue, plan.assets)} imported onSelect={() => selectCue(cue)} />)}</TimelineRow>
          <TimelineRow label="Protected">{plan.protectedFootage.map((item) => <div key={item.id} className="visual-protected-clip" style={{ left: `${item.startSec / duration * 100}%`, width: `${(item.endSec - item.startSec) / duration * 100}%` }}>{item.reason}</div>)}</TimelineRow>
          <div className="visual-playhead" style={{ left: `calc(112px + (100% - 112px) * ${duration ? playhead / duration : 0})` }} />
        </div>
      </div>
        </>
      )}
    </section>
  );
}

function RecipeHoverPreview({ recipe }: { recipe: VisualRecipe }) {
  const kind = recipePreviewKind(recipe.id);
  return <aside className="visual-recipe-preview-flyout">
    <div className="visual-recipe-preview-heading"><div><strong>{recipe.name}</strong><span>{recipe.previewAvailable ? "Latest private usage" : "Illustrative preview"}</span></div><em>Reuse first</em></div>
    <div className="visual-recipe-preview-frame">
      {recipe.previewAvailable ? <img src={visualRecipePreviewUrl(recipe.id)} alt={`Most recent ${recipe.name} usage`} /> : <RecipeIllustration kind={kind} />}
    </div>
    <p>{recipe.description}</p>
    <small>Reuse with Codex creates a scoped request at the current playhead. Codex should adapt this existing treatment before inventing another visual system.</small>
  </aside>;
}

function RecipeIllustration({ kind }: { kind: "chart" | "steps" | "terminal" | "cta" | "illustration" | "cards" }) {
  if (kind === "chart") return <svg className="visual-recipe-illustration" viewBox="0 0 360 202" role="img" aria-label="Chart treatment preview"><rect width="360" height="202" fill="#fff" /><path d="M42 24v138h286" stroke="#1a1a2e" strokeWidth="4" fill="none" /><path d="M48 76L112 58l62 26 52-16 48 88 46 24" stroke="#ff00ce" strokeWidth="8" fill="none" /><path d="M42 116h286" stroke="#007c7d" strokeWidth="2" strokeDasharray="8 7" /><rect x="236" y="150" width="90" height="28" rx="4" fill="#1a1a2e" /><rect x="256" y="158" width="50" height="10" fill="#fff" /></svg>;
  if (kind === "terminal") return <svg className="visual-recipe-illustration" viewBox="0 0 360 202" role="img" aria-label="Windows application treatment preview"><rect width="360" height="202" fill="#f5f5f8" /><rect x="28" y="22" width="304" height="150" rx="8" fill="#1a1a2e" /><rect x="28" y="22" width="304" height="28" rx="8" fill="#dedee6" /><circle cx="48" cy="36" r="5" fill="#007c7d" /><rect x="50" y="70" width="150" height="9" fill="#ff00ce" /><rect x="50" y="94" width="238" height="8" fill="#fff" opacity=".82" /><rect x="50" y="116" width="196" height="8" fill="#fff" opacity=".55" /><rect x="50" y="138" width="110" height="8" fill="#007c7d" /></svg>;
  if (kind === "steps") return <svg className="visual-recipe-illustration" viewBox="0 0 360 202" role="img" aria-label="Sequential reveal treatment preview"><rect width="360" height="202" fill="#fff" /><rect x="30" y="31" width="86" height="54" rx="5" fill="#e6f5f5" stroke="#007c7d" strokeWidth="3" /><rect x="137" y="31" width="86" height="54" rx="5" fill="#fff0fb" stroke="#c700a1" strokeWidth="3" /><rect x="244" y="31" width="86" height="54" rx="5" fill="#1a1a2e" /><path d="M58 130h244" stroke="#dedee6" strokeWidth="16" /><path d="M58 130h244" stroke="#ff00ce" strokeWidth="16" /><circle cx="302" cy="130" r="22" fill="#ff00ce" /><path d="M302 115l5 10 11 2-8 8 2 11-10-5-10 5 2-11-8-8 11-2z" fill="#fff" /></svg>;
  if (kind === "cta") return <svg className="visual-recipe-illustration" viewBox="0 0 360 202" role="img" aria-label="Call to action treatment preview"><rect width="360" height="202" fill="#1a1a2e" /><circle cx="95" cy="101" r="48" fill="#ff00ce" /><path d="M76 101l14 14 28-34" stroke="#fff" strokeWidth="10" fill="none" /><rect x="170" y="55" width="150" height="15" fill="#fff" /><rect x="170" y="84" width="112" height="10" fill="#dedee6" /><rect x="170" y="119" width="132" height="38" rx="5" fill="#007c7d" /><rect x="194" y="133" width="84" height="10" fill="#fff" /></svg>;
  if (kind === "illustration") return <svg className="visual-recipe-illustration" viewBox="0 0 360 202" role="img" aria-label="Illustrated comedy treatment preview"><rect width="360" height="202" fill="#fff" /><circle cx="92" cy="89" r="39" fill="#dedee6" /><path d="M43 177c4-42 24-64 49-64s45 22 49 64" fill="#1a1a2e" /><rect x="164" y="35" width="157" height="37" rx="18" fill="#fff0fb" stroke="#c700a1" strokeWidth="3" /><rect x="184" y="50" width="104" height="8" fill="#c700a1" /><rect x="184" y="91" width="128" height="32" rx="16" fill="#e6f5f5" /><rect x="202" y="103" width="88" height="8" fill="#007c7d" /><rect x="184" y="140" width="110" height="32" rx="16" fill="#1a1a2e" /></svg>;
  return <svg className="visual-recipe-illustration" viewBox="0 0 360 202" role="img" aria-label="Composite graphic treatment preview"><rect width="360" height="202" fill="#fff" /><rect x="24" y="24" width="126" height="154" rx="6" fill="#1a1a2e" /><rect x="45" y="45" width="84" height="110" rx="42" fill="#4a4a5a" /><rect x="179" y="31" width="151" height="35" rx="4" fill="#ff00ce" /><rect x="179" y="83" width="151" height="32" rx="4" fill="#e6f5f5" /><rect x="179" y="132" width="112" height="32" rx="4" fill="#fff0fb" /></svg>;
}

function recipePreviewKind(id: string): "chart" | "steps" | "terminal" | "cta" | "illustration" | "cards" {
  if (/(chart|meter|comparison|orbit|constellation|roadmap|pathway)/.test(id)) return "chart";
  if (/(step|list|stack|recap|principles|loop|callouts|blockers)/.test(id)) return "steps";
  if (/(terminal|prompt|input-output|command|desktop)/.test(id)) return "terminal";
  if (/(cta|finale|thesis|rank|punctuation|abundance)/.test(id)) return "cta";
  if (/(troll|conversation|archive)/.test(id)) return "illustration";
  return "cards";
}

function TimelineRow({ label, children }: { label: string; children: React.ReactNode }) {
  return <><div className="visual-track-label">{label}</div><div className="visual-track-lane">{children}</div></>;
}

function TimelineClip({ cue, duration, label, imported = false, selected, reviewStatus, onSelect }: { cue: VisualCue; duration: number; label: string; imported?: boolean; selected: boolean; reviewStatus?: VisualReviewRecord["status"]; onSelect: () => void }) {
  return <button className={`visual-timeline-clip ${imported ? "imported" : ""} ${selected ? "selected" : ""} ${reviewStatus ?? ""} ${cue.enabled ? "" : "disabled"}`} style={{ left: `${cue.startSec / duration * 100}%`, width: `${Math.max(1.2, (cue.endSec - cue.startSec) / duration * 100)}%` }} onClick={onSelect}>{label}</button>;
}

function SuggestionClip({ suggestion, duration, selected, reviewStatus, kind, onSelect }: { suggestion: VisualSuggestion; duration: number; selected: boolean; reviewStatus?: VisualReviewRecord["status"]; kind: "graphic" | "b-roll" | "ai"; onSelect: () => void }) {
  const label = suggestion.recipeId ?? suggestion.editorialPurpose ?? suggestion.category;
  return <button className={`visual-suggestion-clip ${kind} ${selected ? "selected" : ""} ${reviewStatus ?? ""} ${suggestion.status}`} style={{ left: `${suggestion.startSec / duration * 100}%`, width: `${Math.max(1.2, (suggestion.endSec - suggestion.startSec) / duration * 100)}%` }} onClick={onSelect}>{label}</button>;
}

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${remainder.toFixed(2).padStart(5, "0")}`;
}

function formatDuration(seconds: number) {
  const rounded = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function renderStageLabel(stage: VisualRenderJob["stage"]) {
  return ({
    queued: "Queued",
    preparing: "Preparing",
    validating: "Checking project",
    rendering: "Rendering frames",
    audio: "Attaching audio",
    verifying: "Verifying final video",
    complete: "Complete",
    failed: "Failed",
  } satisfies Record<VisualRenderJob["stage"], string>)[stage];
}

function formatRenderTiming(elapsedSeconds: number, etaSeconds: number | null, status: VisualRenderJob["status"]) {
  if (status === "complete") return `Completed in ${formatDuration(elapsedSeconds)}`;
  if (status === "failed") return `Stopped after ${formatDuration(elapsedSeconds)}`;
  return `Elapsed ${formatDuration(elapsedSeconds)}${etaSeconds === null ? "" : ` · About ${formatDuration(etaSeconds)} remaining`}`;
}
