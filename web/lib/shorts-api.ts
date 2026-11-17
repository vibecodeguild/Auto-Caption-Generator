import {
  API_BASE,
  type CaptionStylePayload,
  type CaptionPresetPayload,
} from "./api";

export type ShortsSource = {
  projectId: string;
  lockedCutSha256: string;
  transcriptSha256: string;
  fps: number;
};
export type ShortSection = {
  id: string;
  startFrame: number;
  endFrameExclusive: number;
};
export type ShortWord = { text: string; start: number; end: number };
export type PostingDrafts = Record<string, { title: string; text: string }>;
export type ShortSettings = {
  style: CaptionStylePayload;
  preset: CaptionPresetPayload;
  modelLabel: string;
  computeLabel: string;
};
export type ShortReceipt = {
  path: string;
  sha256?: string;
  editKey?: string;
  renderKey?: string;
};
export type Short = {
  id: string;
  title: string;
  titleLines: string[];
  rationale: string;
  concerns: string;
  source: ShortsSource;
  sections: ShortSection[];
  revision: number;
  durationSec: number;
  settings: ShortSettings;
  posting: PostingDrafts;
  warnings: string[];
  sourceCurrent: boolean;
  assemblyCurrent: boolean;
  captionCurrent: boolean;
  postingCurrent: boolean;
  deliveryCurrent: boolean;
  assembly: ShortReceipt | null;
  caption: ShortReceipt | null;
  delivery: ShortReceipt | null;
  words: ShortWord[];
  groups: { start: number; end: number; words: ShortWord[] }[];
  platformGuidance: Record<
    string,
    {
      status: string;
      issues: string[];
      note: string;
      url: string;
      checkedOn: string;
    }
  >;
};
export type ShortsState = {
  ready: boolean;
  reason?: string;
  source?: ShortsSource;
  durationFrames?: number;
  durationSec?: number;
  shorts: Short[];
  platforms?: string[];
  layout?: {
    width: number;
    height: number;
    videoY: number;
    videoHeight: number;
    titleY: number;
    titleSize: number;
    captionY: number;
    titleFont: string;
  };
};
export type ShortJob = {
  id: string;
  shortId: string;
  operation: "assemble" | "captions" | "export";
  status: "running" | "canceling" | "failed" | "canceled" | "complete";
  value: number;
  message: string;
  error: string | null;
  result?: { outputPath?: string };
};

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${API_BASE}/api/shorts${path}`, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : `Shorts request failed (${response.status}).`,
    );
  }
  return response.json();
}
export const loadShorts = () => request<ShortsState>("");
export const candidateBrief = () => request<unknown>("/brief");
export const importShorts = (plan: unknown) =>
  request<ShortsState>("/import", "POST", plan);
export const createShort = (plan: unknown) =>
  request<ShortsState>("", "POST", plan);
export const saveShort = (id: string, changes: unknown) =>
  request<ShortsState>(`/${encodeURIComponent(id)}`, "PUT", changes);
export const startShortJob = (id: string, operation: string) =>
  request<ShortJob>(`/${encodeURIComponent(id)}/jobs`, "POST", { operation });
export const getShortJob = (id: string) =>
  request<{ job: ShortJob | null }>(`/${encodeURIComponent(id)}/job`);
export const cancelShortJob = (id: string, jobId: string) =>
  request<ShortJob>(
    `/${encodeURIComponent(id)}/jobs/${encodeURIComponent(jobId)}/cancel`,
    "POST",
  );
export const shortPostingBrief = (id: string) =>
  request<unknown>(`/${encodeURIComponent(id)}/posting-brief`);
export const importShortPosting = (id: string, plan: unknown) =>
  request<ShortsState>(
    `/${encodeURIComponent(id)}/posting-import`,
    "POST",
    plan,
  );
export const shortPostingPackage = (id: string) =>
  request<unknown>(`/${encodeURIComponent(id)}/posting-package`);
export const shortsSourceUrl = (source?: ShortsSource) =>
  `${API_BASE}/api/shorts/source-video?v=${source?.lockedCutSha256 ?? ""}`;
export const shortMediaUrl = (s: Short, kind: "assembly" | "delivery") =>
  `${API_BASE}/api/shorts/${encodeURIComponent(s.id)}/media/${kind}?v=${encodeURIComponent(s[kind]?.path ?? "")}`;

export function downloadShortsJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
