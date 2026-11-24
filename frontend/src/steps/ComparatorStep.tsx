import React, { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../state/api";
import {
  AFE_BIAS_V,
  DAC_REFERENCE_V,
  dacCode,
  validThresholds,
  sendThresholdsToFpga,
} from "../services/thresholdConfiguration";
import UartConnection from "../components/UartConnection";
import SerialTerminalModal from "../components/SerialTerminalModal";
import { Accordion } from "../components/Accordion";
import { useConfig, useRuntime, thresholdSignature } from "../state/store";
import { FtdiUartGuide } from "../guides/FtdiUartGuide"

const CHANNELS = ["P1", "P2", "P3", "P4", "N1", "N2", "N3", "N4"];

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
  const sendStatus = useRuntime((s) => s.thresholdSendStatus);
  const message = useRuntime((s) => s.thresholdSendMessage);
  const ports = useQuery({ queryKey: ["ports"], queryFn: api.ports, retry: 0 });

  useEffect(() => {
    // Keep legacy persisted settings consistent with the fixed hardware configuration.
    setBias(AFE_BIAS_V);
    setMode("physical");
  }, [setBias, setMode]);

  const [port, setPort] = useState("");
  const [baud, setBaud] = useState(115200);
  const [mirror, setMirror] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const closeTerminal = useCallback(() => setTerminalOpen(false), []);

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
  const valid = validThresholds(thresholds);
  const busy = sendStatus === "sending";
  const failed = sendStatus === "error";
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
  }

  function toggleMirror(checked: boolean) {
    if (runActive) return;
    setMirror(checked);
    if (checked) {
      // Positive thresholds are the source when mirroring is enabled.
      for (let i = 0; i < 4; i++) setThreshold(i + 4, -thresholds[i]);
    }
  }

  return (
    <section className="workspace-panel">
      <UartConnection />
      <Accordion
            defaultOpenId="thresholds"
            sections={[
              {
                id: "ftdi",
                title: "FTDI to DE10-Lite Wiring Guide",
                content: <FtdiUartGuide />,
              },
              {
                id: "thresholds",
                title: "Neural event thresholds",
                content: (
                  <section className="card comparator-thresholds">
                    <div className="row between">
                      <div className="actions" style={{ alignItems: "center" }}>
                        <button type="button" onClick={() => setTerminalOpen(true)}>
                          UART Terminal
                        </button>
                        <span className="badge">{acknowledgedCount}/8 acknowledged</span>
                      </div>
                    </div>
                    {runActive && <p className="hint" role="status">Live run active — threshold configuration is locked until Stop.</p>}
                    <p className="muted comparator-thresholds__meta">
                      AFE bias: 1.600 V (fixed) · DAC range: 0–2.5 V · 16-bit
                    </p>
                    <div style={{ overflowX: "auto" }}>
                      <table
                        className="comparator-thresholds__table"
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
                                <th scope="row" style={{ padding: "3px 7px 3px 0" }}>
                                  {name}
                                </th>
                                <td style={{ padding: "3px 7px" }}>
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
                                    className="comparator-thresholds__input"
                                    style={{ width: "110px" }}
                                  />
                                </td>
                                <td style={{ padding: "3px 7px" }}>
                                  {Number.isFinite(voltage)
                                    ? `${voltage.toFixed(4)} V`
                                    : "—"}
                                </td>
                                <td style={{ padding: "3px 7px", fontFamily: "monospace" }}>
                                  {code}
                                </td>
                                <td style={{ padding: "3px 7px" }}>
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
                        disabled={runActive || !valid || busy || !connected || serialMock}
                        onClick={() => void sendThresholdsToFpga()}
                      >
                        {busy ? "Sending thresholds…" : "Send thresholds to FPGA"}
                      </button>
                      <span
                        className={
                          connected && !serialMock && applied === signature ? "badge online" : "badge"
                        }
                      >
                        {connected && !serialMock && applied === signature
                          ? "8/8 encoded / acknowledged"
                          : "Not fully applied"}
                      </span>
                    </div>
                    {!valid && (
                      <p className="error">
                        Thresholds must produce 0–2.5 V DAC values; P ≥ 0 mV and N ≤ 0 mV.
                      </p>
                    )}
                    {(message || (sendStatus === "success" && applied !== signature)) && (
                      <p className={failed ? "error" : "hint"} role="status">
                        {sendStatus === "success" && applied !== signature
                          ? "Thresholds changed since the last acknowledgment. Send the current values again."
                          : message}
                      </p>
                    )}
                    <p className="hint">
                      FPGA acknowledgment confirms SPI command encoding only. The FPGA does
                      not yet transmit SPI to the physical DAC.
                    </p>
                  </section>
                  ),
              },
            ]}
          />
      
      {terminalOpen && <SerialTerminalModal onClose={closeTerminal} />}
    </section>
  );
}
