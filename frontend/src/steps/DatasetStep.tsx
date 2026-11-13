import React, { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../state/api";
import { validateDatasetCsv, type ValidatedCsv } from "./uploadCsv.ts";
import { useConfig, useRuntime, type GeneratorParams } from "../state/store";

function Preview() {
  const p = useRuntime((s) => s.preview);
  if (!p)
    return <div className="chart-empty">Select a dataset to preview.</div>;

  const vals = p.amplitude_uv;
  const t = p.time_ms;
  if (!t.length || !vals.length) return null;

  // Match ScopeView's plot dimensions, grid, and axis typography.
  const w = 850,
    h = 255,
    left = 68,
    right = 18,
    top = 33,
    bottom = 37;

  let lo = Infinity;
  let hi = -Infinity;
  for (const v of vals) {
    if (Number.isFinite(v)) {
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;

  const padding = Math.max((hi - lo) * 0.1, 0.5);
  lo -= padding;
  hi += padding;

  const tMin = t[0];
  const tMax = t[t.length - 1];
  const plotWidth = w - left - right;
  const plotHeight = h - top - bottom;
  const x = (time: number) =>
    left + ((time - tMin) / Math.max(1e-9, tMax - tMin)) * plotWidth;
  const y = (value: number) =>
    h - bottom - ((value - lo) / (hi - lo)) * plotHeight;

  const yDecimals = hi - lo < 10 ? 2 : hi - lo < 100 ? 1 : 0;
  const points = vals
    .map((v, i) => `${x(t[Math.min(i, t.length - 1)])},${y(v)}`)
    .join(" ");

  return (
    <div className="scope-view">
      <div className="row between">
        <strong>Waveform Preview</strong>
        <span className="badge">
          {p.samples.toLocaleString()} samples · {p.duration_ms} ms
        </span>
      </div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Selected neural test waveform, amplitude in microvolts over time in milliseconds"
      >
        {Array.from({ length: 5 }, (_, i) => {
          const gridX = left + (i * plotWidth) / 4;
          const gridY = top + (i * plotHeight) / 4;
          const timeTick = tMin + ((tMax - tMin) * i) / 4;
          const amplitudeTick = hi - ((hi - lo) * i) / 4;
          return (
            <g key={i}>
              <line
                x1={gridX}
                x2={gridX}
                y1={top}
                y2={h - bottom}
                stroke="#294157"
              />
              <line
                x1={left}
                x2={w - right}
                y1={gridY}
                y2={gridY}
                stroke="#294157"
              />
              <text
                x={gridX}
                y={h - 14}
                textAnchor="middle"
                fill="#a2b5c8"
                fontSize="12"
              >
                {timeTick.toFixed(2)}
              </text>
              <text x="4" y={gridY + 4} fill="#a2b5c8" fontSize="12">
                {amplitudeTick.toFixed(yDecimals)}
              </text>
            </g>
          );
        })}
        <polyline
          points={points}
          fill="none"
          stroke="#5ce0b5"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
        <text
          x={w / 2}
          y={h - 1}
          textAnchor="middle"
          fill="#a2b5c8"
          fontSize="12"
        >
          Time (ms)
        </text>
        <text x={left} y="17" fill="#a2b5c8" fontSize="12">
          Amplitude (µV)
        </text>
      </svg>
      <p className="hint">
        {p.sample_rate_hz.toLocaleString()} Hz ·{" "}
        {p.note ?? "CSV preview in microvolts"}
      </p>
    </div>
  );
}

const FIELDS: [keyof GeneratorParams, string][] = [
  ["sample_rate_hz", "Sample rate (Hz)"],
  ["duration_ms", "Duration (ms)"],
  ["positive_uv", "Phase 1 (µV)"],
  ["negative_uv", "Phase 2 (µV)"],
  ["rise1_ms", "Rise 1 (ms)"],
  ["fall1_ms", "Fall 1 (ms)"],
  ["rise2_ms", "Rise 2 (ms)"],
  ["fall2_ms", "Fall 2 (ms)"],
  ["spacing_ms", "Phase gap (ms)"],
  ["offset_ms", "Start offset (ms)"],
  ["noise_uv", "Noise ± (µV)"],
  ["seed", "Noise seed"],
];

function downloadDataset(name: string, time: number[], amplitude: number[]) {
  const rows = [
    "time_ms,amplitude_uv",
    ...time.map((t, i) => `${t},${amplitude[i]}`),
  ];

  const blob = new Blob([rows.join("\n")], {
    type: "text/csv;charset=utf-8",
  });

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = `${name}.csv`;

  document.body.appendChild(link);
  link.click();
  link.remove();

  URL.revokeObjectURL(url);
}

export default function DatasetStep() {
  const name = useConfig((s) => s.datasetName);
  const setName = useConfig((s) => s.setDatasetName);
  const generator = useConfig((s) => s.generator);
  const updateGenerator = useConfig((s) => s.setGenerator);
  const setPreview = useRuntime((s) => s.setPreview);
  const setCapture = useRuntime((s) => s.setCapture);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState<ValidatedCsv | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [validating, setValidating] = useState(false);
  const [draft, setDraft] = useState<GeneratorParams>(() => ({ ...generator }));
  const queryClient = useQueryClient();

  const names = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const preview = useQuery({
    queryKey: ["dataset", name],
    queryFn: () => api.dataset(name),
    enabled: !!name,
    retry: 1,
  });

  const selectedWaveform = useRuntime((s) => s.preview);

  useEffect(() => {
    if (preview.data) {
      const previous = useRuntime.getState().preview;
      if (previous?.name !== preview.data.name) setCapture(null);
      setPreview(preview.data);
    }
  }, [preview.data, setPreview, setCapture]);

  const generate = useMutation({
    mutationFn: api.generate,
    onSuccess: (p) => {
      updateGenerator(draft);
      queryClient.setQueryData(["dataset", p.name], p);
      queryClient.setQueryData<{ datasets: string[] }>(["datasets"], (old) =>
        old
          ? { ...old, datasets: [...new Set([...old.datasets, p.name])] }
          : { datasets: [p.name] },
      );
      void queryClient.invalidateQueries({ queryKey: ["datasets"] });
      setName(p.name);
      setPreview(p);
      setCapture(null);
      setCreating(false);
    },
  });

  const upload = useMutation({
    mutationFn: api.uploadDataset,
    onSuccess: (p) => {
      queryClient.setQueryData(["dataset", p.name], p);
      queryClient.setQueryData<{ datasets: string[] }>(["datasets"], (old) => ({
        datasets: [...new Set([...(old?.datasets ?? []), p.name])],
      }));
      void queryClient.invalidateQueries({ queryKey: ["datasets"] });
      setName(p.name);
      setPreview(p);
      setCapture(null);
      setUploading(false);
      setUploadFile(null);
    },
  });

  async function chooseUploadFile(file?: File) {
    setUploadFile(null);
    setUploadError("");
    upload.reset();
    if (!file) return;
    setValidating(true);
    try {
      setUploadFile(await validateDatasetCsv(file));
    } catch (error) {
      setUploadError(
        error instanceof Error ? error.message : "Invalid CSV file.",
      );
    } finally {
      setValidating(false);
    }
  }

  function closeUpload() {
    if (upload.isPending || validating) return;
    setUploading(false);
  }

  function openCreate() {
    setDraft({ ...generator });
    generate.reset();
    setCreating(true);
  }

  function closeCreate() {
    if (generate.isPending) return;
    setCreating(false);
  }

  useEffect(() => {
    if (!creating) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !generate.isPending) setCreating(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [creating, generate.isPending]);

  const datasetNames = names.data?.datasets ?? [];

  return (
    <section className="workspace-panel">
      <div className="dataset-step">
        <section className="dataset-step__selection">
          <h2>Synthetic Brainwave CSV</h2>
          <div className="dataset-step__controls">
            <label className="dataset-step__existing">
              <select value={name} onChange={(e) => setName(e.target.value)}>
                {name && !datasetNames.includes(name) && (
                  <option value={name}>{name.replaceAll("_", " ")}</option>
                )}
                {datasetNames.map((n) => (
                  <option key={n} value={n}>
                    {n.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>

            <div className="dataset-actions">
              <button
                type="button"
                className="dataset-step__create"
                onClick={openCreate}
              >
                + Create New
              </button>

              <button
                type="button"
                onClick={() => {
                  setUploadFile(null);
                  setUploadError("");
                  upload.reset();
                  setUploading(true);
                }}
              >
                Upload CSV
              </button>

              <button
                type="button"
                disabled={!selectedWaveform || selectedWaveform.name !== name}
                onClick={() => {
                  if (!selectedWaveform) return;

                  downloadDataset(
                    selectedWaveform.name,
                    selectedWaveform.time_ms,
                    selectedWaveform.amplitude_uv,
                  );
                }}
              >
                Download CSV
              </button>
            </div>
          </div>
          {names.isError && (
            <p className="error">Dataset list: {String(names.error)}</p>
          )}
          {preview.isError && (
            <p className="error">Preview: {String(preview.error)}</p>
          )}
        </section>

        <section className="dataset-step__preview">
          <Preview />
        </section>

        {uploading && (
          <div
            className="dataset-modal__backdrop"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) closeUpload();
            }}
          >
            <div
              className="dataset-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="upload-modal-title"
            >
              <div className="dataset-modal__header">
                <h2 id="upload-modal-title">Upload Dataset</h2>
                <button
                  type="button"
                  className="dataset-modal__close"
                  onClick={closeUpload}
                  disabled={upload.isPending || validating}
                  aria-label="Close dialog"
                >
                  ×
                </button>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (uploadFile && !upload.isPending)
                    upload.mutate(uploadFile.file);
                }}
              >
                <div className="dataset-modal__body">
                  <p>CSV format (header required):</p>
                  <pre className="dataset-upload__example">{`time_ms,amplitude_uv
0,0
0.001,10
0.002,25
0.003,10`}</pre>
                  <p className="hint">
                    Use two numeric columns, strictly increasing time in
                    milliseconds, and evenly spaced samples. Maximum file size:
                    10 MB. The filename becomes the dataset name.
                  </p>
                  <label>
                    Choose CSV file
                    <input
                      type="file"
                      accept=".csv,text/csv"
                      disabled={upload.isPending || validating}
                      onChange={(e) =>
                        void chooseUploadFile(e.target.files?.[0])
                      }
                    />
                  </label>
                  {validating && <p role="status">Validating CSV…</p>}
                  {uploadFile && (
                    <p className="status-good" role="status">
                      Valid format · {uploadFile.samples.toLocaleString()}{" "}
                      samples ·{uploadFile.durationMs.toLocaleString()} ms ·{" "}
                      {uploadFile.sampleRateHz.toLocaleString()} Hz
                      <br />
                      Dataset: {uploadFile.name}
                    </p>
                  )}
                  {uploadError && (
                    <p className="error" role="alert">
                      {uploadError}
                    </p>
                  )}
                  {upload.isError && (
                    <p className="error" role="alert">
                      Upload failed:{" "}
                      {upload.error instanceof Error
                        ? upload.error.message
                        : String(upload.error)}
                    </p>
                  )}
                </div>
                <div className="dataset-modal__footer">
                  <button
                    type="button"
                    onClick={closeUpload}
                    disabled={upload.isPending || validating}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="primary"
                    disabled={!uploadFile || upload.isPending || validating}
                  >
                    {upload.isPending ? "Uploading…" : "Upload"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {creating && (
          <div
            className="dataset-modal__backdrop"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) closeCreate();
            }}
          >
            <div
              className="dataset-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dataset-modal-title"
            >
              <div className="dataset-modal__header">
                <h2 id="dataset-modal-title">Create Waveform</h2>
                <button
                  type="button"
                  className="dataset-modal__close"
                  onClick={closeCreate}
                  disabled={generate.isPending}
                  aria-label="Close dialog"
                >
                  ×
                </button>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (draft.name.trim() && !generate.isPending)
                    generate.mutate({
                      ...draft,
                      name: draft.name.trim().replace(/\s+/g, "_"),
                    });
                }}
              >
                <div className="dataset-modal__body">
                  <label>
                    Dataset name
                    <input
                      autoFocus
                      value={draft.name}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, name: e.target.value }))
                      }
                    />
                  </label>
                  <div className="params-grid">
                    {FIELDS.map(([key, label]) => (
                      <label key={key}>
                        {label}
                        <input
                          type="number"
                          step="any"
                          value={draft[key]}
                          onChange={(e) =>
                            setDraft((d) => ({
                              ...d,
                              [key]: Number(e.target.value),
                            }))
                          }
                        />
                      </label>
                    ))}
                  </div>
                  {generate.isError && (
                    <div className="error" role="alert">
                      <strong>Unable to create waveform</strong>
                      <p style={{ whiteSpace: "pre-line" }}>
                        {generate.error.message}
                      </p>
                    </div>
                  )}
                </div>
                <div className="dataset-modal__footer">
                  <button
                    type="button"
                    onClick={closeCreate}
                    disabled={generate.isPending}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="primary"
                    disabled={generate.isPending || !draft.name.trim()}
                  >
                    {generate.isPending ? "Creating…" : "Create"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
