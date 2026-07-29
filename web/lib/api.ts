export const API_BASE = process.env.NEXT_PUBLIC_VCG_API_BASE ?? "http://127.0.0.1:8731";

export type EditorToken = {
  id: string;
  kind: "word" | "silence";
  text: string;
  start_frame: number;
  end_frame: number;
};

export type TranscriptWord = {
  id: string;
  raw: string;
  text: string;
  start: number;
  end: number;
  start_frame: number;
  end_frame: number;
  sentence_id: number;
};

export type SilenceRange = {
  id: string;
  start: number;
  end: number;
  start_frame: number;
  end_frame: number;
  measured_start: number | null;
  measured_end: number | null;
  measured_start_frame: number | null;
  measured_end_frame: number | null;
  audio_analyzed: boolean;
};

export type DynamicSplice = {
  id: string;
  anchor_key: string;
  left_keep_range_id: string;
  right_keep_range_id: string;
  left_word_id: string;
  right_word_id: string;
  left_out_frame: number;
  right_in_frame: number;
  left_whisper_out_frame: number;
  left_suggested_out_frame: number;
  right_whisper_in_frame: number;
  right_suggested_in_frame: number;
  left_out_adjustment: number;
  right_in_adjustment: number;
  left_context: string;
  right_context: string;
  reviewed: boolean;
  kind: "transcript" | "front_trim" | "manual";
  manual_cut_id: string;
  preview_segments_2s: [number, number][];
  preview_segments_4s: [number, number][];
  preview_segments_6s: [number, number][];
};

export type EditorProjectResponse = {
  project_path: string | null;
  video_project?: VideoProjectResponse | null;
  project: {
    source: string;
    fps: number;
    words: TranscriptWord[];
    silence_ranges: SilenceRange[];
    generation: Record<string, unknown>;
  };
  tokens: EditorToken[];
  deleted_word_ids: string[];
  repeated_word_ids: string[];
  deleted_silence_ids: string[];
  splices: DynamicSplice[];
  kept_ranges: unknown[];
  final_cut: {
    out_frame: number;
    suggested_out_frame: number;
    adjustment: number;
    minimum_out_frame: number;
    maximum_out_frame: number | null;
    custom: boolean;
  } | null;
  settings: {
    dead_space_min_seconds: number;
  };
  dead_space_candidate_count: number;
  pause_analysis_pending_count: number;
  fine_tune_summary: {
    cuts_checked: number;
    cuts_adjusted: number;
    cuts_unchanged: number;
  } | null;
  pause_analysis_summary: {
    candidates_checked: number;
    validated_long_pauses: number;
    rejected_candidates: number;
  } | null;
};

export type VideoProjectManifest = {
  schemaVersion: number;
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  paths: Record<string, string>;
  sourceSequence?: SourceClip[];
  sequenceRevision?: number;
  sequenceBuild?: {
    mode: "stream-copy" | "normalized";
    compatible: boolean;
    differences: string[];
    durationSec: number;
  };
  artifacts?: Record<string, number>;
};

export type SourceClip = {
  id: string;
  name: string;
  path: string;
  order: number;
  startSec: number;
  durationSec: number;
  normalizedPath?: string;
  metadata: {
    durationSec: number;
    videoCodec: string | null;
    videoProfile?: string | null;
    videoLevel?: number | null;
    width: number;
    height: number;
    pixelFormat: string | null;
    frameRate: string;
    timeBase?: string | null;
    audioCodec: string | null;
    audioSampleRate: number | null;
    audioChannels: number | null;
  };
};

export type VideoProjectResponse = {
  manifestPath: string;
  root: string;
  name: string;
  preferredSource: string;
  manifest: VideoProjectManifest;
  resolvedPaths: Record<string, string>;
};

export type VideoProjectOpenResponse = {
  videoProject: VideoProjectResponse;
  editorProject: EditorProjectResponse | null;
};

export type CaptionPresetPayload = {
  name: string;
  max_words: number;
  max_duration: number;
  max_chars: number;
};

export type CaptionStylePayload = {
  font_family: string;
  main_font_size: number;
  active_font_size: number;
  main_color: string;
  active_color: string;
  outline_color: string;
  outline_width: number;
  bold: boolean;
  active_bold: boolean;
  position: string;
  margin_v: number;
  outline_enabled: boolean;
  shadow_enabled: boolean;
  shadow_color: string;
  shadow_depth: number;
  glow_enabled: boolean;
  glow_color: string;
  glow_strength: number;
};

export type CaptionOptionsResponse = {
  presets: Record<string, CaptionPresetPayload>;
  models: Record<string, string>;
  compute: Record<string, { device: string; compute_type: string }>;
  styles: Record<string, CaptionStylePayload>;
  built_in_styles: string[];
  default_style: CaptionStylePayload;
  source: string | null;
  output_folder: string;
};

export type CaptionGenerateRequest = {
  input_video_path?: string | null;
  output_folder?: string | null;
  style: CaptionStylePayload;
  preset: CaptionPresetPayload;
  model_label: string;
  compute_label: string;
};

export type TranscribeProjectRequest = {
  model_label: string;
  compute_label: string;
};

export type TranscriptionJobResponse = {
  job_id: string;
};

export type TranscriptionJobStatus = {
  status: "running" | "complete" | "failed";
  value: number;
  message: string;
  result: EditorProjectResponse | null;
  error: string | null;
};

export type ProjectDocumentResponse = {
  filename: string;
  document: unknown;
};

export type CaptionPreviewWord = {
  text: string;
  start: number;
  end: number;
};

export type CaptionPreviewGroup = {
  start: number;
  end: number;
  words: CaptionPreviewWord[];
};

export type CaptionPreviewResponse = {
  source: string;
  word_count: number;
  used_project_transcript: boolean;
  words: CaptionPreviewWord[];
  groups: CaptionPreviewGroup[];
};

export type CaptionPreviewRequest = {
  input_video_path?: string | null;
  preset: CaptionPresetPayload;
  model_label: string;
  compute_label: string;
};

export type AudioPresetPayload = {
  id: string;
  name: string;
  description: string;
};

export type AudioOptionsResponse = {
  presets: AudioPresetPayload[];
  source: string | null;
  output_folder: string;
  defaults: {
    preset_id: string;
    target_i: number;
    target_lra: number;
    target_tp: number;
  };
};

export type AudioSettingsPayload = {
  input_video_path?: string | null;
  preset_id: string;
  target_i: number;
  target_lra: number;
  target_tp: number;
};

export type AudioAnalysisResponse = {
  source: string;
  measurement: {
    input_i: number;
    input_tp: number;
    input_lra: number;
    input_thresh: number;
    target_offset: number;
  };
  target: {
    integrated_lufs: number;
    loudness_range_lu: number;
    true_peak_dbtp: number;
  };
  hotspots: {
    loudest: AudioHotspot;
    quietest_speech: AudioHotspot;
  } | null;
  hotspot_message: string | null;
};

export type AudioHotspot = {
  start_seconds: number;
  focus_seconds: number;
  loudness_lufs: number;
};

export type AudioPreviewResponse = AudioAnalysisResponse & {
  preview_id: string;
  start_seconds: number;
  duration_seconds: number;
};

export type VisualAsset = {
  id: string;
  name: string;
  path: string;
  mediaType: "video" | "image";
  durationSec: number | null;
  hasTransparency: boolean;
  origin?: {
    kind?: string;
    active?: boolean;
    revisionId?: string;
    revisionName?: string;
    [key: string]: unknown;
  };
};

export type VisualCueParameters = {
  text?: string;
  kicker?: string;
  startLabel?: string;
  targetLabel?: string;
  nodes?: string[];
  leftTitle?: string;
  rightTitle?: string;
  leftItems?: string[];
  rightItems?: string[];
  leftColor?: string;
  rightColor?: string;
  accentColor?: string;
  side?: "left" | "right";
  panelWidth?: number;
  videoBounds?: { x: number; y: number; width: number; height: number };
  frameStyle?: string;
  items?: string[];
  milestones?: string[];
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  opacity?: number;
  scale?: number;
  rotation?: number;
  fit?: "cover" | "contain" | "fill";
  muted?: boolean;
  volume?: number;
  sourceStartSec?: number;
  playbackRate?: number;
  loop?: boolean;
  transitionIn?: string;
  transitionOut?: string;
  reviewLabel?: string;
  editorialPurpose?: string;
  recipeId?: string;
  speakerSafety?: VisualSuggestion["speakerSafety"];
  visualFamily?: string;
  candidateTreatmentIds?: string[];
  selectionRationale?: string;
  planningSuggestionId?: string;
  approvedTreatmentId?: string;
  meaningfulChanges?: VisualMeaningfulChange[];
  approvalEvidence?: VisualApprovalEvidence;
};

export type VisualMeaningfulChange = {
  timeSec: number;
  kind: "treatment-enter" | "internal-reveal" | "chart-change" | "ui-action" | "callout-change" | "composition-change" | "speaker-reframe" | "supporting-visual" | "punch-zoom" | "emphasis-change" | "treatment-exit";
  description: string;
};

export type VisualApprovalEvidence = {
  status: "historical-ready" | "sample-ready" | "sample-required";
  selectedTreatmentId: string;
  sourceFrameTimeSec: number;
  representativeTimeSec: number;
  representativeState: string;
  sampleFramePath?: string;
};

export type VisualSemanticItem = {
  id: string;
  label: string;
  text: string;
  parameterPath: string;
  phrase: string;
  anchorType: "spoken" | "scene-relative" | "unanchored";
  spokenStartSec: number;
  fullyVisibleSec: number;
};

export type VisualCue = {
  id: string;
  kind: "module" | "asset" | "composition";
  moduleId?: "punchline-reveal" | "source-footage-hold" | "speaker-side-panel" | "progress-scale" | "dependency-stack" | "dual-comparison";
  assetId?: string;
  compositionId?: string;
  sceneId?: string;
  startSec: number;
  endSec: number;
  enabled: boolean;
  parameters: VisualCueParameters;
  semanticItems: VisualSemanticItem[];
  notes?: string;
};

export type VisualCustomComposition = {
  id: string;
  name: string;
  runtime: "hyperframes";
  projectPath: string;
  entryFile: string;
  rootCompositionId: string;
  storyboardPath?: string;
  timingLedgerPath?: string;
  sourceHash?: string;
};

export type VisualRevision = {
  number: number;
  id: string;
  name: string;
  status: "review" | "delivered" | "superseded";
  runtime: "hyperframes";
  compositionId: string | null;
  hyperframesSource: string;
  entryFile: string;
  reviewRender: string;
  finalRender: string;
  planHash: string;
  reviewHash?: string;
  finalHash?: string;
  createdAt: string;
  updatedAt: string;
};

export type VisualProductionReport = {
  planHash: string;
  representativeApproved: boolean;
  fullReviewApproved: boolean;
  reviewRenderAvailable: boolean;
  layoutInspectionPassed: boolean;
  timingAnchored: boolean;
  unanchoredCount: number;
  unanchoredItems: Array<{ cueId: string; semanticId: string; label: string }>;
  noBlanketOverflow: boolean;
  blanketOverflowFiles: string[];
  speakerSafetyPassed: boolean;
  speakerSafetyIssues: string[];
  planningApprovalPassed: boolean;
  planningApprovalIssues: string[];
  /** False when the locked cut changed after the plan was authored, so cue times refer to old footage. */
  lockedCutMatches: boolean;
  lockedCutIssues: string[];
  canRenderReview: boolean;
  canDeliver: boolean;
  canExportFinal: boolean;
  activeReviewCount: number;
  deliveryReopenVerified: boolean;
  messages: string[];
};

export type ProtectedFootageRange = {
  id: string;
  cueId?: string;
  startSec: number;
  endSec: number;
  reason: string;
};

export type VisualReviewRecord = {
  id: string;
  itemId: string;
  itemType: "cue" | "suggestion";
  startSec: number;
  endSec: number;
  note: string;
  directive: "targeted" | "leave-everything-else" | "replace-all";
  status: "changes-requested" | "ready-for-review";
  createdAt: string;
  updatedAt: string;
  copiedAt?: string;
  acceptedAt?: string;
};

export type VisualPlan = {
  schemaVersion: 2;
  project: { id: string; name: string; createdAt: string; updatedAt: string };
  source: { video: string; transcript: string };
  composition: { width: number; height: number; fps: number; durationSec: number; brandId: string };
  assets: VisualAsset[];
  customCompositions: VisualCustomComposition[];
  protectedFootage: ProtectedFootageRange[];
  cues: VisualCue[];
  revisions: { activeRevision: number | null; items: VisualRevision[] };
  productionGates: {
    representativeApproval: Record<string, unknown> | null;
    fullReviewApproval: Record<string, unknown> | null;
    layoutInspection: Record<string, unknown> | null;
    deliveryReopen: Record<string, unknown> | null;
  };
  reviews: VisualReviewRecord[];
  reviewHistory: VisualReviewRecord[];
};

export type VisualProjectResponse = {
  planPath: string;
  projectRoot: string;
  plan: VisualPlan;
  importedAsset?: VisualAsset;
  finalVideo?: {
    available: boolean;
    revisionId: string | null;
    revisionName: string | null;
    revisionNumber: number | null;
    cacheKey: string | null;
  };
  runtimePreview: {
    available: boolean;
    accurate: true;
    runtime: "hyperframes";
    source: string | null;
    cacheKey: string;
  };
  activeRevision: VisualRevision | null;
  production: VisualProductionReport;
  /** Outcome of the last delivery's library harvest. Null until a final export has run. */
  libraryCuration: LibraryCuration | null;
};

export type LibraryCuration = {
  status: "complete" | "failed" | "not-run";
  treatmentsRecorded: number;
  candidates?: number;
  /** Treatments this video introduced. These are the ones worth rating. */
  introducedTreatmentIds?: string[];
  error?: string;
};

export type VisualRenderJob = {
  job_id: string;
  plan_path: string;
  purpose: "range" | "review" | "final";
  status: "running" | "complete" | "failed";
  stage: "queued" | "preparing" | "validating" | "rendering" | "audio" | "verifying" | "complete" | "failed";
  value: number;
  message: string;
  output_path: string | null;
  error: string | null;
  started_at: string;
  updated_at: string;
  elapsed_seconds: number;
  eta_seconds: number | null;
};

export type CreatorAsset = {
  id: string;
  name: string;
  description: string;
  tags: string[];
  series: string;
  tone: string[];
  provider: string;
  path: string;
  mediaType: "video" | "image";
  durationSec: number | null;
  width: number | null;
  height: number | null;
  importantAction?: { startSec: number; endSec: number } | null;
  audioDefault: string;
  favorite: boolean;
  archived: boolean;
  sha256: string;
  usageCount: number;
  firstUsedAt: string | null;
  lastUsedAt: string | null;
};

export type StockCandidate = {
  id: string;
  provider: "pexels";
  durationSec: number;
  width: number;
  height: number;
  previewUrl: string;
  downloadUrl: string;
  assetPage: string;
  creator: string;
  creatorUrl?: string;
  score: number;
};

export type VisualSuggestion = {
  id: string;
  status: "proposed" | "prepared" | "approved" | "rejected" | "built" | "needs-alternatives";
  category: "clean-speaker" | "protected-footage" | "graphic" | "creator-library" | "project-asset" | "stock" | "ai-brief";
  timelineLane?: "graphics" | "b-roll" | "ai-footage";
  startSec: number;
  endSec: number;
  transcriptContext?: string;
  editorialPurpose?: string;
  confidence?: number;
  protectedFootageConflict?: string | null;
  libraryQuery?: string;
  stockBrief?: { literalQueries?: string[]; metaphoricalQueries?: string[]; avoid?: string[]; desiredDurationSec?: number };
  generationBrief?: Record<string, unknown> | string;
  moduleId?: string | null;
  moduleParameters?: Record<string, unknown>;
  recipeId?: string | null;
  candidateTreatmentIds?: string[];
  visualFamily?: string;
  selectionRationale?: string;
  intentionalRepeat?: boolean;
  repeatRationale?: string;
  meaningfulChanges?: VisualMeaningfulChange[];
  approvalEvidence?: VisualApprovalEvidence;
  scenePacket?: {
    layout: VisualSceneLayout;
    screenshotTimeSec: number;
    purpose: string;
    contentDensity: string;
    motionOpportunities: string[];
    spokenBeats: Array<Record<string, unknown>>;
    protectedRegions: Array<{ label: string; bounds: { x: number; y: number; width: number; height: number } }>;
    bRollFit: string;
    seriesId?: string;
    surroundingConstraints?: string[];
  };
  rankedCandidates?: VisualTreatmentCandidate[];
  decision?: {
    status: "pending" | "approved" | "revision-requested";
    selectedTreatmentId?: string | null;
    notes?: string;
    decidedAt?: string;
  };
  rejectionHistory?: Array<{ selectedTreatmentId?: string | null; notes: string; rejectedAt: string }>;
  seriesId?: string;
  reusePolicy?: "limited" | "repeat-safe" | "intentional-series" | "callback-only";
  speakerSafety?: {
    checked: boolean;
    mode: "full-frame-speaker" | "left-container" | "right-container" | "bottom-container" | "corner-container";
    speakerBounds: { x: number; y: number; width: number; height: number } | null;
    overlayOcclusionBounds: { x: number; y: number; width: number; height: number }[];
    verifiedAtSec: number[];
    maxSpeakerAbsenceSec: number;
  };
  candidates?: StockCandidate[];
  selectedCandidate?: string;
  cueId?: string;
};

export type VisualSuggestionCoverage = {
  runtimeSec?: number;
  decisionCounts?: {
    timelineDecisions: number;
    graphicTreatments: number;
    cleanPerformanceHolds: number;
    protectedFootageDecisions: number;
    bRollDecisions: number;
    unresolvedApprovals: number;
  };
  cadenceAudit?: {
    maxAllowedGapSec: 5;
    maxObservedGapSec: number;
    meaningfulChangeCount: number;
    completeCoverage: boolean;
    violations: Array<{ startSec: number; endSec: number; reason: string }>;
  };
  reuseAudit: {
    contractVersion?: 2 | 3;
    reviewed: boolean;
    reusedModuleIds: string[];
    reusedRecipeIds: string[];
    creatorLibraryQueries: string[];
    bespokeRationales: string[];
  };
  bRollAudit: {
    reviewed: boolean;
    decision: "planned" | "not-suitable";
    rationale: string;
  };
  variationAudit?: {
    reviewed: boolean;
    familyCounts: Record<string, number>;
    treatmentCounts: Record<string, number>;
    intentionalSeriesIds: string[];
    warnings: string[];
  };
};

export type VisualCatalogModule = {
  id: NonNullable<VisualCue["moduleId"]>;
  name?: string;
  purpose: string;
  kind: "module";
  family: string;
  intents: string[];
  allowedLayouts: VisualSceneLayout[];
  contentCapacity: string;
  motionProfile: string;
  reusePolicy: string;
  previewAvailable?: boolean;
  motionPreviewAvailable?: boolean;
  creatorRating: number;
  lockedDefault: boolean;
  lockScopes: string[];
  usageCount: number;
};

export type VisualRecipe = {
  id: string;
  name: string;
  description: string;
  speakerMode: string;
  kind: "recipe";
  family: string;
  intents: string[];
  allowedLayouts: VisualSceneLayout[];
  contentCapacity: string;
  motionProfile: string;
  reusePolicy: string;
  previewAvailable?: boolean;
  motionPreviewAvailable?: boolean;
  creatorRating: number;
  lockedDefault: boolean;
  lockScopes: string[];
  usageCount: number;
};

export type VisualSceneLayout =
  | "full-screen-talking"
  | "talking-left"
  | "talking-right"
  | "talking-bottom-left"
  | "talking-top-left"
  | "talking-bottom-right"
  | "talking-top-right"
  | "computer-screen-only";

export type VisualTreatmentCandidate = {
  treatmentId: string;
  rank: number;
  family?: string;
  fitReason: string;
  limitations?: string;
  creatorRating?: number;
  lockedDefault?: boolean;
  previewAvailable?: boolean;
};

export type VisualTreatment = VisualCatalogModule | VisualRecipe;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = (await response.json()) as { detail?: string };
      detail = data.detail ?? detail;
    } catch {
      // Keep status text.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function openProject(path: string) {
  return request<EditorProjectResponse>("/api/projects/open", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export function openProjectDialog() {
  return request<EditorProjectResponse>("/api/projects/open-dialog", {
    method: "POST",
    body: "{}",
  });
}

export function getCurrentProject() {
  return request<EditorProjectResponse>("/api/projects/current");
}

export function chooseTranscriptVideo() {
  return request<{ source: string } & VideoProjectOpenResponse>("/api/projects/choose-video", {
    method: "POST",
    body: "{}",
  });
}

export function getCurrentVideoProject() {
  return request<VideoProjectResponse>("/api/video-project/current");
}

export function createVideoProject() {
  return request<VideoProjectOpenResponse>("/api/video-project/create-dialog", { method: "POST", body: "{}" });
}

export function openVideoProject() {
  return request<VideoProjectOpenResponse>("/api/video-project/open-dialog", { method: "POST", body: "{}" });
}

export function getVisualPlanPrompt() {
  return request<{ prompt: string }>("/api/video-project/visual-prompt");
}

export function addVideoProjectClips() {
  return request<VideoProjectOpenResponse>("/api/video-project/clips/add-dialog", { method: "POST", body: "{}" });
}

export function reorderVideoProjectClips(clipIds: string[]) {
  return request<VideoProjectOpenResponse>("/api/video-project/clips/reorder", {
    method: "POST",
    body: JSON.stringify({ clip_ids: clipIds }),
  });
}

export function removeVideoProjectClip(clipId: string) {
  return request<VideoProjectOpenResponse>(`/api/video-project/clips/${encodeURIComponent(clipId)}`, { method: "DELETE" });
}

export function transcribeProject(payload: TranscribeProjectRequest) {
  return request<EditorProjectResponse>("/api/projects/transcribe", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startTranscription(payload: TranscribeProjectRequest) {
  return request<TranscriptionJobResponse>("/api/projects/transcribe/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getTranscriptionJob(jobId: string) {
  return request<TranscriptionJobStatus>(`/api/projects/transcribe/jobs/${encodeURIComponent(jobId)}`);
}

export function deleteTokens(tokenIds: string[]) {
  return request<EditorProjectResponse>("/api/projects/current/delete", {
    method: "POST",
    body: JSON.stringify({ token_ids: tokenIds }),
  });
}

export function restoreTokens(tokenIds: string[]) {
  return request<EditorProjectResponse>("/api/projects/current/restore", {
    method: "POST",
    body: JSON.stringify({ token_ids: tokenIds }),
  });
}

export function deleteDeadSpace() {
  return request<EditorProjectResponse>("/api/projects/current/delete-dead-space", {
    method: "POST",
    body: "{}",
  });
}

export function updateEditorSettings(deadSpaceMinSeconds: number) {
  return request<EditorProjectResponse>("/api/projects/current/settings", {
    method: "POST",
    body: JSON.stringify({
      dead_space_min_seconds: deadSpaceMinSeconds,
    }),
  });
}

export function analyzeBoundaries() {
  return request<EditorProjectResponse>("/api/projects/current/analyze-boundaries", {
    method: "POST",
    body: "{}",
  });
}

export function analyzePauses() {
  return request<EditorProjectResponse>("/api/projects/current/analyze-pauses", {
    method: "POST",
    body: "{}",
  });
}

export function adjustSplice(anchorKey: string, leftDelta = 0, rightDelta = 0) {
  return request<EditorProjectResponse>("/api/projects/current/splices/adjust", {
    method: "POST",
    body: JSON.stringify({ anchor_key: anchorKey, left_delta: leftDelta, right_delta: rightDelta }),
  });
}

export function reviewSplice(anchorKey: string, reviewed: boolean) {
  return request<EditorProjectResponse>("/api/projects/current/splices/review", {
    method: "POST",
    body: JSON.stringify({ anchor_key: anchorKey, reviewed }),
  });
}

export type RenderedCutPreviewSplice = {
  id: string;
  anchor_key: string;
  preview_time_seconds: number;
  left_out_frame: number;
  right_in_frame: number;
  left_section: string;
  right_section: string;
};

export type RenderedCutPreviewResponse = {
  preview_id: string;
  duration_seconds: number;
  splices: RenderedCutPreviewSplice[];
  segments: Array<{
    source_start_frame: number;
    source_end_frame: number;
    preview_start_seconds: number;
    preview_end_seconds: number;
  }>;
};

export function renderCutPreview() {
  return request<RenderedCutPreviewResponse>("/api/projects/current/render-preview", {
    method: "POST",
    body: "{}",
  });
}

export function addManualCut(outFrame: number, inFrame: number) {
  return request<EditorProjectResponse>("/api/projects/current/manual-cuts", {
    method: "POST",
    body: JSON.stringify({ out_frame: outFrame, in_frame: inFrame }),
  });
}

export function adjustManualCut(cutId: string, outDelta = 0, inDelta = 0) {
  return request<EditorProjectResponse>("/api/projects/current/manual-cuts/adjust", {
    method: "POST",
    body: JSON.stringify({ cut_id: cutId, out_delta: outDelta, in_delta: inDelta }),
  });
}

export function removeManualCut(cutId: string) {
  return request<EditorProjectResponse>(`/api/projects/current/manual-cuts/${encodeURIComponent(cutId)}`, {
    method: "DELETE",
  });
}

export function setFinalOutFrame(frame: number | null) {
  return request<EditorProjectResponse>("/api/projects/current/final-out-frame", {
    method: "POST",
    body: JSON.stringify({ frame }),
  });
}

export function renderedCutPreviewUrl(previewId: string) {
  return `${API_BASE}/api/projects/current/render-preview/${encodeURIComponent(previewId)}`;
}

export function saveProject() {
  return request<{ saved: string }>("/api/projects/current/save", { method: "POST" });
}

export function getProjectDocument() {
  return request<ProjectDocumentResponse>("/api/projects/current/document");
}

export type ExportCutRequest = {
  normalize_audio?: boolean;
  normalization_preset_id?: string;
  target_i?: number;
  target_lra?: number;
  target_tp?: number;
};

export type ExportCutResponse = {
  output_path: string;
  cut_output_path: string;
  normalized: boolean;
};

export function exportCut(payload: ExportCutRequest = {}) {
  return request<ExportCutResponse>("/api/projects/current/export", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sourceVideoUrl() {
  return `${API_BASE}/api/projects/current/source-video`;
}

export function frameImageUrl(frame: number) {
  return `${API_BASE}/api/projects/current/frame?frame=${frame}`;
}

export function captionOptions() {
  return request<CaptionOptionsResponse>("/api/caption/options");
}

export function chooseCaptionVideo() {
  return request<{ source: string; output_folder: string }>("/api/caption/choose-video", {
    method: "POST",
    body: "{}",
  });
}

export function chooseCaptionOutputFolder() {
  return request<{ output_folder: string }>("/api/caption/choose-output-folder", {
    method: "POST",
    body: "{}",
  });
}

export function saveCaptionStyle(name: string, style: CaptionStylePayload) {
  return request<CaptionOptionsResponse>("/api/caption/styles", {
    method: "POST",
    body: JSON.stringify({ name, style }),
  });
}

export function deleteCaptionStyle(name: string) {
  return request<CaptionOptionsResponse>(`/api/caption/styles/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export function generateCaptionVideo(payload: CaptionGenerateRequest) {
  return request<{ output_path: string; progress: { value: number; message: string }[] }>("/api/caption/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function prepareCaptionPreview(payload: CaptionPreviewRequest) {
  return request<CaptionPreviewResponse>("/api/caption/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function captionSourceVideoUrl() {
  return `${API_BASE}/api/caption/source-video`;
}

export function audioOptions() {
  return request<AudioOptionsResponse>("/api/audio/options");
}

export function chooseAudioVideo() {
  return request<{ source: string; output_folder: string }>("/api/audio/choose-video", {
    method: "POST",
    body: "{}",
  });
}

export function chooseAudioOutputFolder() {
  return request<{ output_folder: string }>("/api/audio/choose-output-folder", {
    method: "POST",
    body: "{}",
  });
}

export function analyzeVideoAudio(payload: AudioSettingsPayload) {
  return request<AudioAnalysisResponse>("/api/audio/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function normalizeVideoAudio(payload: AudioSettingsPayload & { output_folder?: string | null }) {
  return request<{ output_path: string }>("/api/audio/normalize", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function audioSourceVideoUrl() {
  return `${API_BASE}/api/audio/source-video`;
}

export function generateAudioPreview(payload: AudioSettingsPayload & { start_seconds: number; duration_seconds: number }) {
  return request<AudioPreviewResponse>("/api/audio/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function audioPreviewUrl(previewId: string, mode: "original" | "corrected") {
  return `${API_BASE}/api/audio/preview/${encodeURIComponent(previewId)}/${mode}`;
}

export function getCurrentVisualProject() {
  return request<VisualProjectResponse>("/api/visual/current");
}

export function createVisualProject() {
  return request<VisualProjectResponse>("/api/visual/create-dialog", { method: "POST", body: "{}" });
}

export function ensureVisualProject() {
  return request<VisualProjectResponse>("/api/visual/ensure", { method: "POST", body: "{}" });
}

export function openVisualProject() {
  return request<VisualProjectResponse>("/api/visual/open-dialog", { method: "POST", body: "{}" });
}

export function saveVisualProject(plan: VisualPlan) {
  return request<VisualProjectResponse>("/api/visual/save", {
    method: "POST",
    body: JSON.stringify({ plan }),
  });
}

export function getVisualCatalog() {
  return request<{ layouts: VisualSceneLayout[]; modules: VisualCatalogModule[]; recipes: VisualRecipe[] }>("/api/visual/catalog");
}

export function visualRecipePreviewUrl(recipeId: string) {
  return `${API_BASE}/api/visual/catalog/recipes/${encodeURIComponent(recipeId)}/preview`;
}

export function visualTreatmentPreviewUrl(treatmentId: string) {
  return `${API_BASE}/api/visual/catalog/treatments/${encodeURIComponent(treatmentId)}/preview`;
}

export function visualTreatmentMotionPreviewUrl(treatmentId: string) {
  return `${API_BASE}/api/visual/catalog/treatments/${encodeURIComponent(treatmentId)}/motion-preview`;
}

export function visualSourceFrameUrl(timeSec: number) {
  return `${API_BASE}/api/visual/source-frame?time_sec=${encodeURIComponent(timeSec.toFixed(4))}`;
}

export function updateVisualTreatment(treatmentId: string, updates: Partial<VisualTreatment>) {
  return request<VisualTreatment>(`/api/visual/catalog/treatments/${encodeURIComponent(treatmentId)}`, {
    method: "PATCH",
    body: JSON.stringify({ updates }),
  });
}

export function getVisualReviewPrompt(reviewIds?: string[]) {
  return request<VisualProjectResponse & { prompt: string; noteCount: number }>("/api/visual/review-prompt", { method: "POST", body: JSON.stringify({ review_ids: reviewIds ?? null }) });
}

export function importVisualAsset() {
  return request<VisualProjectResponse>("/api/visual/assets/import-dialog", { method: "POST", body: "{}" });
}

export function visualSourceUrl() {
  return `${API_BASE}/api/visual/source`;
}

export function visualFinalVideoUrl(cacheKey?: string | null) {
  const suffix = cacheKey ? `?revision=${encodeURIComponent(cacheKey)}` : "";
  return `${API_BASE}/api/visual/final${suffix}`;
}

export function visualAssetUrl(assetId: string) {
  return `${API_BASE}/api/visual/assets/${encodeURIComponent(assetId)}`;
}

export function visualRuntimePlayerUrl() {
  return `${API_BASE}/api/visual/runtime/player.js`;
}

export function visualRuntimeCompositionUrl(cacheKey?: string | null) {
  const suffix = cacheKey ? `?revision=${encodeURIComponent(cacheKey)}` : "";
  return `${API_BASE}/api/visual/runtime/composition/index.html${suffix}`;
}

export function approveVisualRepresentative(cueId: string) {
  return request<VisualProjectResponse>("/api/visual/gates/representative", { method: "POST", body: JSON.stringify({ cue_id: cueId }) });
}

export function approveVisualFullReview() {
  return request<VisualProjectResponse>("/api/visual/gates/full-review", { method: "POST", body: "{}" });
}

export function verifyVisualDeliveryReopened(revisionNumber: number, planHash: string) {
  return request<VisualProjectResponse>("/api/visual/gates/reopen", { method: "POST", body: JSON.stringify({ revision_number: revisionNumber, plan_hash: planHash }) });
}

export function startVisualRender(payload: { start_sec?: number | null; end_sec?: number | null; quality?: "draft" | "standard" | "high"; purpose?: "range" | "review" | "final" }) {
  return request<{ job_id: string; reused: boolean }>("/api/visual/render", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getVisualRenderJob(jobId: string) {
  return request<VisualRenderJob>(`/api/visual/render/jobs/${encodeURIComponent(jobId)}`);
}

export function getActiveVisualRenderJob() {
  return request<{ job: VisualRenderJob | null }>("/api/visual/render/active");
}

export function visualRenderVideoUrl(jobId: string) {
  return `${API_BASE}/api/visual/render/jobs/${encodeURIComponent(jobId)}/video`;
}

export function getCreatorLibrary(query = "") {
  return request<{ root: string; assets: CreatorAsset[] }>(`/api/creator-library?query=${encodeURIComponent(query)}`);
}

export function importCreatorAsset() {
  return request<{ asset: CreatorAsset; duplicate: boolean; assets: CreatorAsset[] }>("/api/creator-library/import-dialog", { method: "POST", body: "{}" });
}

export function creatorAssetMediaUrl(assetId: string) {
  return `${API_BASE}/api/creator-library/${encodeURIComponent(assetId)}/media`;
}

export function updateCreatorAsset(assetId: string, updates: Partial<CreatorAsset>) {
  return request<{ asset: CreatorAsset; assets: CreatorAsset[] }>(`/api/creator-library/${encodeURIComponent(assetId)}`, { method: "PATCH", body: JSON.stringify({ updates }) });
}

export function useCreatorAsset(assetId: string, startSec: number, endSec: number) {
  return request<VisualProjectResponse>(`/api/creator-library/${encodeURIComponent(assetId)}/use`, { method: "POST", body: JSON.stringify({ start_sec: startSec, end_sec: endSec }) });
}

export function getVisualSuggestions() {
  return request<{ schemaVersion: number; coverage?: VisualSuggestionCoverage; suggestions: VisualSuggestion[] }>("/api/visual/suggestions");
}

export function updateVisualSuggestion(suggestionId: string, updates: Partial<VisualSuggestion>) {
  return request<VisualSuggestion>(`/api/visual/suggestions/${encodeURIComponent(suggestionId)}`, { method: "PATCH", body: JSON.stringify({ updates }) });
}

export function decideVisualSuggestion(suggestionId: string, action: "approve" | "reject" | "request-another" | "approve-series", notes = "") {
  return request<VisualProjectResponse & { suggestion: VisualSuggestion; suggestions: VisualSuggestion[]; coverage?: VisualSuggestionCoverage }>(
    `/api/visual/suggestions/${encodeURIComponent(suggestionId)}/decision`,
    { method: "POST", body: JSON.stringify({ action, notes }) },
  );
}

export function prepareVisualSuggestionEvidence(suggestionId: string) {
  return request<{ suggestion: VisualSuggestion; suggestions: VisualSuggestion[]; coverage?: VisualSuggestionCoverage }>(
    `/api/visual/suggestions/${encodeURIComponent(suggestionId)}/approval-evidence/prepare`,
    { method: "POST", body: "{}" },
  );
}

export function visualSuggestionApprovalFrameUrl(suggestionId: string) {
  return `${API_BASE}/api/visual/suggestions/${encodeURIComponent(suggestionId)}/approval-frame`;
}

export function createRecipeSuggestion(recipeId: string, startSec: number, endSec: number) {
  return request<VisualSuggestion>("/api/visual/suggestions/recipe", {
    method: "POST",
    body: JSON.stringify({ recipe_id: recipeId, start_sec: startSec, end_sec: endSec }),
  });
}

export function buildVisualSuggestion(suggestionId: string) {
  return request<VisualProjectResponse>(`/api/visual/suggestions/${encodeURIComponent(suggestionId)}/build`, { method: "POST", body: "{}" });
}

export function getPexelsSettings() {
  return request<{ configured: boolean; source: string }>("/api/visual/pexels/settings");
}

export function savePexelsKey(apiKey: string) {
  return request<{ configured: boolean; source: string }>("/api/visual/pexels/settings", { method: "POST", body: JSON.stringify({ api_key: apiKey }) });
}

export function searchSuggestionStock(suggestionId: string) {
  return request<{ suggestionId: string; candidates: StockCandidate[] }>(`/api/visual/suggestions/${encodeURIComponent(suggestionId)}/pexels/search`, { method: "POST", body: "{}" });
}

export function selectSuggestionStock(suggestionId: string, candidate: StockCandidate) {
  return request<VisualProjectResponse & { credits?: string }>(`/api/visual/suggestions/${encodeURIComponent(suggestionId)}/pexels/select`, { method: "POST", body: JSON.stringify({ candidate }) });
}

export function getVisualCredits() {
  return request<{ credits: string }>("/api/visual/credits");
}
