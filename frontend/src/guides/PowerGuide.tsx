import { type ImageNote } from "../components/AnnotatedImage";
import TestGuide from "../components/TestGuide";
import pcbRender from "../images/pcb-render2.png"; // Replace with your image path

const switchNotes: ImageNote[] = [
  {
    id: "swLabel",
    text: "Power Switch",
    target: { x: 0.4, y: 0.5 },
    label: { x: 0.55, y: 0.5 },
    strokeColor: "#111827",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "swOn",
    type: "text",
    text: "ON",
    label: { x: 0.365, y: 0.425 },
    textColor: "#FFF",
  },
  {
    id: "swOff",
    type: "text",
    text: "OFF",
    label: { x: 0.365, y: 0.62 },
    textColor: "#FFF",
  },
];
const batteryNotes: ImageNote[] = [
  {
    id: "vohmPbat",
    text: "V Ω",
    type: "arrow",
    target: { x: 0.14, y: 0.675 },
    label: { x: 0.2575, y: 0.675 },
    strokeColor: "#fa2815",
    arrowOrigin: "left",
  },
  {
    id: "comPbat",
    text: "COM",
    target: { x: 0.14, y: 0.705 },
    label: { x: 0.2575, y: 0.725 },
    strokeColor: "#111827",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "instPbat",
    type: "text",
    text: "Confirm ~ +3.7V",
    label: { x: 0.375, y: 0.7 },
    textColor: "#FFF",
  },
  {
    id: "vohmNbat",
    text: "V Ω",
    type: "arrow",
    target: { x: 0.57, y: 0.67 },
    label: { x: 0.6575, y: 0.675 },
    strokeColor: "#fa2815",
    arrowOrigin: "left",
  },
  {
    id: "comNbat",
    text: "COM",
    target: { x: 0.57, y: 0.7 },
    label: { x: 0.6575, y: 0.725 },
    strokeColor: "#111827",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "instNbat",
    type: "text",
    text: "Confirm ~ -3.7V",
    label: { x: 0.775, y: 0.7 },
    textColor: "#FFF",
  },
  {
    id: "bp1",
    type: "text",
    text: "+",
    label: { x: 0.1, y: 0.885 },
    textColor: "#fff",
  },
  {
    id: "bp2",
    type: "text",
    text: "+",
    label: { x: 0.9, y: 0.885 },
    textColor: "#fff",
  },
  {
    id: "bn1",
    type: "text",
    text: "-",
    label: { x: 0.415, y: 0.885 },
    textColor: "#FFF",
  },
  {
    id: "bn2",
    type: "text",
    text: "-",
    label: { x: 0.6, y: 0.885 },
    textColor: "#FFF",
  },
];
const power3V3Notes: ImageNote[] = [
  {
    id: "vohm3v3",
    text: "V Ω",
    type: "arrow",
    target: { x: 0.51, y: 0.11 },
    label: { x: 0.575, y: 0.3 },
    strokeColor: "#fa2815",
    arrowOrigin: "top",
  },
  {
    id: "com3v3",
    text: "COM",
    target: { x: 0.475, y: 0.11 },
    label: { x: 0.375, y: 0.3 },
    strokeColor: "#111827",
    textColor: "#FFF",
    arrowOrigin: "top",
  },
  {
    id: "inst3v3",
    type: "text",
    text: "Confirm +3.3V",
    label: { x: 0.475, y: 0.25 },
    textColor: "#FFF",
  },
];
const powerP2V5Notes: ImageNote[] = [
  {
    id: "vohmP2V5",
    text: "V Ω",
    type: "arrow",
    target: { x: 0.135, y: 0.255 },
    label: { x: 0.35, y: 0.275 },
    strokeColor: "#fa2815",
    arrowOrigin: "left",
  },
  {
    id: "comP2V5",
    text: "COM",
    target: { x: 0.475, y: 0.13 },
    label: { x: 0.35, y: 0.15 },
    strokeColor: "#111827",
    textColor: "#FFF",
    arrowOrigin: "right",
  },
  {
    id: "instP2V5",
    type: "text",
    text: "Confirm +2.5V",
    label: { x: 0.35, y: 0.21 },
    textColor: "#FFF",
  },
];
const powerN2V5Notes: ImageNote[] = [
  {
    id: "vohmN2V5",
    text: "V Ω",
    type: "arrow",
    target: { x: 0.135, y: 0.28 },
    label: { x: 0.35, y: 0.3 },
    strokeColor: "#fa2815",
    arrowOrigin: "left",
  },
  {
    id: "comN2V5",
    text: "COM",
    target: { x: 0.475, y: 0.13 },
    label: { x: 0.35, y: 0.15 },
    strokeColor: "#111827",
    textColor: "#FFF",
    arrowOrigin: "right",
  },
  {
    id: "instN2V5",
    type: "text",
    text: "Confirm -2.5V",
    label: { x: 0.35, y: 0.215 },
    textColor: "#FFF",
  },
];
const power1V6Notes: ImageNote[] = [
  {
    id: "vohm1V6",
    text: "V Ω",
    type: "arrow",
    target: { x: 0.135, y: 0.435 },
    label: { x: 0.35, y: 0.45 },
    strokeColor: "#fa2815",
    arrowOrigin: "left",
  },
  {
    id: "com1V6",
    text: "COM",
    target: { x: 0.475, y: 0.13 },
    label: { x: 0.35, y: 0.15 },
    strokeColor: "#111827",
    textColor: "#FFF",
    arrowOrigin: "right",
  },
  {
    id: "inst1V6",
    type: "text",
    text: "Confirm +1.6V",
    label: { x: 0.35, y: 0.3 },
    textColor: "#FFF",
  },
];

export function PowerGuide() {
  return (
    <TestGuide
      title="PCB Power Tests"
      options={[
        {
          label: "Switch",
          imageNotes: switchNotes,
        },
        {
          label: "Battery",
          imageNotes: batteryNotes,
        },
        {
          label: "+3V3",
          imageNotes: power3V3Notes,
        },
        {
          label: "+2V5",
          imageNotes: powerP2V5Notes,
        },
        {
          label: "-2V5",
          imageNotes: powerN2V5Notes,
        },
        {
          label: "+1V6",
          imageNotes: power1V6Notes,
        },
      ]}
      image={{
        src: pcbRender,
        alt: "PCB with power test points annotated",
        heightRatio: 0.65,
        notes: powerP2V5Notes,
      }}
    />
  );
}
