import React from "react";
const descriptions: Record<
  string,
  { name: string; role: string; purpose: string }
> = {
  setup: {
    name: "Slava",
    role: "PCB & power integration",
    purpose:
      "Hardware assembly, power delivery, and board-to-board connections.",
  },
  dataset: {
    name: "Kenny",
    role: "Synthetic brainwave generation",
    purpose:
      "Synthetic datasets that exercise spike polarity, amplitude, noise, and timing.",
  },
  afe: {
    name: "Mark",
    role: "Analog conditioning",
    purpose:
      "Attenuation, filtering, adjustable gain, and level shifting into the comparator range.",
  },
  comparators: {
    name: "Petar",
    role: "Threshold comparators & DAC",
    purpose:
      "Eight programmable thresholds used to convert analog excursions into digital levels.",
  },
  results: {
    name: "James",
    role: "FPGA event processing",
    purpose:
      "Detect and encode neural events, then transmit compact output packets.",
  },
};
export default function Contributor({ section }: { section: string }) {
  const d = descriptions[section];
  return (
    <details className="contributor">
      <summary>
        <strong>About this subsystem</strong>
        <span>
          Written by {d.name} · {d.role}
        </span>
      </summary>
      <p>
        <b>Purpose:</b> {d.purpose}
      </p>
      <p className="hint">
        Contributor-authored description, schematic, engineering tradeoffs, and
        validation notes will be inserted here. Placeholder text is not
        attributed to the contributor.
      </p>
    </details>
  );
}
