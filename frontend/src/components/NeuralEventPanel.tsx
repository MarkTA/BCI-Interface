import React, { useState } from "react";
import { useRuntime, type NeuralFlags } from "../state/store";

const flagNames: { key: keyof NeuralFlags; label: string }[] = [
  { key: "timeout", label: "Timeout" },
  { key: "saturation", label: "Saturation" },
  { key: "overlap", label: "Overlap" },
  { key: "invalid_sequence", label: "Invalid sequence" },
];

// In the Results accordion, omit the standalone card/title so the existing
// accordion heading remains the single section heading.
export default function NeuralEventPanel({ embedded = false }: { embedded?: boolean }) {
  const events = useRuntime((s) => s.neuralEvents);
  const stats = useRuntime((s) => s.neuralStats);
  const runActive = useRuntime((s) => s.runActive);
  const clear = useRuntime((s) => s.clearNeuralEvents);
  const [showRaw, setShowRaw] = useState(false);
  const recent = events.slice(-30).reverse();

  return <section className={embedded ? undefined : "card"} aria-label="Decoded FPGA neural events">
    <div className="row between" style={{ flexWrap: "wrap", gap: 12 }}>
      {embedded ? <span className="muted">FPGA decoded events</span> : <h2>Neural events · FPGA decoded</h2>}
      <div className="actions">
        <button type="button" onClick={() => setShowRaw((value) => !value)}>
          {showRaw ? "Hide raw hex" : "Show raw hex"}
        </button>
        <button type="button" disabled={!events.length && !stats} onClick={clear}>Clear events</button>
      </div>
    </div>
    <p className="muted">
      Live <code>AA 02</code> packets from James's event FSM, not comparator GPIO transitions.
      Displays the latest 30 events (stores up to 250); totals cover the current/last armed Run.
      FPGA timestamp is a 24-bit microsecond counter that wraps every 16.777216 seconds.
    </p>
    <div className="row" style={{ flexWrap: "wrap", gap: 16, margin: "12px 0" }} aria-live="polite">
      <span><strong>Events:</strong> {stats?.received ?? 0}</span>
      <span><strong>Timeouts:</strong> {stats?.timeouts ?? 0}</span>
      <span><strong>Saturation:</strong> {stats?.saturations ?? 0}</span>
      <span><strong>Overlap:</strong> {stats?.overlaps ?? 0}</span>
      <span><strong>Invalid sequence:</strong> {stats?.invalid_sequences ?? 0}</span>
    </div>
    {!recent.length ? <p className="muted">{runActive
      ? "Listening for neural-event packets. Start AD3 dataset playback or use the FPGA's internal test pulse."
      : "No neural events captured. Connect the FPGA and select Start run to begin listening."}</p> :
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse" }}>
          <thead><tr>
            <th scope="col">FPGA time (ms)</th><th scope="col">CH</th>
            <th scope="col">Peak</th><th scope="col">Trough</th>
            <th scope="col">To peak (µs)</th><th scope="col">Flags</th>
            {showRaw && <th scope="col">Raw UART</th>}
          </tr></thead>
          <tbody>{recent.map((event, i) => {
            const activeFlags = flagNames.filter(({ key }) => event.flags[key]).map(({ label }) => label);
            return <tr key={`${event.timestamp_us}-${i}-${event.raw_hex}`}>
              <td>{(event.timestamp_us / 1000).toFixed(3)}</td>
              <td>{event.channel}</td><td>{event.peak}</td><td>{event.trough}</td>
              <td>{event.time_to_peak_us}</td>
              <td style={{ whiteSpace: "nowrap" }}>{activeFlags.length ? activeFlags.join(", ") : "—"}</td>
              {showRaw && <td><code style={{ whiteSpace: "nowrap" }}>{event.raw_hex}</code></td>}
            </tr>;
          })}</tbody>
        </table>
      </div>}
    <p className="muted" style={{ marginTop: 10 }}>
      The FPGA's quiet confirmation (500 µs), refractory period (100 µs), and timeout (2.5 ms)
      determine how comparator activity is grouped into neural events. A repeating dataset
      need not produce exactly one packet per cycle.
    </p>
  </section>;
}
