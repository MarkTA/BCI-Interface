import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../state/api";
import { useRuntime } from "../state/store";
import { useExperimentRun } from "./experimentRun";
import type { ValidateOptions } from "./validationRuns";

/** Step 6 data lifecycle. History is backend-owned, not the 250-event UI buffer. */
export function useRunValidation() {
  const client = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const lastFinished = useRuntime((s) => s.lastFinishedRecording);
  const runActive = useRuntime((s) => s.runActive);
  const outputActive = useExperimentRun((s) => s.output.active);
  const plan = useExperimentRun((s) => s.plan);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const autoAttempts = useRef(new Set<string>());
  const busy = runActive || outputActive;

  const runs = useQuery({
    queryKey: ["recorded-runs"],
    queryFn: api.recordedRuns,
    refetchInterval: busy ? 3000 : false,
  });
  useEffect(() => {
    if (!selectedRunId && runs.data?.runs.length) {
      setSelectedRunId(runs.data.runs[0].run_id);
    }
  }, [runs.data, selectedRunId]);

  const manifest = useQuery({
    queryKey: ["recorded-run", selectedRunId],
    queryFn: () => api.recordedRun(selectedRunId!),
    enabled: !!selectedRunId,
  });
  const saved = useQuery({
    queryKey: ["run-validation", selectedRunId],
    queryFn: () => api.savedValidation(selectedRunId!),
    enabled: !!selectedRunId,
    retry: 1,
  });

  const validation = useMutation({
    mutationFn: ({ runId, options }: { runId: string; options: ValidateOptions }) =>
      api.validateRecordedRun(runId, options),
    onSuccess: (result, { runId }) => {
      client.setQueryData(["run-validation", runId], result);
      void client.invalidateQueries({ queryKey: ["recorded-run", runId] });
      setAnalysisError(null);
    },
    onError: (error) => setAnalysisError(error instanceof Error ? error.message : String(error)),
  });

  // Only automatically validate a successful Step 6 event playback, using the
  // exact backend run ID returned by the AD3 start call. GPIO diagnostics and
  // abandoned arming attempts are never mistaken for neural-event experiments.
  useEffect(() => {
    const runId = lastFinished?.run_id;
    if (!runId || lastFinished?.mode !== "events" || plan?.recording_run_id !== runId) return;
    setSelectedRunId(runId);
    void client.invalidateQueries({ queryKey: ["recorded-runs"] });
    void client.invalidateQueries({ queryKey: ["recorded-run", runId] });
    if (useExperimentRun.getState().autoAnalysisRequestedFor === runId) return;
    useExperimentRun.setState({ autoAnalysisRequestedFor: runId });
    setAnalysisError(null);
    // An assumed first-event anchor provides a diagnostic comparison only.
    // It NEVER establishes an independent start time or hardware PASS.
    autoAttempts.current.add(runId);
    validation.mutate({ runId, options: { alignment: { mode: "event_anchor", reference_index: 0, observed_index: 0 } } });
  // Mutation is stable in TanStack Query. Only re-run on a new finalized run.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastFinished?.run_id, plan?.recording_run_id, client]);

  // Legacy recordings may have been analyzed without alignment. Automatically
  // generate an explicitly exploratory comparison once, rather than forcing
  // the demonstrator to find the manual anchor controls.
  useEffect(() => {
    const runId = selectedRunId;
    if (!runId || busy || validation.isPending || saved.isPending || manifest.isPending) return;
    if (autoAttempts.current.has(runId)) return;
    const run = manifest.data;
    if (!run || run.status !== "completed" || run.playback.status !== "stopped") return;
    if (saved.data?.matching.status !== "alignment_required" && saved.data) return;
    autoAttempts.current.add(runId);
    validation.mutate({ runId, options: {
      alignment: { mode: "event_anchor", reference_index: 0, observed_index: 0 },
    } });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId, busy, saved.isPending, saved.data, manifest.isPending, manifest.data, validation.isPending]);

  const analyze = (options: ValidateOptions = {}) => {
    if (!selectedRunId || busy || validation.isPending) return;
    setAnalysisError(null);
    validation.mutate({ runId: selectedRunId, options });
  };

  return {
    selectedRunId, setSelectedRunId: (runId: string) => { setSelectedRunId(runId || null); setAnalysisError(null); },
    runs: runs.data?.runs ?? [],
    runsLoading: runs.isPending,
    runsError: runs.error,
    manifest: manifest.data ?? null,
    manifestError: manifest.error,
    report: saved.data ?? null,
    reportError: saved.error,
    loadingReport: saved.isPending && !!selectedRunId,
    validating: validation.isPending && validation.variables?.runId === selectedRunId,
    analysisError,
    busy,
    analyze,
  };
}
