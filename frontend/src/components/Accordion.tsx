import { useId, useState, type ReactNode } from "react";
import "./Accordion.css";

export interface AccordionSection {
  id: string;
  title: string;
  status?: ReactNode;
  content: ReactNode;
}

interface AccordionProps {
  sections: AccordionSection[];
  defaultOpenId?: string | null;
  className?: string;
}

export function Accordion({
  sections,
  defaultOpenId = sections[0]?.id ?? null,
  className = "",
}: AccordionProps) {
  const [openId, setOpenId] = useState<string | null>(defaultOpenId);
  const instanceId = useId();

  return (
    <div className={`accordion ${className}`}>
      {sections.map((section) => {
        const isOpen = openId === section.id;
        const panelId = `${instanceId}-panel-${section.id}`;
        const buttonId = `${instanceId}-button-${section.id}`;

        return (
          <section className="accordion__section" key={section.id}>
            <h3 className="accordion__heading">
              <button
                id={buttonId}
                type="button"
                className="accordion__trigger"
                aria-expanded={isOpen}
                aria-controls={panelId}
                onClick={() => setOpenId(isOpen ? null : section.id)}
              >
                <span className="accordion__title">{section.title}</span>
                {section.status != null && (
                  <span className="accordion__status">{section.status}</span>
                )}
                <span className="accordion__chevron" aria-hidden="true" />
              </button>
            </h3>
            <div
              id={panelId}
              className="accordion__panel"
              role="region"
              aria-labelledby={buttonId}
              hidden={!isOpen}
            >
              {section.content}
            </div>
          </section>
        );
      })}
    </div>
  );
}
