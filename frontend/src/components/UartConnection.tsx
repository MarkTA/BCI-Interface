import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../state/api";
import { useRuntime } from "../state/store";
import { fpgaSerial } from "../services/fpgaSerial";

export default function UartConnection() {
  const ports = useQuery({
    queryKey: ["ports"],
    queryFn: api.ports,
    retry: 0,
  });

  const connected = useRuntime((s) => s.serialConnected);
  const status = useRuntime((s) => s.serialStatus);
  const serialPort = useRuntime((s) => s.serialPort);
  const serialBaud = useRuntime((s) => s.serialBaud);
  const fpgaVerified = useRuntime((s) => s.fpgaVerified);

  const [port, setPort] = useState("");
  const [baud, setBaud] = useState(115200);

  // Restore the active connection when navigating between steps.
  useEffect(() => {
    if (connected) {
      if (serialPort) setPort(serialPort);
      if (serialBaud) setBaud(serialBaud);
    }
  }, [connected, serialPort, serialBaud]);

  // Automatically select the first available port.
  useEffect(() => {
    if (!connected && !port && ports.data?.length) {
      setPort(ports.data[0].device);
    }
  }, [connected, port, ports.data]);

  const busy = fpgaSerial.active;

  function toggleConnection() {
    if (busy) {
      fpgaSerial.disconnect();
    } else {
      fpgaSerial.connect(port, baud, false);
    }
  }

  return (
    <section className="card fpga-connection">
      <div className="row between">
        <h2>UART FPGA Connection</h2>

        <span className={fpgaVerified ? "badge online" : "badge"}>
          {fpgaVerified
            ? "FPGA protocol verified"
            : connected
              ? "Connected · Not verified"
              : "Disconnected"}
        </span>
      </div>

      <div className="fpga-connection__toolbar">
        <button
          type="button"
          className="refresh-button"
          title="Refresh COM ports"
          aria-label="Refresh COM ports"
          disabled={busy || ports.isFetching}
          onClick={() => void ports.refetch()}
        >
          ↻
        </button>
        <select
          aria-label="Serial port"
          title="Serial port"
          value={port}
          disabled={busy}
          onChange={(e) => setPort(e.target.value)}
        >
          {!ports.data?.length && (
            <option value="">No COM ports detected</option>
          )}

          {ports.data?.map((p) => (
            <option key={p.device} value={p.device}>
              {p.device} — {p.description}
            </option>
          ))}
        </select>

        <select
          aria-label="Baud rate"
          title="Baud rate"
          value={baud}
          disabled={busy}
          onChange={(e) => setBaud(Number(e.target.value))}
        >
          <option value={115200}>115200</option>
          <option value={921600}>921600</option>
          <option value={9600}>9600</option>
        </select>

        <button
          type="button"
          className="primary"
          disabled={!busy && !port}
          onClick={toggleConnection}
        >
          {busy ? "Disconnect" : "Connect"}
        </button>
      </div>

      {ports.isError && (
        <p className="error">Unable to list COM ports: {String(ports.error)}</p>
      )}

      {status && !connected && status !== "Disconnected" && (
        <p className="hint" role="status">
          {status}
        </p>
      )}
    </section>
  );
}
