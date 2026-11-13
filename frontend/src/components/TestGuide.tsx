import { useEffect, useState } from "react";
import AnnotatedImage, {
  type AnnotatedImageProps,
  type ImageNote,
} from "./AnnotatedImage";
import "./TestGuide.css";

export type TestGuideOption = {
  label: string;
  imageNotes: ImageNote[];
  /** Optional instructions specific to this test. */
  instructions?: string[];
};

export type TestGuideProps = {
  title: string;
  description?: string;
  image: AnnotatedImageProps;
  /** Optional test selections displayed above the diagram. */
  options?: TestGuideOption[];
  /** Default instructions, used when an option does not specify its own. */
  instructions?: string[];
  className?: string;
};

/** A reusable hardware test guide. Selection changes annotations without tracking completion. */
export default function TestGuide({
  title,
  description,
  image,
  options = [],
  instructions,
  className = "",
}: TestGuideProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);

  // If the options change, fall back to the first available test.
  useEffect(() => {
    setSelectedIndex((current) => (current < options.length ? current : 0));
  }, [options.length]);

  const selectedOption = options[selectedIndex];
  const activeNotes = selectedOption ? selectedOption.imageNotes : image.notes;
  const activeInstructions = selectedOption?.instructions ?? instructions;

  return (
    <section className={`test-guide ${className}`.trim()}>
      <header className="test-guide__header">
        <h2 className="test-guide__title">{title}</h2>
        {description && (
          <p className="test-guide__description">{description}</p>
        )}
      </header>

      {options.length > 0 && (
        <div
          className="test-guide__options"
          role="group"
          aria-label={`${title} test selection`}
        >
          {options.map((option, index) => (
            <button
              key={`${option.label}-${index}`}
              type="button"
              className={`test-guide__option${index === selectedIndex ? " test-guide__option--active" : ""}`}
              aria-pressed={index === selectedIndex}
              onClick={() => setSelectedIndex(index)}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}

      <AnnotatedImage {...image} notes={activeNotes} />

      {activeInstructions && activeInstructions.length > 0 && (
        <ol className="test-guide__instructions">
          {activeInstructions.map((instruction, index) => (
            <li key={index}>{instruction}</li>
          ))}
        </ol>
      )}
    </section>
  );
}
