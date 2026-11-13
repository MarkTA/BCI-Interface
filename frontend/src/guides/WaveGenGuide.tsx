import { type ImageNote } from "../components/AnnotatedImage";
import TestGuide from "../components/TestGuide";
import ad3Rnder from "../images/AD3_wavegen.png";

// Illustrative positions only; confirm against the actual PCB layout.
const wavegenNotes: ImageNote[] = [
  {
    id: "w1",
    text: "AD3 W1",
    type: "arrow",
    target: { x: 0.13, y: 0.025 },
    label: { x: 0.36, y: 0.04 },
    strokeColor: "#facc15",
  },
  {
    id: "gnd",
    text: "AD3 GND",
    target: { x: 0.13, y: 0.04 },
    label: { x: 0.36, y: 0.075 },
    strokeColor: "#111827",
    textColor: "#FFF",
  },
];

export function WaveGenGuide() {
  return (
    <TestGuide
      title="Analog Discovery Waveform Generator"
      image={{
        src: ad3Rnder,
        alt: "PCB with AD3 connections anotated",
        heightRatio: 1.0,
        notes: wavegenNotes,
      }}
    />
  );
}
