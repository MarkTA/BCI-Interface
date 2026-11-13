import React, { useEffect, useMemo, useState } from "react";
const API = "http://127.0.0.1:8000";
type Preview = {
  name: string;
  time_ms: number[];
  amplitude_uv: number[];
  duration_ms: number;
  sample_rate_hz: number;
  samples: number;
  note?: string;
};
type Capture = {
  time_ms: number[];
  channels: Record<string, number[]>;
  mode: string;
  note: string;
};
const DEFAULTS = {
  name: "custom",
  sample_rate_hz: 1000000,
  duration_ms: 5,
  positive_uv: 80,
  negative_uv: -120,
  rise1_ms: 0.3,
  fall1_ms: 0.25,
  rise2_ms: 0.25,
  fall2_ms: 1,
  spacing_ms: 0,
  offset_ms: 0.5,
  noise_uv: 0,
  seed: 1234,
};
type Params = typeof DEFAULTS;
function Trace({
  time,
  traces,
  label,
  unit,
}: {
  time: number[];
  traces: { name: string; values: number[]; color: string }[];
  label: string;
  unit: string;
}) {
  const w = 890,
    h = 255,
    pad = 46;
  const all = traces.flatMap((t) => t.values);
  if (!time.length || !all.length)
    return <div className="chart-empty">No data</div>;
  const t0 = time[0],
    t1 = time[time.length - 1] || 1;
  const lo = Math.min(...all),
    hi = Math.max(...all),
    span = Math.max(hi - lo, 0.00001);
  const ymin = lo - span * 0.12,
    ymax = hi + span * 0.12;
  const sx = (t: number) =>
    pad + ((t - t0) / Math.max(t1 - t0, 1e-6)) * (w - 2 * pad);
  const sy = (v: number) =>
    h - pad - ((v - ymin) / (ymax - ymin)) * (h - 2 * pad);
  return (
    <div className="chart">
      <div className="row between">
        <strong>{label}</strong>
        <div className="legend">
          {traces.map((t) => (
            <span key={t.name} style={{ color: t.color }}>
              ● {t.name}{" "}
            </span>
          ))}
        </div>
      </div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label={label}
        preserveAspectRatio="none"
      >
        {Array.from({ length: 5 }, (_, i) => {
          const x = pad + (i * (w - 2 * pad)) / 4,
            y = pad + (i * (h - 2 * pad)) / 4;
          return (
            <g key={i}>
              <line x1={x} x2={x} y1={pad} y2={h - pad} stroke="#23394d" />
              <line x1={pad} x2={w - pad} y1={y} y2={y} stroke="#23394d" />
              <text
                x={x}
                y={h - 15}
                textAnchor="middle"
                fill="#90a9c1"
                fontSize="12"
              >
                {(t0 + ((t1 - t0) * i) / 4).toFixed(2)}
              </text>
              <text x="5" y={y + 4} fill="#90a9c1" fontSize="12">
                {(ymax - ((ymax - ymin) * i) / 4).toFixed(3)}
              </text>
            </g>
          );
        })}
        {traces.map((t) => (
          <polyline
            key={t.name}
            fill="none"
            stroke={t.color}
            strokeWidth="1.8"
            vectorEffect="non-scaling-stroke"
            points={t.values
              .map(
                (v, i) => `${sx(time[Math.min(i, time.length - 1)])},${sy(v)}`,
              )
              .join(" ")}
          />
        ))}
        <text
          x={w / 2}
          y={h - 1}
          fill="#b1c3d6"
          textAnchor="middle"
          fontSize="11"
        >
          Time (ms)
        </text>
        <text x={pad} y={14} fill="#b1c3d6" fontSize="11">
          {unit}
        </text>
      </svg>
    </div>
  );
}
export default function WaveformPanel() {
  const [names, setNames] = useState<string[]>([]),
    [name, setName] = useState("positive_then_negative");
  const [preview, setPreview] = useState<Preview | null>(null),
    [capture, setCapture] = useState<Capture | null>(null);
  const [params, setParams] = useState<Params>(DEFAULTS),
    [showCustom, setShowCustom] = useState(false);
  const [channels, setChannels] = useState(1),
    [mode, setMode] = useState<"mock" | "ad3">("mock"),
    [peak, setPeak] = useState(1);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const load = async (n: string) => {
    try {
      setError("");
      const res = await fetch(`${API}/api/datasets/${encodeURIComponent(n)}`);
      if (!res.ok) throw new Error(await res.text());
      setPreview(await res.json());
      setName(n);
      setCapture(null);
    } catch (e) {
      setError(String(e));
    }
  };
  useEffect(() => {
    fetch(`${API}/api/datasets`)
      .then((r) => r.json())
      .then((d) => {
        setNames(d.datasets);
        void load(
          d.datasets.includes("positive_then_negative")
            ? "positive_then_negative"
            : d.datasets[0],
        );
      })
      .catch((e) => setError(String(e)));
  }, []);
  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${API}/api/datasets/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(JSON.stringify(d.detail));
      setNames((s) => [...new Set([...s, params.name])].sort());
      setPreview(d);
      setName(params.name);
      setCapture(null);
      setNotice(
        `Generated ${d.samples} samples using Kenny's Python generator.`,
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const run = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const r = await fetch(`${API}/api/capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataset: name,
          mode,
          channels,
          awg_peak_v: peak,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(JSON.stringify(d.detail));
      setCapture(d);
      setNotice(d.note);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const fields: { key: keyof Params; label: string }[] = [
    { key: "sample_rate_hz", label: "Sample rate (Hz)" },
    { key: "duration_ms", label: "Duration (ms)" },
    { key: "positive_uv", label: "Phase 1 amplitude (µV)" },
    { key: "negative_uv", label: "Phase 2 amplitude (µV)" },
    { key: "rise1_ms", label: "Phase 1 rise (ms)" },
    { key: "fall1_ms", label: "Phase 1 fall (ms)" },
    { key: "spacing_ms", label: "Interphase gap (ms)" },
    { key: "rise2_ms", label: "Phase 2 rise (ms)" },
    { key: "fall2_ms", label: "Phase 2 fall (ms)" },
    { key: "offset_ms", label: "Start offset (ms)" },
    { key: "noise_uv", label: "Uniform noise ± (µV)" },
    { key: "seed", label: "Noise seed" },
  ];
  return (
    <div className="waveform-workspace">
      <section className="card">
        <div className="row between">
          <h2>Waveform datasets</h2>
          <span className="badge online">Kenny's Python generator</span>
        </div>
        <div className="grid">
          <label>
            Choose predefined test
            <select value={name} onChange={(e) => void load(e.target.value)}>
              {names.map((n) => (
                <option key={n} value={n}>
                  {n.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <div className="dataset-metadata">
            {preview && (
              <>
                <b>{preview.samples.toLocaleString()}</b> samples ·{" "}
                {preview.duration_ms} ms ·{" "}
                {(preview.sample_rate_hz / 1000).toFixed(0)} kS/s
              </>
            )}
          </div>
        </div>
        <div className="actions">
          <button onClick={() => setShowCustom((s) => !s)}>
            {showCustom
              ? "Hide custom generator"
              : "＋ Generate custom waveform"}
          </button>
        </div>
        {showCustom && (
          <div className="custom-form">
            <h3>Custom biphasic waveform</h3>
            <label>
              Dataset name
              <input
                value={params.name}
                onChange={(e) =>
                  setParams((s) => ({ ...s, name: e.target.value }))
                }
              />
            </label>
            <div className="params-grid">
              {fields.map((f) => (
                <label key={f.key}>
                  {f.label}
                  <input
                    type="number"
                    step="any"
                    value={params[f.key]}
                    onChange={(e) =>
                      setParams((s) => ({
                        ...s,
                        [f.key]: Number(e.target.value),
                      }))
                    }
                  />
                </label>
              ))}
            </div>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void generate()}
            >
              Generate & preview
            </button>
          </div>
        )}
      </section>
      {preview && (
        <section className="card">
          <Trace
            time={preview.time_ms}
            traces={[
              {
                name: "Input waveform",
                values: preview.amplitude_uv,
                color: "#4dd3ab",
              },
            ]}
            label="Dataset preview"
            unit="Amplitude (µV)"
          />
          <div className="hint">
            CSV values are microvolts; the AD3 output is scaled to a
            configurable voltage for your external attenuator. Do not connect a
            1 V WaveGen signal directly to a microvolt-level AFE input.
          </div>
        </section>
      )}
      <section className="card">
        <div className="row between">
          <h2>WaveGen + oscilloscope</h2>
          <span className={mode === "mock" ? "badge" : "badge online"}>
            {mode === "mock" ? "SIMULATION" : "AD3 HARDWARE"}
          </span>
        </div>
        <div className="grid">
          <label>
            Capture source
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as "mock" | "ad3")}
            >
              <option value="mock">Simulation — no hardware</option>
              <option value="ad3">Analog Discovery 3 — WaveForms SDK</option>
            </select>
          </label>
          <label>
            Scope channels
            <select
              value={channels}
              onChange={(e) => setChannels(Number(e.target.value))}
            >
              <option value={1}>Channel 1</option>
              <option value={2}>Channels 1 + 2</option>
            </select>
          </label>
          <label>
            WaveGen peak amplitude (V)
            <input
              type="number"
              step=".1"
              min=".01"
              max="2"
              value={peak}
              onChange={(e) => setPeak(Number(e.target.value))}
            />
          </label>
        </div>
        <div className="actions">
          <button
            className="primary"
            disabled={!preview || busy}
            onClick={() => void run()}
          >
            {busy ? "Working…" : "▶ Play & capture"}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        {notice && <p className="hint">{notice}</p>}
        {capture && (
          <Trace
            time={capture.time_ms}
            label={
              capture.mode === "mock"
                ? "Simulated scope output"
                : "AD3 scope capture"
            }
            unit="Voltage (V)"
            traces={Object.entries(capture.channels).map(([n, v], i) => ({
              name: n.toUpperCase(),
              values: v,
              color: i ? "#ffbf70" : "#59abff",
            }))}
          />
        )}
        <p className="hint">
          Initial hardware capture: a single, free-running oscilloscope buffer
          with the WaveGen repeating. This is not yet an aligned or continuous
          live scope. AD3 scope CH1/CH2 capture independently of waveform
          generation.
        </p>
      </section>
    </div>
  );
}
