import React, { useMemo } from "react";
import type { GpioTraceState } from "../state/store";
import {
  compareGpioCycle, GPIO_CHANNELS, type ReferenceState,
} from "./gpioComparison";

type Props = {
  referenceStates: ReferenceState[];
  observed: GpioTraceState[];
  expectedEdges: Record<string, number>;
};

function StateChart({ states, label }: { states: number[]; label: string }) {
  const left = 56;
  const right = 524;
  const row = 25;
  const width = right - left;
  const length = Math.max(1, states.length);
  return <svg viewBox="0 0 540 232" role="img" aria-label={label}
    style={{ width: "100%", display: "block", background: "#0b1423", borderRadius: 6 }}>
    {GPIO_CHANNELS.map((channel, bit) => {
      const y = 18 + bit * row;
      const highY = y;
      const lowY = y + 12;
      const color = bit < 4 ? "#a78bfa" : "#48d9c1";
      let path = `M${left} ${states[0] & (1 << bit) ? highY : lowY}`;
      for (let i = 0; i < length; i++) {
        const x = left + (i + 1) * width / length;
        const active = (states[i] & (1 << bit)) !== 0;
        path += ` H${x.toFixed(2)}`;
        if (i + 1 < length) {
          const next = (states[i + 1] & (1 << bit)) !== 0;
          if (active !== next) path += ` V${next ? highY : lowY}`;
        }
      }
      return <g key={channel}>
        <line x1={left} x2={right} y1={lowY} y2={lowY} stroke="#374151" strokeWidth={0.6} />
        <text x="10" y={y + 11} fill="#d6deea" fontSize="12">{channel}</text>
        <path d={path} stroke={color} strokeWidth="2" fill="none" strokeLinejoin="round" />
      </g>;
    })}
    <text x="12" y="226" fill="#9ca3af" fontSize="10">Ordered state reports →</text>
    <text x={right} y="226" textAnchor="end" fill="#9ca3af" fontSize="10">{states.length} states</text>
  </svg>;
}

/** Diagnostic visual comparison, not a phase-locked oscilloscope capture. */
export default function GpioComparison({ referenceStates, observed, expectedEdges }: Props) {
  const cycle = useMemo(() => compareGpioCycle(referenceStates, observed), [referenceStates, observed]);
  const expectedIdle = referenceStates.length === 1 && referenceStates[0].mask === 0;
  const nonzeroObserved = observed.some(([n, p]) => n !== 0 || p !== 0);
  const edgeMatch = cycle ? cycle.actualEdges.every((value, i) => value === cycle.expectedEdges[i]) : false;

  return <section className="card" aria-label="Expected versus FPGA comparator activity" style={{ marginTop: 16 }}>
    <div className="row between" style={{ flexWrap: "wrap", gap: 8 }}>
      <h3 style={{ margin: 0 }}>Comparator state sequence · expected vs FPGA</h3>
      {cycle && <span className="badge">{edgeMatch ? "8/8 channels: matching edge counts" : "Inspect channel edge differences"}</span>}
    </div>
    <p className="muted" style={{ marginTop: 8 }}>
      Compares the order of comparator HIGH/LOW states during one repeating waveform cycle.
      The FPGA reports via UART without hardware timestamps, so horizontal positions show <strong>state order, not time</strong>.
      Intermediate states may be merged into a single UART report; this is not a timing or data-loss measurement.
    </p>
    {cycle ? <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", gap: 12 }}>
        <div><h4 style={{ margin: "6px 0" }}>Expected · software comparator model</h4>
          <StateChart states={cycle.expected} label="Expected N1–N4 and P1–P4 comparator sequence for one waveform cycle" />
        </div>
        <div><h4 style={{ margin: "6px 0" }}>Observed · FPGA UART state reports</h4>
          <StateChart states={cycle.actual} label="FPGA reported N1–N4 and P1–P4 states for a recent full cycle" />
        </div>
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        Aligned by a repeated unique comparator state (mask 0x{cycle.anchor.toString(16).toUpperCase().padStart(2, "0")}).
        {` ${cycle.matchedStates}/${cycle.expected.length} expected state masks appeared in order; `}
        {cycle.actual.length} state masks were reported for the selected cycle.
        Missing intermediate masks can result from merged GPIO reports even when every channel's edges are counted.
      </p>
      <div style={{ overflowX: "auto" }}><table style={{ width: "100%", textAlign: "center" }}>
        <thead><tr><th style={{ textAlign: "left" }}>Edges / cycle</th>{GPIO_CHANNELS.map((ch) => <th key={ch}>{ch}</th>)}</tr></thead>
        <tbody>
          <tr><th style={{ textAlign: "left" }}>Predicted</th>{GPIO_CHANNELS.map((ch) => <td key={ch}>{expectedEdges[ch] ?? "—"}</td>)}</tr>
          <tr><th style={{ textAlign: "left" }}>FPGA</th>{GPIO_CHANNELS.map((ch, i) => <td key={ch} style={{ fontWeight: 600, color: cycle.actualEdges[i] === cycle.expectedEdges[i] ? "#6ee7b7" : "#fbbf24" }}>{cycle.actualEdges[i]}</td>)}</tr>
        </tbody>
      </table></div>
    </> : expectedIdle ? <p className="muted" role="status">
      No-spike reference: all comparators should remain LOW. {observed.length === 0
        ? "Awaiting FPGA states."
        : nonzeroObserved ? "⚠ FPGA reported a nonzero comparator state." : "FPGA reports observed so far are LOW."}
    </p> : <p className="muted" role="status">
      {observed.length === 0
        ? "Start the FPGA Run and AD3 dataset playback to collect comparator states."
        : `Received ${observed.length} FPGA state reports. Waiting for two occurrences of a distinctive reference state to identify a complete cycle.`}
    </p>}
  </section>;
}
