import React from "react";
import { useConfig } from "../state/store";

// The SW1–SW3 truth table supplied for Stage D.
// This diagram is a reference for positioning physical switches;
// it does not remotely configure the AFE.
export const GAIN_OPTIONS = [
  { switches: [true, true, true], stage: 3.95, total: 100 },
  { switches: [false, true, true], stage: 6.215, total: 157 },
  { switches: [true, false, true], stage: 8.495, total: 215 },
  { switches: [false, false, true], stage: 10.76, total: 272 },
  { switches: [true, true, false], stage: 13.05, total: 330 },
  { switches: [false, true, false], stage: 15.315, total: 387 },
  { switches: [true, false, false], stage: 17.595, total: 445 },
  { switches: [false, false, false], stage: 19.86, total: 502 },
] as const;

type DipSwitchProps = {
  compact?: boolean;
};

export default function DipSwitch({ compact = false }: DipSwitchProps) {
  const gainOption = useConfig((s) => s.gainOption);
  const setGainOption = useConfig((s) => s.setGainOption);

  const selectedGain = GAIN_OPTIONS[gainOption] ?? GAIN_OPTIONS[0];
  const switches = selectedGain.switches;

  // Use the same controls and physical switch illustration in both steps.
  // Compact mode omits the setup instructions already provided in Step 3.
  const controls = (
    <div className={`gain-controls${compact ? " gain-controls--compact" : ""}`}>
      <label htmlFor={compact ? "run-afe-gain" : "afe-gain"}>
        {compact ? "AFE Gain" : "Total Gain"}
      </label>

      <select
        id={compact ? "run-afe-gain" : "afe-gain"}
        value={gainOption}
        onChange={(event) => setGainOption(Number(event.target.value))}
      >
        {GAIN_OPTIONS.map((option, index) => (
          <option key={option.total} value={index}>
            {option.total}×
          </option>
        ))}
      </select>
      
      {compact ? <span className="pcb_instr">* match to PCB</span> : ''}

      <div className="dip-visual">
        <div
          className="dip-board"
          role="img"
          aria-label={switches
            .map((on, i) => `SW${i + 1} ${on ? "ON" : "OFF"}`)
            .join(", ")}
        >
          <div className="dip-top">ON</div>

          <div className="dip-slots">
            {switches.map((on, index) => (
              <div className="dip-unit" key={index}>
                <div className="dip-track">
                  <div className={`dip-thumb ${on ? "is-on" : "is-off"}`} />
                </div>

                <strong>{index + 1}</strong>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  if (compact) return controls;

  return (
    <div className="gain-layout">
      <div className="gain-instructions">
        <h2>Amplifier Gain Configuration</h2>

        <p>
          Set the amplifier gain using the three-position DIP switch on the
          analog PCB.
        </p>

        <p>
          Select the desired gain, then match the physical switch positions to
          the diagram.
        </p>
      </div>

      {controls}
    </div>
  );
}
