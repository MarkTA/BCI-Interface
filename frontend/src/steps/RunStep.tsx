import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Accordion, type AccordionSection } from "../components/Accordion";
import DipSwitch from "../components/DipSwitch";
import NeuralEventPanel from "../components/NeuralEventPanel";
import {
  RunSelector, ValidationBanner, PerformanceSummary, ReferenceComparison,
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
  const output = useExperimentRun((s) => s.output);
  const lastMode = useExperimentRun((s) => s.lastMode);
  const plan = useExperimentRun((s) => s.plan);

  const valid = validThresholds(thresholds);
  const applied = connected && !mock &&
    appliedSignature === thresholdSignature(thresholds, AFE_BIAS_V);
  const sending = sendStatus === "sending";
  const running = runActive || output.active;
  const canArm = useCanArmExperiment();
  const ad3Ready = ad3Status === "connected";
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
          className={running ? "" : "primary"}
          disabled={busy || (!running && (!canArm || !validRun))}
          onClick={() => void (running ? stopExperiment() : startExperiment("events"))}
        >
          {busy ? "Working…" : running ? "■ Stop Run" : "▶ Start Run"}
        </button>
      </div>
      <div style={{ marginTop: 14 }}>
        <span className={applied ? "badge online" : "badge"} role="status">{status}</span>
      </div>
      <p className="muted" style={{ marginTop: 12, marginBottom: 4 }}>
        {ad3Status === "connected" ? "AD3 connected" : `AD3: ${ad3Status}`}
        {" · "}{connected && !mock ? (serialPort ?? "UART connected") : "UART disconnected"}
        {" · "}{fpgaVerified ? "FPGA verified" : "FPGA not verified"}
        {" · "}{running ? (lastMode === "gpio" ? "GPIO debug running" : "Running") : "Idle"}
      </p>
      {signalSource === "pcb" && !running && (
        <p className="hint" role="status">
          Physical PCB selected in FPGA Setup. This run controller currently supports AD3 digital
          simulation only; PCB playback will be added during hardware integration.
        </p>
      )}
      {signalSource === "ad3" && !ad3Ready && !running && (
        <p className="hint" role="status">
          Test the Analog Discovery connection in Step 3 (Analog Input) before starting a run.
        </p>
      )}
      {!canArm && !running && <p className="hint">Connect the physical FPGA and apply all eight thresholds to start.</p>}
      {plan && lastMode === "events" && <p className="hint">
        Last run: {plan.dataset} · CSV peak {plan.source_peak_uv.toFixed(1)} µV ·
        Modeled AFE peak {plan.afe_peak_mv.toFixed(1)} mV · {plan.cycle_duration_ms.toFixed(3)} ms/cycle
      </p>}
      {error && <p role="alert" className="error">{error}</p>}
      {(sendMessage || (sendStatus === "success" && !applied)) && (
        <p className={sendStatus === "error" ? "error" : "hint"} role="status">
          {sendStatus === "success" && !applied
            ? "Thresholds changed since the last acknowledgment. Send the current values again."
            : sendMessage}
        </p>
      )}
      <p className="hint" style={{ marginBottom: 0 }}>
        Threshold acknowledgments confirm FPGA SPI encoding, not physical DAC output.
        The existing run path drives AD3 digital comparator simulation at 1× playback.
      </p>
    </>
  );
}

// Results are backed by immutable Phase 4/5 run records, not by the bounded
// React neural-event buffer. The event viewer remains live and unchanged.
export default function RunStep() {
  const results = useRunValidation();
  const sections: AccordionSection[] = [
    {
      id: "performance", title: "Performance Summary",
      status: results.report && <span className="validation-section-status">{results.report.validation.performance_summary.some(r => r.status === "FAIL") ? "Target missed" : "Review results"}</span>,
      content: <PerformanceSummary report={results.report} />,
    },
    {
      id: "events", title: "Live Neural Events",
      content: <NeuralEventPanel embedded />,
    },
    {
      id: "comparison", title: "Event Comparison & Timing",
      status: results.report && <span className="validation-section-status">{results.report.matching.counts.tp == null ? "Pending" : `${results.report.matching.counts.tp} matched`}</span>,
      content: <ReferenceComparison report={results.report} onAnalyze={results.analyze}
        validating={results.validating} disabled={results.busy} />,
    },
    {
      id: "oscilloscope", title: "Oscilloscope",
      content: <ScopePair variant="experiment" />,
    },
    {
      id: "log", title: "Experiment Log",
      content: <ExperimentLog manifest={results.manifest} report={results.report} />,
    },
  ];

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
      </section>

      <h2>Results</h2>
      <div className="validation-results-header">
        <RunSelector runs={results.runs} selectedRunId={results.selectedRunId}
          onChange={results.setSelectedRunId} loading={results.runsLoading}
          error={results.runsError} busy={results.validating} />
        <ValidationBanner report={results.report} manifest={results.manifest}
          loading={results.loadingReport} validating={results.validating}
          error={results.analysisError} onAnalyze={results.analyze}
          disabled={results.busy} />
        {results.manifestError && <p className="error" role="alert">Run record: {results.manifestError.message}</p>}
        {results.reportError && !results.validating && results.analysisError && <p className="error" role="alert">Saved analysis: {results.reportError.message}</p>}
      </div>
      <Accordion sections={sections} defaultOpenId="performance" />
      <section className="validation-export-inline" aria-label="Download experiment results">
        <ExportResults manifest={results.manifest} report={results.report}
          busy={results.busy || results.manifest?.status === "recording"} />
      </section>
    </section>
  );
}
