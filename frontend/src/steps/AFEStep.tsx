import React from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../state/api";
import { useConfig, useRuntime } from "../state/store";
import { ScopePair } from "../components/ScopeView";
import DipSwitch, { GAIN_OPTIONS } from "../components/DipSwitch";
import { Accordion } from "../components/Accordion";
import { ScopeGuide } from "../guides/ScopeGuide";
import { WaveGenGuide } from "../guides/WaveGenGuide";
import Ad3Connection from "../components/Ad3Connection";

const FIXED_AWG_PEAK_V = 1.0;

export default function AFEStep() {
  const dataset = useConfig((s) => s.datasetName);
  const gainOption = useConfig((s) => s.gainOption);
  const setCapture = useRuntime((s) => s.setCapture);
  const capture = useMutation({
    mutationFn: api.capture,
    onSuccess: setCapture,
  });
  const selectedGain = GAIN_OPTIONS[gainOption] ?? GAIN_OPTIONS[0];

  return (
    <section className="workspace-panel">
      <Ad3Connection />
      <Accordion
        defaultOpenId="capture"
        sections={[
          {
            id: "wavegen-guide",
            title: "AD3 Setup",
            content: <WaveGenGuide />,
          },
          {
            id: "gain",
            title: "Gain Configuration",
            content: <DipSwitch />,
          },
          {
            id: "scope-guide",
            title: "Scope Test Points",
            content: <ScopeGuide />,
          },
          {
            id: "capture",
            title: "Test Signal Capture",
            status: capture.isPending ? "Acquiring…" : undefined,
            content: (
              <>
                <div className="actions ad3-actions">
                  <button
                    className="primary"
                    disabled={capture.isPending || !dataset}
                    onClick={() =>
                      capture.mutate({
                        dataset,
                        mode: "ad3",
                        channels: 2,
                        awg_peak_v: FIXED_AWG_PEAK_V,
                      })
                    }
                  >
                    {capture.isPending ? "Acquiring…" : "▶ Play & capture"}
                  </button>
                </div>
                {capture.isError && (
                  <p className="error" role="alert">
                    Capture failed: {String(capture.error)}
                  </p>
                )}
                <p className="hint">
                  AD3 WaveGen W1 and two scope channels. Fixed 1 V peak output;
                  both channels are captured together. This is a single-buffer
                  acquisition, not a continuous scope.
                </p>
                <div className="section-gap">
                  <ScopePair />
                </div>
              </>
            ),
          },
        ]}
      />
    </section>
  );
}
