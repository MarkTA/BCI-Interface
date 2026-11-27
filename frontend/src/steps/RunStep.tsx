import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import "./RunResults.css";
import DipSwitch from "../components/DipSwitch";
import NeuralEventPanel from "../components/NeuralEventPanel";
import StepAboutModal from "../components/StepAboutModal";
import {
  RunSelector, ValidationBanner, ResultsOverview, PerformanceSummary, ReferenceComparison,
  ExperimentLog, ExportResults,
} from "../components/RunValidationPanels";
import { useRunValidation } from "../services/useRunValidation";
import { ScopePair } from "../components/ScopeView";
import { api } from "../state/api";
import { useConfig, useRuntime, thresholdSignature } from "../state/store";
import {
  AFE_BIAS_V,
  DAC_REFERENCE_V,
  dacCode,
  validThresholds,
  sendThresholdsToFpga,
} from "../services/thresholdConfiguration";
import {
  useExperimentRun,
  useCanArmExperiment,
  startExperiment,
  stopExperiment,
  requiresRecovery,
  recoverFpga,
} from "../services/experimentRun";

// Use the same dataset list, selected name, and preview query as Step 2.
// Creating, uploading, and downloading CSVs remain exclusive to Step 2.
function ExistingDatasetSelector() {
  const name = useConfig((s) => s.datasetName);
  const setName = useConfig((s) => s.setDatasetName);
  const setPreview = useRuntime((s) => s.setPreview);
  const setCapture = useRuntime((s) => s.setCapture);
  const runActive = useRuntime((s) => s.runActive);
  const runBusy = useExperimentRun((s) => s.busy);
  const outputActive = useExperimentRun((s) => s.output.active);

  const names = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const preview = useQuery({
    queryKey: ["dataset", name],
    queryFn: () => api.dataset(name),
    enabled: !!name,
    retry: 1,
  });

  // Step 2 uses the same React Query cache and runtime preview state.
  // This keeps the system status and subsequent experiment data in sync
  // even when the user changes datasets without visiting Step 2.
  useEffect(() => {
    if (!preview.data || preview.data.name !== name) return;
    const previous = useRuntime.getState().preview;
    if (previous?.name !== preview.data.name) setCapture(null);
    setPreview(preview.data);
  }, [name, preview.data, setPreview, setCapture]);

  const available = names.data?.datasets ?? [];

  return (
    <div>
      <label htmlFor="run-dataset">Dataset</label>
      <select
        id="run-dataset"
        value={name}
        onChange={(event) => {
          const selected = event.target.value;
          if (selected === name) return;
          // Avoid displaying the previous waveform while loading the new CSV.
          setPreview(null);
          setCapture(null);
          setName(selected);
        }}
        disabled={names.isPending || names.isError || available.length === 0 || runActive || runBusy || outputActive}
      >
        {name && !available.includes(name) && (
          <option value={name} disabled>
            {name.replaceAll("_", " ")}
            {names.isPending ? " (loading…)" : " (not in dataset list)"}
          </option>
        )}
        {available.map((dataset) => (
          <option key={dataset} value={dataset}>
            {dataset.replaceAll("_", " ")}
          </option>
        ))}
      </select>
      {names.isPending && <p className="hint">Loading datasets…</p>}
      {names.isSuccess && available.length === 0 && (
        <p className="hint">No datasets available. Add one in Step 2.</p>
      )}
      {names.isError && (
        <p className="error" role="alert">
          Dataset list: {String(names.error)}
        </p>
      )}
      {preview.isError && (
        <p className="error" role="alert">
          Dataset preview: {String(preview.error)}
        </p>
      )}
    </div>
  );
}

// Shares requested threshold values with Step 4. Transmission lives in one
// shared service and remains independent of the mounted React step.
const THRESHOLD_GROUPS = [
  { title: "Positive", labels: ["P1", "P2", "P3", "P4"], start: 0 },
  { title: "Negative", labels: ["N1", "N2", "N3", "N4"], start: 4 },
] as const;

function CompactThresholdInputs() {
  const thresholds = useConfig((s) => s.thresholdsMv);
  const setThreshold = useConfig((s) => s.setThreshold);
  const runActive = useRuntime((s) => s.runActive);
  const connected = useRuntime((s) => s.serialConnected);
  const mock = useRuntime((s) => s.serialMock);
  const acks = useRuntime((s) => s.thresholdAcks);
  const runBusy = useExperimentRun((s) => s.busy);
  const outputActive = useExperimentRun((s) => s.output.active);
  const locked = runActive || runBusy || outputActive;

  const valid = validThresholds(thresholds);

  return (
    <div className="run-thresholds">
      <div className="run-threshold-groups">
        {THRESHOLD_GROUPS.map((group) => (
          <fieldset key={group.title} className="run-threshold-group" disabled={locked}>
            <legend>{group.title} Thresholds (mV)</legend>
            <div className="run-threshold-inputs">
              {group.labels.map((label, offset) => {
                const index = group.start + offset;
                const mv = thresholds[index];
                const ack = acks[index];
                // Compare the echoed 16-bit DAC code with the current input.
                // This confirms FPGA SPI encoding, not the physical DAC voltage.
                const dacVoltage = AFE_BIAS_V + mv / 1000;
                const channelValid = Number.isFinite(mv) &&
                  dacVoltage >= 0 && dacVoltage <= DAC_REFERENCE_V &&
                  (index < 4 ? mv >= 0 : mv <= 0);
                const expectedCode = channelValid
                  ? `0x${dacCode(dacVoltage).toString(16).padStart(4, "0").toUpperCase()}`
                  : null;
                const confirmed = connected && !mock && ack?.channel === index &&
                  ack.status === "encoded" && ack.dac_code.toUpperCase() === expectedCode?.toUpperCase();
                const modified = connected && !mock && !!ack && !confirmed;
                const feedback = confirmed
                  ? "FPGA acknowledged (SPI encoded)"
                  : modified
                    ? "Changed since FPGA acknowledgment — resend thresholds"
                    : "Not acknowledged by FPGA";

                return (
                  <label key={label}>
                    <span className="run-threshold-channel">
                      {label}
                      {confirmed && <span className="run-threshold-check" aria-hidden="true">✓</span>}
                      {modified && <span className="run-threshold-modified" aria-hidden="true">•</span>}
                    </span>
                    <input
                      className={confirmed ? "run-threshold-confirmed" : modified ? "run-threshold-pending" : undefined}
                      type="number"
                      aria-label={`${label} threshold in millivolts; ${feedback}`}
                      title={`${label}: ${feedback}`}
                      step="0.5"
                      min={index < 4 ? 0 : -1600}
                      max={index < 4 ? 900 : 0}
                      value={mv ?? ""}
                      onChange={(event) => {
                        if (!locked) setThreshold(index, Number(event.target.value));
                      }}
                    />
                  </label>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>
      {!valid && (
        <p className="error" role="alert">
          Thresholds must produce 0–2.5 V DAC values; P ≥ 0 mV and N ≤ 0 mV.
        </p>
      )}
      {locked && (
        <p className="hint" role="status">
          Threshold editing is locked during a run.
        </p>
      )}
    </div>
  );
}

// Threshold status and send control share the same runtime state and apply
// function as the full diagnostic view in Comparator Step 4.
function ThresholdRunControl() {
  const dataset = useConfig((s) => s.datasetName);
  const signalSource = useConfig((s) => s.signalSource);
  const thresholds = useConfig((s) => s.thresholdsMv);
  const connected = useRuntime((s) => s.serialConnected);
  const mock = useRuntime((s) => s.serialMock);
  const serialPort = useRuntime((s) => s.serialPort);
  const lastSerialPort = useRuntime((s) => s.lastSerialPort);
  const serialStatus = useRuntime((s) => s.serialStatus);
  const fpgaVerified = useRuntime((s) => s.fpgaVerified);
  const ad3Status = useRuntime((s) => s.ad3Status);
  const runActive = useRuntime((s) => s.runActive);
  const appliedSignature = useRuntime((s) => s.appliedSignature);
  const sendStatus = useRuntime((s) => s.thresholdSendStatus);
  const sendMessage = useRuntime((s) => s.thresholdSendMessage);

  const durationS = useExperimentRun((s) => s.durationS);
  const setDurationS = useExperimentRun((s) => s.setDurationS);
  const busy = useExperimentRun((s) => s.busy);
  const error = useExperimentRun((s) => s.error);
  const errorDetails = useExperimentRun((s) => s.errorDetails);
  const output = useExperimentRun((s) => s.output);
  const lastMode = useExperimentRun((s) => s.lastMode);
  const plan = useExperimentRun((s) => s.plan);
  const [infoOpen, setInfoOpen] = useState(false);
  const closeInfo = useCallback(() => setInfoOpen(false), []);

  const valid = validThresholds(thresholds);
  const applied = connected && !mock &&
    appliedSignature === thresholdSignature(thresholds, AFE_BIAS_V);
  const sending = sendStatus === "sending";
  const running = runActive || output.active;
  const recovery = requiresRecovery(output);
  const canArm = useCanArmExperiment();
  const ad3Ready = ad3Status === "connected";
  const retestAd3 = !running && !recovery && ad3Status === "failed";
  const reconnectFpga = !running && !recovery && !retestAd3 && !connected && !!lastSerialPort;
  const validRun = signalSource === "ad3" && ad3Ready && !!dataset && valid &&
    Number.isFinite(durationS) && durationS >= 1 && durationS <= 60;
  const status = !connected
    ? "FPGA disconnected"
    : mock
      ? "Mock mode — physical FPGA required"
      : !valid
        ? "Invalid thresholds"
        : sending
          ? "Sending…"
          : applied
            ? "8/8 FPGA acknowledged"
            : "Thresholds not applied";

  return (
    <>
      <div className="actions" style={{ alignItems: "end", gap: 12, flexWrap: "wrap" }}>
        <label htmlFor="run-duration">
          Duration (s)
          <input
            id="run-duration"
            style={{ width: 94 }}
            type="number"
            min={1}
            max={60}
            step={1}
            value={durationS}
            disabled={busy || running}
            onChange={(event) => setDurationS(Number(event.target.value))}
          />
        </label>
        <button
          type="button"
          disabled={running || busy || sending || !connected || mock || !valid || applied}
          onClick={() => void sendThresholdsToFpga()}
        >
          {sending ? "Sending thresholds…" : "Send Thresholds"}
        </button>
        <button
          type="button"
          className={running || recovery || retestAd3 || reconnectFpga ? "" : "primary"}
          disabled={busy || serialStatus === "Connecting..." || ad3Status === "checking" || (!running && !recovery && !retestAd3 && !reconnectFpga && (!canArm || !validRun))}
          onClick={() => void (running || recovery || retestAd3 ? stopExperiment() : reconnectFpga ? recoverFpga() : startExperiment("events"))}
        >
          {busy ? (ad3Status === "checking" ? "Validating AD3…" : sending ? "Verifying FPGA…" : reconnectFpga ? "Reconnecting FPGA…" : "Working…") : recovery ? "Stop / Recover" : running ? "■ Stop Run" : retestAd3 ? "Retest AD3" : reconnectFpga ? `Reconnect FPGA (${lastSerialPort})` : "▶ Start Run"}
        </button>
      </div>
      <div className="run-compact-status">
        <span className={applied ? "badge online" : "badge"} role="status">{status}</span>
        <span>{ad3Ready ? "AD3 ready" : `AD3: ${ad3Status}`}</span>
        <span>{connected && !mock ? (serialPort ?? "UART ready") : "UART disconnected"}</span>
        <span>{fpgaVerified ? "FPGA verified" : "FPGA not verified"}</span>
        <strong>{recovery ? "Recovery required" : running ? (lastMode === "gpio" ? "GPIO debug" : "Running") : "Idle"}</strong>
        <button type="button" className="run-info-button" onClick={() => setInfoOpen(true)}>ⓘ Run info</button>
      </div>
      {!running && !recovery && signalSource === "pcb" && <p className="hint run-compact-notice" role="status">Physical PCB playback is not yet supported.</p>}
      {!running && !recovery && signalSource === "ad3" && !ad3Ready && !busy && <p className="hint run-compact-notice" role="status">{retestAd3 ? "Reconnect Analog Discovery and click Retest AD3." : "Test the Analog Discovery connection in Step 3."}</p>}
      {!running && !recovery && ad3Ready && signalSource === "ad3" && !canArm && <p className="hint run-compact-notice">{reconnectFpga ? `Reconnect the FTDI USB cable, then click Reconnect FPGA (${lastSerialPort}). All eight thresholds will be verified again. If the port changed, select it in Step 4.` : "Connect the physical FPGA and apply all eight thresholds."}</p>}
      {!connected && !error && serialStatus !== "Disconnected" && !busy && <p className="hint run-compact-notice" role="status">UART: {serialStatus}</p>}
      {error && <div className="error" role="alert">
        <div>{error}</div>
        {errorDetails && <details style={{ marginTop: 6 }}>
          <summary>Technical details</summary>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", marginBottom: 0 }}>{errorDetails}</pre>
        </details>}
      </div>}
      {sendStatus === "error" && sendMessage && <p role="alert" className="error">{sendMessage}</p>}
      {sendStatus === "success" && !applied && <p className="hint run-compact-notice" role="status">Thresholds changed. Send the current values again.</p>}
      {infoOpen && <StepAboutModal onClose={closeInfo} config={{
        buttonLabel: "Run info", title: "Run Information", sections: [
          { heading: "Thresholds and playback", paragraphs: [
            "Threshold acknowledgments confirm FPGA SPI encoding, not physical DAC voltage.",
            "The current run controller drives Analog Discovery digital comparator simulation at 1× playback. Physical PCB playback will be added during hardware integration.",
            ...(sendMessage ? [sendMessage] : []),
          ] },
          { heading: "Last playback", paragraphs: plan && lastMode === "events" ? [
            `${plan.dataset} · CSV peak ${plan.source_peak_uv.toFixed(1)} µV · Modeled AFE peak ${plan.afe_peak_mv.toFixed(1)} mV · ${plan.cycle_duration_ms.toFixed(3)} ms/cycle`,
          ] : ["No event playback recorded yet." ] },
          { heading: "Neural event stream", paragraphs: [
            "Live AA 02 packets are decoded FPGA events, not comparator GPIO transitions. The preview shows the latest four; View all and CSV include events received by the console for the current or last armed run. The next run clears the live list.",
            "The FPGA timestamp is a 24-bit microsecond counter and wraps every 16.777216 seconds. Quiet confirmation (500 µs), refractory (100 µs), and timeout (2.5 ms) determine how comparator activity is grouped. A repeating dataset may generate more or fewer than one event per cycle.",
            "Saved experiment ZIPs and validation results remain the authoritative persistent record, independent of the live list.",
          ] },
        ],
      }} />}
    </>
  );
}

// Native details keep every diagnostic independently expandable.
function ResultDetails({ title, status, children }: { title: string; status?: string; children: ReactNode }) {
  return <details className="results-detail">
    <summary><span>{title}</span>{status && <span className="results-detail__status">{status}</span>}</summary>
    <div className="results-detail__body">{children}</div>
  </details>;
}

// Results are backed by immutable run records, independent of the live event viewer.
export default function RunStep() {
  const results = useRunValidation();
  const report = results.report;
  const warnings = report ? new Set([...report.warnings, ...report.validation.warnings]).size : 0;
  const recordingErrors = results.manifest?.errors?.length ?? 0;
  return (
    <section className="workspace-panel">
      <section className="card" aria-labelledby="experiment-config-heading">
        <h2 id="experiment-config-heading">Experiment Configuration</h2>
        <div className="run-config-layout">
          <div className="run-config-fields">
            <ExistingDatasetSelector />
            <DipSwitch compact />
          </div>
          <CompactThresholdInputs />
        </div>
      </section>

      <section className="card" aria-labelledby="run-controls-heading">
        <h2 id="run-controls-heading">Run Controls</h2>
        <ThresholdRunControl />
        <NeuralEventPanel />
      </section>

      <section className="card results-dashboard" aria-labelledby="results-heading">
        <div className="results-heading">
          <h2 id="results-heading">Results</h2>
          <ExportResults compact manifest={results.manifest} report={report}
            busy={results.busy || results.validating || results.manifest?.status === "recording"} />
        </div>
        <div className="results-toolbar">
          <RunSelector runs={results.runs} selectedRunId={results.selectedRunId}
            onChange={results.setSelectedRunId} loading={results.runsLoading}
            error={results.runsError} busy={results.busy || results.validating} />
          {results.selectedRunId && <ValidationBanner report={report} manifest={results.manifest}
            loading={results.loadingReport} validating={results.validating}
            error={results.analysisError} onAnalyze={results.analyze} disabled={results.busy} />}
        </div>
        {!results.selectedRunId ? (
          <p className="hint results-empty" role="status">{results.busy
            ? "Experiment in progress — results will appear after the run finishes."
            : "Run a new experiment or select a saved experiment to view results."}</p>
        ) : <>
          {results.manifestError && <p className="error" role="alert">Run record: {results.manifestError.message}</p>}
          {results.reportError && !results.validating && results.analysisError && <p className="error" role="alert">Saved analysis: {results.reportError.message}</p>}
          {recordingErrors > 0 && <p className="error" role="alert">{recordingErrors} recording error(s) — see Experiment log below.</p>}
          {report && results.validating && <p className="hint" role="status">Showing previous saved analysis while reanalysis runs.</p>}
          <ResultsOverview report={report} />
          <div className="results-details" key={results.selectedRunId ?? "none"}>
            <ResultDetails title="Performance & verification details" status={report?.verification_audit ? `${report.verification_audit.software_verified_count}/${report.verification_audit.total_checks} checks` : undefined}>
              <PerformanceSummary report={report} />
            </ResultDetails>
            <ResultDetails title="Event comparison & timing details" status={report?.matching.counts.tp == null ? undefined : `${report.matching.counts.tp.toLocaleString()} matched`}>
              <ReferenceComparison report={report} onAnalyze={results.analyze} validating={results.validating} disabled={results.busy} />
            </ResultDetails>
            <ResultDetails title="Oscilloscope" status="Current capture"><p className="hint">Shows the current scope capture, not a replay of the selected recording.</p><ScopePair variant="experiment" /></ResultDetails>
            <ResultDetails title="Experiment log & warnings" status={warnings || recordingErrors ? `${warnings} warnings · ${recordingErrors} errors` : undefined}>
              <ExperimentLog manifest={results.manifest} report={report} />
            </ResultDetails>
          </div>
        </>}
      </section>
    </section>
  );
}
