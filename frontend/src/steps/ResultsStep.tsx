import React, { useEffect, useRef, useState } from "react";
import { api, type ComparatorPreview, type ComparatorStart, type ComparatorRequest, type PulseScope } from "../state/api";
import { useConfig, useRuntime, thresholdSignature } from "../state/store";
import { ScopePair } from "../components/ScopeView";
import { fpgaSerial } from "../services/fpgaSerial";
import UartConnection from "../components/UartConnection";
import GpioComparison from "../components/ComparatorSequencePanel";
import NeuralEventPanel from "../components/NeuralEventPanel";

const CHANNELS = ["N1", "N2", "N3", "N4", "P1", "P2", "P3", "P4"];
type RunMode = "events" | "gpio";

/** The backend acknowledges arming through the serial WebSocket. Wait for that
 * acknowledgement before requesting AD3 playback (the API requires it).
 */
function waitForRunState(active: boolean, timeoutMs = 5000): Promise<void> {
  if (useRuntime.getState().runActive === active) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let settled = false;
    let unsubscribe = () => {};
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      unsubscribe();
      if (error) reject(error);
      else resolve();
    };
    const timer = window.setTimeout(() =>
      finish(new Error(`FPGA did not acknowledge ${active ? "Start" : "Stop"} run.`)), timeoutMs);
    unsubscribe = useRuntime.subscribe((state) => {
      if (state.runActive === active) finish();
    });
    // Handle an acknowledgment arriving between the initial check and subscribe.
    if (useRuntime.getState().runActive === active) finish();
  });
}

export default function ResultsStep() {
  const dataset = useConfig((s) => s.datasetName);
  const thresholds = useConfig((s) => s.thresholdsMv); // DAC order: P1–P4, N1–N4
  const ad3Status = useRuntime((s) => s.ad3Status);
  const connected = useRuntime((s) => s.serialConnected);
  const serialMock = useRuntime((s) => s.serialMock);
  const serialPort = useRuntime((s) => s.serialPort);
  const runActive = useRuntime((s) => s.runActive);
  const fpgaVerified = useRuntime((s) => s.fpgaVerified);
  const appliedSignature = useRuntime((s) => s.appliedSignature);
  const gpioStats = useRuntime((s) => s.gpioStats);
  const gpioTrace = useRuntime((s) => s.gpioTrace);
  const clearGpioTrace = useRuntime((s) => s.clearGpioTrace);
  const log = useRuntime((s) => s.log);
  const clearLog = useRuntime((s) => s.clearLog);
  const addLog = useRuntime((s) => s.addLog);

  const [durationS, setDurationS] = useState(10);
  const [plan, setPlan] = useState<ComparatorPreview | null>(null);
  const [lastStart, setLastStart] = useState<ComparatorStart | null>(null);
  const [lastMode, setLastMode] = useState<RunMode | null>(null);
  const [busy, setBusy] = useState(false);
  const [scopeBusy, setScopeBusy] = useState(false);
  const [scope, setScope] = useState<PulseScope | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [output, setOutput] = useState({ active: false, mode: "idle" });
  const sawComparatorOutput = useRef(false);
  const activeRef = useRef(runActive);
  activeRef.current = runActive;

  const running = runActive || output.active;
  const canArm = connected && !serialMock &&
    appliedSignature === thresholdSignature(thresholds, 1.6);
  const valid = Boolean(dataset) && thresholds.length === 8 &&
    thresholds.every((v, i) => Number.isFinite(v) && (i < 4 ? v >= 0 : v <= 0)) &&
    Number.isFinite(durationS) && durationS >= 1 && durationS <= 60;

  function requestFor(mode: RunMode): ComparatorRequest {
    return {
      dataset,
      thresholds_mv: [...thresholds],
      playback_speed: mode === "gpio" ? 0.25 : 1,
      gpio_debug_enabled: mode === "gpio",
      duration_s: durationS,
    };
  }

  const requestKey = JSON.stringify({ dataset, thresholds, durationS });
  useEffect(() => {
    setPlan(null);
    setLastStart(null);
    setScope(null);
  }, [requestKey]);

  useEffect(() => {
    if (!runActive) sawComparatorOutput.current = false;
  }, [runActive]);

  useEffect(() => {
    let mounted = true;
    const poll = () => {
      void api.digitalStatus().then((s) => {
        if (!mounted) return;
        setOutput({ active: s.active, mode: s.mode });
        if (s.active && s.mode === "comparators") sawComparatorOutput.current = true;
        // Automatic AD3 timeout must also disarm FPGA event reception.
        if (!s.active && sawComparatorOutput.current && activeRef.current) {
          sawComparatorOutput.current = false;
          fpgaSerial.setRunActive(false);
        }
      }).catch(() => {
        if (mounted) setOutput({ active: false, mode: "unknown" });
      });
    };
    poll();
    const interval = window.setInterval(poll, 1000);
    return () => { mounted = false; window.clearInterval(interval); };
  }, []);

  async function startRun(mode: RunMode) {
    if (busy || running || !valid || !canArm) return;
    setBusy(true);
    setError(null);
    setPlan(null);
    setLastStart(null);
    setScope(null);
    let armed = false;
    try {
      const req = requestFor(mode);
      // Automatic preview validates the dataset, thresholds and (debug only)
      // the UART throughput limit. No separate Preview/Arm action is required.
      const preview = await api.comparatorPreview(req);
      if (preview.warning) throw new Error(preview.warning);
      clearGpioTrace();
      armed = true; // ensure cleanup even if the FPGA mode ACK fails
      await fpgaSerial.armRun(mode === "gpio");
      const started = await api.comparatorStart(req);
      setPlan(started);
      setLastStart(started);
      setLastMode(mode);
      sawComparatorOutput.current = true;
      setOutput({ active: true, mode: "comparators" });
      addLog("INFO", `${mode === "gpio" ? "GPIO debug" : "Neural event"} run: ${started.dataset}, ${started.cycle_duration_ms.toFixed(3)} ms/cycle`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (armed) {
        // If the AD3 start fails, do not leave the UART receiver armed.
        fpgaSerial.setRunActive(false);
        try { await api.digitalStop(); } catch { /* preserve original error */ }
      }
    } finally {
      setBusy(false);
    }
  }

  async function stopRun() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (runActive) {
        if (!fpgaSerial.setRunActive(false)) {
          throw new Error("Could not send Stop to the FPGA serial bridge.");
        }
        // The backend also stops the AD3 before acknowledging Stop.
        await waitForRunState(false);
      } else {
        await api.digitalStop();
      }
      setOutput({ active: false, mode: "idle" });
      sawComparatorOutput.current = false;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      // Best-effort physical output shutdown if the WebSocket is unavailable.
      try { await api.digitalStop(); } catch { /* retain error for the user */ }
    } finally {
      setBusy(false);
    }
  }

  async function captureScope() {
    setScopeBusy(true);
    setError(null);
    try { setScope(await api.digitalScope()); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setScopeBusy(false); }
  }

  function exportLog() {
    const content = log.map((entry) => `${entry.time}\t${entry.kind}\t${entry.text}`).join("\r\n");
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `cortex-serial-${Date.now()}.txt`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="workspace-panel">
    <UartConnection />

    <section className="card" aria-label="Neural event run controls">
      <div className="row between" style={{ gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ marginBottom: 4 }}>AD3 comparators · {dataset || "Select a waveform"}</h2>
          <span className="muted">Neural event detection · 1× playback</span>
        </div>
        <div className="actions" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <label>Duration (s)
            <input style={{ width: 86 }} type="number" min={1} max={60} step={1}
              disabled={busy || running} value={durationS}
              onChange={(e) => setDurationS(Number(e.target.value))} />
          </label>
          <button className={running ? "" : "primary"}
            disabled={busy || (!running && (!canArm || !valid))}
            onClick={() => void (running ? stopRun() : startRun("events"))}>
            {busy ? "Working…" : running ? "■ Stop run" : "▶ Start run"}
          </button>
        </div>
      </div>
      <p className="muted" style={{ marginTop: 10, marginBottom: 4 }}>
        {ad3Status === "connected" ? "AD3 connected" : `AD3: ${ad3Status}`}
        {" · "}{connected && !serialMock ? (serialPort ?? "UART connected") : "UART disconnected"}
        {" · "}{fpgaVerified ? "FPGA verified" : "FPGA not verified"}
        {" · "}{running ? (lastMode === "gpio" ? "GPIO debug running" : "Running") : "Idle"}
      </p>
      {!canArm && !running && <p className="muted">Connect the FPGA and apply all eight thresholds to start.</p>}
      <p className="muted" style={{ marginBottom: 0 }}>FPGA GPIO reporting is disabled automatically over UART.</p>
      {plan && lastMode === "events" && <p className="muted" style={{ marginBottom: 0 }}>
        CSV peak {plan.source_peak_uv.toFixed(1)} µV · Modeled AFE peak {plan.afe_peak_mv.toFixed(1)} mV · {plan.cycle_duration_ms.toFixed(3)} ms/cycle
      </p>}
      {error && <p role="alert" className="error">{error}</p>}
    </section>

    <details className="card" aria-label="GPIO debug controls">
      <summary style={{ cursor: "pointer", fontWeight: 600, padding: "2px 0" }}>
        GPIO debug <span className="muted" style={{ fontWeight: 400 }}>· 0.25× playback</span>
      </summary>
      <p className="muted" style={{ marginTop: 12 }}>
        Enables FPGA GPIO reports over UART for this test only. Uses 0.25× playback.
      </p>
      <div className="actions" style={{ gap: 10, flexWrap: "wrap" }}>
        <button className="primary"
          disabled={busy || running || !canArm || !valid}
          onClick={() => void startRun("gpio")}>
          {busy ? "Working…" : "Start GPIO debug"}
        </button>
        <button disabled={busy || !running || lastMode !== "gpio"} onClick={() => void stopRun()}>Stop debug</button>
        <button disabled={busy || scopeBusy || !output.active || lastMode !== "gpio"}
          onClick={() => void captureScope()}>
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
    </details>

    <NeuralEventPanel />
    <section className="card">
      <div className="row between"><h2>Terminal output</h2><div className="actions">
        <button onClick={exportLog} disabled={!log.length}>Save text</button>
        <button onClick={() => window.print()}>Print</button>
        <button onClick={clearLog}>Clear</button>
      </div></div>
      <div className="terminal" role="log">{!log.length && <span className="placeholder">No messages received.</span>}
        {log.map(x => <div key={x.id} className="line"><span className="timestamp">{x.time}</span>
          <span className={`kind ${x.kind.toLowerCase()}`}>{x.kind}</span><span className="text">{x.text}</span></div>)}
      </div>
    </section>
    <section className="card"><h2>Analog capture · experiment view</h2><ScopePair variant="experiment" /></section>
  </section>;
}
