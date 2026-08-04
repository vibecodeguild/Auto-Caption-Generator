export const API_BASE = process.env.NEXT_PUBLIC_VCG_API_BASE ?? "http://127.0.0.1:8731";

export type CreatorProductionCurrent = {
  initialized: boolean;
  reason?: string;
  recoveryAction?: string;
  workflowId?: string;
  episodeId?: string;
  state?: string;
  currentHash?: string;
  capabilitySummary?: Record<string, number>;
  reviewStale?: boolean;
  workflowUpgradeRequired?: boolean;
  workflowUpgradeReason?: string | null;
  artifactAvailability?: Record<string, boolean>;
  authority?: {
    productionOwnsRouting: boolean;
    nativeWorkflowDiscoveryPerformed: boolean;
    lockedTranscriptIsTimingAuthority: boolean;
    durationTargetsEnabled: boolean;
  };
};

export type CreatorProductionJob = {
  id: string;
  taskKind: "analyze" | "plan" | "classify-layouts" | "adapt" | "materialize" | "revise";
  status: "queued" | "running" | "canceling" | "completed" | "failed" | "canceled" | "interrupted";
  stage: string;
  error: string | null;
  createdAt: string;
  updatedAt: string;
  outputArtifactRef: Record<string, unknown> | null;
  handoffPrompt?: string;
  handoffPacketRef?: {
    path: string;
    sha256: string;
    packetHash: string;
  } | null;
};

export type CreatorCapability = {
  id: string;
  category: string;
  scope: string;
  sourceAvailability: string;
  implementationMaturity: string;
  technicalAdmission: string;
  productionSelection: string;
  statusReason?: string;
};

export type CreatorCapabilityCatalog = {
  inventorySummary: Record<string, number>;
  capabilities: CreatorCapability[];
};

export type CreatorPipelineSequence = {
  id: string;
  chapterId: string;
  absoluteStartFrame: number;
  absoluteEndFrameExclusive: number;
  editorialJob: string;
  semanticForm: string;
  presentationRole: string;
  candidates: Array<{
    capabilityId: string;
    sourceResourceIds: string[];
    implementationMaturity: string;
    technicalAdmission: string;
    projectAdmissions: Array<Record<string, unknown>>;
  }>;
  decision?: {
    disposition: string;
    selectedCapabilityId: string | null;
    topRankedCapabilityId: string | null;
  };
};

export type CreatorProductionPipeline = {
  fps?: { numerator: number; denominator: number };
  sequences: CreatorPipelineSequence[];
  adaptationDebt: CreatorPipelineSequence[];
  sourceEvidenceStatus: "not-ready" | "agent-classification-required" | "layout-classification-blocked" | "complete";
};

export type CreatorRenderJob = {
  id: string;
  status: "queued" | "running" | "canceling" | "completed" | "failed" | "canceled" | "interrupted";
  stage: string;
  value: number;
  message: string;
  buildHash: string;
  error: string | null;
  chapterStates: Array<{ chapterId: string; cacheStatus: string; status: string }>;
};

export type CreatorReviewNote = {
  id: string;
  buildHash: string;
  sequenceId: string;
  elementId: string | null;
  wordId: string | null;
  absoluteFrame: number;
  note: string;
  status: "changes-requested" | "ready-for-review";
  saveStatus: "saved" | "saving" | "failed" | "stale";
};

export type CreatorReview = {
  revision: number;
  buildHash: string;
  activeNotes: CreatorReviewNote[];
  noteHistory: CreatorReviewNote[];
  approvalRecords: Array<Record<string, unknown>>;
  autosave: { status: string; failureReason: string | null; updatedAt: string };
};

export type CreatorReviewSequence = {
  id: string;
  chapterId: string;
  absoluteStartFrame: number;
  absoluteEndFrameExclusive: number;
  startWordId: string | null;
  endWordId: string | null;
  editorialJob: string;
  semanticForm: string;
  presentationRole: string;
  selectedCanvasTopology: string;
  compositionGraph: {
    elements: Array<{
      id: string;
      kind: string;
      geometry: { x: number; y: number; width: number; height: number };
      properties: Record<string, unknown>;
      tokenBindings: Record<string, unknown>;
    }>;
    events: Array<{
      id: string;
      targetElementId: string;
      absoluteFrame: number;
      operation: string;
      parameters: Record<string, unknown>;
    }>;
  };
};

export type CreatorReviewContext = {
  review: CreatorReview;
  build: Record<string, unknown>;
  manifest: {
    revision: number;
    sequences: CreatorReviewSequence[];
  };
  preflight: {
    passed: boolean;
    findings: Array<{
      severity: string;
      gate: string;
      sequenceId?: string;
      elementId?: string;
      absoluteFrame?: number;
    }>;
  } | null;
};

export type CreatorEvidenceDraft = {
  schemaVersion: number;
  episodeId: string;
  availableLayoutIds: string[];
  classificationMethod: "agent-frame-classification";
  sequences: Array<{
    sequenceId: string;
    absoluteStartFrame: number;
    absoluteEndFrameExclusive: number;
  }>;
};

export function listCreatorChannelProfiles() {
  return request<{
    profiles: Array<{
      id: string;
      version: number;
      referenceGrammarRef: string;
      fileName: string;
    }>;
  }>("/api/creator-production/channel-profiles");
}

export function initializeCreatorProduction(channelProfileId: string) {
  return request<CreatorProductionCurrent>("/api/creator-production/initialize", {
    method: "POST",
    body: JSON.stringify({ channel_profile_id: channelProfileId }),
  });
}

export function getCreatorProductionCurrent() {
  return request<CreatorProductionCurrent>("/api/creator-production/current");
}

export function upgradeCreatorProductionWorkflow(actor: string, reason: string) {
  return request<CreatorProductionCurrent>("/api/creator-production/workflow-upgrade", {
    method: "POST",
    body: JSON.stringify({ actor, reason }),
  });
}

export function getCreatorCapabilities() {
  return request<CreatorCapabilityCatalog>("/api/creator-production/capabilities");
}

export function getCreatorProductionPipeline() {
  return request<CreatorProductionPipeline>("/api/creator-production/pipeline");
}

export function listCreatorProductionJobs() {
  return request<{ jobs: CreatorProductionJob[]; recoveredJobIds: string[] }>(
    "/api/creator-production/jobs",
  );
}

export function createCreatorProductionJob(
  taskKind: CreatorProductionJob["taskKind"],
  inputArtifactKeys: string[],
  requestedResourceIds: string[] = [],
  taskParameters: Record<string, unknown> = {},
) {
  return request<CreatorProductionJob>("/api/creator-production/jobs", {
    method: "POST",
    body: JSON.stringify({
      task_kind: taskKind,
      input_artifact_keys: inputArtifactKeys,
      requested_resource_ids: requestedResourceIds,
      task_parameters: taskParameters,
    }),
  });
}

export function getCreatorProductionHandoff(jobId: string) {
  return request<{
    job: CreatorProductionJob;
    packet: Record<string, unknown>;
    handoffPrompt: string;
  }>(`/api/creator-production/jobs/${jobId}/handoff`);
}

export function cancelCreatorProductionJob(jobId: string) {
  return request<CreatorProductionJob>(`/api/creator-production/jobs/${jobId}/cancel`, {
    method: "POST",
    body: "{}",
  });
}

export function listCreatorRenderJobs() {
  return request<{ jobs: CreatorRenderJob[]; recoveredJobIds: string[] }>(
    "/api/creator-production/render-jobs",
  );
}

export function createCreatorRenderJob() {
  return request<CreatorRenderJob>("/api/creator-production/render-jobs", {
    method: "POST",
    body: "{}",
  });
}

export function startCreatorRenderJob(jobId: string) {
  return request<CreatorRenderJob>(`/api/creator-production/render-jobs/${jobId}/start`, {
    method: "POST",
    body: "{}",
  });
}

export function cancelCreatorRenderJob(jobId: string) {
  return request<CreatorRenderJob>(`/api/creator-production/render-jobs/${jobId}/cancel`, {
    method: "POST",
    body: "{}",
  });
}

export function getCreatorReview() {
  return request<CreatorReviewContext>(
    "/api/creator-production/review",
  );
}

export function saveCreatorReviewNote(note: {
  id: string;
  sequence_id: string;
  element_id: string | null;
  word_id: string | null;
  absolute_frame: number;
  note: string;
}) {
  return request<{ review: CreatorReview }>("/api/creator-production/review/notes", {
    method: "POST",
    body: JSON.stringify(note),
  });
}

export function acceptCreatorReviewNote(noteId: string) {
  return request<{ review: CreatorReview }>(
    `/api/creator-production/review/notes/${noteId}/accept`,
    { method: "POST", body: "{}" },
  );
}

export function approveCreatorReview() {
  return request<{ review: CreatorReview; delivery: { reusedExactReviewBytes: boolean } }>(
    "/api/creator-production/review/approve",
    { method: "POST", body: "{}" },
  );
}

export function creatorReviewVideoUrl() {
  return `${API_BASE}/api/creator-production/review-video`;
}

export function getCreatorSourceEvidence() {
  return request<{
    status: "complete" | "agent-classification-required";
    draft?: CreatorEvidenceDraft;
    ledger?: Record<string, unknown>;
  }>("/api/creator-production/source-evidence");
}

export function saveCreatorSourceEvidence(ledger: Record<string, unknown>) {
  return request<{ status: "complete" }>("/api/creator-production/source-evidence", {
    method: "POST",
    body: JSON.stringify({ ledger }),
  });
}

export function creatorSourceFrameUrl(timeSeconds: number) {
  return `${API_BASE}/api/visual/source-frame?time_sec=${encodeURIComponent(timeSeconds.toFixed(6))}`;
}

export function createCreatorStudioHandoff(input: {
  sequence_id: string;
  element_id: string | null;
  absolute_frame: number;
}) {
  return request<Record<string, unknown>>("/api/creator-production/studio/handoff", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function applyCreatorStudioEdits(
  handoff: Record<string, unknown>,
  edits: Array<Record<string, unknown>>,
) {
  return request<{
    manifestRef: Record<string, unknown>;
    buildLockRef: Record<string, unknown>;
    receiptRef: Record<string, unknown>;
    overrideRef: Record<string, unknown>;
  }>("/api/creator-production/studio/edits", {
    method: "POST",
    body: JSON.stringify({ handoff, edits }),
  });
}

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
  /** Set when visual-plan.json exists but cannot load (e.g. retired module ids). */
  visualPlanWarning?: string | null;
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
  moduleId?: "punchline-reveal" | "speaker-side-panel" | "progress-scale" | "dependency-stack";
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

export type MasterbeaterBeat = {
  id: string;
  beatType: string;
  /** Editorial label or paraphrase (optional). */
  span?: string;
  label?: string;
  rationale: string;
  /** Exact transcript words for the beat. */
  wordsText?: string;
  startWordId?: string;
  endWordId?: string;
  wordIds?: string[];
  /** Canonical timing for later graphic work. */
  startFrame?: number;
  endFrame?: number;
  endFrameExclusive?: number;
  /** Informational only. */
  startSec?: number;
  endSec?: number;
};

export type MasterbeaterEditOp =
  | "removeWord"
  | "removeWordRange"
  | "addWordPrev"
  | "addWordNext"
  | "changeBeatType"
  | "deleteBeat"
  | "addBeat"
  | "mergeBeats"
  | "splitBeat"
  | "membershipChange"
  | string;

export type MasterbeaterEditEvent = {
  op: MasterbeaterEditOp;
  beatId?: string;
  wordId?: string;
  wordText?: string;
  side?: "prev" | "next";
  detail?: string;
};

export type MasterbeaterLedgerEntry = {
  id?: string;
  at?: string;
  op?: string;
  beatId?: string | null;
  wordId?: string | null;
  wordText?: string | null;
  side?: string | null;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  beatCountBefore?: number;
  beatCountAfter?: number;
  detail?: string;
};

export type MasterbeaterResult = {
  agent?: string;
  schemaVersion?: number;
  mode?: string;
  modeInferred?: boolean;
  timingAuthority?: string;
  fps?: number;
  beatCount?: number;
  beats?: MasterbeaterBeat[];
  gaps?: string[];
  notes?: string;
  outputPath?: string;
  originalPath?: string;
  ledgerPath?: string;
  ledgerEntry?: MasterbeaterLedgerEntry;
  ledgerEntryCount?: number;
  originalFile?: string;
  originalBeatCount?: number;
  basedOnOriginal?: boolean;
  edited?: boolean;
  role?: string;
  ok?: boolean;
  source?: {
    projectRoot?: string;
    transcript?: string;
    approxDurationSec?: number;
    wordCount?: number;
  };
};

/** Compact word row for Visual Package Stage 1 (not the editor TranscriptWord). */
export type VisualPackageTranscriptWord = {
  id: string;
  text: string;
  startFrame?: number;
  endFrame?: number;
  startSec?: number;
  endSec?: number;
};

export type ScenelayerPick = {
  beatId: string;
  layoutId?: string | null;
  source?: "algorithm" | "human" | string;
};

export type ScenelayerResult = {
  ok?: boolean;
  firstRun?: boolean;
  agent?: string;
  schemaVersion?: number;
  role?: string;
  beatCount?: number;
  labeledCount?: number;
  unlabeledCount?: number;
  beats?: ScenelayerPick[];
  originalPath?: string;
  reviewedPath?: string;
  ledgerPath?: string;
  ledgerEntry?: Record<string, unknown>;
  ledgerEntryCount?: number;
  layoutIds?: string[];
  edited?: boolean;
  result?: ScenelayerResult;
};

export type ScenelayerStatus = {
  ok?: boolean;
  originalPath?: string;
  originalExists?: boolean;
  reviewedPath?: string;
  reviewedExists?: boolean;
  ledgerPath?: string;
  ledgerExists?: boolean;
  ledgerEntryCount?: number;
  beatCount?: number;
  labeledCount?: number;
  unlabeledCount?: number;
  result?: ScenelayerResult | null;
  byBeatId?: Record<string, ScenelayerPick>;
  /** First algorithm labels (immutable original file). */
  originalByBeatId?: Record<string, ScenelayerPick>;
  layoutIds?: string[];
};

export type AssignmentPick = {
  beatId: string;
  usageId?: string | null;
  source?: "algorithm" | "human" | string;
  layoutId?: string | null;
  displayName?: string | null;
  posterUrl?: string | null;
  hasPoster?: boolean;
  engineId?: string | null;
  missingUsage?: boolean;
};

export type AssignmentEligibleUsage = {
  id: string;
  displayName?: string;
  posterUrl?: string | null;
  hasPoster?: boolean;
  engineId?: string;
};

export type AssignmentResult = {
  agent?: string;
  schemaVersion?: number;
  role?: string;
  beatCount?: number;
  assignedCount?: number;
  unassignedCount?: number;
  beats?: AssignmentPick[];
  ok?: boolean;
  firstRun?: boolean;
  originalPath?: string;
  reviewedPath?: string;
  ledgerPath?: string;
  ledgerEntry?: Record<string, unknown>;
  ledgerEntryCount?: number;
  goldenUsageCount?: number;
  edited?: boolean;
};

export type AssignmentStatus = {
  ok?: boolean;
  originalPath?: string;
  originalExists?: boolean;
  reviewedPath?: string;
  reviewedExists?: boolean;
  ledgerPath?: string;
  ledgerExists?: boolean;
  ledgerEntryCount?: number;
  goldenUsageCount?: number;
  beatCount?: number;
  assignedCount?: number;
  unassignedCount?: number;
  result?: AssignmentResult | null;
  byBeatId?: Record<string, AssignmentPick>;
  eligibleByBeatType?: Record<string, AssignmentEligibleUsage[]>;
  usages?: Record<
    string,
    {
      id: string;
      displayName?: string | null;
      posterUrl?: string | null;
      hasPoster?: boolean;
      beatTypes?: string[];
      allowedLayouts?: string[];
      engineId?: string;
    }
  >;
  layoutByBeatId?: Record<string, string | null>;
};

export type VisualPackageStatus = {
  ok: boolean;
  projectRoot: string;
  transcriptPath: string;
  transcriptExists: boolean;
  /** Ordered final-transcript words for inline Stage 1 review. */
  transcriptWords?: VisualPackageTranscriptWord[];
  transcriptWordCount?: number;
  /** Original agent suggestion path (immutable from UI). */
  outputPath: string;
  outputExists: boolean;
  reviewedPath?: string;
  reviewedExists?: boolean;
  ledgerPath?: string;
  ledgerExists?: boolean;
  ledgerEntryCount?: number;
  beatCount: number;
  originalBeatCount?: number;
  /** Working set (reviewed if present, else original). */
  result: MasterbeaterResult | null;
  original?: MasterbeaterResult | null;
  reviewed?: MasterbeaterResult | null;
  reviewVideoPath?: string;
  reviewVideoExists?: boolean;
  reviewVideoKind?: string;
  fps?: number;
  /** Stage 2 scenelayer (layout labels). */
  scenelayer?: ScenelayerStatus;
  /** Stage 2 assignment slice. */
  assignment?: AssignmentStatus;
  /** Stage 3 placement. */
  placement?: PlacementStatus;
};

export type PlacementLine = {
  slot: string;
  text: string;
  revealFrame: number;
};

export type PlacementBeat = {
  beatId: string;
  usageId?: string | null;
  engineId?: string;
  locked?: boolean;
  startFrame?: number;
  endFrameExclusive?: number;
  lines?: PlacementLine[];
  meta?: Record<string, unknown>;
  assets?: Record<string, unknown>;
  motion?: Record<string, unknown>;
  source?: string;
  displayName?: string;
  beatType?: string;
  wordsText?: string;
};

export type PlacementEngineInterface = {
  engineId: string;
  fixedLineSlots?: string[];
  listSlot?: string | null;
  listMin?: number;
  listMax?: number;
  metaKeys?: string[];
  assetKeys?: string[];
  motionKeys?: string[];
  notes?: string;
  kicker?: boolean;
  error?: string;
};

export type PlacementResult = {
  ok?: boolean;
  firstRun?: boolean;
  placementCount?: number;
  lockedCount?: number;
  unlockedCount?: number;
  allLocked?: boolean;
  finalRenderReady?: boolean;
  beats?: PlacementBeat[];
  result?: PlacementResult;
  engineInterfaces?: Record<string, PlacementEngineInterface>;
  placement?: PlacementBeat;
  engineParameters?: Record<string, unknown>;
  ledgerEntryCount?: number;
};

export type PlacementStatus = {
  ok?: boolean;
  originalExists?: boolean;
  reviewedExists?: boolean;
  placementCount?: number;
  lockedCount?: number;
  unlockedCount?: number;
  allLocked?: boolean;
  finalRenderReady?: boolean;
  ledgerEntryCount?: number;
  result?: { beats?: PlacementBeat[] } | null;
  byBeatId?: Record<string, PlacementBeat>;
  engineInterfaces?: Record<string, PlacementEngineInterface>;
};

export function getVisualPackageStatus() {
  return request<VisualPackageStatus>("/api/visual-package/status");
}

export function runMasterbeater() {
  return request<MasterbeaterResult>("/api/visual-package/masterbeater/run", {
    method: "POST",
    body: "{}",
  });
}

/**
 * Auto-save Stage 1 word-bound edits to the reviewed working copy.
 * Original masterbeater-beats.json is never overwritten. Optional `edit` is
 * appended to masterbeater-edit-ledger.json for process refinement.
 */
export function saveMasterbeaterBeats(payload: {
  beats: MasterbeaterBeat[];
  mode?: string;
  gaps?: string[];
  edit?: MasterbeaterEditEvent;
}) {
  return request<MasterbeaterResult>("/api/visual-package/masterbeater/beats", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/** Stage 2: label each beat layout from first frame (before Assign). */
export function runScenelayer() {
  return request<ScenelayerResult>("/api/visual-package/scenelayer/run", {
    method: "POST",
    body: "{}",
  });
}

/** Human override of one beat's OBS layout. */
export function saveScenelayerOverride(payload: {
  beatId: string;
  layoutId: string | null;
  detail?: string;
}) {
  return request<ScenelayerResult>("/api/visual-package/scenelayer/override", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/** Stage 2: deal golden usages onto working Masterbeater beats. */
export function runAssignment() {
  return request<AssignmentResult>("/api/visual-package/assignment/run", {
    method: "POST",
    body: "{}",
  });
}

/** Stage 3: draft placements for assigned beats (skips locked on re-run). */
export function runPlacement() {
  return request<PlacementResult>("/api/visual-package/placement/run", {
    method: "POST",
    body: "{}",
  });
}

/** Native image picker → copies into the project's placement image store. */
export function importPlacementImageDialog() {
  return request<{ assetId: string; fileName: string; sourceName: string }>(
    "/api/visual-package/placement/import-image-dialog",
    { method: "POST", body: "{}" },
  );
}

/** Save one beat placement (lines / lock / meta). */
export function savePlacementBeat(payload: {
  beatId: string;
  lines?: PlacementLine[];
  meta?: Record<string, unknown>;
  assets?: Record<string, unknown>;
  motion?: Record<string, unknown>;
  startFrame?: number;
  endFrameExclusive?: number;
  locked?: boolean;
  detail?: string;
}) {
  return request<PlacementResult>("/api/visual-package/placement/beat", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/** Live Tier B HyperFrames composition for one placement beat (no FFmpeg encode). */
export type PlacementPreview = {
  ok?: boolean;
  available?: boolean;
  reused?: boolean;
  beatId?: string;
  engineId?: string;
  cacheKey?: string;
  durationSec?: number;
  startFrame?: number;
  /** Full speech-beat end (preview window). */
  endFrameExclusive?: number;
  /** When the graphic undocks; may be earlier than endFrameExclusive. */
  graphicEndFrameExclusive?: number;
  startSec?: number;
  endSec?: number;
  graphicEndSec?: number;
  rangeStartSec?: number;
  rangeEndSec?: number;
  fps?: number;
  width?: number;
  height?: number;
  compositionUrl?: string;
};

export function buildPlacementPreview(payload: {
  beatId: string;
  lines?: PlacementLine[];
  meta?: Record<string, unknown>;
  assets?: Record<string, unknown>;
  motion?: Record<string, unknown>;
  startFrame?: number;
  endFrameExclusive?: number;
  force?: boolean;
}) {
  return request<PlacementPreview>("/api/visual-package/placement/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function placementPreviewCompositionUrl(cacheKey?: string | null) {
  const suffix = cacheKey ? `?revision=${encodeURIComponent(cacheKey)}` : "";
  return `${API_BASE}/api/visual-package/placement/preview/composition/index.html${suffix}`;
}

/**
 * Trimmed beat audio/video source for the Stage 3 studio's app-owned audio element.
 * The preview composition itself has no <audio> (the HyperFrames transport clock can
 * freeze on in-composition audio); speech playback is the app's job.
 */
export function placementPreviewSourceUrl(cacheKey?: string | null) {
  const suffix = cacheKey ? `?revision=${encodeURIComponent(cacheKey)}` : "";
  return `${API_BASE}/api/visual-package/placement/preview/composition/source.mp4${suffix}`;
}

/**
 * Human override of one beat's usage. Original assignment.json is never
 * overwritten; working copy + ledger update only.
 */
export function saveAssignmentOverride(payload: {
  beatId: string;
  usageId: string | null;
  detail?: string;
}) {
  return request<AssignmentResult>("/api/visual-package/assignment/override", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/** Resolve Graphics Library media path (API-relative) to a full URL. */
export function assignmentPosterUrl(posterUrl: string | null | undefined): string | null {
  if (!posterUrl) return null;
  if (posterUrl.startsWith("http://") || posterUrl.startsWith("https://")) return posterUrl;
  return `${API_BASE}${posterUrl.startsWith("/") ? "" : "/"}${posterUrl}`;
}

export function visualPackageSourceVideoUrl() {
  return `${API_BASE}/api/visual-package/source-video`;
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

export type UsageStatus = "candidate" | "golden";

export const GRAPHICS_LIBRARY_LAYOUT_IDS = [
  "full-screen-talking",
  "talking-left",
  "talking-right",
  "talking-bottom-left",
  "talking-bottom-right",
  "talking-top-left",
  "talking-top-right",
  "computer-screen-only",
] as const;

export type GraphicsLibraryLayoutId = (typeof GRAPHICS_LIBRARY_LAYOUT_IDS)[number];

/** Closed VCG beat universe — same ids as Masterbeater / beat-universe.md */
export const GRAPHICS_LIBRARY_BEAT_TYPES = [
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

export type GraphicsLibraryBeatType = (typeof GRAPHICS_LIBRARY_BEAT_TYPES)[number];

/**
 * Short job descriptions from the approved VCG beat universe
 * (docs/vcg-graphics-process/beat-universe.md). Used in Graphics Library help UI.
 */
export const GRAPHICS_LIBRARY_BEAT_TYPE_GUIDE: Record<
  GraphicsLibraryBeatType,
  { job: string; howToSpot: string }
> = {
  aftershock: {
    job: "Immediate secondary punches after the main punchline.",
    howToSpot: "Rapid follow-ups on the same bit, no new premise, right after the main land.",
  },
  callback: {
    job: "Return to earlier material later.",
    howToSpot: "Explicit reference to an earlier joke, proof, hook, or line.",
  },
  context: {
    job: "Background, definition, or stakes — with no open loop.",
    howToSpot: "Why it matters / what it is, without teasing unfinished payoff.",
  },
  cta: {
    job: "Drive a specific viewer action or destination.",
    howToSpot: "Subscribe, follow, link, next video, community.",
  },
  example: {
    job: "Numbered or named worked case.",
    howToSpot: "“Example 1…”, “First way…”, concrete case intro.",
  },
  hook: {
    job: "Open a curiosity gap the viewer must keep watching to close.",
    howToSpot: "Bold promise, question, or mid-video open loop without full payoff yet.",
  },
  list: {
    job: "Multi-item sequence meant as sequential visual rows.",
    howToSpot: "“Three things…”, numbered items that each deserve a moment.",
  },
  proof: {
    job: "Hard fact, metric, or credential hit.",
    howToSpot: "Dollars, percentages, ranks, time saved, named result.",
  },
  prompt: {
    job: "AI prompt, command, or short code gist.",
    howToSpot: "“Use this prompt…”, recited syntax, command language.",
  },
  punchline: {
    job: "Main land / reinterpretation that pays off now.",
    howToSpot: "Joke payoff or sharp thesis that resolves the setup.",
  },
  setup: {
    job: "Baseline assumption before a twist.",
    howToSpot: "“Normal world,” wrong expectation, calm premise before the land.",
  },
  structure: {
    job: "System view: process, stack, pathway, or tradeoff.",
    howToSpot: "Pipeline, X vs Y, ordered model — not a flat tip list.",
  },
  ui: {
    job: "Point at on-screen software.",
    howToSpot: "“Click here…”, “this panel…”, named UI during screen share.",
  },
};

/** Beat type ids sorted A→Z for UI lists and help. */
export function graphicsLibraryBeatTypesAlphabetical(): GraphicsLibraryBeatType[] {
  return [...GRAPHICS_LIBRARY_BEAT_TYPES].sort((a, b) => a.localeCompare(b));
}

/** Graphics Library usage (when/where contract). Has-a engineId. */
export type GraphicsLibraryUsage = {
  id: string;
  displayName: string;
  status: UsageStatus;
  engineId: string;
  engineInterface?: string[];
  allowedLayouts?: string[];
  beatTypes?: GraphicsLibraryBeatType[] | string[];
  sample?: {
    relativePath?: string | null;
    posterRelativePath?: string | null;
    durationSec?: number | null;
    hasAudio?: boolean;
    source?: string;
    layoutId?: string | null;
    renderedAt?: string | null;
  } | null;
  createdAt: string;
  updatedAt: string;
  hasSample?: boolean;
  hasPoster?: boolean;
  sampleUrl?: string | null;
  posterUrl?: string | null;
};

export type GraphicsLibraryProductionSet = {
  root: string;
  exists: boolean;
  policy: string;
  allowedStatuses: string[];
  usages: Array<{
    id: string;
    displayName: string;
    status: UsageStatus;
    engineId: string;
    allowedLayouts: string[];
    beatTypes: string[];
  }>;
  ids: string[];
  count: number;
  empty: boolean;
  emptyReason?: string | null;
  message: string;
};

export type GraphicsLibrarySummary = {
  root: string;
  exists: boolean;
  rootLabel?: string;
  updatedAt?: string;
  entryCount: number;
  statusCounts: Record<string, number>;
  withSample: number;
  settings?: Record<string, unknown>;
  layoutClips?: {
    root: string;
    present: string[];
    missing: string[];
    complete: boolean;
    clips: Array<{
      layoutId: string;
      relativePath: string;
      present: boolean;
      path?: string;
      bytes?: number;
    }>;
  };
  productionSet?: {
    policy: string;
    count: number;
    ids: string[];
    empty: boolean;
    emptyReason?: string | null;
    message: string;
  };
  entries: GraphicsLibraryUsage[];
  ensureReport?: { created: number; total: number; root: string };
  importReport?: { imported: number; skippedUnbuildable: number; total: number; root: string };
};

const GRAPHICS_LIBRARY_API = "/api/graphics-library";

export function getGraphicsLibrary() {
  return request<GraphicsLibrarySummary>(GRAPHICS_LIBRARY_API);
}

export type GraphicsLibraryMetricBucket = {
  total: number;
  golden: number;
  candidate: number;
};

export type GraphicsLibraryMetricRow = GraphicsLibraryMetricBucket & {
  id: string;
};

export type GraphicsLibraryMatrixCell = GraphicsLibraryMetricBucket & {
  layoutId: string;
};

export type GraphicsLibraryMatrixRow = {
  beatType: string;
  cells: GraphicsLibraryMatrixCell[];
};

export type GraphicsLibraryMetrics = {
  root: string;
  exists: boolean;
  entryCount: number;
  byBeatType: GraphicsLibraryMetricRow[];
  byLayout: GraphicsLibraryMetricRow[];
  untaggedBeatTypes: GraphicsLibraryMetricBucket;
  untaggedLayouts: GraphicsLibraryMetricBucket;
  /** Beat type × layout cross-tab — a zero cell is an Assignment coverage gap. */
  matrix?: { layouts: string[]; rows: GraphicsLibraryMatrixRow[] };
};

export function getGraphicsLibraryMetrics() {
  return request<GraphicsLibraryMetrics>(`${GRAPHICS_LIBRARY_API}/metrics`);
}

export function getGraphicsLibraryProductionSet(policy: "golden-only" = "golden-only") {
  return request<GraphicsLibraryProductionSet>(
    `${GRAPHICS_LIBRARY_API}/production-set?policy=${encodeURIComponent(policy)}`,
  );
}

export function createGraphicsLibrary() {
  return request<GraphicsLibrarySummary>(`${GRAPHICS_LIBRARY_API}/create`, { method: "POST", body: "{}" });
}

export function openGraphicsLibraryDialog() {
  return request<GraphicsLibrarySummary>(`${GRAPHICS_LIBRARY_API}/open-dialog`, { method: "POST", body: "{}" });
}

/** Ensure candidate usage rows exist for each known engine (never auto-golden). */
export function ensureGraphicsLibraryEngineUsages() {
  return request<GraphicsLibrarySummary>(`${GRAPHICS_LIBRARY_API}/ensure-engine-usages`, {
    method: "POST",
    body: "{}",
  });
}

export function importGraphicsLibraryHarvest() {
  return request<GraphicsLibrarySummary>(`${GRAPHICS_LIBRARY_API}/import-harvest`, { method: "POST", body: "{}" });
}

export function getGraphicsLibraryUsage(entryId: string) {
  return request<GraphicsLibraryUsage>(`${GRAPHICS_LIBRARY_API}/usages/${encodeURIComponent(entryId)}`);
}

export function updateGraphicsLibraryUsage(entryId: string, updates: Partial<GraphicsLibraryUsage>) {
  return request<GraphicsLibraryUsage>(`${GRAPHICS_LIBRARY_API}/usages/${encodeURIComponent(entryId)}`, {
    method: "PATCH",
    body: JSON.stringify({ updates }),
  });
}

export function graphicsLibrarySampleUrl(entryId: string, cacheKey?: string | null) {
  const base = `${API_BASE}${GRAPHICS_LIBRARY_API}/usages/${encodeURIComponent(entryId)}/media/sample`;
  return cacheKey ? `${base}?t=${encodeURIComponent(cacheKey)}` : base;
}

export function graphicsLibraryPosterUrl(entryId: string, cacheKey?: string | null) {
  const base = `${API_BASE}${GRAPHICS_LIBRARY_API}/usages/${encodeURIComponent(entryId)}/media/poster`;
  return cacheKey ? `${base}?t=${encodeURIComponent(cacheKey)}` : base;
}

/** Cache-bust key so re-rendered posters/samples replace stale browser images. */
export function graphicsLibraryMediaCacheKey(entry: Pick<GraphicsLibraryUsage, "sample" | "updatedAt">) {
  return entry.sample?.renderedAt || entry.updatedAt || "";
}

export function graphicsLibraryUsagePosterSrc(entry: GraphicsLibraryUsage) {
  const key = graphicsLibraryMediaCacheKey(entry);
  if (entry.posterUrl) {
    return `${API_BASE}${entry.posterUrl}${key ? `?t=${encodeURIComponent(key)}` : ""}`;
  }
  return graphicsLibraryPosterUrl(entry.id, key);
}

export function graphicsLibraryUsageSampleSrc(entry: GraphicsLibraryUsage) {
  const key = graphicsLibraryMediaCacheKey(entry);
  if (entry.sampleUrl) {
    return `${API_BASE}${entry.sampleUrl}${key ? `?t=${encodeURIComponent(key)}` : ""}`;
  }
  return graphicsLibrarySampleUrl(entry.id, key);
}

export type GraphicsLibraryRenderProgress = {
  pct: number;
  message: string;
};

/**
 * Render (or re-render) a usage sample. Streams NDJSON progress from the API.
 * `onProgress` receives live status; resolves with the updated usage when done.
 */
export async function renderGraphicsLibrarySample(
  entryId: string,
  force = false,
  quality: "draft" | "standard" | "high" = "draft",
  layoutId?: string | null,
  onProgress?: (progress: GraphicsLibraryRenderProgress) => void,
): Promise<GraphicsLibraryUsage> {
  const response = await fetch(
    `${API_BASE}${GRAPHICS_LIBRARY_API}/usages/${encodeURIComponent(entryId)}/render-sample`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force, quality, layoutId: layoutId || undefined }),
    },
  );
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

  // Streaming NDJSON path (current API). Fall back to a single JSON body if needed.
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("ndjson") && !contentType.includes("stream")) {
    return (await response.json()) as GraphicsLibraryUsage;
  }

  if (!response.body) {
    throw new Error("Sample render returned an empty body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalEntry: GraphicsLibraryUsage | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let event: {
        type?: string;
        pct?: number;
        message?: string;
        entry?: GraphicsLibraryUsage;
        detail?: string;
      };
      try {
        event = JSON.parse(trimmed) as typeof event;
      } catch {
        continue;
      }
      if (event.type === "progress") {
        onProgress?.({
          pct: typeof event.pct === "number" ? event.pct : 0,
          message: event.message || "Rendering…",
        });
      } else if (event.type === "done" && event.entry) {
        finalEntry = event.entry;
      } else if (event.type === "error") {
        throw new Error(event.detail || "Sample render failed.");
      }
    }
  }

  if (buffer.trim()) {
    try {
      const event = JSON.parse(buffer.trim()) as {
        type?: string;
        entry?: GraphicsLibraryUsage;
        detail?: string;
      };
      if (event.type === "done" && event.entry) finalEntry = event.entry;
      if (event.type === "error") throw new Error(event.detail || "Sample render failed.");
    } catch (error) {
      if (error instanceof Error && error.message !== "Sample render failed." && !finalEntry) {
        // trailing partial line — ignore if we already have a result
      } else if (!finalEntry) {
        throw error;
      }
    }
  }

  if (!finalEntry) {
    throw new Error("Sample render finished without an entry payload.");
  }
  return finalEntry;
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
