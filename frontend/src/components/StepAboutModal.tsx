import React, { useEffect, useRef } from "react";
import type { StepAboutConfig } from "../config/stepAbout";

type Props = {
  config: StepAboutConfig;
  onClose: () => void;
};

export default function StepAboutModal({ config, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="modal step-about-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="step-about-title"
      >
        <div className="row between">
          <h2 id="step-about-title">{config.title}</h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close step information"
          >
            ✕
          </button>
        </div>

        {config.presenter && (
          <p className="hint">Presented by: {config.presenter}</p>
        )}

        {config.sections.length > 0 && (
          <div className="step-about-modal__content">
            {config.sections.map((section) => (
              <section key={section.heading}>
                <h3>{section.heading}</h3>
                {section.paragraphs.map((paragraph, index) => (
                  <p key={index}>{paragraph}</p>
                ))}
              </section>
            ))}
          </div>
        )}

        <div className="step-about-modal__footer">
          <button type="button" className="primary" onClick={onClose}>
            Close
          </button>
        </div>
      </section>
    </div>
  );
}
