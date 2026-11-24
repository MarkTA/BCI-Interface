import { create } from "zustand";
import {
  api,
  type ComparatorRequest,
  type ComparatorStart,
  type DigitalStatus,
  type PulseScope,
} from "../state/api";
import { thresholdSignature, useConfig, useRuntime } from "../state/store";
import { fpgaSerial } from "./fpgaSerial";
import { AFE_BIAS_V, validThresholds } from "./thresholdConfiguration";

export type ExperimentMode = "events" | "gpio";

type ExperimentRunState = {
  durationS: number;
  setDurationS: (seconds: number) => void;
  busy: boolean;
  error: string | null;
  lastMode: ExperimentMode | null;
  // Prevent duplicate background-to-UI auto-analysis if Step 6 remounts.
  autoAnalysisRequestedFor: string | null;
  plan: ComparatorStart | null;
  // Backend-reported AD3 output, independent of FPGA UART run state.
  output: DigitalStatus;
  scope: PulseScope | null;
  scopeBusy: boolean;
};

/** Transient run/session state is shared by Steps 5 and 6, surviving navigation.
 * Hardware acknowledgment and events still live in useRuntime (Zustand).
 */
export const useExperimentRun = create<ExperimentRunState>((set) => ({
  durationS: 10,
  setDurationS: (durationS) => set({ durationS }),
  busy: false,
  error: null,
  lastMode: null,
  autoAnalysisRequestedFor: null,
  plan: null,
  output: { active: false, mode: "idle" },
  scope: null,
  scopeBusy: false,
}));

export function isExperimentRunning(): boolean {
  return useRuntime.getState().runActive || useExperimentRun.getState().output.active;
}

export function canArmExperiment(): boolean {
  const runtime = useRuntime.getState();
  const thresholds = useConfig.getState().thresholdsMv;
  return runtime.serialConnected && !runtime.serialMock &&
    runtime.thresholdSendStatus !== "sending" && validThresholds(thresholds) &&
    runtime.appliedSignature === thresholdSignature(thresholds, AFE_BIAS_V);
}

/** Reactive readiness for both Step 5 GPIO debug and Step 6 experiments. */
export function useCanArmExperiment(): boolean {
  const thresholds = useConfig((s) => s.thresholdsMv);
  const connected = useRuntime((s) => s.serialConnected);
  const mock = useRuntime((s) => s.serialMock);
  const applied = useRuntime((s) => s.appliedSignature);
  const sending = useRuntime((s) => s.thresholdSendStatus === "sending");
  return connected && !mock && !sending && validThresholds(thresholds) &&
    applied === thresholdSignature(thresholds, AFE_BIAS_V);
}

function requestFor(mode: ExperimentMode): ComparatorRequest {
  const { datasetName, thresholdsMv } = useConfig.getState();
  return {
    dataset: datasetName,
    thresholds_mv: [...thresholdsMv],
    playback_speed: mode === "gpio" ? 0.25 : 1,
    gpio_debug_enabled: mode === "gpio",
    duration_s: useExperimentRun.getState().durationS,
  };
}

function validRequest(req: ComparatorRequest): boolean {
  return !!req.dataset && validThresholds(req.thresholds_mv) &&
    Number.isFinite(req.duration_s) && req.duration_s >= 1 && req.duration_s <= 60;
}

/** The serial service reports run_state asynchronously. Wait for Stop ACK. */
function waitForRunState(active: boolean, timeoutMs = 5000): Promise<void> {
  if (useRuntime.getState().runActive === active) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let settled = false;
    let unsubscribe = () => {};
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      unsubscribe();
      if (error) reject(error);
      else resolve();
    };
    const timer = setTimeout(() => finish(
      new Error(`FPGA did not acknowledge ${active ? "Start" : "Stop"} run.`),
    ), timeoutMs);
    unsubscribe = useRuntime.subscribe((state) => {
      if (state.runActive === active) finish();
    });
    if (useRuntime.getState().runActive === active) finish();
  });
}

// Shared between Steps 5/6 and the app-level AD3 status monitor.
let sawComparatorOutput = false;
// Ignore stale AD3 status responses that began before a run transition.
let runTransition = 0;

/** Existing two-stage run sequence: preview → arm FPGA → start AD3 playback.
 * GPIO debug remains accessible only from FPGA Setup; normal experiments from Run.
 */
export async function startExperiment(mode: ExperimentMode): Promise<void> {
  const state = useExperimentRun.getState();
  if (state.busy || isExperimentRunning()) return;
  if (useConfig.getState().signalSource !== "ad3") {
    useExperimentRun.setState({ error: "Select AD3 Simulation in FPGA Setup. Physical PCB runs are not yet supported." });
    return;
  }
  // A successful Step 3 connection test is required before a neural-event run.
  if (mode === "events" && useRuntime.getState().ad3Status !== "connected") {
    useExperimentRun.setState({ error: "Test the Analog Discovery connection in Step 3 before starting a run." });
    return;
  }
  const req = requestFor(mode);
  if (!validRequest(req) || !canArmExperiment()) return;

  ++runTransition;
  useExperimentRun.setState({ busy: true, error: null, plan: null, scope: null });
  let armed = false;
  try {
    const preview = await api.comparatorPreview(req);
    if (preview.warning) throw new Error(preview.warning);

    // Prevent a change to the dataset or thresholds during the async preview
    // from arming the FPGA for a different configuration than the UI shows.
    const currentReq = requestFor(mode);
    if (mode === "events" && useRuntime.getState().ad3Status !== "connected") {
      throw new Error("AD3 connection is no longer verified. Retest in Step 3.");
    }
    if (useConfig.getState().signalSource !== "ad3" || !canArmExperiment() || JSON.stringify(req) !== JSON.stringify(currentReq)) {
      throw new Error("Experiment settings changed during setup. Review and start again.");
    }

    useRuntime.getState().clearGpioTrace();
    sawComparatorOutput = false; // fresh run must not inherit the previous timeout marker
    armed = true; // best-effort cleanup if arming or AD3 startup fails
    await fpgaSerial.armRun(mode === "gpio");
    if (mode === "events" && useRuntime.getState().ad3Status !== "connected") {
      throw new Error("AD3 connection is no longer verified. Retest in Step 3.");
    }
    if (useConfig.getState().signalSource !== "ad3" || !canArmExperiment() || JSON.stringify(req) !== JSON.stringify(requestFor(mode))) {
      throw new Error("Experiment settings changed while arming. FPGA run canceled.");
    }
    const started = await api.comparatorStart(req);
    sawComparatorOutput = true;
    ++runTransition;
    useExperimentRun.setState({
      plan: started,
      lastMode: mode,
      output: { active: true, mode: "comparators" },
    });
    useRuntime.getState().addLog(
      "INFO",
      `${mode === "gpio" ? "GPIO debug" : "Neural event"} run: ${started.dataset}, ${started.cycle_duration_ms.toFixed(3)} ms/cycle`,
    );
  } catch (error) {
    ++runTransition;
    useExperimentRun.setState({ error: error instanceof Error ? error.message : String(error) });
    if (armed) {
      fpgaSerial.setRunActive(false);
      try { await api.digitalStop(); } catch { /* retain initial failure */ }
      sawComparatorOutput = false;
      useExperimentRun.setState({ output: { active: false, mode: "idle" } });
    }
  } finally {
    useExperimentRun.setState({ busy: false });
  }
}

export async function stopExperiment(): Promise<void> {
  if (useExperimentRun.getState().busy) return;
  ++runTransition;
  useExperimentRun.setState({ busy: true, error: null });
  try {
    if (useRuntime.getState().runActive) {
      if (!fpgaSerial.setRunActive(false)) {
        throw new Error("Could not send Stop to the FPGA serial bridge.");
      }
      // The existing backend also stops AD3 before confirming FPGA Stop.
      await waitForRunState(false);
    } else {
      await api.digitalStop();
    }
    sawComparatorOutput = false;
    ++runTransition;
    useExperimentRun.setState({ output: { active: false, mode: "idle" } });
  } catch (error) {
    useExperimentRun.setState({ error: error instanceof Error ? error.message : String(error) });
    // If UART goes away, still attempt to shut down physical AD3 outputs.
    try { await api.digitalStop(); } catch { /* keep the original error */ }
  } finally {
    useExperimentRun.setState({ busy: false });
  }
}

/** GPIO-only diagnostic capture, retained by Step 5. */
export async function captureGpioScope(): Promise<void> {
  if (useExperimentRun.getState().scopeBusy) return;
  useExperimentRun.setState({ scopeBusy: true, error: null });
  try {
    const scope = await api.digitalScope();
    useExperimentRun.setState({ scope });
  } catch (error) {
    useExperimentRun.setState({ error: error instanceof Error ? error.message : String(error) });
  } finally {
    useExperimentRun.setState({ scopeBusy: false });
  }
}

/** Poll continuously while App is mounted, even when neither step is visible.
 * If AD3 stops automatically at duration timeout, disarm FPGA event capture.
 */
export function monitorExperimentOutput(): () => void {
  let mounted = true;
  let polling = false;
  const poll = async () => {
    if (!mounted || polling) return;
    polling = true;
    const atRequest = runTransition;
    try {
      const status = await api.digitalStatus();
      if (!mounted || atRequest !== runTransition || useExperimentRun.getState().busy) return;
      useExperimentRun.setState({ output: status });
      if (status.active && status.mode === "comparators") sawComparatorOutput = true;
      if (!status.active && sawComparatorOutput && useRuntime.getState().runActive) {
        sawComparatorOutput = false;
        fpgaSerial.setRunActive(false);
      }
    } catch {
      if (mounted && atRequest === runTransition && !useExperimentRun.getState().busy) {
        useExperimentRun.setState({ output: { active: false, mode: "unknown" } });
      }
    } finally {
      polling = false;
    }
  };
  void poll();
  const timer = setInterval(() => { void poll(); }, 1000);
  return () => { mounted = false; clearInterval(timer); };
}
