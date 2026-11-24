import { type ImageNote } from "../components/AnnotatedImage";
import TestGuide from "../components/TestGuide";
import AD3_Comparator_Simulator from "../images/AD3_Comparator_Simulator.png";

// Illustrative positions only; confirm against the actual PCB layout.
const ad3_to_de10_notes: ImageNote[] = [
  {
    id: "dio0",
    text: "AD3 DIO0 to pin 13",
    type: "arrow",
    target: { x: 0.68, y: 0.6 },
    label: { x: 0.9, y: 0.618 },
    strokeColor: "#ff79e2",
    textColor: "#FFF",
  },
  {
    id: "dio1",
    text: "AD3 DIO1 to pin 15",
    type: "arrow",
    target: { x: 0.68, y: 0.6275 },
    label: { x: 0.9, y: 0.648 },
    strokeColor: "#57ee4f",
    textColor: "#FFF",
  },
  {
    id: "dio2",
    text: "AD3 DIO2 to pin 17",
    type: "arrow",
    target: { x: 0.68, y: 0.655 },
    label: { x: 0.9, y: 0.678 },
    strokeColor: "#a260f7",
    textColor: "#FFF",
  },
  {
    id: "dio3",
    text: "AD3 DIO3 to pin 19",
    type: "arrow",
    target: { x: 0.68, y: 0.685 },
    label: { x: 0.9, y: 0.708 },
    strokeColor: "#926a44",
    textColor: "#FFF",
  },
  {
    id: "dio4",
    text: "AD3 DIO4 to pin 21",
    type: "arrow",
    target: { x: 0.68, y: 0.71 },
    label: { x: 0.9, y: 0.778 },
    strokeColor: "#ff79e2",
    textColor: "#FFF",
  },
  {
    id: "dio5",
    text: "AD3 DIO5 to pin 23",
    type: "arrow",
    target: { x: 0.68, y: 0.7375 },
    label: { x: 0.9, y: 0.808 },
    strokeColor: "#57ee4f",
    textColor: "#FFF",
  },
  {
    id: "dio6",
    text: "AD3 DIO6 to pin 24",
    type: "arrow",
    target: { x: 0.68, y: 0.765 },
    label: { x: 0.9, y: 0.838 },
    strokeColor: "#a260f7",
    textColor: "#FFF",
  },
  {
    id: "dio7",
    text: "AD3 DIO7 to pin 25",
    type: "arrow",
    target: { x: 0.68, y: 0.795 },
    label: { x: 0.9, y: 0.868 },
    strokeColor: "#926a44",
    textColor: "#FFF",
  },
  {
    id: "gnd",
    text: "AD3 GND to pin 12",
    target: { x: 0.7, y: 0.575 },
    label: { x: 0.9, y: 0.518 },
    strokeColor: "#111827",
    textColor: "#FFF",
    outlineColor: "#FFF"
  },
  {
    id: "dio8",
    text: "AD3 DIO8 to pin 2",
    type: "arrow",
    target: { x: 0.7, y: 0.435 },
    label: { x: 0.9, y: 0.38 },
    stripeColor: "#fff",
    strokeColor: "#ff79e2",
    textColor: "#FFF",
  },
  {
    id: "clk",
    text: "AD3 + DE10 Clock Sync",
    type: "text",
    label: { x: 0.9, y: 0.3425 },
    textColor: "#FFF",
  },
];

export function FpgaConnectionGuide() {
  return (
    <TestGuide
      title="AD3 Comparator Simulation"
      image={{
        src: AD3_Comparator_Simulator,
        alt: "PCB with AD3 connections anotated",
        heightRatio: 0.79,
        notes: ad3_to_de10_notes,
      }}
    />
  );
}
