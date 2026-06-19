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
  left_out_adjustment: number;
  right_in_adjustment: number;
  left_context: string;
  right_context: string;
  reviewed: boolean;
  preview_segments_2s: [number, number][];
  preview_segments_4s: [number, number][];
  preview_segments_6s: [number, number][];
};

export type EditorProjectResponse = {
  project_path: string | null;
  project: {
    source: string;
    fps: number;
    words: TranscriptWord[];
    silence_ranges: SilenceRange[];
  };
  tokens: EditorToken[];
  deleted_word_ids: string[];
  deleted_silence_ids: string[];
  splices: DynamicSplice[];
  kept_ranges: unknown[];
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
  return request<{ source: string }>("/api/projects/choose-video", {
    method: "POST",
    body: "{}",
  });
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

export function saveProject() {
  return request<{ saved: string }>("/api/projects/current/save", { method: "POST" });
}

export function getProjectDocument() {
  return request<ProjectDocumentResponse>("/api/projects/current/document");
}

export function exportCut() {
  return request<{ output_path: string }>("/api/projects/current/export", { method: "POST", body: "{}" });
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
