import type { Capture, GeneratorParams, Waveform } from "./store";
export const BASE = "http://127.0.0.1:8000";
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, options);

  if (!r.ok) {
    let message = `HTTP ${r.status}: ${r.statusText}`;

    try {
      const body = await r.json();

      if (Array.isArray(body.detail)) {
        // FastAPI / Pydantic validation errors
        message = body.detail
          .map((error: { loc?: (string | number)[]; msg?: string }) => {
            const field = error.loc
              ?.filter((part) => part !== "body")
              .join(".");

            return field
              ? `${field}: ${error.msg ?? "Invalid value"}`
              : (error.msg ?? "Invalid value");
          })
          .join("\n");
      } else if (typeof body.detail === "string") {
        // FastAPI HTTPException
        message = body.detail;
      } else if (typeof body.message === "string") {
        message = body.message;
      } else {
        message = JSON.stringify(body);
      }
    } catch {
      // Preserve the HTTP status if the response is not valid JSON.
    }

    throw new Error(message);
  }

  return r.json() as Promise<T>;
}
export type ComparatorRequest = {
  dataset: string;
  thresholds_mv: number[]; // DAC order P1..P4, N1..N4; signed offsets from 1.6 V
  playback_speed: number;   // 1.0 = Kenny's original waveform timing
  gpio_debug_enabled: boolean; // Must match ENABLE_GPIO_DEBUG in FPGA bitstream
  duration_s: number;
};
export type ComparatorPreview = {
  dataset: string;
  source_duration_ms: number;
  cycle_duration_ms: number;
  playback_speed: number;
  gpio_debug_enabled: boolean;
  sample_count: number;
  sample_interval_us: number;
  afe_peak_mv: number;      // Derived modeled AFE peak (mV)
  afe_gain: number;         // Nominal analog AFE voltage gain (V/V)
  source_peak_uv: number;   // Actual peak magnitude in selected CSV (µV)
  signal_range_mv: [number, number];
  expected_edges_per_cycle: Record<string, number>;
  // One ideal repeating digital cycle: 8-bit DIO masks at each transition.
  // N1..N4 bits 0..3; P1..P4 bits 4..7.
  reference_states: { sample_index: number; mask: number }[];
  expected_edges_per_second: number;
  warning: string | null;
};
export type ComparatorStart = ComparatorPreview & {
  active: boolean;
  mode: string;
  sample_rate_hz: number;
  channels: Record<string, number>;
};
export type DigitalStatus = { active: boolean; mode: string; outputs_low?: boolean };
export type PulseScope = {
  time_us: number[]; voltage_v: number[]; min_v: number;
  max_v: number; pulse_width_us: number | null; edge_count: number; note: string;
};
export const api = {
  datasets: () => request<{ datasets: string[] }>("/api/datasets"),
  dataset: (name: string) =>
    request<Waveform>(`/api/datasets/${encodeURIComponent(name)}`),
  // Add this property inside the existing `api` object in src/state/api.ts:
  uploadDataset: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    // Do not set Content-Type: fetch adds the multipart boundary automatically.
    return request<Waveform>("/api/datasets/upload", {
      method: "POST",
      body: form,
    });
  },
  generate: (p: GeneratorParams) =>
    request<Waveform>("/api/datasets/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }),
  capture: (p: {
    dataset: string;
    mode: "mock" | "ad3";
    channels: 1 | 2;
    awg_peak_v: number;
  }) =>
    request<Capture>("/api/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }),
  comparatorPreview: (req: ComparatorRequest) =>
    request<ComparatorPreview>("/api/ad3/digital/comparators/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
  comparatorStart: (req: ComparatorRequest) =>
    request<ComparatorStart>("/api/ad3/digital/comparators", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
  digitalStatus: () => request<DigitalStatus>("/api/ad3/digital/status"),
  digitalStop: () => request<DigitalStatus>("/api/ad3/digital/stop", { method: "POST" }),
  digitalScope: () => request<PulseScope>("/api/ad3/digital/scope", { method: "POST" }),
  ports: () => request<{ device: string; description: string }[]>("/api/ports"),
  health: () => request<{ ok: boolean; service: string }>("/api/health"),
  ad3Connection: () =>
    request<{
      connected: boolean;
      ready: boolean;
      status: "ready" | "warning" | "unavailable";
      message: string;
      warning: string | null;
    }>("/api/ad3/connection"),
};
