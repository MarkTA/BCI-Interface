import React, { useMemo } from "react";
import { useRuntime } from "../state/store";

/** One voltage scale per physical channel; captures share an acquisition clock. */
export default function ScopeView({
  channel,
  variant = "diagnostic",
}: {
  channel: 1 | 2;
  variant?: "diagnostic" | "experiment";
}) {
  const capture = useRuntime((s) => s.capture);
  const name = `ch${channel}`;
  const values = capture?.channels[name];
  const color = channel === 1 ? "#54aefe" : "#f8ba6d";
  const chart = useMemo(() => {
    if (!capture || !values?.length || !capture.time_ms.length) return null;
    const t = capture.time_ms;
    const w = 850,
      h = 255,
      left = 68,
      right = 18,
      top = 33,
      bottom = 37;
    // Avoid spreading large sample arrays into Math.min/max, which can exceed
    // JavaScript argument limits as acquisition buffers grow.
    let lo = Infinity,
      hi = -Infinity;
    for (const v of values) {
      if (Number.isFinite(v)) {
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
    const padding = Math.max((hi - lo) * 0.15, 0.002);
    lo -= padding;
    hi += padding;
    const tMin = t[0],
      tMax = t[t.length - 1];
    const sx = (x: number) =>
      left + ((x - tMin) / Math.max(1e-9, tMax - tMin)) * (w - left - right);
    const sy = (y: number) =>
      h - bottom - ((y - lo) / (hi - lo)) * (h - top - bottom);
    const points = values
      .map((v, i) => `${sx(t[Math.min(i, t.length - 1)])},${sy(v)}`)
      .join(" ");
    return { w, h, left, right, top, bottom, lo, hi, tMin, tMax, points };
  }, [capture, values]);

  return (
    <div className="scope-channel">
      <div className="row between">
        <strong style={{ color }}>● CH{channel}</strong>
        <span className="muted">Independent voltage scale</span>
      </div>
      {!values ? (
        <div className="chart-empty">
          No CH{channel} capture yet.{" "}
          {variant === "experiment"
            ? "Capture both channels in Analog Conditioning."
            : "Use Play & capture to acquire both channels."}
        </div>
      ) : !chart ? (
        <div className="chart-empty">
          No valid CH{channel} samples returned.
        </div>
      ) : (
        <svg
          viewBox={`0 0 ${chart.w} ${chart.h}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={`CH${channel} captured voltage over time`}
        >
          {Array.from({ length: 5 }, (_, i) => {
            const x =
              chart.left + (i * (chart.w - chart.left - chart.right)) / 4;
            const y =
              chart.top + (i * (chart.h - chart.top - chart.bottom)) / 4;
            return (
              <g key={i}>
                <line
                  x1={x}
                  x2={x}
                  y1={chart.top}
                  y2={chart.h - chart.bottom}
                  stroke="#294157"
                />
                <line
                  x1={chart.left}
                  x2={chart.w - chart.right}
                  y1={y}
                  y2={y}
                  stroke="#294157"
                />
                <text
                  x={x}
                  y={chart.h - 14}
                  textAnchor="middle"
                  fill="#a2b5c8"
                  fontSize="12"
                >
                  {(chart.tMin + ((chart.tMax - chart.tMin) * i) / 4).toFixed(
                    2,
                  )}
                </text>
                <text x="4" y={y + 4} fill="#a2b5c8" fontSize="12">
                  {(chart.hi - ((chart.hi - chart.lo) * i) / 4).toFixed(3)}
                </text>
              </g>
            );
          })}
          <polyline
            points={chart.points}
            stroke={color}
            fill="none"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
          <text
            x={chart.w / 2}
            y={chart.h - 1}
            textAnchor="middle"
            fill="#a2b5c8"
            fontSize="12"
          >
            Time (ms)
          </text>
          <text x={chart.left} y="17" fill="#a2b5c8" fontSize="12">
            Voltage (V)
          </text>
        </svg>
      )}
    </div>
  );
}

export function ScopePair({
  variant = "diagnostic",
}: {
  variant?: "diagnostic" | "experiment";
}) {
  const capture = useRuntime((s) => s.capture);
  const preview = useRuntime((s) => s.preview);
  return (
    <div className="scope-view scope-pair">
      <div className="row between">
        <b>
          {capture?.mode === "mock" ? "Simulated capture" : "AD3 scope capture"}
        </b>
        <span className="badge">CH1 + CH2</span>
      </div>
      <ScopeView channel={1} variant={variant} />
      <ScopeView channel={2} variant={variant} />
      {capture && (
        <p className="hint">
          {capture.note}
          {preview && ` · Dataset: ${preview.name}`}
        </p>
      )}
    </div>
  );
}
