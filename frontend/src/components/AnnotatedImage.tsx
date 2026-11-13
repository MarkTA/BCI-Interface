import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import "../AnnotatedImage.css";

/** All positions are normalized (0–1) relative to the displayed image. */
export type Point = { x: number; y: number };

export type ImageNote = {
  id: string;
  text: string;
  /** Label position, normalized to the image (0–1). */
  label: Point;
  /** 'arrow' is the default; 'text' displays only a label. */
  type?: "arrow" | "text";
  /** Required for arrow notes; ignored for text-only notes. */
  target?: Point;
  /** Arrow, target ring, and arrowhead color. */
  strokeColor?: string;
  /** Arrow, target ring, and arrowhead color. */
  stripeColor?: string;
  /** Label color; defaults to strokeColor or the theme primary color. */
  textColor?: string;
  /** Colored arrow stroke width in CSS pixels; defaults to --annotation-arrow-width. */
  strokeWidth?: number;
  /** Outline thickness on each side in CSS pixels. */
  outlineWidth?: number;
  /** Outline color; defaults to dark, but use a light color for dark leads. */
  outlineColor?: string;
  /** Side of the label where the arrow shaft begins. Defaults to 'left'. */
  arrowOrigin?: "top" | "bottom" | "left" | "right";
  /** Backward-compatible alias for strokeColor. */
  color?: string;
};

export type AnnotatedImageProps = {
  src: string;
  alt: string;
  /** Height / width. For example 0.6 means 600px high at 1000px wide. */
  heightRatio: number;
  notes: ImageNote[];
  className?: string;
};

const WIDTH = 1000;
const clamp = (n: number) => Math.max(0, Math.min(1, n));

export default function AnnotatedImage({
  src,
  alt,
  heightRatio,
  notes,
  className = "",
}: AnnotatedImageProps) {
  const labelRefs = useRef(new Map<string, HTMLSpanElement>());
  const [labelSizes, setLabelSizes] = useState<
    Record<string, { width: number; height: number }>
  >({});

  useLayoutEffect(() => {
    const observer = new ResizeObserver(() => {
      const next: Record<string, { width: number; height: number }> = {};
      labelRefs.current.forEach((element, id) => {
        next[id] = { width: element.offsetWidth, height: element.offsetHeight };
      });
      setLabelSizes((prev) =>
        JSON.stringify(prev) === JSON.stringify(next) ? prev : next,
      );
    });
    labelRefs.current.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [notes]);

  const ratio =
    Number.isFinite(heightRatio) && heightRatio > 0 ? heightRatio : 0.6;
  const height = WIDTH * ratio;
  const xy = (p: Point) => ({ x: clamp(p.x) * WIDTH, y: clamp(p.y) * height });

  return (
    <div
      className={`annotated-image ${className}`.trim()}
      style={{ aspectRatio: `1 / ${ratio}` }}
    >
      <img className="annotated-image__background" src={src} alt={alt} />
      <svg
        className="annotated-image__overlay"
        viewBox={`0 0 ${WIDTH} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${alt} annotations`}
      >
        {notes.map((note) => {
          const labelPosition = xy(note.label);
          const size = labelSizes[note.id] ?? { width: 0, height: 0 };
          // The label's anchor is its bottom-center. Convert its measured CSS
          // dimensions into the SVG viewBox units for responsive positioning.
          const origin = note.arrowOrigin ?? "left";
          const start = {
            x:
              labelPosition.x +
              (origin === "left"
                ? -size.width / 2
                : origin === "right"
                  ? size.width / 2
                  : 0),
            y:
              labelPosition.y +
              (origin === "top"
                ? -size.height
                : origin === "bottom"
                  ? 0
                  : -size.height / 2),
          };
          const isArrow = note.type !== "text" && note.target !== undefined;
          const end = isArrow ? xy(note.target!) : null;
          const strokeColor =
            note.strokeColor ?? note.color ?? "var(--color-primary, #38bdf8)";
          const textColor = note.textColor ?? strokeColor;
          const arrowStyle = {
            ...(note.strokeWidth !== undefined && {
              "--annotation-arrow-width": `${Math.max(0, note.strokeWidth)}px`,
            }),
            ...(note.outlineWidth !== undefined && {
              "--annotation-outline-width": `${Math.max(0, note.outlineWidth)}px`,
            }),
            ...(note.outlineColor && {
              "--annotation-outline-color": note.outlineColor,
            }),
          } as CSSProperties;
          // A separate arrowhead polygon inherits each note's own stroke color.
          const dx = end ? end.x - start.x : 0;
          const dy = end ? end.y - start.y : 0;
          const length = Math.hypot(dx, dy) || 1;
          const ux = dx / length;
          const uy = dy / length;
          const tip = end ? { x: end.x, y: end.y } : null;
          // Larger head, with the shaft overlapping its base for a seamless join.
          const headLength = 19;
          const wing = 9;
          const base = tip
            ? { x: tip.x - ux * headLength, y: tip.y - uy * headLength }
            : null;
          const shaftEnd = base
            ? { x: base.x + ux * 5, y: base.y + uy * 5 }
            : null;
          // Start at the selected edge; no arbitrary offset from the label.
          const lineStart = start;
          return (
            <g key={note.id} style={arrowStyle}>
              <title>{note.text}</title>
              {end && tip && base && shaftEnd && (
                <>
                  {/* Pass 1: the complete dark/light silhouette. */}
                  <polygon
                    className="annotated-image__arrowhead-outline"
                    points={`${tip.x},${tip.y} ${base.x - uy * wing},${base.y + ux * wing} ${base.x + uy * wing},${base.y - ux * wing}`}
                    vectorEffect="non-scaling-stroke"
                  />
                  <line
                    className="annotated-image__arrow-outline"
                    x1={lineStart.x}
                    y1={lineStart.y}
                    x2={shaftEnd.x}
                    y2={shaftEnd.y}
                    vectorEffect="non-scaling-stroke"
                  />

                  {/* Pass 2: colored head and shaft. Overlap hides the joint. */}
                  <polygon
                    className="annotated-image__arrowhead-fill"
                    points={`${tip.x},${tip.y} ${base.x - uy * wing},${base.y + ux * wing} ${base.x + uy * wing},${base.y - ux * wing}`}
                    fill={strokeColor}
                  />
                  <line
                    className="annotated-image__arrow-line"
                    x1={lineStart.x}
                    y1={lineStart.y}
                    x2={shaftEnd.x}
                    y2={shaftEnd.y}
                    stroke={strokeColor}
                    vectorEffect="non-scaling-stroke"
                  />
                  {note.stripeColor && (
                    <line
                      className="annotated-image__arrow-stripe"
                      x1={lineStart.x}
                      y1={lineStart.y}
                      x2={shaftEnd.x}
                      y2={shaftEnd.y}
                      stroke={note.stripeColor}
                      vectorEffect="non-scaling-stroke"
                    />
                  )}
                </>
              )}
              <foreignObject
                x={labelPosition.x - 160}
                y={labelPosition.y - 40}
                width="320"
                height="40"
                className="annotated-image__label-container"
              >
                <div className="annotated-image__label-wrap">
                  <span
                    ref={(element) => {
                      if (element) labelRefs.current.set(note.id, element);
                      else labelRefs.current.delete(note.id);
                    }}
                    className="annotated-image__label"
                    style={{ color: textColor }}
                  >
                    {note.text}
                  </span>
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
