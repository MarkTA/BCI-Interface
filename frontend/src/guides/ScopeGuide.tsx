import { type ImageNote } from "../components/AnnotatedImage";
import TestGuide from "../components/TestGuide";
import pcbRender from "../images/pcb-render2.png"; // Replace with your image path

const ATTN_HLF: ImageNote[] = [
  {
    id: "ATTN_HLF_P",
    text: "AD3 CH1+",
    type: "arrow",
    target: { x: 0.1325, y: 0.2 },
    label: { x: 0.2575, y: 0.25 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "ATTN_HLF_N",
    text: "AD3 CH1-",
    stripeColor: "#fafbfd96",
    target: { x: 0.475, y: 0.12 },
    label: { x: 0.375, y: 0.23 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "top",
  },
  {
    id: "ATTN_HLF_TXT",
    type: "text",
    text: "Half Attenuation (500:1)",
    label: { x: 0.375, y: 0.35 },
    textColor: "#FFF",
  },
];
const ATTN_OUT: ImageNote[] = [
  {
    id: "ATTN_OUT_P",
    text: "AD3 CH1+",
    type: "arrow",
    target: { x: 0.1325, y: 0.16 },
    label: { x: 0.2575, y: 0.15 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "ATTN_OUT_N",
    text: "AD3 CH1-",
    stripeColor: "#fafbfd96",
    target: { x: 0.475, y: 0.12 },
    label: { x: 0.375, y: 0.23 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "top",
  },
  {
    id: "ATTN_OUT_TXT",
    type: "text",
    text: "Full Attenuation (1000:1)",
    label: { x: 0.375, y: 0.35 },
    textColor: "#FFF",
  },
];
const FILTER_HP: ImageNote[] = [
  {
    id: "FILTER_HP_P",
    text: "AD3 CH1+",
    type: "arrow",
    target: { x: 0.1325, y: 0.375 },
    label: { x: 0.2575, y: 0.4 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "FILTER_HP_N",
    text: "AD3 CH1-",
    stripeColor: "#fafbfd96",
    target: { x: 0.475, y: 0.12 },
    label: { x: 0.375, y: 0.23 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "top",
  },
  {
    id: "FILTER_HP_TXT",
    type: "text",
    text: "High-Pass Filter (300Hz < f)",
    label: { x: 0.375, y: 0.325 },
    textColor: "#FFF",
  },
];
const FILTER_OUT: ImageNote[] = [
  {
    id: "FILTER_OUT_P",
    text: "AD3 CH1+",
    type: "arrow",
    target: { x: 0.1325, y: 0.342 },
    label: { x: 0.2575, y: 0.365 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "FILTER_OUT_N",
    text: "AD3 CH1-",
    stripeColor: "#fafbfd96",
    target: { x: 0.475, y: 0.12 },
    label: { x: 0.375, y: 0.23 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "top",
  },
  {
    id: "FILTER_OUT_TXT",
    type: "text",
    text: "Band-Pass Filter (300Hz < f < 3kHz)",
    label: { x: 0.375, y: 0.3 },
    textColor: "#FFF",
  },
];

const SIG_BIAS: ImageNote[] = [
  {
    id: "SIG_BIAS_P",
    text: "AD3 CH1+",
    type: "arrow",
    target: { x: 0.1325, y: 0.625 },
    label: { x: 0.2575, y: 0.645 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "SIG_BIAS_N",
    text: "AD3 CH1-",
    stripeColor: "#fafbfd96",
    target: { x: 0.475, y: 0.12 },
    label: { x: 0.375, y: 0.23 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "top",
  },
  {
    id: "SIG_BIAS_TXT",
    type: "text",
    text: "Signal Biased to 1.6V",
    label: { x: 0.375, y: 0.45 },
    textColor: "#FFF",
  },
];

const GAIN_10X: ImageNote[] = [
  {
    id: "GAIN_10X_P",
    text: "AD3 CH1+",
    type: "arrow",
    target: { x: 0.1325, y: 0.5175 },
    label: { x: 0.2575, y: 0.5375 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "GAIN_10X_N",
    text: "AD3 CH1-",
    stripeColor: "#fafbfd96",
    target: { x: 0.475, y: 0.12 },
    label: { x: 0.375, y: 0.23 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "top",
  },
  {
    id: "GAIN_10X_TXT",
    type: "text",
    text: "Signal Amplified 10x",
    label: { x: 0.375, y: 0.4 },
    textColor: "#FFF",
  },
];

const AFE_OUT: ImageNote[] = [
  {
    id: "AFE_OUT_P",
    text: "AD3 CH1+",
    type: "arrow",
    target: { x: 0.1325, y: 0.542 },
    label: { x: 0.2575, y: 0.565 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "left",
  },
  {
    id: "AFE_OUT_N",
    text: "AD3 CH1-",
    stripeColor: "#fafbfd96",
    target: { x: 0.475, y: 0.12 },
    label: { x: 0.375, y: 0.23 },
    strokeColor: "#1534fa",
    textColor: "#FFF",
    arrowOrigin: "top",
  },
  {
    id: "AFE_OUT_TXT",
    type: "text",
    text: "Analog System Out",
    label: { x: 0.375, y: 0.4 },
    textColor: "#FFF",
  },
];

export function ScopeGuide() {
  return (
    <TestGuide
      title="Oscilloscope Test Points"
      options={[
        {
          label: "ATTN_HLF",
          imageNotes: ATTN_HLF,
        },
        {
          label: "ATTN_OUT",
          imageNotes: ATTN_OUT,
        },
        {
          label: "FILTER_HP",
          imageNotes: FILTER_HP,
        },
        {
          label: "FILTER_OUT",
          imageNotes: FILTER_OUT,
        },
        {
          label: "SIG_BIAS",
          imageNotes: SIG_BIAS,
        },
        {
          label: "GAIN_10X",
          imageNotes: GAIN_10X,
        },
        {
          label: "AFE_OUT",
          imageNotes: AFE_OUT,
        },
      ]}
      image={{
        src: pcbRender,
        alt: "PCB with power test points annotated",
        heightRatio: 0.65,
        notes: AFE_OUT,
      }}
    />
  );
}
