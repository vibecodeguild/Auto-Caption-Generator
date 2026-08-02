"use client";

import {
  BarChart3,
  FolderOpen,
  HelpCircle,
  Library,
  Play,
  Star,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createGraphicsLibrary,
  getGraphicsLibrary,
  getGraphicsLibraryMetrics,
  graphicsLibraryBeatTypesAlphabetical,
  graphicsLibraryMediaCacheKey,
  graphicsLibraryUsagePosterSrc,
  graphicsLibraryUsageSampleSrc,
  openGraphicsLibraryDialog,
  renderGraphicsLibrarySample,
  updateGraphicsLibraryUsage,
  GRAPHICS_LIBRARY_BEAT_TYPE_GUIDE,
  GRAPHICS_LIBRARY_LAYOUT_IDS,
  type GraphicsLibraryUsage,
  type UsageStatus,
  type GraphicsLibrarySummary,
  type GraphicsLibraryRenderProgress,
  type GraphicsLibraryMetrics,
  type GraphicsLibraryMetricRow,
  type GraphicsLibraryMetricBucket,
} from "../lib/api";

const STATUS_ORDER: UsageStatus[] = ["candidate", "golden"];

function statusClass(status: string) {
  return `usage-status usage-status-${status}`;
}

function MetricsBarChart({
  title,
  rows,
  untagged,
  emptyLabel,
  showEmpty = true,
}: {
  title: string;
  rows: GraphicsLibraryMetricRow[];
  untagged: GraphicsLibraryMetricBucket;
  emptyLabel: string;
  /** When true, include zero-count rows so coverage gaps are visible. */
  showEmpty?: boolean;
}) {
  const ranked = showEmpty ? rows : rows.filter((row) => row.total > 0);
  const maxTotal = Math.max(untagged.total, ...ranked.map((row) => row.total), 1);
  const chartRows: Array<{
    id: string;
    total: number;
    golden: number;
    candidate: number;
    muted?: boolean;
  }> = ranked.map((row) => ({
    ...row,
    muted: row.total === 0,
  }));
  if (untagged.total > 0) {
    chartRows.push({
      id: emptyLabel,
      total: untagged.total,
      golden: untagged.golden,
      candidate: untagged.candidate,
      muted: true,
    });
  }

  const taggedTotal = chartRows.reduce((sum, row) => sum + row.total, 0);
  const covered = ranked.filter((row) => row.total > 0).length;
  const known = ranked.length;

  return (
    <section className="graphics-library-metrics-chart">
      <header className="graphics-library-metrics-chart-head">
        <h3>{title}</h3>
        <span>
          {taggedTotal} tags
          {known > 0 ? ` · ${covered}/${known} covered` : ""}
        </span>
      </header>
      {chartRows.length === 0 ? (
        <p className="graphics-library-metrics-empty">No tagged usages yet.</p>
      ) : (
        <ul className="graphics-library-metrics-bars">
          {chartRows.map((row) => {
            const widthPct =
              row.total <= 0 ? 0 : Math.max(4, Math.round((row.total / maxTotal) * 100));
            const goldenPct = row.total > 0 ? Math.round((row.golden / row.total) * 100) : 0;
            return (
              <li key={row.id} className={row.muted ? "is-muted" : undefined}>
                <div className="graphics-library-metrics-row-label">
                  <strong>{row.id}</strong>
                  <span>
                    {row.total}
                    {row.golden > 0 ? ` · ${row.golden} golden` : row.total === 0 ? " · none" : ""}
                  </span>
                </div>
                <div className="graphics-library-metrics-bar-track" aria-hidden="true">
                  {row.total > 0 ? (
                    <div className="graphics-library-metrics-bar-fill" style={{ width: `${widthPct}%` }}>
                      <i style={{ width: `${goldenPct}%` }} />
                    </div>
                  ) : (
                    <div className="graphics-library-metrics-bar-empty" />
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

type GraphicsLibraryWorkspaceProps = {
  /** Incremented when app Settings changes the private graphics library folder. */
  refreshSignal?: number;
};

export default function GraphicsLibraryWorkspace({ refreshSignal = 0 }: GraphicsLibraryWorkspaceProps) {
  const [summary, setSummary] = useState<GraphicsLibrarySummary | null>(null);
  const [metrics, setMetrics] = useState<GraphicsLibraryMetrics | null>(null);
  const [view, setView] = useState<"library" | "metrics">("library");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** True only while a sample render is in flight (blocks re-clicks even before React re-renders). */
  const [rendering, setRendering] = useState(false);
  const [renderProgress, setRenderProgress] = useState<GraphicsLibraryRenderProgress | null>(null);
  const renderInFlight = useRef(false);
  const [message, setMessage] = useState("Private Graphics Library — usages and samples stay on this machine.");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [nameDraft, setNameDraft] = useState("");
  const [statusDraft, setStatusDraft] = useState<UsageStatus>("candidate");
  const [beatTypesDraft, setBeatTypesDraft] = useState<string[]>([]);
  const [layoutsDraft, setLayoutsDraft] = useState<string[]>([]);
  const [engineDraft, setEngineDraft] = useState("");
  /** Layout used for the next sample render (must be one of allowedLayouts when set). */
  const [sampleLayoutDraft, setSampleLayoutDraft] = useState<string>("");
  const [beatHelpOpen, setBeatHelpOpen] = useState(false);
  const lastRefreshSignal = useRef(0);
  const uiLocked = busy || rendering;
  const beatTypesAlphabetical = useMemo(() => graphicsLibraryBeatTypesAlphabetical(), []);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const data = await getGraphicsLibrary();
      setSummary(data);
      if (!data.exists) {
        setMetrics(null);
        setView("library");
        setMessage("No Graphics Library yet. Create one or open an existing private folder via Settings.");
      } else {
        setMessage(`${data.entryCount} usages · ${data.withSample} with samples · ${data.root}`);
        try {
          setMetrics(await getGraphicsLibraryMetrics());
        } catch {
          setMetrics(null);
        }
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!beatHelpOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setBeatHelpOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [beatHelpOpen]);

  useEffect(() => {
    if (!refreshSignal || refreshSignal === lastRefreshSignal.current) return;
    lastRefreshSignal.current = refreshSignal;
    void refresh();
  }, [refreshSignal, refresh]);

  const selected = useMemo(
    () => summary?.entries.find((entry) => entry.id === selectedId) ?? null,
    [summary, selectedId],
  );

  /** Layouts with a recorded clip — only these are valid for sample render. */
  const presentLayoutClips = useMemo(() => {
    const fromSummary = summary?.layoutClips?.present;
    if (Array.isArray(fromSummary) && fromSummary.length > 0) {
      return fromSummary;
    }
    // Fall back to scanning the clips[] array if present[] is missing/empty shape.
    const clips = summary?.layoutClips?.clips;
    if (Array.isArray(clips)) {
      return clips
        .filter((item) => item?.present && item.layoutId)
        .map((item) => item.layoutId);
    }
    return [];
  }, [summary?.layoutClips]);

  /**
   * Sample dropdown = allowed layouts for this usage ∩ layouts with a recorded clip.
   * You can't sample on a layout this graphic isn't allowed to use.
   */
  const sampleLayoutOptions = useMemo(() => {
    const allowed = layoutsDraft.length
      ? layoutsDraft
      : [...(selected?.allowedLayouts || [])];
    if (!allowed.length) return [];
    return allowed.filter((layout) => presentLayoutClips.includes(layout));
  }, [layoutsDraft, presentLayoutClips, selected?.allowedLayouts]);

  useEffect(() => {
    if (!selected) return;
    setNameDraft(selected.displayName || "");
    setStatusDraft(selected.status);
    setBeatTypesDraft([...(selected.beatTypes || [])]);
    const layouts = [...(selected.allowedLayouts || [])];
    setLayoutsDraft(layouts);
    setEngineDraft(selected.engineId || "");
  }, [selected]);

  // Keep sample layout selection on a layout that has a real clip.
  useEffect(() => {
    if (!selected) return;
    const sampleLayout = selected.sample?.layoutId || "";
    setSampleLayoutDraft((prev) => {
      if (sampleLayout && sampleLayoutOptions.includes(sampleLayout)) {
        return sampleLayout;
      }
      if (prev && sampleLayoutOptions.includes(prev)) {
        return prev;
      }
      return sampleLayoutOptions[0] || "";
    });
  }, [selected, sampleLayoutOptions]);

  const sampleCacheKey = selected ? graphicsLibraryMediaCacheKey(selected) : "";
  const sampleMediaUrl = selected ? graphicsLibraryUsageSampleSrc(selected) : "";
  const posterMediaUrl = selected ? graphicsLibraryUsagePosterSrc(selected) : "";

  const renderSampleForSelected = async (force: boolean) => {
    if (!selected || renderInFlight.current) return;
    const layoutId =
      (sampleLayoutDraft && sampleLayoutOptions.includes(sampleLayoutDraft)
        ? sampleLayoutDraft
        : sampleLayoutOptions[0]) || undefined;
    if (!layoutId) {
      setMessage(
        "Pick an allowed layout that has a recorded clip, or enable a layout that already has a clip.",
      );
      return;
    }
    const entryId = selected.id;
    const label = selected.displayName;
    renderInFlight.current = true;
    setRendering(true);
    setRenderProgress({ pct: 0, message: "Starting sample render…" });
    setMessage(`Rendering sample for ${label} on ${layoutId || "default layout"}…`);
    try {
      const entry = await renderGraphicsLibrarySample(
        entryId,
        force,
        "draft",
        layoutId,
        (progress) => {
          setRenderProgress(progress);
        },
      );
      applyUsageToSummary(entry);
      setMessage(
        force
          ? `Sample re-rendered on ${layoutId || "default layout"}.`
          : `Rendered sample for ${label} (${layoutId || "default layout"}).`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      renderInFlight.current = false;
      setRendering(false);
      setRenderProgress(null);
    }
  };

  // Keep a selection once data is present so metadata is never an empty pane.
  useEffect(() => {
    if (!summary?.entries?.length) return;
    if (selectedId && summary.entries.some((entry) => entry.id === selectedId)) return;
    setSelectedId(summary.entries[0].id);
  }, [summary, selectedId]);

  const filtered = useMemo(() => {
    const entries = summary?.entries ?? [];
    const q = query.trim().toLowerCase();
    return entries
      .filter((entry) => (filterStatus === "all" ? true : entry.status === filterStatus))
      .filter((entry) => {
        if (!q) return true;
        const hay = [
          entry.id,
          entry.displayName,
          entry.engineId || "",
          ...(entry.beatTypes || []),
          ...(entry.engineInterface || []),
        ]
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      })
      .sort((a, b) => {
        const sa = STATUS_ORDER.indexOf(a.status);
        const sb = STATUS_ORDER.indexOf(b.status);
        if (sa !== sb) return sa - sb;
        return a.displayName.localeCompare(b.displayName);
      });
  }, [summary, filterStatus, query]);

  const applyUsageToSummary = useCallback((entry: GraphicsLibraryUsage) => {
    setSummary((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        entries: prev.entries.map((item) => (item.id === entry.id ? { ...item, ...entry } : item)),
      };
    });
    setSelectedId(entry.id);
  }, []);

  const run = async (action: () => Promise<GraphicsLibrarySummary | GraphicsLibraryUsage>, success?: string) => {
    setBusy(true);
    try {
      const result = await action();
      if ("entryCount" in result) {
        setSummary(result);
        setMessage(success || `${result.entryCount} graphics ready.`);
      } else {
        applyUsageToSummary(result);
        setMessage(success || `Updated ${result.displayName}.`);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  /** Persist usage fields immediately — no separate Save button. */
  const persistUsage = async (
    fields: Partial<GraphicsLibraryUsage>,
    success?: string,
  ) => {
    if (!selected) return;
    setBusy(true);
    try {
      const entry = await updateGraphicsLibraryUsage(selected.id, fields);
      applyUsageToSummary(entry);
      if (fields.displayName != null) setNameDraft(entry.displayName || "");
      if (fields.status != null) setStatusDraft(entry.status);
      if (fields.engineId != null) setEngineDraft(entry.engineId || "");
      if (fields.beatTypes != null) setBeatTypesDraft([...(entry.beatTypes || [])]);
      if (fields.allowedLayouts != null) setLayoutsDraft([...(entry.allowedLayouts || [])]);
      if (success) {
        setMessage(success);
      } else if (fields.beatTypes) {
        setMessage(`Beat types saved (${(fields.beatTypes || []).length}).`);
      } else if (fields.allowedLayouts) {
        setMessage(`Layouts saved (${(fields.allowedLayouts || []).length}).`);
      } else if (fields.displayName != null) {
        setMessage("Name saved.");
      } else if (fields.engineId != null) {
        setMessage("Engine saved.");
      } else if (fields.status != null) {
        setMessage(
          fields.status === "golden"
            ? `Promoted ${entry.displayName} to golden.`
            : `Marked ${entry.displayName} as candidate.`,
        );
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const toggleLayout = (layout: string) => {
    const next = layoutsDraft.includes(layout)
      ? layoutsDraft.filter((item) => item !== layout)
      : [...layoutsDraft, layout];
    setLayoutsDraft(next);
    void persistUsage({ allowedLayouts: next });
  };

  const toggleBeatType = (beatType: string) => {
    const next = beatTypesDraft.includes(beatType)
      ? beatTypesDraft.filter((item) => item !== beatType)
      : [...beatTypesDraft, beatType];
    setBeatTypesDraft(next);
    void persistUsage({ beatTypes: next });
  };

  const commitName = () => {
    if (!selected) return;
    const next = nameDraft.trim();
    if (!next || next === (selected.displayName || "")) return;
    void persistUsage({ displayName: next });
  };

  const commitEngine = () => {
    if (!selected) return;
    const next = engineDraft.trim();
    if (!next || next === (selected.engineId || "")) return;
    void persistUsage({ engineId: next });
  };

  const setStatusQuick = async (status: UsageStatus) => {
    if (!selected || status === selected.status) return;
    setStatusDraft(status);
    await persistUsage({ status });
  };

  return (
    <main className="graphics-library">
      {!summary?.exists ? (
        <section className="graphics-library-empty">
          <Library size={36} />
          <h3>Private by design</h3>
          <p>
            The Graphics Library UI ships with the app. Sample clips and your approved list stay in a
            private folder on this machine so building in public never publishes your face or channel graphics.
          </p>
          {message ? <p className="graphics-library-empty-hint">{message}</p> : null}
          <div className="graphics-library-empty-actions">
            <button
              className="primary"
              onClick={() => void run(createGraphicsLibrary, "Graphics Library created.")}
              disabled={busy}
              data-tip="Create a new private Graphics Library folder on this machine (default location under Videos)."
            >
              <Library size={16} /> Create Graphics Library
            </button>
            <button
              onClick={() => void run(openGraphicsLibraryDialog, "Opened Graphics Library folder.")}
              disabled={busy}
              data-tip="Open an existing private Graphics Library folder on this machine."
            >
              <FolderOpen size={16} /> Choose folder
            </button>
          </div>
          <p className="graphics-library-empty-hint">
            You can also manage this under Settings (gear icon) → Graphics Library.
          </p>
        </section>
      ) : (
        <div className="graphics-library-layout">
          {message ? (
            <p
              className={[
                "graphics-library-status-line",
                rendering ? "is-rendering" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              role="status"
              aria-live="polite"
            >
              {message}
            </p>
          ) : null}
          <div className="graphics-library-view-tabs" role="tablist" aria-label="Graphics Library views">
            <button
              type="button"
              role="tab"
              aria-selected={view === "library"}
              className={view === "library" ? "active" : ""}
              onClick={() => setView("library")}
            >
              <Library size={15} /> Library
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "metrics"}
              className={view === "metrics" ? "active" : ""}
              onClick={() => setView("metrics")}
              data-tip="Counts of usages by beat type and by allowed layout."
            >
              <BarChart3 size={15} /> Metrics
            </button>
          </div>
          {view === "metrics" ? (
            <section className="graphics-library-metrics-panel" aria-label="Graphics Library metrics">
              <header className="graphics-library-metrics-intro">
                <div>
                  <h2>Library metrics</h2>
                  <p>
                    How many usages declare each beat type and each allowed layout. A usage with several
                    tags is counted once per tag. Teal is total count; magenta is the golden share.
                    Zero rows show coverage gaps.
                  </p>
                  <div className="graphics-library-metrics-legend" aria-hidden="true">
                    <span className="legend-total">Total usages</span>
                    <span className="legend-golden">Golden share</span>
                    <span className="legend-empty">No coverage</span>
                  </div>
                </div>
                <div className="graphics-library-metrics-totals">
                  <span>
                    <strong>{metrics?.entryCount ?? summary.entryCount}</strong> usages
                  </span>
                  <span>
                    <strong>{summary.productionSet?.count ?? 0}</strong> golden
                  </span>
                  <span>
                    <strong>{summary.withSample}</strong> samples
                  </span>
                </div>
              </header>
              {metrics ? (
                <div className="graphics-library-metrics-grid">
                  <MetricsBarChart
                    title="By beat type"
                    rows={metrics.byBeatType}
                    untagged={metrics.untaggedBeatTypes}
                    emptyLabel="(no beat types set)"
                  />
                  <MetricsBarChart
                    title="By allowed layout"
                    rows={metrics.byLayout}
                    untagged={metrics.untaggedLayouts}
                    emptyLabel="(no layouts set)"
                  />
                </div>
              ) : (
                <p className="graphics-library-metrics-empty">Metrics could not be loaded. Try refresh.</p>
              )}
            </section>
          ) : null}
          {view === "library" ? (
          <>
          <section className="graphics-library-list-panel">
            <div className="graphics-library-filters">
              <input
                type="search"
                placeholder="Search id, name, engine, beat type…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <select value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}>
                <option value="all">All statuses</option>
                {STATUS_ORDER.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </div>
            <div className="graphics-library-stats">
              <span>{filtered.length} shown</span>
              <span>{summary.withSample} samples</span>
              <span
                className={summary.productionSet?.empty ? "golden-warn" : "usage-status usage-status-golden"}
                data-tip={
                  summary.productionSet?.message ||
                  "Production set = usages with status golden."
                }
              >
                production {summary.productionSet?.count ?? 0}
              </span>
              {STATUS_ORDER.map((status) =>
                summary.statusCounts[status] ? (
                  <span key={status} className={statusClass(status)}>
                    {status} {summary.statusCounts[status]}
                  </span>
                ) : null,
              )}
            </div>
            <div className="graphics-library-list">
              {filtered.map((entry) => {
                const showStatus = entry.status !== "candidate";
                return (
                  <button
                    key={entry.id}
                    type="button"
                    className={[
                      "graphics-library-card",
                      `is-${entry.status}`,
                      selectedId === entry.id ? "active" : "",
                    ].join(" ")}
                    onClick={() => setSelectedId(entry.id)}
                    data-tip={`Select “${entry.displayName}” (${entry.status}${entry.hasSample ? ", sample ready" : ", no sample yet"}).`}
                  >
                    <div className="graphics-library-thumb">
                      {entry.hasPoster ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          key={`${entry.id}-${graphicsLibraryMediaCacheKey(entry)}`}
                          src={graphicsLibraryUsagePosterSrc(entry)}
                          alt=""
                        />
                      ) : entry.hasSample ? (
                        <span className="graphics-library-thumb-fallback">
                          <Play size={20} />
                        </span>
                      ) : (
                        <span className="graphics-library-thumb-fallback">
                          {entry.displayName.slice(0, 2).toUpperCase()}
                        </span>
                      )}
                    </div>
                    <div className="graphics-library-card-copy">
                      <span className="graphics-library-card-name" title={entry.displayName}>
                        {entry.displayName}
                      </span>
                      {showStatus ? (
                        <span className={`graphics-library-card-badge is-${entry.status}`}>{entry.status}</span>
                      ) : null}
                    </div>
                  </button>
                );
              })}
              {filtered.length === 0 ? <p className="graphics-library-empty-list">No entries match these filters.</p> : null}
            </div>
          </section>

          <section className="graphics-library-stage">
            {!selected ? (
              <div className="graphics-library-empty-detail">
                <p>Select a graphic to play its sample. All fields are managed in the metadata panel.</p>
              </div>
            ) : (
              <div className="graphics-library-player-wrap">
                <div className="graphics-library-promote-bar">
                  <div className="graphics-library-promote-copy">
                    <strong>{selected.displayName}</strong>
                  </div>
                  <label
                    className={[
                      "usage-status-toggle",
                      selected.status === "golden" ? "is-golden" : "is-candidate",
                      uiLocked ? "is-busy" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    data-tip={
                      selected.status === "golden"
                        ? "Golden — production may use this. Click to demote to candidate."
                        : "Candidate — designing/refining. Click to promote to golden."
                    }
                  >
                    <span className="usage-status-toggle-label">Candidate</span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={selected.status === "golden"}
                      aria-label={
                        selected.status === "golden"
                          ? "Status golden. Switch to candidate."
                          : "Status candidate. Switch to golden."
                      }
                      className="usage-status-toggle-switch"
                      disabled={uiLocked}
                      onClick={() =>
                        void setStatusQuick(selected.status === "golden" ? "candidate" : "golden")
                      }
                    >
                      <span className="usage-status-toggle-thumb" />
                    </button>
                    <span className="usage-status-toggle-label usage-status-toggle-label-golden">
                      <Star size={14} /> Golden
                    </span>
                  </label>
                </div>

                <div className="graphics-library-player">
                  {selected.hasSample ? (
                    <video
                      key={`${selected.id}-${sampleCacheKey}-${selected.sample?.layoutId || ""}`}
                      controls
                      playsInline
                      poster={selected.hasPoster ? posterMediaUrl : undefined}
                      src={sampleMediaUrl}
                    />
                  ) : (
                    <div className="graphics-library-no-sample">
                      <p>No sample clip yet for this graphic.</p>
                    </div>
                  )}
                </div>
                <div className="graphics-library-player-actions graphics-library-sample-controls">
                  <label
                    className="graphics-library-sample-layout"
                    data-tip="Only layouts with a recorded full-frame clip are listed. The engine still decides where the graphic sits — layout only picks the source footage."
                  >
                    <span>Sample layout</span>
                    <select
                      value={sampleLayoutDraft}
                      disabled={uiLocked || sampleLayoutOptions.length === 0}
                      onChange={(event) => setSampleLayoutDraft(event.target.value)}
                    >
                      {sampleLayoutOptions.length === 0 ? (
                        <option value="">
                          {!summary?.layoutClips
                            ? "Restart API to load layout clips"
                            : !layoutsDraft.length
                              ? "Enable allowed layouts first"
                              : presentLayoutClips.length === 0
                                ? "No layout clips recorded yet"
                                : "No allowed layout has a clip yet"}
                        </option>
                      ) : (
                        sampleLayoutOptions.map((layout) => (
                          <option key={layout} value={layout}>
                            {layout}
                            {selected.sample?.layoutId === layout ? " (current sample)" : ""}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                  <div className="graphics-library-render-action">
                    <button
                      className="primary"
                      disabled={
                        uiLocked ||
                        renderInFlight.current ||
                        !sampleLayoutDraft ||
                        sampleLayoutOptions.length === 0
                      }
                      data-tip={
                        rendering
                          ? "Sample render already in progress."
                          : sampleLayoutOptions.length === 0
                            ? !layoutsDraft.length
                              ? "Enable at least one allowed layout for this usage first."
                              : presentLayoutClips.length === 0
                                ? "Record layout clips first (layout-clips/<layout-id>.mp4)."
                                : "None of this usage's allowed layouts have a recorded clip yet."
                            : selected.hasSample
                              ? "Overwrite sample + poster using the selected layout clip as source footage."
                              : "Render a sample using the selected layout clip as source footage."
                      }
                      onClick={() => void renderSampleForSelected(true)}
                    >
                      <Play size={16} />
                      {rendering
                        ? `Rendering… ${renderProgress?.pct ?? 0}%`
                        : selected.hasSample
                          ? "Re-render sample"
                          : "Render sample"}
                    </button>
                    {rendering ? (
                      <div
                        className="graphics-library-render-progress"
                        role="status"
                        aria-live="polite"
                        aria-busy="true"
                      >
                        <div className="graphics-library-render-progress-bar">
                          <div
                            className="graphics-library-render-progress-fill"
                            style={{ width: `${Math.max(2, renderProgress?.pct ?? 0)}%` }}
                          />
                        </div>
                        <span className="graphics-library-render-progress-label">
                          {renderProgress
                            ? `${renderProgress.pct}% · ${renderProgress.message}`
                            : "Starting sample render…"}
                        </span>
                      </div>
                    ) : null}
                  </div>
                  {selected.sample?.layoutId ? (
                    <span className="usage-field-hint">
                      Current sample layout: {selected.sample.layoutId}
                    </span>
                  ) : null}
                  {summary?.layoutClips ? (
                    <span className="usage-field-hint">
                      Layout clips ready:{" "}
                      {(summary.layoutClips.present?.length
                        ? summary.layoutClips.present
                        : presentLayoutClips
                      ).join(", ") || "none"}
                      .
                      {summary.layoutClips.missing?.length
                        ? ` Still to record: ${summary.layoutClips.missing.join(", ")}.`
                        : presentLayoutClips.length > 0
                          ? " All eight layouts recorded."
                          : ""}
                    </span>
                  ) : (
                    <span className="usage-field-hint">
                      Layout clips are on disk, but this API process does not report them yet.
                      Restart the API (`npm run dev` or the VS Code API task) so it loads the
                      layout-clips code — then refresh this page.
                    </span>
                  )}
                </div>
              </div>
            )}
          </section>

          <aside className="graphics-library-meta-column" aria-label="Usage metadata">
            {!selected ? (
              <div className="graphics-library-empty-detail compact">
                <p>Select a usage to manage when/where metadata here.</p>
              </div>
            ) : (
              <div className="graphics-library-meta-scroll">
                <section className="graphics-library-meta-panel" aria-label="Usage metadata">
                  <div className="graphics-library-section-title">
                    <h4>Usage</h4>
                    <span>When/where contract + engine — changes save as you go</span>
                  </div>

                  <label className="graphics-library-field" data-tip="Human-readable name shown in the library list. Saves when you leave the field.">
                    <span className="usage-meta-key">Name</span>
                    <input
                      className="usage-meta-value"
                      value={nameDraft}
                      disabled={uiLocked}
                      onChange={(event) => setNameDraft(event.target.value)}
                      onBlur={() => commitName()}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.currentTarget.blur();
                        }
                      }}
                    />
                  </label>

                  <div className="graphics-library-field">
                    <span className="usage-meta-key">Usage id</span>
                    <div className="usage-meta-value usage-meta-readonly">
                      <code>{selected.id}</code>
                    </div>
                  </div>

                  <label
                    className="graphics-library-field"
                    data-tip="candidate = designing/refining in the library. golden = production may use it. Demote golden back to candidate anytime."
                  >
                    <span className="usage-meta-key">Status</span>
                    <select
                      className="usage-meta-value"
                      value={statusDraft}
                      disabled={uiLocked}
                      onChange={(event) => {
                        const next = event.target.value as UsageStatus;
                        setStatusDraft(next);
                        void persistUsage({ status: next });
                      }}
                    >
                      <option value="candidate">candidate (designing)</option>
                      <option value="golden">golden (production)</option>
                    </select>
                  </label>

                  <div className="graphics-library-field">
                    <span className="usage-meta-key usage-meta-key-with-help">
                      Beat types (when to use)
                      <button
                        type="button"
                        className="usage-help-button"
                        aria-label="What do these beat types mean?"
                        data-tip="Short description of each closed VCG beat type."
                        onClick={() => setBeatHelpOpen(true)}
                      >
                        <HelpCircle size={15} />
                      </button>
                    </span>
                    <div className="usage-layout-pills usage-meta-value" role="group" aria-label="Beat types">
                      {beatTypesAlphabetical.map((beatType) => {
                        const selectedBeat = beatTypesDraft.includes(beatType);
                        return (
                          <button
                            key={beatType}
                            type="button"
                            className={["usage-layout-pill", selectedBeat ? "is-selected" : ""].join(" ")}
                            aria-pressed={selectedBeat}
                            disabled={uiLocked}
                            onClick={() => toggleBeatType(beatType)}
                            data-tip={GRAPHICS_LIBRARY_BEAT_TYPE_GUIDE[beatType]?.job}
                          >
                            {beatType}
                          </button>
                        );
                      })}
                    </div>
                    {beatTypesDraft.length === 0 ? (
                      <span className="usage-field-hint">None selected — tag at least one before promoting for production selection.</span>
                    ) : null}
                  </div>

                  <div className="graphics-library-field">
                    <span className="usage-meta-key" data-tip="OBS layouts where this graphic may be placed (face-safe).">
                      Allowed layouts
                    </span>
                    <div className="usage-layout-pills usage-meta-value" role="group" aria-label="Allowed layouts">
                      {GRAPHICS_LIBRARY_LAYOUT_IDS.map((layout) => {
                        const selected = layoutsDraft.includes(layout);
                        return (
                          <button
                            key={layout}
                            type="button"
                            className={["usage-layout-pill", selected ? "is-selected" : ""].join(" ")}
                            aria-pressed={selected}
                            disabled={uiLocked}
                            onClick={() => toggleLayout(layout)}
                            data-tip={
                              selected
                                ? `${layout} — allowed. Click to remove.`
                                : `${layout} — not allowed. Click to allow.`
                            }
                          >
                            {layout}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <label
                    className="graphics-library-field"
                    data-tip="Engine that draws this usage (usage has-a engine). Must be a real production engine id. Saves when you leave the field."
                  >
                    <span className="usage-meta-key">Engine id</span>
                    <input
                      className="usage-meta-value"
                      value={engineDraft}
                      disabled={uiLocked}
                      onChange={(event) => setEngineDraft(event.target.value)}
                      onBlur={() => commitEngine()}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.currentTarget.blur();
                        }
                      }}
                    />
                  </label>

                  <div
                    className="graphics-library-field"
                    data-tip="Live passthrough of the engine draw interface (content keys). Not stored on the usage."
                  >
                    <span className="usage-meta-key">Engine interface</span>
                    <div className="usage-meta-value usage-meta-readonly">
                      {(selected.engineInterface || []).length
                        ? selected.engineInterface!.join(", ")
                        : "—"}
                    </div>
                  </div>

                  <div className="graphics-library-field">
                    <span className="usage-meta-key">Sample</span>
                    <div className="usage-meta-value usage-meta-readonly">
                      {selected.hasSample ? (
                        <a
                          className="usage-media-link"
                          href={graphicsLibraryUsageSampleSrc(selected)}
                          target="_blank"
                          rel="noreferrer"
                          data-tip="Open the sample clip in a new tab."
                        >
                          Open sample
                          {selected.sample?.durationSec != null
                            ? ` (${Number(selected.sample.durationSec).toFixed(1)}s)`
                            : ""}
                        </a>
                      ) : (
                        "missing"
                      )}
                    </div>
                  </div>

                  <div className="graphics-library-field">
                    <span className="usage-meta-key">Poster</span>
                    <div className="usage-meta-value usage-meta-readonly">
                      {selected.hasPoster ? (
                        <a
                          className="usage-media-link"
                          href={graphicsLibraryUsagePosterSrc(selected)}
                          target="_blank"
                          rel="noreferrer"
                          data-tip="Open the poster image in a new tab."
                        >
                          Open poster
                        </a>
                      ) : (
                        "missing"
                      )}
                    </div>
                  </div>

                  <div className="graphics-library-field">
                    <span className="usage-meta-key">Created</span>
                    <div className="usage-meta-value usage-meta-readonly">
                      {selected.createdAt ? new Date(selected.createdAt).toLocaleString() : "—"}
                    </div>
                  </div>

                  <div className="graphics-library-field">
                    <span className="usage-meta-key">Updated</span>
                    <div className="usage-meta-value usage-meta-readonly">
                      {selected.updatedAt ? new Date(selected.updatedAt).toLocaleString() : "—"}
                    </div>
                  </div>
                </section>
              </div>
            )}
          </aside>
          </>
          ) : null}
        </div>
      )}

      {beatHelpOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) setBeatHelpOpen(false);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setBeatHelpOpen(false);
          }}
        >
          <section
            className="graphics-library-beat-help-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="beat-help-title"
          >
            <div className="graphics-library-beat-help-header">
              <div>
                <p className="graphics-library-beat-help-kicker">Closed VCG beat universe</p>
                <h2 id="beat-help-title">When to use each beat</h2>
              </div>
              <button
                type="button"
                className="header-icon-button"
                aria-label="Close beat help"
                onClick={() => setBeatHelpOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <p className="graphics-library-beat-help-intro">
              A beat type answers only: what job does this moment do for the viewer? Click a row to
              toggle it on this usage (same tags as the pills in metadata). Sorted alphabetically.
            </p>
            <ul className="graphics-library-beat-help-list" role="group" aria-label="Beat types for this usage">
              {beatTypesAlphabetical.map((beatType) => {
                const guide = GRAPHICS_LIBRARY_BEAT_TYPE_GUIDE[beatType];
                const selectedBeat = beatTypesDraft.includes(beatType);
                return (
                  <li key={beatType}>
                    <button
                      type="button"
                      className={[
                        "graphics-library-beat-help-row",
                        selectedBeat ? "is-selected" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      aria-pressed={selectedBeat}
                      disabled={uiLocked || !selected}
                      data-tip={
                        selectedBeat
                          ? "Selected for this usage — click to remove"
                          : "Click to tag this usage with this beat type"
                      }
                      onClick={() => toggleBeatType(beatType)}
                    >
                      <span className="graphics-library-beat-help-check" aria-hidden="true">
                        {selectedBeat ? "✓" : ""}
                      </span>
                      <span className="graphics-library-beat-help-copy">
                        <code>{beatType}</code>
                        <strong>{guide.job}</strong>
                        <span>{guide.howToSpot}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="graphics-library-beat-help-actions">
              <span className="graphics-library-beat-help-count">
                {beatTypesDraft.length === 0
                  ? "None selected"
                  : `${beatTypesDraft.length} selected`}
              </span>
              <button type="button" className="primary" onClick={() => setBeatHelpOpen(false)}>
                Done
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
