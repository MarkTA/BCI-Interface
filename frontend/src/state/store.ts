import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Step = "setup" | "dataset" | "afe" | "comparators" | "results";
export type Waveform = {
  name: string;
  time_ms: number[];
  amplitude_uv: number[];
  duration_ms: number;
  sample_rate_hz: number;
  samples: number;
  note?: string;
};
export type Capture = {
  time_ms: number[];
  channels: Record<string, number[]>;
  mode: string;
  note: string;
};
export type Entry = {
  id: number;
  time: string;
  kind: "RX" | "TX" | "INFO" | "ERROR";
  text: string;
};
export type GeneratorParams = {
  name: string;
  sample_rate_hz: number;
  duration_ms: number;
  positive_uv: number;
  negative_uv: number;
  rise1_ms: number;
  fall1_ms: number;
  rise2_ms: number;
  fall2_ms: number;
  spacing_ms: number;
  offset_ms: number;
  noise_uv: number;
  seed: number;
};
export const defaultGenerator: GeneratorParams = {
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

type Preferences = {
  step: Step;
  setStep: (s: Step) => void;
  checkboxes: Record<string, boolean>;
  setCheckbox: (key: string, value: boolean) => void;
  datasetName: string;
  setDatasetName: (name: string) => void;
  generator: GeneratorParams;
  setGenerator: (p: Partial<GeneratorParams>) => void;
  scopeMode: "mock" | "ad3";
  scopeChannels: 1 | 2;
  awgPeakV: number;
  setScope: (
    p: Partial<Pick<Preferences, "scopeMode" | "scopeChannels" | "awgPeakV">>,
  ) => void;
  gainDescription: string;
  setGainDescription: (value: string) => void;
  gainOption: number;
  setGainOption: (value: number) => void;
  scopeNotes: string;
  setScopeNotes: (value: string) => void;
  thresholdsMv: number[];
  biasV: number;
  comparatorMode: "physical" | "simulated";
  setThreshold: (index: number, value: number) => void;
  setComparatorMode: (mode: "physical" | "simulated") => void;
  setBias: (value: number) => void;
};
export const useConfig = create<Preferences>()(
  persist(
    (set) => ({
      step: "setup",
      setStep: (step) => set({ step }),
      checkboxes: {},
      setCheckbox: (key, value) =>
        set((s) => ({ checkboxes: { ...s.checkboxes, [key]: value } })),
      datasetName: "positive_then_negative",
      setDatasetName: (datasetName) => set({ datasetName }),
      generator: defaultGenerator,
      setGenerator: (p) =>
        set((s) => ({ generator: { ...s.generator, ...p } })),
      scopeMode: "mock",
      scopeChannels: 1,
      awgPeakV: 1,
      setScope: (p) => set(p),
      gainDescription: "",
      setGainDescription: (gainDescription) => set({ gainDescription }),
      gainOption: 0,
      setGainOption: (gainOption) => set({ gainOption }),
      scopeNotes: "AFE output (nominally 1.6 V biased)",
      setScopeNotes: (scopeNotes) => set({ scopeNotes }),
      thresholdsMv: [5, 10, 20, 40, -5, -10, -20, -40],
      biasV: 1.6,
      comparatorMode: "simulated",
      setThreshold: (i, value) =>
        set((s) => ({
          thresholdsMv: s.thresholdsMv.map((x, j) => (i === j ? value : x)),
        })),
      setComparatorMode: (comparatorMode) => set({ comparatorMode }),
      setBias: (biasV) => set({ biasV }),
    }),
    {
      name: "bci-experiment-preferences",
      partialize: (s) => ({
        checkboxes: s.checkboxes,
        datasetName: s.datasetName,
        generator: s.generator,
        scopeMode: s.scopeMode,
        scopeChannels: s.scopeChannels,
        awgPeakV: s.awgPeakV,
        thresholdsMv: s.thresholdsMv,
        biasV: s.biasV,
        comparatorMode: s.comparatorMode,
        scopeNotes: s.scopeNotes,
        gainDescription: s.gainDescription,
        gainOption: s.gainOption,
      }),
    },
  ),
);

export type ThresholdAckResult = {
  channel: number;
  name: string;
  requested_voltage: number;
  actual_voltage: number;
  dac_code: string;
  spi_command: string;
  sequence: number;
  status: "encoded";
};

type Runtime = {
  preview: Waveform | null;
  capture: Capture | null;
  setPreview: (x: Waveform | null) => void;
  setCapture: (x: Capture | null) => void;
  ad3Status: "unchecked" | "checking" | "connected" | "failed";
  setAd3Status: (status: Runtime["ad3Status"]) => void;
  runActive: boolean;
  setRunActive: (active: boolean) => void;
  serialConnected: boolean;
  serialPort: string | null;
  serialBaud: number | null;
  serialMock: boolean;
  serialStatus: string;
  setSerial: (
    connected: boolean,
    status: string,
    details?: { port?: string; baud?: number; mock?: boolean },
  ) => void;
  log: Entry[];
  addLog: (kind: Entry["kind"], text: string) => void;
  clearLog: () => void;
  fpgaVerified: boolean;
  thresholdAcks: Record<number, ThresholdAckResult>;
  setThresholdAck: (ack: ThresholdAckResult) => void;
  clearThresholdAcks: () => void;
  appliedSignature: string | null;
  setAppliedSignature: (signature: string | null) => void;
};
let nextEntryId = 0;
export const useRuntime = create<Runtime>((set) => ({
  preview: null,
  capture: null,
  setPreview: (preview) => set({ preview }),
  setCapture: (capture) => set({ capture }),
  ad3Status: "unchecked",
  setAd3Status: (ad3Status) => set({ ad3Status }),
  runActive: false,
  setRunActive: (runActive) => set({ runActive }),
  serialConnected: false,
  serialPort: null,
  serialBaud: null,
  serialMock: false,
  serialStatus: "Disconnected",
  setSerial: (serialConnected, serialStatus, details) =>
    set({
      serialConnected,
      serialStatus,
      serialPort:
        serialConnected && !details?.mock ? (details?.port ?? null) : null,
      serialBaud:
        serialConnected && !details?.mock ? (details?.baud ?? null) : null,
      serialMock: serialConnected && !!details?.mock,
      ...(!serialConnected
        ? { runActive: false, fpgaVerified: false, thresholdAcks: {}, appliedSignature: null }
        : {}),
    }),
  log: [],
  addLog: (kind, text) =>
    set((s) => ({
      log: [
        ...s.log.slice(-999),
        {
          id: ++nextEntryId,
          time: new Date().toLocaleTimeString(),
          kind,
          text,
        },
      ],
    })),
  clearLog: () => set({ log: [] }),
  fpgaVerified: false,
  thresholdAcks: {},
  setThresholdAck: (ack) =>
    set((s) => ({
      fpgaVerified: true,
      thresholdAcks: { ...s.thresholdAcks, [ack.channel]: ack },
    })),
  clearThresholdAcks: () => set({ thresholdAcks: {}, appliedSignature: null }),
  appliedSignature: null,
  setAppliedSignature: (appliedSignature) => set({ appliedSignature }),
}));
export const thresholdSignature = (thresholds: number[], bias: number) =>
  JSON.stringify({ thresholds, bias });
