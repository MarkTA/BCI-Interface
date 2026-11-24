import { useState } from "react";
import { api } from "../state/api";
import type {
  RecordedRun, NeuralMatching, SummaryRow, ValidationReport, ValidateOptions, ValidationStatus,
} from "../services/validationRuns";
import { formatSummaryValue } from "../services/validationRuns";

function StatusBadge({ status }: { status: ValidationStatus | string }) {
  const tone = status === "PASS" ? "pass" : status === "FAIL" ? "fail" : "unknown";
  return <span className={`validation-status validation-status--${tone}`}>
    {status === "NOT_AVAILABLE" ? "Not verified" : status.replaceAll("_", " ")}
  </span>;
}

function timeLabel(utc?: string | null) {
  if (!utc) return "—";
  const date = new Date(utc);
  return Number.isNaN(date.getTime()) ? utc : date.toLocaleString();
}

function formatNumber(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}

function metricLabel(value: boolean | null) {
  return value === null ? "—" : value ? "✓" : "Mismatch";
}

export function RunSelector({
  runs, selectedRunId, onChange, loading, error, busy,
}: {
  runs: RecordedRun[];
  selectedRunId: string | null;
  onChange: (runId: string) => void;
  loading: boolean;
  error: Error | null;
  busy: boolean;
}) {
  return <div className="validation-run-selector">
    <label htmlFor="validation-run">Recorded experiment</label>
    <select id="validation-run" value={selectedRunId ?? ""} onChange={(e) => onChange(e.target.value)}
      disabled={loading || !runs.length || busy}>
      {!selectedRunId && <option value="">Select an experiment</option>}
      {selectedRunId && !runs.some((run) => run.run_id === selectedRunId) &&
        <option value={selectedRunId}>{selectedRunId.slice(0, 8)} (loading…)</option>}
      {runs.map((run) => <option key={run.run_id} value={run.run_id}>
        {timeLabel(run.armed_at_utc)} · {run.playback.config?.dataset ?? "No dataset"} · {run.status}
      </option>)}
    </select>
    {error && <p className="error" role="alert">Run history: {error.message}</p>}
    {!loading && !runs.length && !error && <p className="hint">No recorded runs yet. Complete an experiment to populate this panel.</p>}
  </div>;
}

export function ValidationBanner({
  report, manifest, loading, validating, error, onAnalyze, disabled,
}: {
  report: ValidationReport | null;
  manifest: RecordedRun | null;
  loading: boolean;
  validating: boolean;
  error: string | null;
  onAnalyze: (options?: ValidateOptions) => void;
  disabled: boolean;
}) {
  const hasAnalysis = !!report;
  return <div className="validation-overview" role="status" aria-live="polite">
    <div>
      <strong>{validating ? "Analyzing recorded experiment…" : loading ? "Loading results…" :
        hasAnalysis ? "Analysis complete" : manifest ? "Preparing analysis…" : "Run an experiment to see results"}</strong>
      <p>{hasAnalysis
        ? "Hardware synchronization and FPGA packet accounting are evaluated automatically. See each result for its verified status."
        : "Recording and analysis happen automatically when a run finishes."}</p>
    </div>
    <div className="validation-overview__actions">
      {manifest && <span className="muted">{manifest.playback.config?.dataset?.replaceAll("_", " ") ?? "Recorded waveform"}</span>}
      <button type="button" disabled={disabled || validating || !manifest || manifest.playback.status !== "stopped"}
        onClick={() => onAnalyze({ alignment: { mode: "event_anchor", reference_index: 0, observed_index: 0 } })}>
        {validating ? "Analyzing…" : "Reanalyze"}
      </button>
    </div>
    {error && <p className="error" role="alert">Analysis could not finish: {error}</p>}
  </div>;
}

const SIMPLE_LABELS: Record<string, string> = {
  "Detection F1": "Spike detection",
  "Timestamp max |error|": "Absolute timestamp",
  "Time-to-peak max |error|": "Time to peak",
  "Data reduction": "Data reduction",
};
function labelFor(row: SummaryRow) {
  if (row.name.startsWith("Peak ")) return "Peak classification";
  if (row.name.startsWith("Trough ")) return "Trough classification";
  return SIMPLE_LABELS[row.name] ?? row.name;
}
function summaryReason(row: SummaryRow, report: ValidationReport) {
  if (row.status === "PASS") return row.name.startsWith("Peak ") || row.name.startsWith("Trough ")
    ? "Verified for received isolated spikes in AD3 digital simulation; analog PCB not tested."
    : "Requirement met for this test.";
  if (row.status === "FAIL") return row.name === "Data reduction"
    ? "This waveform produces too many events to achieve the 10× bandwidth target. Try a sparser dataset."
    : "Below required performance";
  if (row.name === "Detection F1") return report.matching.status === "matched"
    ? "Hardware timing is aligned; full packet accounting is still required."
    : "Event correspondence is estimated, not independently synchronized.";
  if (row.name.startsWith("Peak ") || row.name.startsWith("Trough "))
    return "Agreement with the reference model; final acceptance requires independently synchronized event matching.";
  if (row.name.startsWith("Timestamp")) return report.hardware_sync?.status === "ALIGNED"
    ? "Hardware synchronization is active; additional capture or timing evidence is required."
    : "Requires a hardware synchronization signal.";
  if (row.name.startsWith("Time-to-peak")) return report.matching.status === "matched"
    ? "Hardware-aligned event matching is available; capture evidence is still required."
    : "Agreement is measured, but event correspondence is estimated.";
  return "Additional measurement evidence required.";
}

export function PerformanceSummary({ report }: { report: ValidationReport | null }) {
  if (!report) return <p className="hint">Your results will appear here automatically after the run.</p>;
  const rows = report.validation.performance_summary;
  const failures = rows.filter(r => r.status === "FAIL").length;
  const passes = rows.filter(r => r.status === "PASS").length;
  const expected = report.matching.counts.expected;
  const observed = report.matching.counts.observed;
  const tp = report.matching.counts.tp;
  return <>
    <div className="validation-conclusion">
      <strong>{failures > 0 ? `${failures} requirement${failures > 1 ? "s" : ""} not met` :
        passes === rows.length ? "All requirements met" : "Digital comparison available — verification incomplete"}</strong>
      <p><b>Test mode: AD3 digital comparator simulation.</b> Physical PCB performance requires separate calibration.</p>
      <p>{tp != null
        ? `${tp.toLocaleString()} matched events out of ${expected.toLocaleString()} expected and ${observed.toLocaleString()} received. ${report.hardware_sync?.status === "ALIGNED" ? "DIO8 hardware synchronization active." : "Matching is exploratory; no independently established timing origin."} ${report.capture_reconciliation?.complete ? "FPGA event counts agree with the PC recording." : "FPGA capture accounting is not yet verified."}`
        : `${expected.toLocaleString()} expected events; ${observed.toLocaleString()} received. Event correspondence is still being calculated.`}</p>
    </div>
    <div className="validation-metric-grid">
      {rows.map(row => <div key={row.name} className={`validation-metric-card validation-metric-card--${row.status.toLowerCase()}`}>
        <div className="validation-metric-card__top"><span>{labelFor(row)}</span><StatusBadge status={row.status} /></div>
        <div className="validation-metric-card__value">{formatSummaryValue(row)}</div>
        <div className="validation-metric-card__target">Target: {row.target}{row.units === "µs" ? " µs" : row.units === "×" ? "×" : ""}</div>
        <p>{summaryReason(row, report)}</p>
      </div>)}
    </div>
    {report.verification_audit &&
      <details className="validation-technical-details">
        <summary>Verification checklist · {report.verification_audit.software_verified_count} of {report.verification_audit.total_checks} evidence checks complete</summary>
        <div className="validation-verification-checks">
          {report.verification_audit.checks.map(check =>
            <div key={check.key} className="validation-evidence-row">
              <strong>{check.status === "verified" ? "✓" : check.status === "hardware_required" ? "◯" : "…"} {check.title}</strong>
              <span>{check.status === "verified" ? "Checked" : check.status === "hardware_required" ? "Hardware step needed" : "Pending"}</span>
              <p>{check.detail}</p>
            </div>)}
        </div>
      </details>}
    <p className="validation-summary-footnote">Measured agreement is not the same as independently verified hardware accuracy. Missing evidence is labeled <strong>Not verified</strong>, not failed. Absolute timestamp validation also requires a shared timing reference; for synchronized runs, that reference is supplied by DIO8.</p>
    <details className="validation-technical-details"><summary>Measurement details and exact verification notes</summary>
      <div className="validation-table-wrap"><table className="validation-table"><thead><tr><th>Metric</th><th>Value</th><th>Requirement</th><th>Explanation</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.name}><th scope="row">{row.name}</th><td>{formatSummaryValue(row)}</td>
        <td>{row.target}{row.units === "µs" ? " µs" : row.units === "×" ? "×" : ""}</td><td>{row.reason}</td></tr>)}</tbody></table></div>
      <p className="muted">Playback {formatNumber(report.input_snapshots.playback_duration_s_host_observed, 3)} s · AD3 {formatNumber(report.input_snapshots.sample_rate_hz, 0)} Sa/s · Baseline {formatNumber(report.validation.metrics.data_reduction.baseline.continuous_bit_rate_bps, 0)} bit/s</p>
    </details>
  </>;
}

function EventCounts({ matching }: { matching: NeuralMatching }) {
  const { expected, observed, tp, fp, fn } = matching.counts;
  return <div className="validation-counts">
    <div><span>Expected</span><strong>{expected}</strong></div>
    <div><span>Observed</span><strong>{observed}</strong></div>
    <div><span>Matched (TP)</span><strong>{tp ?? "—"}</strong></div>
    <div><span>Extra (FP)</span><strong>{fp ?? "—"}</strong></div>
    <div><span>Missing (FN)</span><strong>{fn ?? "—"}</strong></div>
  </div>;
}

export function ReferenceComparison({ report, onAnalyze, disabled, validating }: {
  report: ValidationReport | null;
  onAnalyze: (options?: ValidateOptions) => void;
  disabled: boolean;
  validating: boolean;
}) {
  const [refIndex, setRefIndex] = useState("0");
  const [obsIndex, setObsIndex] = useState("0");
  if (!report) return <p className="hint">Run validation to see expected/observed counts and event comparisons.</p>;
  const matching = report.matching;
  const numRef = Number(refIndex);
  const numObs = Number(obsIndex);
  const validAnchor = refIndex.trim() !== "" && obsIndex.trim() !== "" &&
    Number.isInteger(numRef) && Number.isInteger(numObs) && numRef >= 0 && numObs >= 0 &&
    numRef < matching.counts.expected && numObs < matching.counts.observed;
  const visibleMatches = matching.matches.slice(0, 30);
  return <>
    <EventCounts matching={matching} />
    {report.relative_timing && report.relative_timing.consecutive_pairs > 0 &&
      <div className="validation-relative-timing">
        <h4>Relative Timing (diagnostic)</h4>
        <p className="muted">Diagnostic only: relative event timing compared with the model. Not an absolute timestamp measurement.</p>
        <dl className="validation-log-details">
          <div><dt>Adjacent event pairs</dt><dd>{report.relative_timing.consecutive_pairs}</dd></div>
          <div><dt>Mean absolute interval error</dt><dd>{formatNumber(report.relative_timing.mean_absolute_interval_error_us, 3)} µs</dd></div>
          <div><dt>Maximum absolute interval error</dt><dd>{formatNumber(report.relative_timing.max_absolute_interval_error_us, 3)} µs</dd></div>
          <div><dt>Cumulative relative drift</dt><dd>{formatNumber(report.relative_timing.cumulative_relative_drift_us, 3)} µs</dd></div>
          <div><dt>Relative clock difference</dt><dd>{formatNumber(report.relative_timing.relative_clock_error_ppm, 3)} ppm</dd></div>
          <div><dt>Max anchored residual</dt><dd>{formatNumber(report.relative_timing.max_absolute_anchored_residual_us, 3)} µs</dd></div>
        </dl>
      </div>}

    <details className="validation-technical-details"><summary>Advanced: alignment controls and event-by-event diagnostics</summary>
    <p className="hint">Matching window: ±{matching.tolerance_us} µs · Alignment: {matching.alignment.mode.replaceAll("_", " ")}. {matching.alignment.explanation}</p>
    <div className="validation-anchor">
      <div><strong>Exploratory event alignment</strong>
        <p className="muted">Choose two events you have identified as the same spike; indices are zero-based. Don't assume the first two events correspond on repeating waveforms. This cannot certify the hardware's timing or F1 accuracy.</p>
      </div>
      <label>Expected index<input aria-label="Expected anchor event index" type="number" min={0} step={1}
        max={Math.max(0, matching.counts.expected - 1)} value={refIndex} onChange={e => setRefIndex(e.target.value)} /></label>
      <label>FPGA index<input aria-label="FPGA anchor event index" type="number" min={0} step={1}
        max={Math.max(0, matching.counts.observed - 1)} value={obsIndex} onChange={e => setObsIndex(e.target.value)} /></label>
      <button type="button" disabled={disabled || validating || !validAnchor} onClick={() =>
        onAnalyze({ alignment: { mode: "event_anchor", reference_index: numRef, observed_index: numObs } })}>
        Compare (exploratory)
      </button>
    </div>
    {matching.status === "alignment_required" ?
      <p className="hint">Event-to-event matches are unavailable until an alignment is chosen. Counts alone do not determine TP, FP, or FN.</p> :
      <>
        <div className="validation-table-wrap"><table className="validation-table">
          <thead><tr><th>Expected #</th><th>FPGA #</th><th>CH</th><th>Reference (µs)</th><th>Aligned FPGA (µs)</th><th>Residual (µs)</th><th>Peak</th><th>Trough</th><th>TTP error (µs)</th></tr></thead>
          <tbody>{visibleMatches.map(m => <tr key={`${m.reference_index}:${m.observed_index}`}>
            <td>{m.reference_index}</td><td>{m.observed_index}</td><td>{m.channel}</td>
            <td>{formatNumber(m.reference_onset_us)}</td><td>{formatNumber(m.observed_aligned_us)}</td>
            <td>{formatNumber(m.alignment_residual_us)}</td>
            <td className={m.peak_match === false ? "validation-mismatch" : ""}>{metricLabel(m.peak_match)}</td>
            <td className={m.trough_match === false ? "validation-mismatch" : ""}>{metricLabel(m.trough_match)}</td>
            <td>{formatNumber(m.time_to_peak_error_us)}</td>
          </tr>)}</tbody>
        </table></div>
        {matching.matches.length === 0 && <p className="muted">No events matched with the selected time origin.</p>}
        {matching.matches.length > visibleMatches.length && <p className="hint">Showing first {visibleMatches.length} of {matching.matches.length} matches. Export the run for the complete results.</p>}
        <div className="validation-unmatched">
          <div><h4>Missing reference events ({matching.false_negatives.length})</h4>
            {matching.false_negatives.length ?
              <ol>{matching.false_negatives.slice(0, 10).map(e => <li key={e.reference_index}>
                #{e.reference_index} · CH{e.channel} · {formatNumber(e.reference_onset_us)} µs
              </li>)}</ol> : <p className="muted">None</p>}
          </div>
          <div><h4>Unexpected FPGA events ({matching.false_positives.length})</h4>
            {matching.false_positives.length ?
              <ol>{matching.false_positives.slice(0, 10).map(e => <li key={e.observed_index}>
                #{e.observed_index} · CH{e.channel} · {e.observed_timestamp_us} µs (FPGA clock)
              </li>)}</ol> : <p className="muted">None</p>}
          </div>
        </div>
        {(matching.false_positives.length > 10 || matching.false_negatives.length > 10) &&
          <p className="hint">Showing first 10 per list. Full lists are saved in validation.json.</p>}
      </>}
    </details>
  </>;
}

export function ExperimentLog({ manifest, report }: { manifest: RecordedRun | null; report: ValidationReport | null }) {
  if (!manifest) return <p className="hint">Select a recorded experiment to inspect its metadata and warnings.</p>;
  return <>
    <dl className="validation-log-details">
      <div><dt>Run ID</dt><dd><code>{manifest.run_id}</code></dd></div>
      <div><dt>Started</dt><dd>{timeLabel(manifest.armed_at_utc)}</dd></div>
      <div><dt>Finished</dt><dd>{timeLabel(manifest.finished_at_utc)}</dd></div>
      <div><dt>Dataset</dt><dd>{manifest.playback.config?.dataset ?? "—"}</dd></div>
      <div><dt>Recorded playback</dt><dd>{formatNumber(manifest.playback.host_playback_duration_s, 3)} s · {manifest.playback.status}</dd></div>
      <div><dt>FPGA</dt><dd>{manifest.fpga_uart.port} · {manifest.fpga_uart.baud_rate} baud</dd></div>
      <div><dt>Neural packets</dt><dd>{manifest.capture.neural_event_count}</dd></div>
      <div><dt>FPGA event capture</dt><dd>{manifest.capture.fpga_counter_reconciliation?.complete
        ? "Counters match — received all reported packets"
        : "Not independently confirmed"}</dd></div>
      {manifest.capture.fpga_counters && <div><dt>FPGA generated / queued / sent</dt>
        <dd>{manifest.capture.fpga_counters.generated} / {manifest.capture.fpga_counters.queued} / {manifest.capture.fpga_counters.transmitted}</dd></div>}
      <div><dt>Host RX bytes</dt><dd>{manifest.capture.raw_rx_bytes} (not independently measured FPGA TX)</dd></div>
      <div><dt>Unparsed bytes</dt><dd>{manifest.capture.unframed_or_unparsed_bytes}</dd></div>
      <div><dt>Host recording</dt><dd>{manifest.capture.host_capture_complete ? "Completed" : "Incomplete"}</dd></div>
      {report && <div><dt>Analyzed</dt><dd>{timeLabel(report.generated_at_utc)}</dd></div>}
    </dl>
    {manifest.errors?.length > 0 && <div className="validation-alert"><strong>Recording errors</strong><ul>{manifest.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
    {report && <div className="validation-alert"><strong>Validation limitations</strong><ul>
      {[...new Set([...report.warnings, ...report.validation.warnings])].map((w, i) => <li key={i}>{w}</li>)}
    </ul></div>}
    <p className="hint">This is the persisted run manifest and validation warnings, not the full packet log. The ZIP export includes raw UART and event records.</p>
  </>;
}

export function ExportResults({ manifest, report, busy }: {
  manifest: RecordedRun | null;
  report: ValidationReport | null;
  busy: boolean;
}) {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  if (!manifest) return <p className="hint">Choose a recorded experiment before exporting.</p>;
  const blocked = busy || downloading;
  const exportZip = async () => {
    if (blocked) return;
    setDownloadError(null);
    setDownloading(true);
    try {
      await api.downloadRecordedRunZip(manifest.run_id);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : String(error));
    } finally {
      setDownloading(false);
    }
  };
  return <div className="validation-export">
    <p>Export the complete recording as a ZIP containing the manifest, waveform snapshot, comparator pattern, raw UART, decoded FPGA events, and <code>validation.json</code> when analysis has been saved.</p>
    <button type="button" className="validation-export-button" disabled={blocked} onClick={() => void exportZip()}>
      {downloading ? "Preparing download…" : busy ? "Stop the current run to export" : "Export experiment ZIP"}
    </button>
    {downloadError && <p className="error" role="alert">Export: {downloadError}</p>}
    {!report && <p className="hint">This recording has not been analyzed yet. Export will still contain the captured data.</p>}
    <p className="muted">Run ID: <code>{manifest.run_id}</code></p>
  </div>;
}
