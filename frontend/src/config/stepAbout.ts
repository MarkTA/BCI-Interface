import type { Step } from "../state/store";

export type StepAboutSection = {
  heading: string;
  paragraphs: string[];
};

export type StepAboutConfig = {
  buttonLabel: string;
  title: string;
  presenter?: string;
  sections: StepAboutSection[];
};

// Each contributor can edit their section without touching the modal component.
// Leave sections empty to show a blank modal during the demo.
export const STEP_ABOUT: Record<Step, StepAboutConfig> = {
  setup: {
    buttonLabel: "About PCB",
    title: "PCB Lead: Slava",
    presenter: "Slava",
    sections: [],
  },
  dataset: {
    buttonLabel: "About Signals",
    title: "Signal Lead: Kenny",
    presenter: "Kenny",
    sections: [],
  },
  afe: {
    buttonLabel: "About AFE",
    title: "Analog Front End",
    presenter: "Mark",
    sections: [
      {
        heading: "Overview",
        paragraphs: [
          "The analog front end prepares small neural-like signals for threshold detection. It attenuates the test waveform, filters unwanted frequency content, amplifies the signal, and shifts the output around a 1.6 V bias for the comparator stage.",
        ],
      },
      {
        heading: "Design and Validation",
        paragraphs: [
          "Our design uses a fourth-order band-pass filter and selectable amplifier gain. The Analog Discovery 3 generates test signals and captures the analog output, allowing us to compare the measured waveform with the expected response.",
        ],
      },
      {
        heading: "Next Steps",
        paragraphs: [
          "Validate the integrated analog and comparator PCB and characterize noise, gain, and signal integrity under the final hardware conditions.",
        ],
      },
    ],
  },
  comparators: {
    buttonLabel: "About Events",
    title: "Neural Event Thresholds",
    presenter: "Petar",
    sections: [],
  },
  results: {
    buttonLabel: "About FPGA",
    title: "Digital Processing and Output",
    presenter: "James",
    sections: [],
  },
  run: {
    buttonLabel: "About Run & Results",
    title: "Experiment Run & Results",
    sections: [
  {
    heading: "Overview",
    paragraphs: [
      "Run an experiment to test how accurately the FPGA detects and classifies neural signals. The console records the FPGA output and compares it against a software reference model to evaluate system performance.",
    ],
  },
  {
    heading: "1. Verify Connections",
    paragraphs: [
      "Ensure the Analog Discovery 3 (AD3) and FPGA are connected.",
      "Confirm the AD3 connection has been tested in Step 3 and FPGA communication has been verified in Step 5.",
    ],
  },
  {
    heading: "2. Configure the Experiment",
    paragraphs: [
      "Select a neural waveform dataset and set the experiment duration (1–60 seconds).",
      "Review the comparator thresholds. Green checkmarks indicate that the FPGA has acknowledged the configured values.",
      "If necessary, return to Step 4 to update and verify the thresholds.",
    ],
  },
  {
    heading: "3. Run the Experiment",
    paragraphs: [
      "Click Start Run to begin waveform playback and FPGA event detection.",
      "Monitor detected events in the Neural Events panel.",
      "Click Stop Run to finish early, or allow the experiment to stop automatically.",
    ],
  },
  {
    heading: "4. Review Performance",
    paragraphs: [
      "The console automatically records and analyzes the experiment.",
      "Expand Performance Summary to view spike detection accuracy, peak and trough classification, timing errors, and data reduction.",
      "Each metric displays its measured value, engineering target, and validation status.",
    ],
  },
  {
    heading: "5. Compare Events",
    paragraphs: [
      "Expand Reference Comparison to compare expected neural events against those detected by the FPGA.",
      "Review matched events, missing detections, unexpected events, and classification differences.",
      "For exploratory matching, select corresponding reference and FPGA event indices, then click Compare (exploratory).",
    ],
  },
  {
    heading: "6. Save and Review Results",
    paragraphs: [
      "Use Recorded experiment to select and review previous experiments.",
      "Expand Experiment Log to view recording details and validation warnings.",
      "Expand Export Results and click Export experiment ZIP to download the complete recording and validation report.",
    ],
  },
  {
    heading: "Understanding Results",
    paragraphs: [
      "PASS: The measured result meets the engineering requirement with sufficient validation evidence.",
      "FAIL: The measured result does not meet the requirement.",
      "Not verified: Additional measurements or synchronization are required to confirm compliance.",
      "The AD3 and FPGA use independent clocks. Until their timing is synchronized, some accuracy measurements cannot be independently verified. Exploratory comparisons are useful for debugging but do not establish final hardware performance.",
    ],
  },
 ],
  },
};
