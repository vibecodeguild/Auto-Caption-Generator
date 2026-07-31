"use client";

import { AlertTriangle, CheckCircle2, ClipboardCopy, LoaderCircle, RefreshCw, Search, ShieldCheck, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  acceptCreatorReviewNote,
  applyCreatorStudioEdits,
  approveCreatorReview,
  cancelCreatorRenderJob,
  cancelCreatorProductionJob,
  createCreatorRenderJob,
  createCreatorStudioHandoff,
  createCreatorProductionJob,
  creatorReviewVideoUrl,
  getCreatorCapabilities,
  getCreatorProductionHandoff,
  getCreatorProductionCurrent,
  getCreatorProductionPipeline,
  getCreatorReview,
  initializeCreatorProduction,
  listCreatorRenderJobs,
  listCreatorChannelProfiles,
  listCreatorProductionJobs,
  saveCreatorReviewNote,
  startCreatorRenderJob,
  upgradeCreatorProductionWorkflow,
  type CreatorCapabilityCatalog,
  type CreatorProductionCurrent,
  type CreatorProductionJob,
  type CreatorProductionPipeline,
  type CreatorRenderJob,
  type CreatorReview,
  type CreatorReviewContext,
  type CreatorReviewSequence,
} from "../lib/api";

const JOB_INPUTS: Record<CreatorProductionJob["taskKind"], string[]> = {
  analyze: ["transcriptReceipt", "productionProfile", "channelProfile", "capabilityCatalog"],
  plan: ["analysisLedger", "transcriptReceipt", "productionProfile", "channelProfile", "capabilityCatalog"],
  "classify-layouts": ["semanticManifest", "analysisLedger", "transcriptReceipt", "captureLayoutCatalog"],
  adapt: ["semanticManifest", "analysisLedger", "transcriptReceipt", "productionProfile", "channelProfile", "capabilityCatalog"],
  materialize: ["semanticManifest", "sourceEvidence", "analysisLedger", "transcriptReceipt", "productionProfile", "channelProfile", "capabilityCatalog"],
  revise: ["episodeManifest", "reviewState", "sourceEvidence", "transcriptReceipt", "productionProfile", "channelProfile", "capabilityCatalog"],
};

export default function CreatorProductionWorkspace() {
  const [current, setCurrent] = useState<CreatorProductionCurrent | null>(null);
  const [jobs, setJobs] = useState<CreatorProductionJob[]>([]);
  const [catalog, setCatalog] = useState<CreatorCapabilityCatalog | null>(null);
  const [pipeline, setPipeline] = useState<CreatorProductionPipeline | null>(null);
  const [renderJobs, setRenderJobs] = useState<CreatorRenderJob[]>([]);
  const [review, setReview] = useState<CreatorReview | null>(null);
  const [reviewContext, setReviewContext] = useState<CreatorReviewContext | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [reviewNoteId, setReviewNoteId] = useState<string | null>(null);
  const [reviewNoteTarget, setReviewNoteTarget] = useState<{
    sequenceId: string;
    elementId: string | null;
    absoluteFrame: number;
  } | null>(null);
  const [reviewNoteSaveStatus, setReviewNoteSaveStatus] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [playheadFrame, setPlayheadFrame] = useState(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Production is ready to inspect the active private project.");
  const [channelProfileId, setChannelProfileId] = useState("");
  const [channelProfiles, setChannelProfiles] = useState<Array<{ id: string; version: number }>>([]);
  const [studioElementId, setStudioElementId] = useState("");
  const [studioHandoff, setStudioHandoff] = useState<Record<string, unknown> | null>(null);
  const [studioEdits, setStudioEdits] = useState("[]");

  const refresh = useCallback(async () => {
    const next = await getCreatorProductionCurrent();
    setCurrent(next);
    if (next.initialized) {
      const [jobResult, capabilityResult, pipelineResult, renderResult] = await Promise.all([
        listCreatorProductionJobs(),
        getCreatorCapabilities(),
        getCreatorProductionPipeline(),
        listCreatorRenderJobs(),
      ]);
      setJobs(jobResult.jobs);
      setCatalog(capabilityResult);
      setPipeline(pipelineResult);
      setRenderJobs(renderResult.jobs);
      if (next.artifactAvailability?.reviewState) {
        const context = await getCreatorReview();
        setReview(context.review);
        setReviewContext(context);
      } else {
        setReview(null);
        setReviewContext(null);
      }
    }
  }, []);

  useEffect(() => {
    void refresh().catch((error: Error) => setMessage(error.message));
    void listCreatorChannelProfiles().then((result) => {
      setChannelProfiles(result.profiles);
      setChannelProfileId((currentId) => currentId || (
        result.profiles[0]
          ? `${result.profiles[0].id}@${result.profiles[0].version}`
          : ""
      ));
    }).catch((error: Error) => setMessage(error.message));
  }, [refresh]);

  useEffect(() => {
    if (
      !jobs.some((job) => ["queued", "running", "canceling"].includes(job.status))
      && !renderJobs.some((job) => ["queued", "running", "canceling"].includes(job.status))
    ) return;
    const timer = window.setInterval(() => {
      void refresh().catch((error: Error) => setMessage(error.message));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [jobs, refresh, renderJobs]);

  useEffect(() => {
    if (!reviewNote.trim() || !reviewNoteId || !reviewNoteTarget) return;
    const timer = window.setTimeout(() => {
      setReviewNoteSaveStatus("saving");
      void saveCreatorReviewNote({
        id: reviewNoteId,
        sequence_id: reviewNoteTarget.sequenceId,
        element_id: reviewNoteTarget.elementId,
        word_id: null,
        absolute_frame: reviewNoteTarget.absoluteFrame,
        note: reviewNote.trim(),
      }).then((result) => {
        setReview(result.review);
        setReviewNoteSaveStatus("saved");
      }).catch((error: Error) => {
        setReviewNoteSaveStatus("failed");
        setMessage(`Change request autosave failed: ${error.message}`);
      });
    }, 900);
    return () => window.clearTimeout(timer);
  }, [reviewNote, reviewNoteId, reviewNoteTarget]);

  const filteredCapabilities = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const items = catalog?.capabilities ?? [];
    if (!normalized) return items;
    return items.filter((item) =>
      [item.id, item.category, item.scope, item.implementationMaturity, item.technicalAdmission]
        .some((value) => value.toLowerCase().includes(normalized)),
    );
  }, [catalog, query]);

  const selectedReviewSequence = useMemo(
    () => reviewContext?.manifest.sequences.find(
      (item) => item.absoluteStartFrame <= playheadFrame
        && playheadFrame < item.absoluteEndFrameExclusive,
    ) ?? null,
    [playheadFrame, reviewContext],
  );

  async function initialize() {
    if (!channelProfileId) {
      setMessage("Add or select a versioned channel profile before initialization.");
      return;
    }
    setBusy(true);
    try {
      await initializeCreatorProduction(channelProfileId);
      await refresh();
      setMessage("Production authority, transcript timing, profiles, and native capability snapshot are locked.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function launch(taskKind: CreatorProductionJob["taskKind"]) {
    setBusy(true);
    try {
      const job = await createCreatorProductionJob(taskKind, JOB_INPUTS[taskKind]);
      const handoff = await getCreatorProductionHandoff(job.id);
      await navigator.clipboard.writeText(handoff.handoffPrompt);
      await refresh();
      setMessage(`${taskKind} handoff copied. Paste it into a normal visible Codex task.`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function upgradeWorkflow() {
    setBusy(true);
    try {
      await upgradeCreatorProductionWorkflow(
        "creator",
        "Creator explicitly approved clearing the faulty test and re-locking this project to the current production workflow package.",
      );
      await refresh();
      setMessage("The project is locked to the current production workflow. Stale downstream artifacts were superseded.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function adapt(sequence: CreatorProductionPipeline["adaptationDebt"][number]) {
    const candidate = sequence.candidates.find(
      (item) => item.capabilityId === sequence.decision?.topRankedCapabilityId,
    );
    if (!candidate || candidate.sourceResourceIds.length === 0) {
      setMessage(`No frozen source resource is available for ${sequence.id}.`);
      return;
    }
    setBusy(true);
    try {
      const job = await createCreatorProductionJob(
        "adapt",
        JOB_INPUTS.adapt,
        candidate.sourceResourceIds,
        { sequenceId: sequence.id, capabilityId: candidate.capabilityId },
      );
      const handoff = await getCreatorProductionHandoff(job.id);
      await navigator.clipboard.writeText(handoff.handoffPrompt);
      await refresh();
      setMessage(`Adaptation handoff copied for ${candidate.capabilityId} in ${sequence.id}.`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function copyHandoff(jobId: string) {
    try {
      const handoff = await getCreatorProductionHandoff(jobId);
      await navigator.clipboard.writeText(handoff.handoffPrompt);
      setMessage("Creator Production handoff copied. Paste it into a normal visible Codex task.");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  async function renderReview() {
    setBusy(true);
    try {
      const job = await createCreatorRenderJob();
      await startCreatorRenderJob(job.id);
      await refresh();
      setMessage("Final-quality chapter rendering started. Verified unchanged chapters will be reused.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    const sequence = selectedReviewSequence;
    if (!sequence || !reviewNote.trim()) {
      setMessage("Seek to a planned sequence and enter a change request.");
      return;
    }
    const noteId = reviewNoteId ?? `note-${Date.now()}`;
    const target = reviewNoteTarget ?? {
      sequenceId: sequence.id,
      elementId: studioElementId || null,
      absoluteFrame: playheadFrame,
    };
    try {
      setReviewNoteSaveStatus("saving");
      const result = await saveCreatorReviewNote({
        id: noteId,
        sequence_id: target.sequenceId,
        element_id: target.elementId,
        word_id: null,
        absolute_frame: target.absoluteFrame,
        note: reviewNote.trim(),
      });
      setReview(result.review);
      setReviewNote("");
      setReviewNoteId(null);
      setReviewNoteTarget(null);
      setReviewNoteSaveStatus("saved");
      setMessage("Change request saved privately.");
    } catch (error) {
      setReviewNoteSaveStatus("failed");
      setMessage((error as Error).message);
    }
  }

  function seekToNote(frame: number) {
    const fps = pipeline?.fps ? pipeline.fps.numerator / pipeline.fps.denominator : 30;
    if (videoRef.current) videoRef.current.currentTime = frame / fps;
    setPlayheadFrame(frame);
  }

  function seekToSequence(sequence: CreatorReviewSequence) {
    seekToNote(sequence.absoluteStartFrame);
    setStudioElementId("");
    setStudioHandoff(null);
  }

  function seekNextSequence() {
    const sequences = reviewContext?.manifest.sequences ?? [];
    if (sequences.length === 0) return;
    const next = sequences.find((item) => item.absoluteStartFrame > playheadFrame) ?? sequences[0];
    seekToSequence(next);
  }

  function seekNextFinding() {
    const findings = reviewContext?.preflight?.findings ?? [];
    const ordered = findings
      .filter((item) => Number.isInteger(item.absoluteFrame))
      .sort((first, second) => (first.absoluteFrame ?? 0) - (second.absoluteFrame ?? 0));
    if (ordered.length === 0) {
      setMessage("There are no automated findings with a review frame.");
      return;
    }
    const next = ordered.find((item) => (item.absoluteFrame ?? 0) > playheadFrame) ?? ordered[0];
    seekToNote(next.absoluteFrame ?? 0);
  }

  function seekNextActiveNote() {
    const ordered = [...(review?.activeNotes ?? [])].sort(
      (first, second) => first.absoluteFrame - second.absoluteFrame,
    );
    if (ordered.length === 0) {
      setMessage("There are no active review notes.");
      return;
    }
    const next = ordered.find((item) => item.absoluteFrame > playheadFrame) ?? ordered[0];
    seekToNote(next.absoluteFrame);
  }

  async function prepareStudioHandoff() {
    if (!selectedReviewSequence) {
      setMessage("Seek into a sequence before preparing a Studio handoff.");
      return;
    }
    try {
      const handoff = await createCreatorStudioHandoff({
        sequence_id: selectedReviewSequence.id,
        element_id: studioElementId || null,
        absolute_frame: playheadFrame,
      });
      setStudioHandoff(handoff);
      setMessage("Stable Studio selection context created for the current build.");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  async function saveStudioEdits() {
    if (!studioHandoff) {
      setMessage("Prepare a current Studio handoff before saving source edits.");
      return;
    }
    try {
      const edits = JSON.parse(studioEdits) as unknown;
      if (!Array.isArray(edits)) throw new Error("Studio edits must be a JSON array.");
      await applyCreatorStudioEdits(studioHandoff, edits as Array<Record<string, unknown>>);
      setStudioHandoff(null);
      setStudioEdits("[]");
      await refresh();
      setMessage("Studio edits were persisted as a versioned manifest source override. Only the affected chapter is dirty.");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  const activeJob = jobs.find((job) => ["queued", "running", "canceling"].includes(job.status));
  const activeRenderJob = renderJobs.find((job) => ["queued", "running", "canceling"].includes(job.status));
  const artifacts = current?.artifactAvailability ?? {};
  const nextTask: CreatorProductionJob["taskKind"] | null = !artifacts.analysisLedger
    ? "analyze"
    : !artifacts.semanticManifest
      ? "plan"
      : !artifacts.sourceEvidence
        ? "classify-layouts"
        : !artifacts.episodeManifest
          ? "materialize"
          : null;

  return (
    <main className="creator-production">
      <header className="creator-production-header">
        <div>
          <span className="eyebrow">Production-owned workflow</span>
          <h2>Creator Video Production</h2>
          <p>{message}</p>
        </div>
        <div className="creator-production-actions">
          <button onClick={() => void refresh()} disabled={busy}><RefreshCw size={16} /> Refresh</button>
          {!current?.initialized
            ? <button className="primary" onClick={() => void initialize()} disabled={busy}>Initialize Production</button>
            : current.workflowUpgradeRequired
              ? <button className="primary" onClick={() => void upgradeWorkflow()} disabled={busy}>
                  Upgrade workflow
                </button>
            : activeJob
              ? <button onClick={() => void cancelCreatorProductionJob(activeJob.id).then(refresh)}><Square size={14} /> Cancel</button>
              : nextTask
                ? <button className="primary" onClick={() => void launch(nextTask)} disabled={busy}>
                    <ClipboardCopy size={15} /> Prepare {nextTask}
                  </button>
                : <button disabled title="No automated task is currently eligible.">
                    Pipeline current
                  </button>}
        </div>
      </header>

      {current?.initialized ? (
        <>
          <section className="creator-production-cards">
            <article>
              <ShieldCheck size={21} />
              <strong>Instruction authority</strong>
              <span>Production only</span>
              <small>Immutable handoffs run only in a visible Codex task; application validators control promotion.</small>
            </article>
            <article>
              <CheckCircle2 size={21} />
              <strong>Timing authority</strong>
              <span>Locked transcript</span>
              <small>No inferred offsets, alignment pass, or duration-driven chaptering.</small>
            </article>
            <article>
              <strong className="creator-production-count">{catalog?.capabilities.length ?? 0}</strong>
              <strong>Native sources inventoried</strong>
              <span>{catalog?.inventorySummary?.productionSelectable ?? 0} currently admitted</span>
              <small>Source-only capabilities remain visible and become explicit adaptation work.</small>
            </article>
          </section>

          <section className="creator-production-grid">
            <article className="creator-production-panel">
              <div className="creator-production-panel-title">
                <div><span className="eyebrow">Pipeline</span><h3>Persistent jobs</h3></div>
              </div>
              <div className="creator-job-list">
                {jobs.length === 0 && <p className="muted">No Production tasks have run yet.</p>}
                {jobs.map((job) => (
                  <div className={`creator-job ${job.status}`} key={job.id}>
                    {job.status === "running" || job.status === "canceling"
                      ? <LoaderCircle className="spin" size={18} />
                      : job.status === "completed"
                        ? <CheckCircle2 size={18} />
                        : job.status === "failed"
                          ? <AlertTriangle size={18} />
                          : <span className="creator-job-dot" />}
                    <div>
                      <strong>{job.taskKind}</strong>
                      <span>{job.stage}</span>
                      {job.error && <small>{job.error}</small>}
                      {job.status === "queued" && job.handoffPacketRef
                        ? <button onClick={() => void copyHandoff(job.id)}>
                            <ClipboardCopy size={13} /> Copy handoff
                          </button>
                        : null}
                    </div>
                    <time>{new Date(job.updatedAt).toLocaleTimeString()}</time>
                  </div>
                ))}
              </div>
            </article>

            <article className="creator-production-panel capability-browser">
              <div className="creator-production-panel-title">
                <div><span className="eyebrow">Governance</span><h3>Native capability library</h3></div>
                <label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a rule, blueprint, or transition" /></label>
              </div>
              <div className="creator-capability-list">
                {filteredCapabilities.map((item) => (
                  <div key={item.id}>
                    <strong>{item.id.replace(/^hf-[^:]+:/, "")}</strong>
                    <span>{item.scope}</span>
                    <small>{item.implementationMaturity} · {item.technicalAdmission}</small>
                  </div>
                ))}
              </div>
            </article>
          </section>
          {pipeline && pipeline.adaptationDebt.length > 0 && (
            <section className="creator-production-panel creator-adaptation-debt">
              <div className="creator-production-panel-title">
                <div><span className="eyebrow">No silent fallback</span><h3>Capability adaptations required</h3></div>
                <span>{pipeline.adaptationDebt.length} sequence{pipeline.adaptationDebt.length === 1 ? "" : "s"}</span>
              </div>
              <p className="muted">These sequences have a strong native HyperFrames fit, but that recipe has not yet been compiled and admitted for the exact scene.</p>
              <div className="creator-debt-list">
                {pipeline.adaptationDebt.map((sequence) => (
                  <article key={sequence.id}>
                    <div>
                      <strong>{sequence.editorialJob}</strong>
                      <span>{sequence.id} · {sequence.semanticForm}</span>
                      <small>{sequence.decision?.topRankedCapabilityId ?? "No hard-valid candidate"}</small>
                    </div>
                    <button onClick={() => void adapt(sequence)} disabled={busy || Boolean(activeJob)}>
                      Adapt strongest fit
                    </button>
                  </article>
                ))}
              </div>
            </section>
          )}
          {pipeline && pipeline.sequences.length > 0 && (
            <section className="creator-production-panel creator-coverage-panel">
              <div className="creator-production-panel-title">
                <div><span className="eyebrow">Whole-video coverage</span><h3>One executable editorial plan</h3></div>
                <span>{pipeline.sequences.length} sequence{pipeline.sequences.length === 1 ? "" : "s"}</span>
              </div>
              <div className="creator-coverage-list">
                {pipeline.sequences.map((sequence) => (
                  <button
                    key={sequence.id}
                    onClick={() => {
                      const reviewSequence = reviewContext?.manifest.sequences.find((item) => item.id === sequence.id);
                      if (reviewSequence) seekToSequence(reviewSequence);
                    }}
                  >
                    <strong>{sequence.editorialJob}</strong>
                    <span>{sequence.semanticForm} · {sequence.presentationRole}</span>
                    <small>
                      frames {sequence.absoluteStartFrame.toLocaleString()}–{(sequence.absoluteEndFrameExclusive - 1).toLocaleString()}
                      {" · "}
                      {sequence.decision?.selectedCapabilityId ?? sequence.decision?.topRankedCapabilityId ?? "unresolved"}
                    </small>
                  </button>
                ))}
              </div>
            </section>
          )}
          {artifacts.semanticManifest && !artifacts.sourceEvidence && (
            <section className="creator-production-panel creator-evidence-panel">
              <div className="creator-production-panel-title">
                <div><span className="eyebrow">Measured source safety</span><h3>Agent capture-layout classification required</h3></div>
              </div>
              <p className="muted">Production inspects the locked source, assigns each frame span to one of the eight documented OBS layouts, and copies the locked speaker bounds. No dimensions are requested from the creator. Ambiguous or undocumented layouts remain blocking.</p>
            </section>
          )}
          {artifacts.buildLock && (!artifacts.reviewState || current.reviewStale) && (
            <section className="creator-production-panel creator-render-panel">
              <div>
                <span className="eyebrow">Final-quality review</span>
                <h3>{activeRenderJob ? activeRenderJob.message : "Render only the completed editorial chapters"}</h3>
                <p className="muted">This is the only visual approval render. Approved exact bytes become the final delivery; there is no second full render.</p>
              </div>
              {activeRenderJob ? (
                <div className="creator-render-progress">
                  <progress value={activeRenderJob.value} max={100} />
                  <span>{activeRenderJob.value}% · {activeRenderJob.stage}</span>
                  <button onClick={() => void cancelCreatorRenderJob(activeRenderJob.id).then(refresh)}>Cancel render</button>
                </div>
              ) : (
                <button className="primary" onClick={() => void renderReview()} disabled={busy}>Render final-quality review</button>
              )}
            </section>
          )}
          {review && !current.reviewStale && (
            <section className="creator-review-workspace">
              <div className="creator-review-player">
                <video
                  ref={videoRef}
                  src={creatorReviewVideoUrl()}
                  controls
                  onTimeUpdate={(event) => {
                    const fps = pipeline?.fps ? pipeline.fps.numerator / pipeline.fps.denominator : 30;
                    setPlayheadFrame(Math.round(event.currentTarget.currentTime * fps));
                  }}
                />
                <nav className="creator-review-navigation" aria-label="Review navigation">
                  <button onClick={seekNextSequence}>Next sequence</button>
                  <button onClick={seekNextFinding}>Next finding</button>
                  <button onClick={seekNextActiveNote}>Next active note</button>
                </nav>
                {selectedReviewSequence && (
                  <div className="creator-review-context">
                    <div>
                      <span className="eyebrow">Current selection</span>
                      <strong>{selectedReviewSequence.id}</strong>
                      <small>
                        {selectedReviewSequence.editorialJob} · {selectedReviewSequence.semanticForm}
                        {" · "}words {selectedReviewSequence.startWordId ?? "none"} → {selectedReviewSequence.endWordId ?? "none"}
                      </small>
                    </div>
                    <label>
                      Element
                      <select value={studioElementId} onChange={(event) => {
                        setStudioElementId(event.target.value);
                        setStudioHandoff(null);
                      }}>
                        <option value="">Sequence</option>
                        {selectedReviewSequence.compositionGraph.elements.map((element) => (
                          <option key={element.id} value={element.id}>{element.id} ({element.kind})</option>
                        ))}
                      </select>
                    </label>
                    <button onClick={() => void prepareStudioHandoff()}>Prepare Studio handoff</button>
                  </div>
                )}
                <div className="creator-review-compose">
                  <span>Frame {playheadFrame.toLocaleString()}</span>
                  <textarea value={reviewNote} onChange={(event) => {
                    const value = event.target.value;
                    if (value.trim() && !reviewNoteId && selectedReviewSequence) {
                      setReviewNoteId(`note-${Date.now()}`);
                      setReviewNoteTarget({
                        sequenceId: selectedReviewSequence.id,
                        elementId: studioElementId || null,
                        absoluteFrame: playheadFrame,
                      });
                    }
                    setReviewNote(value);
                    setReviewNoteSaveStatus("idle");
                  }} placeholder="Request a targeted change at this exact playhead…" />
                  <small className={`creator-note-save-status ${reviewNoteSaveStatus}`}>
                    {reviewNoteSaveStatus === "saving" && "Autosaving…"}
                    {reviewNoteSaveStatus === "saved" && "Saved"}
                    {reviewNoteSaveStatus === "failed" && "Save failed — your text is still here"}
                    {reviewNoteSaveStatus === "idle" && reviewNote.trim() && "Autosave pending"}
                  </small>
                  <button onClick={() => void saveNote()} disabled={!reviewNote.trim()}>Save change request</button>
                </div>
                {studioHandoff && (
                  <div className="creator-studio-adapter">
                    <div>
                      <span className="eyebrow">Manifest-aware Studio adapter</span>
                      <strong>Selection is bound to revision {reviewContext?.manifest.revision}</strong>
                      <small>Only allowlisted edits can return from Studio. Direct or stale source changes cannot render.</small>
                    </div>
                    <code>
                      {String(
                        (studioHandoff.studioContext as Record<string, unknown> | undefined)
                          ?.previewCommand ?? "",
                      )}
                    </code>
                    <textarea
                      value={studioEdits}
                      onChange={(event) => setStudioEdits(event.target.value)}
                      spellCheck={false}
                      placeholder={'[{"kind":"element-geometry","targetId":"title","path":"x","value":0.08}]'}
                    />
                    <button onClick={() => void saveStudioEdits()}>Save Studio edits to manifest</button>
                  </div>
                )}
              </div>
              <aside className="creator-review-notes">
                <div>
                  <span className="eyebrow">Active notes first</span>
                  <h3>{review.activeNotes.length} change request{review.activeNotes.length === 1 ? "" : "s"}</h3>
                </div>
                {review.activeNotes.map((note, index) => (
                  <article key={note.id}>
                    <button className="creator-note-jump" onClick={() => seekToNote(note.absoluteFrame)}>
                      <strong>{index + 1}. {note.sequenceId}</strong>
                      <span>Frame {note.absoluteFrame.toLocaleString()} · {note.saveStatus}</span>
                      <p>{note.note}</p>
                    </button>
                    <button
                      disabled={note.status !== "ready-for-review"}
                      title={note.status !== "ready-for-review" ? "Build and review this requested revision before accepting it." : ""}
                      onClick={() => void acceptCreatorReviewNote(note.id).then((result) => setReview(result.review))}
                    >
                      {note.status === "ready-for-review" ? "Accept revision" : "Awaiting revision"}
                    </button>
                  </article>
                ))}
                {review.activeNotes.length > 0 ? (
                  <button className="primary" onClick={() => void launch("revise")} disabled={busy || Boolean(activeJob)}>Build requested revisions</button>
                ) : (
                  <button className="primary" onClick={() => void approveCreatorReview().then((result) => {
                    setReview(result.review);
                    void refresh();
                    setMessage("Approved. The exact reviewed bytes are now the final delivery.");
                  })}>Approve current revision and render</button>
                )}
              </aside>
            </section>
          )}
        </>
      ) : (
        <section className="creator-production-empty">
          <ShieldCheck size={34} />
          <h3>Initialize the new production authority</h3>
          <p>This freezes the exact workflow, transcript timing, channel identity, HyperFrames sources, runtime, and licenses for this private project.</p>
          <label className="creator-channel-select">Channel identity<select value={channelProfileId} onChange={(event) => setChannelProfileId(event.target.value)}>
            {channelProfiles.map((profile) => (
              <option key={`${profile.id}@${profile.version}`} value={`${profile.id}@${profile.version}`}>
                {profile.id} · v{profile.version}
              </option>
            ))}
          </select></label>
          <button className="primary" onClick={() => void initialize()} disabled={busy || !channelProfileId}>Initialize Production</button>
        </section>
      )}
    </main>
  );
}
