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
import { AFE_BIAS_V, validThresholds, sendThresholdsToFpga } from "./thresholdConfiguration";

export type ExperimentMode = "events" | "gpio";

type ExperimentRunState = {
  durationS: number;
  setDurationS: (seconds: number) => void;
  busy: boolean;
  error: string | null;
  errorDetails: string | null;
  lastMode: ExperimentMode | null;
  // Prevent duplicate background-to-UI auto-analysis if Step 6 remounts.
  autoAnalysisRequestedFor: string | null;
  // Session-only result selection; never restore saved history on app startup.
  resultsRunId: string | null;
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
  errorDetails: null,
  lastMode: null,
  autoAnalysisRequestedFor: null,
  resultsRunId: null,
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

/** Human-facing guidance; keep the original SDK/transport message separately. */
export function describeRunError(raw: string, phase: "start" | "stop" | "status" = "start"): string {
  const action = phase === "start" ? "Run could not start." : phase === "stop" ? "Run cleanup encountered a problem." : "Analog Discovery needs attention.";
  if (/UART reconnect|USB-UART|Serial read failed|Serial connection (?:closed|disconnected)|Serial WebSocket|FPGA GPIO\/sync arm|FPGA GPIO mode acknowledgment/i.test(raw))
    return `${raw.startsWith("UART reconnect") ? "FPGA reconnection failed." : action} FPGA communication could not be verified. Reconnect the FTDI USB cable, then click Reconnect FPGA to reopen the previous COM port and verify the current thresholds. If Windows assigned a different port, select it in Step 4.`;
  if (/Cannot load WaveForms SDK|libdwf|dwf\.dll/i.test(raw))
    return `${action} WaveForms SDK is unavailable. Install or repair Digilent WaveForms and restart the backend.`;
  if (/no connected device|no available AD[23]|no device found|device not found|USB disconnected/i.test(raw))
    return `${action} Analog Discovery was not detected. Reconnect its USB cable, close WaveForms if it is open, click Stop / Recover or Retest AD3 to check the connection again.`;
  if (/FDwfDeviceOpen|device.*(?:busy|in use)|already opened/i.test(raw))
    return `${action} Could not open Analog Discovery. Check USB and close other applications using the instrument, then retry Stop / Recover or Retest AD3.`;
  if (/FDwfDigitalOut|Digital Out|AD3 (?:stop failed|recovery required)|Analog Discovery (?:stop|recovery|output)|SDK/i.test(raw))
    return `${action} Analog Discovery digital output could not be configured or stopped. Its output state may be unconfirmed. Check USB, retry Stop / Recover.`;
  if (/Analog Discovery connection validation failed/i.test(raw))
    return `${action} Analog Discovery did not pass its connection test. Check USB, close WaveForms if open, then retry Stop / Recover or Retest AD3.`;
  if (/serial bridge did not confirm|could not send Stop|connection closed before|UART disconnected|serial connection closed/i.test(raw))
    return `${action} FPGA UART cleanup was not confirmed. Reconnect the FPGA serial link and verify thresholds before another run.`;
  if (/capture counters not confirmed/i.test(raw))
    return `${action} FPGA event counters could not be verified. The recording is incomplete; check the FPGA statistics response before relying on the results.`;
  if (/GPIO.*(?:arm|acknowledg)|sync arm|FPGA.*acknowledg|FPGA.*not confirmed/i.test(raw))
    return `${action} FPGA did not confirm the requested operation. Check the UART wiring, FPGA build and acknowledgments.`;
  if (/disk full|persistent recording|recording is unavailable|snapshot failed/i.test(raw))
    return `${action} Experiment recording is unavailable. Check available disk space and write permissions.`;
  if (/failed to fetch|networkerror|network request|load failed|aborterror|timeouterror/i.test(raw))
    return `${action} The local backend did not respond. Check that it is running and retry recovery before starting another experiment.`;
  return `${action} ${raw}`;
}

function reportRunError(raw: string, phase: "start" | "stop" | "status", extra = ""): void {
  useExperimentRun.setState({ error: describeRunError(raw, phase) + (extra ? ` ${extra}` : ""), errorDetails: raw });
  useRuntime.getState().addLog("ERROR", raw);
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
  if (state.busy || isExperimentRunning() || requiresRecovery(state.output) || useRuntime.getState().ad3Status === "checking") return;
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
  useExperimentRun.setState({ busy: true, error: null, errorDetails: null, plan: null, scope: null, resultsRunId: null });
  let armed = false;
  let armConfirmed = false;
  let playbackAttempted = false;
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
    armConfirmed = true;
    if (mode === "events" && useRuntime.getState().ad3Status !== "connected") {
      throw new Error("AD3 connection is no longer verified. Retest in Step 3.");
    }
    if (useConfig.getState().signalSource !== "ad3" || !canArmExperiment() || JSON.stringify(req) !== JSON.stringify(requestFor(mode))) {
      throw new Error("Experiment settings changed while arming. FPGA run canceled.");
    }
    playbackAttempted = true;
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
    const message = error instanceof Error ? error.message : String(error);
    reportRunError(message, "start");
    if (armed) {
      await finishRun(true, message, playbackAttempted);
      if (!armConfirmed) {
        // A WebSocket can remain open after the USB adapter disappears, or the
        // FPGA may simply not answer. Do not keep stale verification in either case.
        if (useRuntime.getState().serialConnected) fpgaSerial.disconnect(message);
        reportRunError(message, "start", "FPGA verification was cleared; reconnect and verify before starting again.");
      }
    }
  } finally {
    useExperimentRun.setState({ busy: false });
  }
}

export function requiresRecovery(output: DigitalStatus): boolean {
  return output.mode === "recovery_required" || output.mode === "unknown" || output.mode === "stop_failed";
}

/** Finalize UART capture independently of Analog Discovery recovery. Only
 * disconnect the serial bridge as a last resort if its cleanup is unconfirmed. */
async function finishRun(startFailed = false, initialError: string | null = null, playbackAttempted = false, revalidate = false): Promise<void> {
  const errors: string[] = initialError ? [initialError] : [];
  const addError = (message: string) => { if (!errors.includes(message)) errors.push(message); };
  const text = (err: unknown) => err instanceof Error ? err.message : String(err);
  const hadSerial = useRuntime.getState().serialConnected;
  const needsSerialStop = startFailed || useRuntime.getState().runActive;
  let serialCleanupFailed = false;
  let output: DigitalStatus;
  try {
    if (needsSerialStop && hadSerial) {
      try {
        for (const message of await fpgaSerial.stopRun()) addError(message);
      } catch (err) {
        serialCleanupFailed = true;
        addError(text(err));
        // Only an unconfirmed serial recording lock needs this fallback.
        fpgaSerial.disconnect();
        useRuntime.getState().setRunActive(false);
      }
    } else if (needsSerialStop) {
      addError("UART disconnected before run cleanup was confirmed.");
      useRuntime.getState().setRunActive(false);
    }

    try {
      if (!needsSerialStop) {
        // Explicit Stop / Recover: retry the SDK after the user reconnects USB.
        output = await api.digitalStop();
      } else {
        output = await api.digitalStatus();
        if (output.active) output = await api.digitalStop();
      }
    } catch (err) {
      addError(text(err));
      try { output = await api.digitalStatus(); }
      catch { output = { active: false, mode: "unknown", outputs_low: false }; }
      if (!requiresRecovery(output) && !output.active) {
        output = { ...output, mode: "unknown", outputs_low: false };
      }
    }
    if (output.active || requiresRecovery(output)) {
      if (output.active && !requiresRecovery(output)) output = { ...output, mode: "unknown", outputs_low: false };
      addError(output.error ?? "Analog Discovery output stop not confirmed.");
      useRuntime.getState().setAd3Status("failed");
    } else if (playbackAttempted && initialError && /FDwf|WaveForms SDK|no available AD[23]|USB disconnected/i.test(initialError)) {
      useRuntime.getState().setAd3Status("failed");
    }
    useExperimentRun.setState({ output });
    if (revalidate && !output.active && !requiresRecovery(output)) {
      // A successful SDK stop is not a connection test. Reuse Step 3's
      // acquisition diagnostic only on explicit recovery, not normal stops.
      useRuntime.getState().setAd3Status("checking");
      try {
        const result = await api.ad3Connection();
        if (!result.ready) throw new Error(result.message || result.warning || "Readiness check did not pass");
        useRuntime.getState().setAd3Status("connected");
        useRuntime.getState().addLog("INFO", "Analog Discovery connection revalidated after recovery.");
      } catch (err) {
        useRuntime.getState().setAd3Status("failed");
        addError(`Analog Discovery connection validation failed: ${text(err)}`);
        // The diagnostic can invalidate the SDK handle if it fails. Keep
        // the stop/recovery button available when the backend needs recovery.
        try { output = await api.digitalStatus(); }
        catch { output = { active: false, mode: "unknown", outputs_low: false }; }
        useExperimentRun.setState({ output });
      }
    }
  } finally {
    sawComparatorOutput = false;
    ++runTransition;
    if (errors.length) {
      const primary = errors[0];
      const extra = serialCleanupFailed ? "UART was disconnected because recording cleanup could not be confirmed." :
        hadSerial && useRuntime.getState().serialConnected ? "FPGA UART remains connected; threshold acknowledgments are retained." : "";
      reportRunError(primary, startFailed ? "start" : "stop", extra);
      useExperimentRun.setState({ errorDetails: errors.join("\n") });
      for (const message of errors.slice(1)) useRuntime.getState().addLog("ERROR", message);
    }
  }
}

export async function stopExperiment(initialError: string | null = null): Promise<void> {
  const state = useExperimentRun.getState();
  const ad3Status = useRuntime.getState().ad3Status;
  if (state.busy || (ad3Status === "checking" && !isExperimentRunning())) return;
  const revalidate = initialError === null && !isExperimentRunning() &&
    (requiresRecovery(state.output) || ad3Status === "failed");
  ++runTransition;
  useExperimentRun.setState({ busy: true, error: null, errorDetails: null });
  try {
    await finishRun(false, initialError, false, revalidate);
  } finally {
    useExperimentRun.setState({ busy: false });
  }
}


/** Explicit recovery, never resume a failed experiment or trust old ACKs. */
export async function recoverFpga(): Promise<void> {
  const state = useExperimentRun.getState();
  const runtime = useRuntime.getState();
  if (state.busy || isExperimentRunning() || requiresRecovery(state.output) || runtime.thresholdSendStatus === "sending" || runtime.serialStatus === "Connecting...") return;
  const port = runtime.lastSerialPort;
  const baud = runtime.lastSerialBaud ?? 115200;
  if (!port) return;
  ++runTransition;
  useExperimentRun.setState({ busy: true, error: null, errorDetails: null });
  try {
    // If the old socket was still open, close it and allow the bridge to release the port.
    if (fpgaSerial.active) fpgaSerial.disconnect();
    // USB removal may still be finalizing the old bridge. Retry only that
    // transient ownership error, and never substitute another port.
    for (let attempt = 0; ; attempt++) {
      try { await fpgaSerial.reconnect(port, baud); break; }
      catch (err) {
        if (attempt >= 4 || !/already in use by another session/i.test(String(err))) throw err;
        await new Promise(resolve => setTimeout(resolve, 600));
      }
    }
    await sendThresholdsToFpga();
    if (!canArmExperiment()) throw new Error(useRuntime.getState().thresholdSendMessage || "Incomplete FPGA threshold verification");
    useRuntime.getState().addLog("INFO", `FPGA reconnected on ${port} and all eight threshold acknowledgments verified.`);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    fpgaSerial.disconnect(message);
    reportRunError(`UART reconnect on ${port} failed: ${message}`, "start");
  } finally {
    ++runTransition;
    useExperimentRun.setState({ busy: false });
  }
}

/** GPIO-only diagnostic capture, retained by Step 5. */
export async function captureGpioScope(): Promise<void> {
  if (useExperimentRun.getState().scopeBusy) return;
  useExperimentRun.setState({ scopeBusy: true, error: null, errorDetails: null });
  try {
    const scope = await api.digitalScope();
    useExperimentRun.setState({ scope });
  } catch (error) {
    reportRunError(error instanceof Error ? error.message : String(error), "status");
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
      if (requiresRecovery(status)) {
        useRuntime.getState().setAd3Status("failed");
        if (!useExperimentRun.getState().error) {
          reportRunError(status.error ?? "Analog Discovery output state is unconfirmed.", "status");
        }
      }
      if (status.active && status.mode === "comparators") sawComparatorOutput = true;
      if (sawComparatorOutput && status.active && !useRuntime.getState().serialConnected) {
        // The backend also stops playback on socket loss; retry independently if needed.
        void stopExperiment("USB-UART connection lost during playback; capture interrupted.");
        return;
      }
      if (!status.active && sawComparatorOutput && useRuntime.getState().runActive) {
        sawComparatorOutput = false;
        void stopExperiment(requiresRecovery(status) ? status.error ?? "Analog Discovery automatic stop failed." : null);
      }
    } catch {
      if (mounted && atRequest === runTransition && !useExperimentRun.getState().busy) {
        // Keep the previous active state visible if polling alone fails.
        useExperimentRun.setState((state) => ({ output: { ...state.output, mode: "unknown" } }));
      }
    } finally {
      polling = false;
    }
  };
  void poll();
  const timer = setInterval(() => { void poll(); }, 1000);
  return () => { mounted = false; clearInterval(timer); };
}
