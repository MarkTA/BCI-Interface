import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../state/api";
import { useRuntime } from "../state/store";
import { useExperimentRun } from "./experimentRun";
import type { ValidateOptions } from "./validationRuns";

/** Step 6 data lifecycle. Saved experiment history is backend-owned, independent of the live event list. */
export function useRunValidation() {
  const client = useQueryClient();
  const sessionRunId = useExperimentRun((s) => s.resultsRunId);
  const runBusy = useExperimentRun((s) => s.busy);
  const lastFinished = useRuntime((s) => s.lastFinishedRecording);
  const runActive = useRuntime((s) => s.runActive);
  const outputActive = useExperimentRun((s) => s.output.active);
  const plan = useExperimentRun((s) => s.plan);
  const [analysisFailure, setAnalysisFailure] = useState<{ runId: string; message: string } | null>(null);
  const autoAttempts = useRef(new Set<string>());
  const busy = runBusy || runActive || outputActive;
  // Mask the selection immediately during arming, playback, and final capture drain.
  const selectedRunId = busy ? null : sessionRunId;

  const runs = useQuery({
    queryKey: ["recorded-runs"],
    queryFn: api.recordedRuns,
    refetchInterval: busy ? 3000 : false,
  });

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
      setAnalysisFailure((previous) => previous?.runId === runId ? null : previous);
    },
    onError: (error, { runId }) => setAnalysisFailure({ runId, message: error instanceof Error ? error.message : String(error) }),
  });

  // Only automatically validate a successful Step 6 event playback, using the
  // exact backend run ID returned by the AD3 start call. GPIO diagnostics and
  // abandoned arming attempts are never mistaken for neural-event experiments.
  useEffect(() => {
    const runId = lastFinished?.run_id;
    if (busy || !runId || lastFinished?.mode !== "events" || plan?.recording_run_id !== runId) return;
    // Do not reselect an already handled run on remount or after clearing history.
    if (useExperimentRun.getState().autoAnalysisRequestedFor === runId) return;
    useExperimentRun.setState({ resultsRunId: runId, autoAnalysisRequestedFor: runId });
    void client.invalidateQueries({ queryKey: ["recorded-runs"] });
    void client.invalidateQueries({ queryKey: ["recorded-run", runId] });
    setAnalysisFailure(null);
    // An assumed first-event anchor provides a diagnostic comparison only.
    // It NEVER establishes an independent start time or hardware PASS.
    autoAttempts.current.add(runId);
    validation.mutate({ runId, options: { alignment: { mode: "event_anchor", reference_index: 0, observed_index: 0 } } });
  // Mutation is stable in TanStack Query. Only re-run on a new finalized run.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastFinished?.run_id, plan?.recording_run_id, busy, client]);

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
    setAnalysisFailure(null);
    validation.mutate({ runId: selectedRunId, options });
  };

  return {
    selectedRunId, setSelectedRunId: (runId: string) => {
      if (busy) return;
      useExperimentRun.setState({ resultsRunId: runId || null });
      setAnalysisFailure(null);
    },
    runs: runs.data?.runs ?? [],
    runsLoading: runs.isPending,
    runsError: runs.error,
    manifest: selectedRunId ? manifest.data ?? null : null,
    manifestError: selectedRunId ? manifest.error : null,
    report: selectedRunId ? saved.data ?? null : null,
    reportError: selectedRunId ? saved.error : null,
    loadingReport: saved.isPending && !!selectedRunId,
    validating: validation.isPending && validation.variables?.runId === selectedRunId,
    analysisError: selectedRunId && analysisFailure?.runId === selectedRunId ? analysisFailure.message : null,
    busy,
    analyze,
  };
}
