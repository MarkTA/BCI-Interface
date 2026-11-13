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
