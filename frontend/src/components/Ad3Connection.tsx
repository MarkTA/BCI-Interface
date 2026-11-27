import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../state/api";
import { useRuntime } from "../state/store";
import { useExperimentRun, requiresRecovery } from "../services/experimentRun";

type DiagnosticStatus = "ready" | "warning" | "unavailable" | null;

export default function Ad3Connection() {
  const status = useRuntime((s) => s.ad3Status);
  const setStatus = useRuntime((s) => s.setAd3Status);
  const runActive = useRuntime((s) => s.runActive);
  const runBusy = useExperimentRun((s) => s.busy);
  const output = useExperimentRun((s) => s.output);
  const locked = runActive || runBusy || output.active || requiresRecovery(output);

  const [message, setMessage] = useState("");
  const [warning, setWarning] = useState("");
  const [diagnosticStatus, setDiagnosticStatus] =
    useState<DiagnosticStatus>(null);

  const test = useMutation({
    mutationFn: api.ad3Connection,

    onMutate: () => {
      setStatus("checking");
      setMessage("");
      setWarning("");
      setDiagnosticStatus(null);
    },

    onSuccess: (result) => {
      setStatus(result.ready ? "connected" : "failed");
      setDiagnosticStatus(result.status);
      setMessage(result.message);
      setWarning(result.warning ?? "");
    },

    onError: (error) => {
      setStatus("failed");
      setDiagnosticStatus("unavailable");
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to test Analog Discovery 3.",
      );
      setWarning(
        "Check the USB connection, WaveForms SDK, and backend service.",
      );
    },
  });

  const ready = status === "connected";
  const checking = status === "checking" || test.isPending;

  const statusText = checking
    ? "Checking hardware..."
    : ready
      ? "AD3 Ready"
      : status === "failed"
        ? diagnosticStatus === "warning"
          ? "Hardware Warning"
          : "AD3 Unavailable"
        : "Not Tested";

  return (
    <section className="card input-card">
      <div className="input__toolbar">
        <h2>Analog Discovery SDK:</h2>
        <button
          type="button"
          className="primary"
          disabled={checking || locked}
          onClick={() => test.mutate()}
        >
          {checking
            ? "Checking..."
            : ready
              ? "Retest Connection"
              : "Test Connection"}
        </button>
        <div className="spacer"/>
        <span className={ready ? "badge online" : "badge"} role="status">
          {statusText}
        </span>
      </div>

      {message && (
        <p className={status === "failed" ? "error" : "hint"} role="status">
          {message}
        </p>
      )}

      {warning && (
        <div className="ad3-warning" role="alert">
          <strong>
            {diagnosticStatus === "warning"
              ? "Hardware Diagnostic"
              : "Connection Diagnostic"}
          </strong>
          <p>{warning}</p>
        </div>
      )}
    </section>
  );
}
