import { type ImageNote } from "../components/AnnotatedImage";
import TestGuide from "../components/TestGuide";
import DE10_FTDI from "../images/DE10_FTDI.png";

// Illustrative positions only; confirm against the actual PCB layout.
const ftdiNotes: ImageNote[] = [
  {
    id: "rx",
    text: "FTDI RX to DE10 D1/TX",
    type: "arrow",
    target: { x: 0.79, y: 0.765 },
    label: { x: 0.385, y: 0.57 },
    strokeColor: "#151dfa",
    arrowOrigin: "top",
    textColor: "#FFF"
  },
  {
    id: "tx",
    text: "FTDI TX to DE10 D0/RX",
    type: "arrow",
    target: { x: 0.79, y: 0.8 },
    label: { x: 0.385, y: 0.45 },
    strokeColor: "#33d131",
    arrowOrigin: "bottom",
    textColor: "#FFF"
  },
  {
    id: "gnd",
    text: "FTDI GND to DE10 GND",
    target: { x: 0.6, y: 0.4 },
    label: { x: 0.4, y: 0.365 },
    strokeColor: "#111827",
    textColor: "#FFF",
    arrowOrigin: "bottom",
  },
  {
    id: "pwr",
    text: "Jumper set to 3V3",
    label: { x: 0.15, y: 0.335 },
    strokeColor: "#111827",
    textColor: "#FFF",
  },
];

export function FtdiUartGuide() {
  return (
    <TestGuide
      title="DE10-Lite FTDI Guide"
      image={{
        src: DE10_FTDI,
        alt: "DE10-Lite FTDI Guide",
        heightRatio: 0.524,
        notes: ftdiNotes,
      }}
    />
  );
}
