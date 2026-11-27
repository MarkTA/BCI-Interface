import type { NeuralEvent } from "../state/store";

/** Preserve acquisition order (including timestamp rollover) and the original UART frame. */
export function neuralEventsCsv(events: readonly NeuralEvent[]): string {
  const header = "event_index,timestamp_us,channel,peak_count,trough_count,time_to_peak_us,flags_mask,timeout,saturation,overlap,invalid_sequence,raw_hex";
  const rows = events.map((event, index) => [
    index + 1, event.timestamp_us, event.channel, event.peak, event.trough,
    event.time_to_peak_us, event.flags_mask, Number(event.flags.timeout),
    Number(event.flags.saturation), Number(event.flags.overlap),
    Number(event.flags.invalid_sequence), `"${event.raw_hex.replaceAll('"', '""')}"`,
  ].join(","));
  return [header, ...rows].join("\r\n") + "\r\n";
}

export function downloadNeuralEvents(events: readonly NeuralEvent[], runId?: string | null) {
  const url = URL.createObjectURL(new Blob([neuralEventsCsv(events)], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `CortexSignals_events_${runId ?? Date.now()}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
