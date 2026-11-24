/** API response types for Phase 5 (saved validation of a recorded FPGA run). */
export type ValidationStatus = "PASS" | "FAIL" | "NOT_AVAILABLE";
export type MatchingStatus = "alignment_required" | "exploratory" | "matched";

export interface RecordedRun {
  run_id: string;
  status: string;
  armed_at_utc: string;
  finished_at_utc: string | null;
  source_mode: string;
  fpga_uart: { port: string; baud_rate: number; gpio_debug_enabled: boolean };
  playback: {
    status: string;
    config?: { dataset?: string; thresholds_mv?: number[]; requested_duration_s?: number };
    host_playback_duration_s?: number;
    start_confirmed_at_utc?: string | null;
    stop_at_utc?: string | null;
    stop_reason?: string | null;
    ad3_info?: { sample_rate_hz?: number; cycle_duration_ms?: number };
  };
  capture: {
    host_capture_complete: boolean;
    fpga_counters?: { generated: number; queued: number; transmitted: number; fifo_stall_cycles: number } | null;
    fpga_counter_reconciliation?: { status: string; complete: boolean; reason?: string } | null;
    neural_event_count: number;
    raw_rx_bytes: number;
    packet_counts: Record<string, number>;
    unframed_or_unparsed_bytes: number;
  };
  errors: string[];
}

export interface SummaryRow {
  name: string;
  value: number | string | null;
  units: string;
  target: string;
  status: ValidationStatus;
  reason: string;
}

export interface MatchRow {
  reference_index: number;
  observed_index: number;
  channel: number;
  reference_onset_us: number;
  observed_timestamp_us: number;
  observed_aligned_us: number;
  alignment_residual_us: number;
  timestamp_error_us: number | null;
  peak_match: boolean | null;
  trough_match: boolean | null;
  time_to_peak_error_us: number | null;
  flags_match: boolean | null;
}

export interface NeuralMatching {
  status: MatchingStatus;
  tolerance_us: number;
  counts: { expected: number; observed: number; tp: number | null; fp: number | null; fn: number | null };
  alignment: {
    mode: "none" | "event_anchor" | "external_sync" | "shared_origin";
    status: string;
    explanation: string;
    observed_minus_reference_us: number | null;
    absolute_timing_available: boolean;
  };
  matches: MatchRow[];
  false_negatives: { reference_index: number; channel: number; reference_onset_us: number }[];
  false_positives: { observed_index: number; channel: number; observed_timestamp_us: number; observed_aligned_us: number }[];
  warnings: string[];
}

export interface ValidationReport {
  schema_version: number;
  generated_at_utc: string;
  run_id: string;
  mode: string;
  input_snapshots: {
    sample_rate_hz: number;
    playback_duration_s_host_observed: number;
    events_in_comparison_window: number;
    modeled_uart_completed_events_in_window: number;
    host_rx_framed_bytes_in_window: number;
    pre_playback_events_excluded: number;
  };
  options: { alignment: { mode: string } | null; tolerance_us: number };
  matching: NeuralMatching;
  hardware_sync?: { status: string; reason?: string };
  capture_reconciliation?: {
    status: string;
    complete: boolean;
    generated?: number;
    queued?: number;
    transmitted?: number;
    received?: number;
    fifo_stall_cycles?: number;
    reason?: string;
  };
  relative_timing?: {
    type: string;
    consecutive_pairs: number;
    mean_interval_error_us: number | null;
    mean_absolute_interval_error_us: number | null;
    max_absolute_interval_error_us: number | null;
    cumulative_relative_drift_us: number | null;
    relative_clock_error_ppm: number | null;
    max_absolute_anchored_residual_us: number | null;
    warnings: string[];
  };
  source_annotations?: {
    status: string;
    source: string;
    isolated_reference_indices: number[];
    reason: string;
  };
  verification_audit?: {
    software_verified_count: number;
    total_checks: number;
    hardware_required_count: number;
    checks: { key: string; title: string; status: string; detail: string }[];
  };
  validation: {
    overall_status: ValidationStatus;
    capture_complete: boolean;
    accuracy_acceptance_eligible: boolean;
    performance_summary: SummaryRow[];
    warnings: string[];
    metrics: {
      detection: { precision: number | null; recall: number | null; f1: number | null };
      data_reduction: { baseline: { continuous_bit_rate_bps: number }; gross_uart_bit_rate_bps: number | null; source: string | null };
    };
  };
  warnings: string[];
}

export type ValidateOptions = {
  alignment?: null | { mode: "event_anchor"; reference_index: number; observed_index: number };
};

/** Show fractional classification metrics as percentages, without implying PASS. */
export function formatSummaryValue(row: SummaryRow): string {
  if (row.value === null || row.value === undefined) return "—";
  if (row.value === "∞") return "∞×";
  if (typeof row.value === "string") return row.units === "×" ? `${row.value}×` : row.value;
  if (row.units === "fraction") return `${(row.value * 100).toFixed(1)}%`;
  if (row.units === "µs") return `${row.value.toFixed(1)} µs`;
  if (row.units === "×") return `${row.value.toFixed(2)}×`;
  return row.value.toFixed(3);
}
