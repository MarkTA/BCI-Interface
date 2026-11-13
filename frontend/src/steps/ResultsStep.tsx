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
