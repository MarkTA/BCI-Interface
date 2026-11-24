import { fpgaSerial } from "./fpgaSerial";
import { thresholdSignature, useConfig, useRuntime } from "../state/store";

// Physical threshold values are relative to the AFE's fixed 1.6 V bias.
// The FPGA currently ACKs SPI-command ENCODING, not physical DAC programming.
export const AFE_BIAS_V = 1.6;
export const DAC_REFERENCE_V = 2.5;

export function validThresholds(thresholds: number[]): boolean {
  return (
    thresholds.length === 8 &&
    thresholds.every((mv, index) => {
      const voltage = AFE_BIAS_V + mv / 1000;
      return (
        Number.isFinite(mv) &&
        voltage >= 0 && voltage <= DAC_REFERENCE_V &&
        (index < 4 ? mv >= 0 : mv <= 0)
      );
    })
  );
}

export function dacCode(voltage: number): number {
  return Math.max(
    0,
    Math.min(65535, Math.floor((voltage / DAC_REFERENCE_V) * 65536 + 0.5)),
  );
}

/** Sends the current requested values and records the snapshot only after all
 * eight returned channel/code acknowledgments match the submitted values.
 * This shared operation persists across navigation between Steps 4 and 6.
 */
export async function sendThresholdsToFpga(): Promise<void> {
  const state = useRuntime.getState();
  if (state.thresholdSendStatus === "sending") return;

  if (state.runActive) {
    state.setThresholdSendState("error", "Stop the live run before changing thresholds.");
    return;
  }
  if (!state.serialConnected || state.serialMock) {
    state.setThresholdSendState("error", "Connect to the physical FPGA first.");
    return;
  }

  const submittedThresholds = [...useConfig.getState().thresholdsMv];
  if (!validThresholds(submittedThresholds)) {
    state.setThresholdSendState("error", "Correct invalid threshold values before sending.");
    return;
  }

  const submittedSignature = thresholdSignature(submittedThresholds, AFE_BIAS_V);
  state.setAppliedSignature(null);
  state.setThresholdSendState("sending", "Sending eight threshold commands to the FPGA…");

  try {
    const results = await fpgaSerial.setThresholds(
      submittedThresholds.map((mv) => AFE_BIAS_V + mv / 1000),
    );
    if (
      results.length !== 8 ||
      results.some((ack, index) => {
        const expectedCode = `0x${dacCode(AFE_BIAS_V + submittedThresholds[index] / 1000)
          .toString(16).padStart(4, "0").toUpperCase()}`;
        return (
          ack.channel !== index ||
          ack.status !== "encoded" ||
          ack.dac_code?.toUpperCase() !== expectedCode.toUpperCase()
        );
      })
    ) {
      throw new Error("Incomplete or mismatched FPGA threshold acknowledgments");
    }
    if (!useRuntime.getState().serialConnected || useRuntime.getState().serialMock) {
      throw new Error("FPGA disconnected before threshold confirmation");
    }

    // Populate the per-channel diagnostic table from the completed reply too;
    // some bridges may emit the aggregate response without separate ACK events.
    for (const ack of results) useRuntime.getState().setThresholdAck(ack);
    useRuntime.getState().addLog(
      "INFO",
      "All eight threshold SPI commands encoded and acknowledged by FPGA",
    );
    if (thresholdSignature(useConfig.getState().thresholdsMv, AFE_BIAS_V) === submittedSignature) {
      useRuntime.getState().setAppliedSignature(submittedSignature);
      useRuntime.getState().setThresholdSendState(
        "success",
        "8/8 FPGA acknowledgments received. SPI encoded; physical DAC not programmed.",
      );
    } else {
      // Values were edited while requests were in flight; the old set is no
      // longer sufficient to arm a new run.
      useRuntime.getState().setThresholdSendState(
        "idle",
        "Thresholds changed during transmission. Send the current values again.",
      );
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    useRuntime.getState().setThresholdSendState(
      "error", `Threshold configuration failed: ${reason}`,
    );
    useRuntime.getState().addLog("ERROR", `Threshold configuration failed: ${reason}`);
  }
}
