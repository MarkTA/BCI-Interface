import AnnotatedImage, { type ImageNote } from "../components/AnnotatedImage";
import pcbRender from "../images/pcb-render.png";

// Illustrative positions only; confirm against the actual PCB layout.
const wavegenNotes: ImageNote[] = [
  {
    id: "w1",
    text: "AD3 W1",
    type: "arrow",
    target: { x: 0.13, y: 0.06 },
    label: { x: 0.36, y: 0.08 },
    strokeColor: "#facc15",
  },
  {
    id: "gnd",
    text: "AD3 GND",
    target: { x: 0.13, y: 0.087 },
    label: { x: 0.36, y: 0.135 },
    strokeColor: "#111827",
    textColor: "#FFF",
  },
  {
    id: "instruction",
    type: "text",
    text: "Analog Discovery Wave Generator",
    label: { x: 0.5, y: 0.5 },
    textColor: "#FFF",
  },
];

export function PCBWaveGenDiagram() {
  return (
    <AnnotatedImage
      src={pcbRender}
      alt="CortexSignals PCB top view"
      heightRatio={0.65}
      notes={wavegenNotes}
    />
  );
}
