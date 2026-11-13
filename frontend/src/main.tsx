import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useConfig, useRuntime, type Step } from "./state/store";
import SetupStep from "./steps/SetupStep";
import DatasetStep from "./steps/DatasetStep";
import AFEStep from "./steps/AFEStep";
import ComparatorStep from "./steps/ComparatorStep";
import ResultsStep from "./steps/ResultsStep";
import StepAboutModal from "./components/StepAboutModal";
import { STEP_ABOUT } from "./config/stepAbout";
import "./style.css";
const client = new QueryClient({
  defaultOptions: { queries: { staleTime: 30000, retry: 1 } },
});
const STEPS: { key: Step; title: string; short: string }[] = [
  { key: "setup", title: "PCB Setup", short: "PCB Setup" },
  { key: "dataset", title: "Synthetic Brainwaves", short: "Signal Dataset" },
  { key: "afe", title: "Analog Conditioning", short: "Analog Input" },
  { key: "comparators", title: "Neural Events", short: "Thresholds" },
  { key: "results", title: "Data Output", short: "Digital Output" },
];
function App() {
  const step = useConfig((s) => s.step),
    setStep = useConfig((s) => s.setStep),
    check = useConfig((s) => s.checkboxes),
    datasetName = useConfig((s) => s.datasetName),
    preview = useRuntime((s) => s.preview),
    ad3Status = useRuntime((s) => s.ad3Status),
    serial = useRuntime((s) => s.serialConnected),
    serialPort = useRuntime((s) => s.serialPort),
    serialBaud = useRuntime((s) => s.serialBaud),
    serialMock = useRuntime((s) => s.serialMock),
    fpgaVerified = useRuntime((s) => s.fpgaVerified);
  const [about, setAbout] = useState(false);
  const [stepAboutOpen, setStepAboutOpen] = useState(false);
  const progress = [
    ["power", "ad3", "ribbon", "uart"].every((k) => check[k]),
    !!preview,
    false,
    false,
  ];

  const [theme, setTheme] = useState<"light" | "dark">(() => {
    return localStorage.getItem("theme") === "light" ? "light" : "dark";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    setStepAboutOpen(false);
  }, [step]);

  const toggleTheme = () => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  };
  const render = () => {
    switch (step) {
      case "setup":
        return <SetupStep />;
      case "dataset":
        return <DatasetStep />;
      case "afe":
        return <AFEStep />;
      case "comparators":
        return <ComparatorStep />;
      case "results":
        return <ResultsStep />;
    }
  };
  return (
    <main className="shell">
      <header className="app-header">
        <div className="header-status">
          <div className="status-strip" aria-label="Connection status">
            <h3>System status</h3>
            <span className={preview ? "status-good" : "status-muted"}>
              <span className="status-dot" aria-hidden="true" />
              Dataset: {preview ? preview.name || datasetName : "Not loaded"}
            </span>
            <span
              className={
                ad3Status === "connected"
                  ? "status-good"
                  : ad3Status === "failed"
                    ? "status-error"
                    : "status-muted"
              }
            >
              <span className="status-dot" aria-hidden="true" />
              AD3:{" "}
              {
                {
                  unchecked: "Not checked",
                  checking: "Checking…",
                  connected: "Connected",
                  failed: "Check failed",
                }[ad3Status]
              }
            </span>
            <span
              className={serial && !serialMock ? "status-good" : "status-muted"}
            >
              <span className="status-dot" aria-hidden="true" />
              UART:{" "}
              {serial
                ? serialMock
                  ? "Mock connected"
                  : `${serialPort ?? "Port"} · ${serialBaud ?? "?"} baud`
                : "Disconnected"}
            </span>
            
            <span className={fpgaVerified ? "status-good" : "status-muted"}>
              <span className="status-dot" aria-hidden="true" />
              FPGA: {fpgaVerified ? "Protocol verified" : "Not verified"}
            </span>
          </div>
        </div>
        <div className="header-title">
          <div className="eyebrow">CORTEX SIGNALS / ASU CAPSTONE</div>
          <h1>BCI Console</h1>
        </div>
        <div className="header-actions">
          <button onClick={() => setAbout(true)}>About project</button>
          <button
            type="button"
            id="theme-toggle"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? "Light Mode" : "Dark Mode"}
          </button>
        </div>
      </header>

      <nav className="workflow" aria-label="Experiment steps">
        {STEPS.map((s, i) => (
          <button
            key={s.key}
            type="button"
            className={`step-tab ${step === s.key ? "active" : ""}`}
            onClick={() => setStep(s.key)}
            aria-current={step === s.key ? "step" : undefined}
          >
            <span className="step-number">{progress[i] ? "✓" : i + 1}</span>
            <span className="step-label">
              <strong>{s.short}</strong>
              {/* <small>{s.title}</small> */}
            </span>
          </button>
        ))}
      </nav>
      <div className="step-about-bar">
        <button
          type="button"
          className="step-about-button"
          onClick={() => setStepAboutOpen(true)}
        >
          <span aria-hidden="true">ⓘ</span> {STEP_ABOUT[step].buttonLabel}
        </button>
      </div>
      {render()}

      {stepAboutOpen && (
        <StepAboutModal
          config={STEP_ABOUT[step]}
          onClose={() => setStepAboutOpen(false)}
        />
      )}

      {about && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setAbout(false);
          }}
        >
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="About BCI Cortex Signals"
          >
            <div className="row between">
              <h2>About Cortex Signals</h2>
              <button
                onClick={() => setAbout(false)}
                aria-label="Close about dialog"
              >
                ✕
              </button>
            </div>
            <p>
              This ASU electrical engineering capstone explores converting
              continuous neural waveforms into compact digital events through
              analog conditioning, programmable threshold comparators, and FPGA
              logic.
            </p>
            <p>
              <b>Team contributions:</b> Slava — PCB/power; Kenny — waveforms;
              Mark — analog frontend and application; Petar — DAC/comparators;
              James — FPGA. Faculty mentor: Dr. Frank Fan.
            </p>
            <p className="hint">
              This console is a laboratory prototype. Contributor-specific
              technical writeups and verified hardware images will be added as
              the team provides them.
            </p>
            <button className="primary" onClick={() => setAbout(false)}>
              Close
            </button>
          </section>
        </div>
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
