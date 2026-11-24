import { useEffect, useRef } from "react";
import { useRuntime } from "../state/store";

type Props = { onClose: () => void };

/** Serial diagnostics belong to Step 4, but the log remains shared and live. */
export default function SerialTerminalModal({ onClose }: Props) {
  const log = useRuntime((s) => s.log);
  const clearLog = useRuntime((s) => s.clearLog);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);

  function exportLog() {
    const content = log.map((entry) => `${entry.time}\t${entry.kind}\t${entry.text}`).join("\r\n");
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `cortex-serial-${Date.now()}.txt`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="modal serial-terminal-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="serial-terminal-title"
      >
        <div className="row between">
          <h2 id="serial-terminal-title">UART Terminal</h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close terminal">
            ✕
          </button>
        </div>
        <div className="terminal" role="log" aria-live="off">
          {!log.length && <span className="placeholder">No messages received.</span>}
          {log.map((entry) => (
            <div key={entry.id} className="line">
              <span className="timestamp">{entry.time}</span>
              <span className={`kind ${entry.kind.toLowerCase()}`}>{entry.kind}</span>
              <span className="text">{entry.text}</span>
            </div>
          ))}
        </div>
        <div className="actions serial-terminal-modal__actions">
          <button type="button" onClick={exportLog} disabled={!log.length}>Save text</button>
          <button type="button" onClick={() => window.print()}>Print</button>
          <button type="button" onClick={clearLog} disabled={!log.length}>Clear</button>
        </div>
      </section>
    </div>
  );
}
