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
};
