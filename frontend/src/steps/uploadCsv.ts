export interface ValidatedCsv {
  name: string;
  samples: number;
  durationMs: number;
  sampleRateHz: number;
  file: File;
}

const MAX_BYTES = 10 * 1024 * 1024;
const NAME_PATTERN = /^[A-Za-z0-9_-]{1,50}$/;

export async function validateDatasetCsv(file: File): Promise<ValidatedCsv> {
  if (!file.name.toLowerCase().endsWith(".csv"))
    throw new Error("Choose a .csv file.");
  if (file.size > MAX_BYTES)
    throw new Error("CSV files must be 10 MB or smaller.");
  if (!file.size) throw new Error("The CSV file is empty.");

  const name = file.name.slice(0, -4).trim().replace(/\s+/g, "_");
  if (!NAME_PATTERN.test(name))
    throw new Error(
      "Filename must be 1–50 characters: letters, numbers, underscores, or hyphens.",
    );

  const lines = (await file.text())
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter((line) => line.trim() !== "");
  if (
    !lines.length ||
    lines[0].replace(/\s/g, "").toLowerCase() !== "time_ms,amplitude_uv"
  ) {
    throw new Error("The first row must be: time_ms,amplitude_uv");
  }
  if (lines.length < 3)
    throw new Error("Include at least two waveform samples.");
  if (lines.length - 1 > 200_000)
    throw new Error("Maximum 200,000 samples per dataset.");
  const times: number[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].split(",");
    if (
      cells.length !== 2 ||
      cells.some((c) => !c.trim() || !Number.isFinite(Number(c)))
    ) {
      throw new Error(`Row ${i + 1}: expected two finite numeric values.`);
    }
    const time = Number(cells[0]);
    if (times.length && time <= times[times.length - 1]) {
      throw new Error(`Row ${i + 1}: time_ms must increase strictly.`);
    }
    times.push(time);
  }
  const interval = times[1] - times[0];
  for (let i = 2; i < times.length; i++) {
    const dt = times[i] - times[i - 1];
    if (Math.abs(dt - interval) > Math.max(1e-9, interval * 0.001)) {
      throw new Error(
        `Row ${i + 2}: sampling intervals must be uniform (within 0.1%).`,
      );
    }
  }
  const sampleRate = 1000 / interval;
  if (sampleRate < 1000 || sampleRate > 2_000_000)
    throw new Error("Sample rate must be between 1,000 and 2,000,000 Hz.");
  return {
    name,
    samples: times.length,
    durationMs: times[times.length - 1] - times[0],
    sampleRateHz: 1000 / interval,
    file,
  };
}
