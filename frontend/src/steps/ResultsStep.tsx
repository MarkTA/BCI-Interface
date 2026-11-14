import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../state/api";
import { useConfig, useRuntime, thresholdSignature } from "../state/store";
import { ScopePair } from "../components/ScopeView";
import { fpgaSerial } from "../services/fpgaSerial";
import UartConnection from "../components/UartConnection";
export default function ResultsStep() {
  const ports = useQuery({ queryKey: ["ports"], queryFn: api.ports, retry: 0 });
  const [port, setPort] = useState(""),
    [mock, setMock] = useState(true),
    [baud, setBaud] = useState(115200),
    [input, setInput] = useState("PING"),
    [newLine, setNewLine] = useState(true);

  const connected = useRuntime((s) => s.serialConnected),
    status = useRuntime((s) => s.serialStatus),
    serialPort = useRuntime((s) => s.serialPort),
    serialBaud = useRuntime((s) => s.serialBaud),
    serialMock = useRuntime((s) => s.serialMock),
    addLog = useRuntime((s) => s.addLog),
    clearLog = useRuntime((s) => s.clearLog),
    log = useRuntime((s) => s.log),
    capture = useRuntime((s) => s.capture);

  type PulseScope = {time_us: number[]; voltage_v: number[]; min_v: number; max_v: number; pulse_width_us: number | null; edge_count: number; note: string};
  const [pulseScope, setPulseScope] = useState<PulseScope | null>(null);
  const [scopeBusy, setScopeBusy] = useState(false);
  async function capturePulseScope() {
    setScopeBusy(true); setDigitalError(null);
    try {
      const base = window.location.port === "5173" ? "http://127.0.0.1:8000" : "";
      const response = await fetch(`${base}/api/ad3/digital/scope`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Scope capture failed");
      setPulseScope(data as PulseScope);
    } catch (error) { setDigitalError(String(error)); }
    finally { setScopeBusy(false); }
  }
  const [digitalBusy, setDigitalBusy] = useState(false);
  const [digitalActive, setDigitalActive] = useState(false);
  const [digitalStatusKnown, setDigitalStatusKnown] = useState(false);
  const [digitalError, setDigitalError] = useState<string | null>(null);
  const [pulseChannel, setPulseChannel] = useState(4);
  const [pulseFrequency, setPulseFrequency] = useState(5);
  const [pulseWidth, setPulseWidth] = useState(100);
  const [pulseDuration, setPulseDuration] = useState(5);
  useEffect(() => {
    let mounted = true;
    const poll = () => api.digitalStatus().then((result) => {
      if (mounted) { setDigitalActive(result.active); setDigitalStatusKnown(true); }
    }).catch(() => { if (mounted) setDigitalStatusKnown(false); });
    poll();
    const timer = window.setInterval(poll, 1000);
    return () => { mounted = false; window.clearInterval(timer); };
  }, []);
  async function startDigitalPulse() {
    setDigitalError(null);
    setPulseScope(null);
    if (pulseWidth >= 1_000_000 / pulseFrequency) {
      setDigitalError("Pulse width must be shorter than the pulse period.");
      return;
    }
    setDigitalBusy(true);
    try {
      await api.digitalPulse({ channel: pulseChannel, frequency_hz: pulseFrequency, width_us: pulseWidth, duration_s: pulseDuration });
      setDigitalActive(true);
      setDigitalStatusKnown(true);
    } catch (error) { setDigitalError(String(error)); }
    finally { setDigitalBusy(false); }
  }
  async function stopDigitalPulse() {
    setDigitalBusy(true);
    setDigitalError(null);
    try { await api.digitalStop(); setDigitalActive(false); setDigitalStatusKnown(true); }
    catch (error) { setDigitalStatusKnown(false); setDigitalError(String(error)); }
    finally { setDigitalBusy(false); }
  }
  const runActive = useRuntime((s) => s.runActive);
  const preview = useRuntime((s) => s.preview);
  const ad3Status = useRuntime((s) => s.ad3Status);
  const fpgaVerified = useRuntime((s) => s.fpgaVerified);
  const appliedSignature = useRuntime((s) => s.appliedSignature);
  const dataset = useConfig((s) => s.datasetName),
    thresholds = useConfig((s) => s.thresholdsMv),
    bias = useConfig((s) => s.biasV),
    mode = useConfig((s) => s.comparatorMode);

  // Synchronize controls with the active serial connection.
  useEffect(() => {
    if (connected) {
      if (serialPort) setPort(serialPort);
      if (serialBaud) setBaud(serialBaud);
      setMock(serialMock);
    }
  }, [connected, serialPort, serialBaud, serialMock]);

  // Select the first available port only when disconnected.
  useEffect(() => {
    if (!connected && !port && ports.data?.length) {
      setPort(ports.data[0].device);
    }
  }, [connected, ports.data, port]);
  function connect() {
    if (fpgaSerial.active) fpgaSerial.disconnect();
    else fpgaSerial.connect(port, baud, mock);
  }
  function send() {
    fpgaSerial.sendText(input + (newLine ? "\n" : ""));
  }
  function exportLog() {
    const text = log
      .map((x) => `${x.time}\t${x.kind}\t${JSON.stringify(x.text)}`)
      .join("\r\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `bci-terminal-${new Date().toISOString().replace(/[:.]/g, "-")}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function snapshot() {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            savedAt: new Date().toISOString(),
            dataset,
            thresholdsMv: thresholds,
            biasV: bias,
            comparatorMode: mode,
            capture,
            serialLog: log,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = `bci-experiment-${Date.now()}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <section className="workspace-panel">
      <UartConnection />
      <section className="card run-control-card" aria-label="Run controls">
        <div className="run-control-heading">
          <div className="run-control-title">
            <h2>Run control</h2>
            <span className="muted run-control-subtitle">System readiness and acquisition status</span>
          </div>
          <button
            className={`run-toggle-button ${runActive ? "is-running" : "primary"}`}
            disabled={!runActive && (!connected || serialMock || appliedSignature !== thresholdSignature(thresholds, 1.6))}
            onClick={() => fpgaSerial.setRunActive(!runActive)}
            aria-pressed={runActive}
            title={runActive ? "Stop run" : "Start run"}
          >
            <span aria-hidden="true">{runActive ? "■" : "▶"}</span>
            {runActive ? "Stop run" : "Start run"}
          </button>
        </div>
        <div className="run-readiness" aria-label="System status">
          <div className={`run-readiness-item ${preview ? "is-ready" : ""}`}>
            <span className="run-readiness-dot" aria-hidden="true" />
            <span className="run-readiness-label">Dataset</span>
            <span className="run-readiness-value" title={preview?.name ?? undefined}>{preview ? preview.name || dataset : "Not loaded"}</span>
          </div>
          <div className={`run-readiness-item ${ad3Status === "connected" ? "is-ready" : ad3Status === "failed" ? "is-error" : ""}`}>
            <span className="run-readiness-dot" aria-hidden="true" />
            <span className="run-readiness-label">AD3</span>
            <span className="run-readiness-value">{{ unchecked: "Not checked", checking: "Checking…", connected: "Connected", failed: "Check failed" }[ad3Status]}</span>
          </div>
          <div className={`run-readiness-item ${connected && !serialMock ? "is-ready" : ""}`}>
            <span className="run-readiness-dot" aria-hidden="true" />
            <span className="run-readiness-label">UART</span>
            <span className="run-readiness-value">{connected ? serialMock ? "Mock connected" : `${serialPort ?? "Port"} · ${serialBaud ?? "?"} baud` : "Disconnected"}</span>
          </div>
          <div className={`run-readiness-item ${fpgaVerified ? "is-ready" : ""}`}>
            <span className="run-readiness-dot" aria-hidden="true" />
            <span className="run-readiness-label">FPGA</span>
            <span className="run-readiness-value">{fpgaVerified ? "Protocol verified" : "Not verified"}</span>
          </div>
        </div>
        {!runActive && appliedSignature !== thresholdSignature(thresholds, 1.6) && (
          <p className="run-control-note">Apply and acknowledge all eight thresholds to enable Start.</p>
        )}
      </section>
      <section className="card" aria-label="AD3 digital comparator test">
        <h2>AD3 digital comparator test</h2>
        <p className="muted">Hardware pulse validation (not yet derived from the selected neural waveform). DIO0–3 = N1–N4; DIO4–7 = P1–P4.</p>
        <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
          <label>Comparator <select value={pulseChannel} disabled={digitalBusy || digitalActive} onChange={(e) => setPulseChannel(Number(e.target.value))}>
            {Array.from({ length: 8 }, (_, i) => <option key={i} value={i}>{i < 4 ? `N${i + 1}` : `P${i - 3}`} (DIO{i})</option>)}
          </select></label>
          <label>Frequency (Hz) <input type="number" min="0.01" max="10000" step="any" value={pulseFrequency} disabled={digitalBusy || digitalActive} onChange={(e) => setPulseFrequency(Number(e.target.value))} /></label>
          <label>Width (µs) <input type="number" min="0.01" max="1000000" step="any" value={pulseWidth} disabled={digitalBusy || digitalActive} onChange={(e) => setPulseWidth(Number(e.target.value))} /></label>
          <label>Duration (s) <input type="number" min="0.1" max="60" step="any" value={pulseDuration} disabled={digitalBusy || digitalActive} onChange={(e) => setPulseDuration(Number(e.target.value))} /></label>
        </div>
        <div className="actions" style={{ marginTop: 12 }}>
          <button className="primary" disabled={digitalBusy || digitalActive || !runActive || !Number.isFinite(pulseFrequency) || pulseFrequency <= 0 || !Number.isFinite(pulseWidth) || pulseWidth <= 0 || !Number.isFinite(pulseDuration) || pulseDuration <= 0} onClick={startDigitalPulse}>Start pulses</button>
          <button disabled={digitalBusy} onClick={stopDigitalPulse}>Stop / reset LOW</button>
          <button disabled={digitalBusy || scopeBusy || !digitalActive} onClick={capturePulseScope}>{scopeBusy ? "Capturing…" : "Capture scope (CH1)"}</button>
          <span className="muted">{!digitalStatusKnown ? "Digital output status unknown" : digitalActive ? "Digital output active" : "Digital output idle"}</span>
        </div>
        {pulseScope && <div style={{ marginTop: 12 }}>
          <div className="muted">CH1: {pulseScope.min_v.toFixed(3)}–{pulseScope.max_v.toFixed(3)} V · Pulse width: {pulseScope.pulse_width_us === null ? "not detected" : `${pulseScope.pulse_width_us.toFixed(2)} µs`} · Edges: {pulseScope.edge_count}</div>
          <svg viewBox="0 0 800 180" role="img" aria-label="Triggered scope waveform" style={{ width: "100%", height: 180, background: "#111827", borderRadius: 6 }}>
            <polyline fill="none" stroke="#56d4f0" strokeWidth="1.5" points={pulseScope.voltage_v.filter((_, i) => i % 4 === 0).map((v, i, arr) => `${i * 800 / Math.max(1, arr.length - 1)},${165 - (v + 0.5) * 150 / 4.5}`).join(" ")} />
          </svg>
          <p className="muted">{pulseScope.note}</p>
        </div>}
        {digitalError && <p role="alert" style={{ color: "#d45" }}>{digitalError}</p>}
      </section>
      <section className="card">
        <div className="row between">
          <h2>Terminal output</h2>
          <div className="actions">
            <button onClick={exportLog} disabled={!log.length}>
              Save text
            </button>
            <button onClick={() => window.print()}>Print</button>
            <button onClick={clearLog}>Clear</button>
          </div>
        </div>
        <div className="terminal" role="log">
          {!log.length && (
            <span className="placeholder">No messages received.</span>
          )}
          {log.map((x) => (
            <div key={x.id} className="line">
              <span className="timestamp">{x.time}</span>
              <span className={`kind ${x.kind.toLowerCase()}`}>{x.kind}</span>
              <span className="text">
                {JSON.stringify(x.text).slice(1, -1)}
              </span>
            </div>
          ))}
        </div>
      </section>
      <section className="card">
        <h2>Analog capture · experiment view</h2>
        <ScopePair variant="experiment" />
      </section>
    </section>
  );
}
