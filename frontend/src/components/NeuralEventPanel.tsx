import { useEffect, useRef, useState, type UIEvent } from "react";
import { useRuntime, type NeuralEvent, type NeuralFlags } from "../state/store";
import { downloadNeuralEvents } from "../services/neuralEventCsv";
import "./NeuralEventPanel.css";

const flagNames: { key: keyof NeuralFlags; label: string }[] = [
  { key: "timeout", label: "Timeout" },
  { key: "saturation", label: "Saturation" },
  { key: "overlap", label: "Overlap" },
  { key: "invalid_sequence", label: "Invalid sequence" },
];
const ROW_HEIGHT = 34;
const OVERSCAN = 8;

function EventRow({ event, rowIndex }: { event: NeuralEvent; rowIndex: number }) {
  const flags = flagNames.filter(({ key }) => event.flags[key]).map(({ label }) => label).join(", ") || "—";
  return <tr className="neural-events__row" aria-rowindex={rowIndex}>
    <td>{(event.timestamp_us / 1000).toFixed(3)}</td>
    <td>{event.channel}</td><td>{event.peak}</td><td>{event.trough}</td>
    <td>{event.time_to_peak_us}</td>
    <td title={flags}>{flags}</td>
    <td><code>{event.raw_hex}</code></td>
  </tr>;
}

function EventTable({ events, full = false }: { events: readonly NeuralEvent[]; full?: boolean }) {
  const [scrollTop, setScrollTop] = useState(0);
  // Window the long list. Acquisition order is stable even as new events arrive.
  // The viewport is at most 440px high; render a generous overscan around it.
  const start = full ? Math.min(Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN), Math.max(0, events.length - 1)) : 0;
  const end = full ? Math.min(events.length, Math.max(start + 1, Math.ceil((scrollTop + 440) / ROW_HEIGHT) + OVERSCAN)) : events.length;
  const onScroll = (event: UIEvent<HTMLDivElement>) => setScrollTop(event.currentTarget.scrollTop);
  return <div className={`neural-events__table-wrap${full ? " neural-events__table-wrap--full" : ""}`}
    onScroll={full ? onScroll : undefined} tabIndex={full ? 0 : undefined}
    aria-label={full ? "Scrollable event history" : undefined}>
    <table className="neural-events__table" aria-rowcount={events.length + 1}>
      <colgroup><col style={{ width: "15%" }} /><col style={{ width: "5%" }} />
        <col style={{ width: "7%" }} /><col style={{ width: "8%" }} />
        <col style={{ width: "12%" }} /><col style={{ width: "21%" }} /><col style={{ width: "32%" }} /></colgroup>
      <thead><tr><th scope="col">FPGA time (ms)</th><th scope="col">CH</th>
        <th scope="col">Peak</th><th scope="col">Trough</th><th scope="col">TTP (µs)</th>
        <th scope="col">Flags</th><th scope="col">Raw UART (hex)</th></tr></thead>
      <tbody>
        {start > 0 && <tr aria-hidden="true"><td colSpan={7} className="neural-events__spacer" style={{ height: start * ROW_HEIGHT }} /></tr>}
        {events.slice(start, end).map((event, i) => <EventRow key={start + i} event={event} rowIndex={start + i + 2} />)}
        {end < events.length && <tr aria-hidden="true"><td colSpan={7} className="neural-events__spacer" style={{ height: (events.length - end) * ROW_HEIGHT }} /></tr>}
      </tbody>
    </table>
  </div>;
}

function EventHistory({ events, runId, running, onClose }: {
  events: readonly NeuralEvent[]; runId: string | null; running: boolean; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    if (node && !node.open) node.showModal();
    return () => { if (node?.open) node.close(); };
  }, []);
  return <dialog ref={dialog} className="modal neural-events__dialog" aria-labelledby="neural-history-title"
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
    }}>
    <div className="row between neural-events__heading">
      <h2 id="neural-history-title">Neural Event History</h2>
      <button type="button" autoFocus onClick={onClose} aria-label="Close event history">✕</button>
    </div>
    <p className="hint">{events.length.toLocaleString()} events received by this console · {running ? "Live" : "Last capture"} · Oldest first{runId ? ` · ${runId}` : ""}</p>
    {events.length ? <EventTable events={events} full /> : <p className="hint">No events received.</p>}
    <p className="hint">FPGA timestamps wrap every 16.777216 s. Rows and CSV preserve acquisition order. For authoritative saved evidence, use the experiment ZIP in Results.</p>
    <div className="actions neural-events__history-actions">
      <button type="button" disabled={!events.length} onClick={() => downloadNeuralEvents(events, runId)}>Download CSV</button>
      <button type="button" onClick={onClose}>Close</button>
    </div>
  </dialog>;
}

export default function NeuralEventPanel() {
  const events = useRuntime((s) => s.neuralEvents);
  const stats = useRuntime((s) => s.neuralStats);
  const running = useRuntime((s) => s.runActive);
  const runId = useRuntime((s) => s.neuralRunId);
  const [historyOpen, setHistoryOpen] = useState(false);
  const recent = events.slice(-4).reverse();

  return <section className="neural-events" aria-labelledby="live-neural-events-title">
    <div className="row between neural-events__heading">
      <h3 id="live-neural-events-title">Live Neural Events</h3>
      <div className="actions neural-events__actions">
        <button type="button" onClick={() => setHistoryOpen(true)} disabled={!events.length && !running}>View all{events.length ? ` (${events.length.toLocaleString()})` : ""}</button>
        <button type="button" disabled={!events.length} onClick={() => downloadNeuralEvents(events, runId)}>Download CSV</button>
      </div>
    </div>
    <div className="neural-events__stats">
      <span><strong>Events:</strong> {(stats?.received ?? events.length).toLocaleString()}</span>
      <span>Timeout: {stats?.timeouts ?? 0}</span>
      <span>Saturation: {stats?.saturations ?? 0}</span>
      <span>Overlap: {stats?.overlaps ?? 0}</span>
      <span>Invalid: {stats?.invalid_sequences ?? 0}</span>
    </div>
    {recent.length ? <EventTable events={recent} /> : <p className="hint neural-events__empty">{running ? "Listening for FPGA events…" : "No events captured. Start a run to begin."}</p>}
    {historyOpen && <EventHistory events={events} runId={runId} running={running} onClose={() => setHistoryOpen(false)} />}
  </section>;
}
