import { useConfig, useRuntime } from "../state/store";
import { Accordion } from "../components/Accordion";
import GpioComparison from "../components/ComparatorSequencePanel";
import { FpgaConnectionGuide } from "../guides/FpgaConnectionGuide";

import {
  useExperimentRun,
  useCanArmExperiment,
  startExperiment,
  stopExperiment,
  captureGpioScope,
} from "../services/experimentRun";

const CHANNELS = ["N1", "N2", "N3", "N4", "P1", "P2", "P3", "P4"];

export default function FPGAStep() {
  const dataset = useConfig((s) => s.datasetName);
  const signalSource = useConfig((s) => s.signalSource);
  const setSignalSource = useConfig((s) => s.setSignalSource);
  const runActive = useRuntime((s) => s.runActive);
  const gpioStats = useRuntime((s) => s.gpioStats);
  const gpioTrace = useRuntime((s) => s.gpioTrace);

  // Both steps read one run controller. Normal experiments belong in Step 6;
  // FPGA Setup retains its GPIO-only diagnostic mode and troubleshooting tools.
  const durationS = useExperimentRun((s) => s.durationS);
  const plan = useExperimentRun((s) => s.plan);
  const lastMode = useExperimentRun((s) => s.lastMode);
  const busy = useExperimentRun((s) => s.busy);
  const scopeBusy = useExperimentRun((s) => s.scopeBusy);
  const scope = useExperimentRun((s) => s.scope);
  const error = useExperimentRun((s) => s.error);
  const output = useExperimentRun((s) => s.output);
  const running = runActive || output.active;
  const canArm = useCanArmExperiment();
  const valid = !!dataset && Number.isFinite(durationS) && durationS >= 1 && durationS <= 60;
  const sourceLocked = busy || running;

  return <section className="workspace-panel">
    <section className="card fpga-signal-source" aria-label="FPGA signal source">
      <div className="input__toolbar fpga-signal-source__toolbar">
        <h2>Signal Source:</h2>
        <select
          id="fpga-signal-source"
          aria-label="Signal source"
          value={signalSource}
          disabled={sourceLocked}
          onChange={(event) => setSignalSource(event.target.value as "ad3" | "pcb")}
        >
          <option value="ad3">AD3 Simulation</option>
          <option value="pcb">Physical PCB</option>
        </select>
        <div className="spacer" />
        <span className="badge" role="status" title="Software selection only; change hardware wiring to match.">
          {signalSource === "ad3" ? "AD3 DIO Inputs" : "PCB Comparator Inputs"}
        </span>
      </div>
    </section>

    <Accordion
      defaultOpenId="gpio-test"
      sections={[
        {
          id: "ad3-comparator",
          title: "AD3 DIO to DE10-Lite Guide (AD3 Simulation)",
          content: <FpgaConnectionGuide />,
        },
        {
          id: "gpio-test",
          title: "AD3 Comparator Simulation Test",
          content: (<>
            <p className="muted" style={{ marginTop: 12 }}>
              Enables FPGA GPIO reports over UART for this test only. Uses 0.25× playback.
              {signalSource === "pcb" && " Select AD3 Simulation above to run this digital test."}
            </p>
            <div className="actions" style={{ gap: 10, flexWrap: "wrap" }}>
              <button className="primary"
                disabled={busy || running || !canArm || !valid || signalSource !== "ad3"}
                onClick={() => void startExperiment("gpio")}>
                {busy ? "Working…" : "Start GPIO debug"}
              </button>
              <button disabled={busy || !running} onClick={() => void stopExperiment()}>{lastMode === "gpio" ? "Stop debug" : "Stop active run"}</button>
              <button disabled={busy || scopeBusy || !output.active || lastMode !== "gpio"}
                onClick={() => void captureGpioScope()}>
                {scopeBusy ? "Capturing…" : "Capture CH1"}
              </button>
            </div>
            {plan && lastMode === "gpio" && <div style={{ marginTop: 12 }}>
              <p className="muted">{plan.expected_edges_per_second.toFixed(0)} expected edges/s · {plan.cycle_duration_ms.toFixed(3)} ms/cycle</p>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", textAlign: "center" }}>
                  <thead><tr><th>Comparator</th>{CHANNELS.map(ch => <th key={ch}>{ch}</th>)}</tr></thead>
                  <tbody>
                    <tr><th>Expected / cycle</th>{CHANNELS.map(ch => <td key={ch}>{plan.expected_edges_per_cycle[ch] ?? 0}</td>)}</tr>
                    <tr><th>FPGA counted</th>{CHANNELS.map(ch => <td key={ch}>{gpioStats?.edges_by_channel?.[ch] ?? "—"}</td>)}</tr>
                  </tbody>
                </table>
              </div>
              {gpioStats && <p className="muted">{gpioStats.gpio_packets} GPIO packets · {gpioStats.total_edges} transitions observed</p>}
              <GpioComparison referenceStates={plan.reference_states ?? []} observed={gpioTrace}
                expectedEdges={plan.expected_edges_per_cycle} />
            </div>}
            {scope && lastMode === "gpio" && <div style={{ marginTop: 12 }}>
              <p className="muted">CH1 {scope.min_v.toFixed(3)}–{scope.max_v.toFixed(3)} V · HIGH {scope.pulse_width_us?.toFixed(2) ?? "—"} µs · {scope.edge_count} edges</p>
              <svg viewBox="0 0 800 180" role="img" aria-label="AD3 digital scope capture"
                style={{ width: "100%", height: 180, background: "#111827", borderRadius: 6 }}>
                <polyline fill="none" stroke="#56d4f0" strokeWidth={1.5}
                  points={scope.voltage_v.filter((_, i) => i % 4 === 0).map((v, i, a) =>
                    `${i * 800 / Math.max(1, a.length - 1)},${168 - (v + 0.5) * 150 / 4.5}`).join(" ")} />
              </svg>
              <p className="muted">{scope.note}</p>
            </div>}
            {error && <p role="alert" className="error">{error}</p>}
          </>),
        },
      ]}
    />
  </section>;
}
