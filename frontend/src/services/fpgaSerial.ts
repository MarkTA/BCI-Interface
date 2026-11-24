import { useRuntime, type ThresholdAckResult, type GpioStats, type GpioTraceState, type NeuralEvent, type NeuralStats } from "../state/store";

/** One WebSocket per browser page, independent of mounted React steps. */
export type ThresholdResult = ThresholdAckResult;

class FpgaSerialService {
  private socket: WebSocket | null = null;
  private connecting = false;
  private pendingThreshold: {
    id: number;
    resolve: (results: ThresholdResult[]) => void;
    reject: (reason: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  } | null = null;
  private nextRequestId = 0;
  private pendingRun: {
    resolve: () => void;
    reject: (reason: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  } | null = null;

  get active(): boolean {
    return this.connecting || this.socket !== null;
  }

  connect(port: string, baud: number, mock: boolean): void {
    if (this.active) return;
    const { addLog, setSerial } = useRuntime.getState();
    if (!mock && !port) {
      addLog("ERROR", "Select a COM port first");
      return;
    }
    const params = new URLSearchParams(
      mock ? { mock: "1" } : { port, baud: String(baud) },
    );
    const ws = new WebSocket(`ws://127.0.0.1:8000/ws?${params}`);
    this.socket = ws;
    this.connecting = true;
    setSerial(false, "Connecting...");

    ws.onopen = () => {
      if (this.socket !== ws) return;
      addLog(
        "INFO",
        "WebSocket opened; waiting for serial bridge confirmation",
      );
    };
    ws.onmessage = (event: MessageEvent<string>) => {
      if (this.socket !== ws) return;
      const state = useRuntime.getState();
      try {
        const packet = JSON.parse(event.data) as {
          type: string;
          run_id?: string | null;
          recording_status?: string | null;
          gpio_debug?: boolean;
          data?: string;
          message?: string;
          hex?: string;
          channel?: number;
          request_id?: number;
          results?: ThresholdResult[];
          gpio_packets?: number;
          total_edges?: number;
          edges_by_channel?: Record<string, number>;
          negative_mask?: number;
          positive_mask?: number;
          states?: GpioTraceState[];
          events?: NeuralEvent[];
          stats?: NeuralStats;
          received?: number;
          timeouts?: number;
          saturations?: number;
          overlaps?: number;
          invalid_sequences?: number;
        };
        if (packet.type === "status") {
          this.connecting = false;
          state.setSerial(true, packet.message ?? "Connected", {
            port,
            baud,
            mock,
          });
        } else if (packet.type === "run_state") {
          if (packet.data === "running" && this.pendingRun) {
            const pending = this.pendingRun;
            this.pendingRun = null;
            clearTimeout(pending.timer);
            pending.resolve();
          }
          if (packet.data === "running") {
            state.recordingStarted(packet.run_id ?? null, packet.gpio_debug ? "gpio" : "events");
            state.setGpioStats(null);
            state.clearGpioTrace();
            state.clearNeuralEvents();
          }
          if (packet.data === "stopped") {
            state.recordingStopped(packet.run_id ?? null, packet.recording_status ?? null);
          }
          state.setRunActive(packet.data === "running");
          state.addLog("INFO", packet.message ?? `Run state: ${packet.data}`);
        } else if (packet.type === "run_error") {
          state.addLog("ERROR", packet.message ?? "FPGA run configuration failed");
          this.failRun(packet.message ?? "FPGA did not acknowledge GPIO debug mode");
        } else if (packet.type === "gpio_mode") {
          state.addLog("INFO", packet.message ?? "FPGA GPIO mode confirmed");
        } else if (packet.type === "gpio_stats") {
          state.setGpioStats(packet as GpioStats);
        } else if (packet.type === "gpio_trace") {
          const valid = (packet.states ?? []).filter(
            (row): row is GpioTraceState =>
              Array.isArray(row) && row.length === 2 &&
              row.every((value) => Number.isInteger(value) && value >= 0 && value <= 15),
          );
          if (valid.length) state.appendGpioTrace(valid);
        } else if (packet.type === "neural_events") {
          if (packet.events && packet.stats) {
            state.appendNeuralEvents(packet.events, packet.stats);
          }
        } else if (packet.type === "neural_stats") {
          state.setNeuralStats(packet as NeuralStats);
        } else if (packet.type === "threshold_complete") {
          if (this.pendingThreshold?.id === packet.request_id) {
            const pending = this.pendingThreshold;
            this.pendingThreshold = null;
            if (pending) {
              clearTimeout(pending.timer);
              pending.resolve(packet.results ?? []);
            }
          }
        } else if (packet.type === "threshold_error") {
          state.addLog("ERROR", packet.message ?? "Threshold request failed");
          if (this.pendingThreshold?.id === packet.request_id) {
            this.failThreshold(packet.message ?? "Threshold request failed");
          }
        } else if (packet.type === "uart_tx" || packet.type === "uart_rx") {
          state.addLog(
            packet.type === "uart_tx" ? "TX" : "RX",
            `CH${packet.channel ?? "?"}: ${packet.hex ?? ""}`,
          );
        } else if (packet.type === "threshold_ack") {
          const ack = packet as typeof packet & ThresholdResult;
          state.setThresholdAck(ack);
          state.addLog(
            "INFO",
            `${ack.name}: ${ack.spi_command} — ENCODED (not written to DAC)`,
          );
        } else if (packet.type === "error") {
          state.addLog("ERROR", packet.message ?? "Serial bridge error");
          // The backend closes the socket if opening the port fails.
        } else {
          state.addLog(
            packet.type === "rx" ? "RX" : "INFO",
            packet.data ?? packet.message ?? "",
          );
        }
      } catch {
        state.addLog("ERROR", "Invalid backend response");
      }
    };
    ws.onerror = () => {
      if (this.socket === ws)
        useRuntime.getState().addLog("ERROR", "Serial WebSocket error");
    };
    ws.onclose = () => {
      if (this.socket !== ws) return;
      this.socket = null;
      this.connecting = false;
      this.failThreshold("Serial connection closed");
      this.failRun("Serial connection closed");
      const state = useRuntime.getState();
      state.setSerial(false, "Disconnected");
      state.addLog("INFO", "Serial socket closed");
    };
  }

  disconnect(): void {
    const ws = this.socket;
    if (!ws) return;
    this.socket = null;
    this.connecting = false;
    this.failThreshold("Serial connection disconnected");
    this.failRun("Serial connection disconnected");
    ws.close();
    const state = useRuntime.getState();
    state.setSerial(false, "Disconnected");
    state.addLog("INFO", "Serial socket disconnected");
  }

  private failThreshold(message: string): void {
    const pending = this.pendingThreshold;
    if (!pending) return;
    this.pendingThreshold = null;
    clearTimeout(pending.timer);
    pending.reject(new Error(message));
  }

  private failRun(message: string): void {
    const pending = this.pendingRun;
    if (!pending) return;
    this.pendingRun = null;
    clearTimeout(pending.timer);
    pending.reject(new Error(message));
  }

  /** Program the runtime GPIO mode over UART and wait for FPGA acknowledgment. */
  armRun(gpioDebug: boolean): Promise<void> {
    if (this.pendingRun || this.pendingThreshold || useRuntime.getState().runActive ||
        this.socket?.readyState !== WebSocket.OPEN ||
        !useRuntime.getState().serialConnected || useRuntime.getState().serialMock) {
      return Promise.reject(new Error("Connect the physical FPGA and finish threshold updates first"));
    }
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => this.failRun("FPGA GPIO mode acknowledgment timed out"), 5000);
      this.pendingRun = { resolve, reject, timer };
      try {
        this.socket!.send(JSON.stringify({ type: "set_run_state", active: true, gpio_debug: gpioDebug }));
      } catch (error) {
        this.failRun(error instanceof Error ? error.message : "WebSocket send failed");
      }
    });
  }

  setRunActive(active: boolean): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN || !useRuntime.getState().serialConnected) return false;
    if (active && (this.pendingThreshold || useRuntime.getState().serialMock)) return false;
    this.socket.send(JSON.stringify({ type: "set_run_state", active, gpio_debug: false }));
    return true;
  }

  setThresholds(voltages: number[]): Promise<ThresholdResult[]> {
    if (useRuntime.getState().runActive) {
      return Promise.reject(new Error("Stop the live run before changing thresholds"));
    }
    if (
      this.socket?.readyState !== WebSocket.OPEN ||
      !useRuntime.getState().serialConnected
    ) {
      return Promise.reject(new Error("Connect to the FPGA first"));
    }
    if (useRuntime.getState().serialMock) {
      return Promise.reject(
        new Error("Disable mock mode to verify FPGA acknowledgments"),
      );
    }
    if (this.pendingThreshold || this.pendingRun) {
      return Promise.reject(
        new Error("Finish the current threshold update or FPGA run setup first"),
      );
    }
    if (
      voltages.length !== 8 ||
      voltages.some((v) => !Number.isFinite(v) || v < 0 || v > 2.5)
    ) {
      return Promise.reject(
        new Error("Provide eight DAC voltages in the 0–2.5 V range"),
      );
    }
    useRuntime.getState().clearThresholdAcks();
    const requestId = ++this.nextRequestId;
    return new Promise<ThresholdResult[]>((resolve, reject) => {
      const timer = setTimeout(
        () => this.failThreshold("FPGA threshold acknowledgment timed out"),
        20000,
      );
      this.pendingThreshold = { id: requestId, resolve, reject, timer };
      try {
        this.socket!.send(
          JSON.stringify({
            type: "set_thresholds",
            request_id: requestId,
            thresholds: voltages,
          }),
        );
      } catch (error) {
        this.failThreshold(
          error instanceof Error ? error.message : "WebSocket send failed",
        );
      }
    });
  }

  sendText(data: string): boolean {
    if (
      this.socket?.readyState !== WebSocket.OPEN ||
      !useRuntime.getState().serialConnected
    ) {
      useRuntime
        .getState()
        .addLog("ERROR", "Connect to the serial bridge before sending");
      return false;
    }
    this.socket.send(JSON.stringify({ type: "tx", data }));
    useRuntime.getState().addLog("TX", data);
    return true;
  }
}

export const fpgaSerial = new FpgaSerialService();
