import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../state/api";
import { fpgaSerial } from "../services/fpgaSerial";
import UartConnection from "../components/UartConnection";
import { useConfig, useRuntime, thresholdSignature } from "../state/store";

const AFE_BIAS_V = 1.6;
const DAC_REFERENCE_V = 2.5;
const CHANNELS = ["P1", "P2", "P3", "P4", "N1", "N2", "N3", "N4"];

function dacCode(voltage: number): number {
  return Math.max(
    0,
    Math.min(65535, Math.floor((voltage / DAC_REFERENCE_V) * 65536 + 0.5)),
  );
}

export default function ComparatorStep() {
  const thresholds = useConfig((s) => s.thresholdsMv);
  const runActive = useRuntime((s) => s.runActive);
  const setThreshold = useConfig((s) => s.setThreshold);
  const setBias = useConfig((s) => s.setBias);
  const setMode = useConfig((s) => s.setComparatorMode);
  const connected = useRuntime((s) => s.serialConnected);
  const serialMock = useRuntime((s) => s.serialMock);
  const serialPort = useRuntime((s) => s.serialPort);
  const serialBaud = useRuntime((s) => s.serialBaud);
  const serialStatus = useRuntime((s) => s.serialStatus);
  const fpgaVerified = useRuntime((s) => s.fpgaVerified);
  const acks = useRuntime((s) => s.thresholdAcks);
  const applied = useRuntime((s) => s.appliedSignature);
  const setApplied = useRuntime((s) => s.setAppliedSignature);
  const addLog = useRuntime((s) => s.addLog);
  const ports = useQuery({ queryKey: ["ports"], queryFn: api.ports, retry: 0 });

  useEffect(() => {
    // Keep legacy persisted settings consistent with the fixed hardware configuration.
    setBias(AFE_BIAS_V);
    setMode("physical");
  }, [setBias, setMode]);

  const [port, setPort] = useState("");
  const [baud, setBaud] = useState(115200);
  const [mirror, setMirror] = useState(false);
  const [applying, setApplying] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (connected) {
      if (serialPort) setPort(serialPort);
      if (serialBaud) setBaud(serialBaud);
    }
  }, [connected, serialPort, serialBaud]);

  useEffect(() => {
    if (!connected && !port && ports.data?.length)
      setPort(ports.data[0].device);
  }, [connected, port, ports.data]);

  const signature = thresholdSignature(thresholds, AFE_BIAS_V);
  const valid =
    thresholds.length === 8 &&
    thresholds.every((v, i) => {
      const voltage = AFE_BIAS_V + v / 1000;
      return (
        Number.isFinite(v) &&
        voltage >= 0 &&
        voltage <= DAC_REFERENCE_V &&
        (i < 4 ? v >= 0 : v <= 0)
      );
    });
  const busy = applying;
  const acknowledgedCount = thresholds.filter((v, i) => {
    const ack = acks[i];
    return (
      connected &&
      !serialMock &&
      ack?.dac_code ===
        `0x${dacCode(AFE_BIAS_V + v / 1000)
          .toString(16)
          .padStart(4, "0")
          .toUpperCase()}`
    );
  }).length;

  function editThreshold(index: number, value: number) {
    if (runActive) return;
    setThreshold(index, value);
    if (mirror) {
      const partner = index < 4 ? index + 4 : index - 4;
      setThreshold(partner, -value);
    }
    setMessage("");
    setFailed(false);
  }

  function toggleMirror(checked: boolean) {
    if (runActive) return;
    setMirror(checked);
    if (checked) {
      // Positive thresholds are the source when mirroring is enabled.
      for (let i = 0; i < 4; i++) setThreshold(i + 4, -thresholds[i]);
    }
    setMessage("");
  }

  async function apply() {
    if (runActive) { setMessage("Stop the live run before changing thresholds."); return; }
    if (!connected || serialMock) {
      setMessage("Connect to the physical FPGA first.");
      return;
    }
    if (!valid || applying) return;
    const submitted = signature;
    setApplied(null);
    setFailed(false);
    setApplying(true);
    setMessage("Sending eight threshold commands to the FPGA…");
    try {
      const results = await fpgaSerial.setThresholds(
        thresholds.map((v) => AFE_BIAS_V + v / 1000),
      );
      if (
        results.length !== 8 ||
        results.some((r, i) => r.channel !== i || r.status !== "encoded")
      ) {
        throw new Error("Incomplete FPGA acknowledgments");
      }
      if (
        thresholdSignature(useConfig.getState().thresholdsMv, AFE_BIAS_V) ===
        submitted
      ) {
        setApplied(submitted);
      }
      addLog(
        "INFO",
        "All eight threshold SPI commands encoded and acknowledged by FPGA",
      );
      setMessage(
        "8/8 FPGA acknowledgments received. SPI encoded; physical DAC not programmed.",
      );
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      setFailed(true);
      setMessage(`Threshold configuration failed: ${reason}`);
      addLog("ERROR", `Threshold configuration failed: ${reason}`);
    } finally {
      setApplying(false);
    }
  }

  return (
    <section className="workspace-panel">
      <UartConnection />
      <section className="card">
        <div className="row between">
          <h2>Neural event thresholds</h2>
          <span className="badge">{acknowledgedCount}/8 acknowledged</span>
        </div>
        {runActive && <p className="hint" role="status">Live run active — threshold configuration is locked until Stop.</p>}
        <p className="muted">
          AFE bias: 1.600 V (fixed) · DAC range: 0–2.5 V · 16-bit
        </p>
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              textAlign: "left",
            }}
          >
            <thead>
              <tr>
                <th scope="col">Channel</th>
                <th scope="col">Threshold (mV)</th>
                <th scope="col">DAC voltage</th>
                <th scope="col">DAC code</th>
                <th scope="col">FPGA response</th>
              </tr>
            </thead>
            <tbody>
              {CHANNELS.map((name, i) => {
                const mv = thresholds[i];
                const voltage = AFE_BIAS_V + mv / 1000;
                const code = Number.isFinite(voltage)
                  ? `0x${dacCode(voltage).toString(16).padStart(4, "0").toUpperCase()}`
                  : "—";
                const ack = acks[i];
                const matches =
                  connected && !serialMock && ack?.dac_code === code;
                const response = matches
                  ? `${ack.spi_command} · Encoded`
                  : ack
                    ? "Modified"
                    : failed
                      ? "Error / not acknowledged"
                      : "Not sent";
                return (
                  <tr key={name}>
                    <th scope="row" style={{ padding: "10px 12px 10px 0" }}>
                      {name}
                    </th>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="number"
                        disabled={runActive}
                        step="0.5"
                        min={i < 4 ? 0 : -1600}
                        max={i < 4 ? 900 : 0}
                        aria-label={`${name} threshold in millivolts`}
                        value={mv}
                        onChange={(e) =>
                          editThreshold(i, Number(e.target.value))
                        }
                        style={{ width: "110px" }}
                      />
                    </td>
                    <td style={{ padding: "8px" }}>
                      {Number.isFinite(voltage)
                        ? `${voltage.toFixed(4)} V`
                        : "—"}
                    </td>
                    <td style={{ padding: "8px", fontFamily: "monospace" }}>
                      {code}
                    </td>
                    <td style={{ padding: "8px" }}>
                      <span
                        className={
                          matches
                            ? "status-good"
                            : failed && !ack
                              ? "error"
                              : "muted"
                        }
                      >
                        {response}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <label className="check" style={{ marginTop: 16 }}>
          <input
            type="checkbox"
            checked={mirror}
            disabled={runActive}
            onChange={(e) => toggleMirror(e.target.checked)}
          />{" "}
          Mirror positive thresholds (N1–N4 = −P1–P4)
        </label>
        <div className="actions" style={{ marginTop: 16 }}>
          <button
            className="primary"
            disabled={runActive || !valid || applying || !connected || serialMock}
            onClick={() => void apply()}
          >
            {applying ? "Sending thresholds…" : "Send thresholds to FPGA"}
          </button>
          <span
            className={
              connected && applied === signature ? "badge online" : "badge"
            }
          >
            {connected && applied === signature
              ? "8/8 encoded / acknowledged"
              : "Not fully applied"}
          </span>
        </div>
        {!valid && (
          <p className="error">
            Thresholds must produce 0–2.5 V DAC values; P ≥ 0 mV and N ≤ 0 mV.
          </p>
        )}
        {message && (
          <p className={failed ? "error" : "hint"} role="status">
            {message}
          </p>
        )}
        <p className="hint">
          FPGA acknowledgment confirms SPI command encoding only. The FPGA does
          not yet transmit SPI to the physical DAC.
        </p>
      </section>
    </section>
  );
}
