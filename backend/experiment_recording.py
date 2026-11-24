"""Persistent, run-scoped FPGA UART capture for CortexSignals.

Records what the *PC actually received*, not a guarantee of what FPGA sent.
Streaming binary + JSONL files prevent the React event-window limit from losing
experiment data. Only one run can be active per process (as with SerialManager).
No dependence on FastAPI, AD3, or WebSockets, so tests use plain Python.
"""
from __future__ import annotations

from datetime import datetime, timezone
from capture_protocol import reconcile_capture
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
import zipfile


PACKET_NAMES = {0x02: "neural_event", 0x03: "gpio_report",
                0x04: "sync_marker", 0x85: "sync_arm_ack",
                0x81: "threshold_ack", 0x84: "gpio_ack", 0x86: "capture_counter"}
RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _default_root() -> Path:
    # Writable even in a packaged/PyInstaller application.
    base = Path(os.environ.get("BCI_RUNS_DIR", "")) if os.environ.get("BCI_RUNS_DIR") else (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BCI Experiment Console" / "runs"
    )
    return base


class ExperimentRecorder:
    """One concurrent run, append-only raw RX and decoded packet/event logs."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else _default_root()
        self._lock = threading.RLock()
        self._run: dict | None = None
        self._start_ns: int | None = None
        self._files: dict = {}
        self._failed = False

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return self._run["run_id"] if self._run is not None else None

    def _path(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("Invalid run ID")
        return self.root / run_id

    def _write_manifest(self) -> None:
        assert self._run is not None
        directory = self._path(self._run["run_id"])
        staging = directory / "manifest.json.tmp"
        staging.write_text(json.dumps(self._run, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(staging, directory / "manifest.json")

    def _elapsed_us(self) -> int:
        return (time.monotonic_ns() - self._start_ns) // 1000

    def _append(self, name: str, data: bytes | str) -> None:
        if self._failed:
            return
        try:
            self._files[name].write(data)
        except OSError as exc:
            self._failed = True
            if self._run is not None:
                self._run["errors"].append(f"Recording write failed ({name}): {exc}")

    def _log_json(self, name: str, entry: dict) -> None:
        self._append(name, json.dumps(entry, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")

    def start(self, *, port: str, baud: int, gpio_debug: bool) -> dict:
        """Call after verified GPIO-mode ACK and before setting run_active=True.

        An unwritable log directory aborts arming; we never silently proceed
        with a run that cannot record its UART traffic.
        """
        with self._lock:
            if self._run is not None:
                raise RuntimeError("An experiment recording is already active")
            run_id = uuid.uuid4().hex
            directory = self._path(run_id)
            directory.mkdir(parents=True, exist_ok=False)
            opened = {}
            try:
                opened["raw"] = (directory / "uart_rx.bin").open("wb")
                opened["playback_raw"] = (directory / "playback_window_uart_rx.bin").open("wb")
                opened["packets"] = (directory / "uart_packets.jsonl").open("w", encoding="utf-8")
                opened["events"] = (directory / "fpga_events.jsonl").open("w", encoding="utf-8")
                opened["sync"] = (directory / "fpga_sync_markers.jsonl").open("w", encoding="utf-8")
                opened["tx"] = (directory / "host_uart_tx.jsonl").open("w", encoding="utf-8")
                self._files = opened
                self._start_ns = time.monotonic_ns()
                self._failed = False
                self._run = {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "recording",
                    "armed_at_utc": _utc_now(),
                    "finished_at_utc": None,
                    "armed_duration_s": None,
                    "fpga_uart": {
                        "port": port, "baud_rate": baud, "data_bits": 8,
                        "parity": "none", "stop_bits": 1,
                        "line_bits_per_byte": 10, "gpio_debug_enabled": gpio_debug,
                        "fpga_bitstream_id": None,
                    },
                    "source_mode": "ad3_comparator_simulation",
                    "playback": {"status": "not_started"},
                    "capture": {
                        "host_capture_complete": False,
                        "fpga_counters": None,
                        "fpga_counter_reconciliation": None,
                        "raw_rx_bytes": 0,
                        "playback_window_raw_rx_bytes": 0,
                        "packet_counts": {},
                        "framed_packet_bytes": 0,
                        "unframed_or_unparsed_bytes": 0,
                        "raw_rx_line_bits_8n1": 0,
                        "neural_event_count": 0,
                        "neural_packet_bytes": 0,
                        "gpio_report_bytes": 0,
                        "other_framed_bytes": 0,
                        "host_tx_bytes": 0,
                        "receiver_caveat": (
                            "UART RX bytes actually delivered to this host, not an "
                            "independent FPGA TX measurement. UART/FPGA drops or "
                            "corruption without a checksum cannot be ruled out."
                        ),
                    },
                    "errors": [],
                }
                self._write_manifest()
            except Exception:
                for file in opened.values():
                    file.close()
                self._run = None
                self._files = {}
                self._start_ns = None
                # Preserve partial failed directory for diagnosis (not a completed run).
                raise
            return self._run.copy()

    def _window_open(self) -> bool:
        return bool(self._run and self._run["playback"]["status"] in ("starting", "running"))

    def record_rx_chunk(self, chunk: bytes) -> None:
        """Call for each physical serial.read() chunk, before frame parsing."""
        with self._lock:
            if self._run is None or not chunk:
                return
            self._append("raw", chunk)
            self._run["capture"]["raw_rx_bytes"] += len(chunk)
            if self._window_open():
                self._append("playback_raw", chunk)
                self._run["capture"]["playback_window_raw_rx_bytes"] += len(chunk)

    def record_packet(self, packet: bytes, *, decoded_event: dict | None = None) -> None:
        """Record all recognized received packets, regardless of React gating."""
        with self._lock:
            if self._run is None:
                return
            kind = PACKET_NAMES.get(packet[1], "unknown") if len(packet) >= 2 else "unknown"
            elapsed = self._elapsed_us()
            entry = {
                "host_rx_elapsed_us": elapsed,
                "host_rx_utc": _utc_now(),
                "kind": kind,
                "playback_window": self._window_open(),
                "raw_hex": packet.hex(" ").upper(),
            }
            self._log_json("packets", entry)
            capture = self._run["capture"]
            counts = capture["packet_counts"]
            counts[kind] = counts.get(kind, 0) + 1
            capture["framed_packet_bytes"] += len(packet)
            if kind == "neural_event":
                capture["neural_event_count"] += 1
                capture["neural_packet_bytes"] += len(packet)
                if decoded_event is not None:
                    self._log_json("events", {**entry, **decoded_event})
                else:
                    self.mark_incomplete("Neural event packet had no decoded record")
            elif kind == "gpio_report":
                capture["gpio_report_bytes"] += len(packet)
            else:
                capture["other_framed_bytes"] += len(packet)

    def record_sync_marker(self, marker: dict) -> None:
        """Persist validated sync markers independent of the React display limit."""
        with self._lock:
            if self._run is None:
                return
            self._log_json("sync", {**marker, "host_rx_elapsed_us": self._elapsed_us(),
                                     "playback_window": self._window_open()})

    def record_capture_counters(self, counters: dict) -> None:
        """Save FPGA snapshot before finishing host logs."""
        with self._lock:
            if self._run is None:
                raise RuntimeError('No experiment recording is active')
            self._run['capture']['fpga_counters'] = dict(counters)
            self._write_manifest()

    def record_host_tx(self, data: bytes, *, purpose: str) -> None:
        """Host-to-FPGA traffic is logged separately; never count as FPGA TX."""
        with self._lock:
            if self._run is None:
                return
            self._run["capture"]["host_tx_bytes"] += len(data)
            self._log_json("tx", {"host_tx_elapsed_us": self._elapsed_us(),
                                  "purpose": purpose, "raw_hex": data.hex(" ").upper()})

    def begin_playback(self, *, configuration: dict, dataset_bytes: bytes,
                       comparator_words: bytes) -> None:
        """Persist the exact source file and the comparator pattern before AD3 starts."""
        with self._lock:
            if self._run is None:
                raise RuntimeError("Arm the FPGA run before starting playback")
            if self._run["playback"]["status"] != "not_started":
                raise RuntimeError("This run already has a playback attempt")
            if not comparator_words or len(comparator_words) > 32768:
                raise ValueError("Expected 1..32768 DIO pattern samples")
            directory = self._path(self._run["run_id"])
            # Save inputs before touching the AD3. Failure aborts this run.
            try:
                (directory / "dataset.csv").write_bytes(dataset_bytes)
                (directory / "comparator_pattern.bin").write_bytes(comparator_words)
            except OSError as exc:
                self._run["errors"].append(f"Playback snapshot failed: {exc}")
                self._failed = True
                raise
            self._run["playback"] = {
                "status": "starting",
                "request_at_utc": _utc_now(),
                "request_elapsed_us": self._elapsed_us(),
                "source_csv_sha256": sha256(dataset_bytes).hexdigest(),
                "comparator_pattern_sha256": sha256(comparator_words).hexdigest(),
                "pattern_sample_count": len(comparator_words),
                "pattern_layout": "one byte per playback sample; each byte contains DIO7..DIO0",
                "config": configuration,
                "start_confirmed_at_utc": None,
                "start_confirmed_elapsed_us": None,
                "ad3_info": None,
                "stop_at_utc": None,
                "stop_elapsed_us": None,
                "stop_reason": None,
                "host_playback_duration_s": None,
                "timing_caveat": (
                    "Host-side AD3 start request and stop observation; neither "
                    "timestamp is synchronized to the FPGA event counter. "
                    "Playback window includes startup latency and may include "
                    "trailing UART packets."
                ),
            }
            self._write_manifest()

    def replace_actual_pattern(self, words: bytes) -> None:
        """Adapt snapshot if the AD3 supports fewer samples than requested.

        WaveForms selects the minimum custom DIO memory capacity at startup;
        the reference must use the pattern it actually loaded, not a nominal
        1024-sample pattern when those differ.
        """
        with self._lock:
            if self._run is None or not self._window_open():
                raise RuntimeError("No pending AD3 playback")
            if not words or len(words) > 32768:
                raise ValueError("Invalid actual comparator pattern size")
            (self._path(self._run["run_id"]) / "comparator_pattern.bin").write_bytes(words)
            entry = self._run["playback"]
            entry["comparator_pattern_sha256"] = sha256(words).hexdigest()
            entry["pattern_sample_count"] = len(words)
            entry["pattern_recomputed_for_ad3_capacity"] = True
            self._write_manifest()

    def playback_started(self, ad3_info: dict) -> None:
        with self._lock:
            if self._run is None or self._run["playback"]["status"] != "starting":
                return
            entry = self._run["playback"]
            entry["status"] = "running"
            entry["start_confirmed_at_utc"] = _utc_now()
            entry["start_confirmed_elapsed_us"] = self._elapsed_us()
            # Store returned hardware sample rate/cycle duration, not only nominal.
            entry["ad3_info"] = ad3_info
            self._write_manifest()

    def playback_stopped(self, reason: str = "manual") -> None:
        """Thread-safe callback from AD3Manager.stop (including auto-timeout)."""
        with self._lock:
            if self._run is None or not self._window_open():
                return
            entry = self._run["playback"]
            entry["stop_elapsed_us"] = self._elapsed_us()
            entry["stop_at_utc"] = _utc_now()
            entry["stop_reason"] = reason
            entry["host_playback_duration_s"] = round(
                (entry["stop_elapsed_us"] - entry["request_elapsed_us"]) / 1e6, 6
            )
            entry["status"] = "stopped"
            try:
                self._write_manifest()
            except OSError as exc:
                # Called from a timer thread. Never let disk failures prevent
                # AD3Manager from completing the hardware-safe stop.
                self._run["errors"].append(f"Cannot persist AD3 stop time: {exc}")
                self._failed = True

    def playback_failed(self, message: str) -> None:
        with self._lock:
            if self._run is None:
                return
            self._run["errors"].append(f"AD3 playback failed: {message}")
            self._run["playback"]["status"] = "failed"
            self._write_manifest()

    def mark_incomplete(self, message: str) -> None:
        with self._lock:
            if self._run is not None:
                self._run["errors"].append(message)
                self._failed = True

    def finish(self, *, reason: str, errors: list[str] | None = None) -> dict | None:
        """Finalize even on disconnect. Files are readable for an aborted run."""
        with self._lock:
            if self._run is None:
                return None
            info = self._run
            if errors:
                info["errors"].extend(errors)
            info["finished_at_utc"] = _utc_now()
            info["armed_duration_s"] = round(self._elapsed_us() / 1e6, 6)
            capture = info["capture"]
            capture["raw_rx_line_bits_8n1"] = capture["raw_rx_bytes"] * 10
            capture["unframed_or_unparsed_bytes"] = max(
                0, capture["raw_rx_bytes"] - capture["framed_packet_bytes"]
            )
            # A normal stop guarantees the host RX loop was active while armed,
            # not that all FPGA events were emitted or received correctly.
            complete = (reason == "stopped" and not self._failed and not info["errors"]
                        and info["playback"]["status"] in ("stopped", "not_started"))
            capture["host_capture_complete"] = complete
            capture["fpga_counter_reconciliation"] = reconcile_capture(
                capture.get("fpga_counters"), capture["neural_event_count"],
                complete, capture["unframed_or_unparsed_bytes"]
            )
            if info["playback"]["status"] == "not_started":
                info["status"] = "no_playback"
            elif info["playback"]["status"] == "failed":
                info["status"] = "failed"
            elif complete and info["playback"]["status"] == "stopped":
                info["status"] = "completed"
            else:
                info["status"] = "interrupted" if reason != "stopped" else "incomplete"
            if reason != "stopped":
                info["errors"].append(f"Run ended: {reason}")
            for file in self._files.values():
                try:
                    file.flush()
                    file.close()
                except OSError as exc:
                    self._failed = True
                    info["errors"].append(f"Log flush/close failed: {exc}")
            if self._failed:
                info["status"] = "incomplete"
                capture["host_capture_complete"] = False
            # Flush failures invalidate the previously computed snapshot.
            capture["fpga_counter_reconciliation"] = reconcile_capture(
                capture.get("fpga_counters"), capture["neural_event_count"],
                capture["host_capture_complete"], capture["unframed_or_unparsed_bytes"]
            )
            try:
                self._write_manifest()
            except OSError as exc:
                # Keep the reader and WebSocket lifecycle intact if a disk fills
                # during finalization; the result is explicitly incomplete.
                info["errors"].append(f"Cannot finalize manifest: {exc}")
                info["status"] = "incomplete"
                capture["host_capture_complete"] = False
            finally:
                self._files = {}
                self._run = None
                self._start_ns = None
            return info

    def get_run(self, run_id: str) -> dict:
        with self._lock:
            self._path(run_id)  # Validate even for active snapshots.
            if self._run is not None and self._run["run_id"] == run_id:
                return json.loads(json.dumps(self._run, allow_nan=False))
            path = self._path(run_id) / "manifest.json"
            if not path.is_file():
                raise FileNotFoundError(run_id)
            return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self, *, limit: int = 50) -> list[dict]:
        with self._lock:
            if not self.root.exists():
                return []
            records = []
            for directory in self.root.iterdir():
                if not directory.is_dir() or not RUN_ID_PATTERN.fullmatch(directory.name):
                    continue
                try:
                    records.append(self.get_run(directory.name))
                except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError):
                    continue
            records.sort(key=lambda record: record.get("armed_at_utc", ""), reverse=True)
            return records[:limit]

    def make_archive(self, run_id: str) -> Path:
        """Zip an already finalized run; caller serves the resulting file."""
        with self._lock:
            self._path(run_id)
            if self.active_run_id == run_id:
                raise RuntimeError("Stop recording before exporting the run")
            self.get_run(run_id)
            directory = self._path(run_id)
            archive = directory / f"CortexSignals_{run_id}.zip"
            temp = directory / f".{archive.name}.tmp"
            try:
                with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                    for path in sorted(directory.iterdir()):
                        if path.is_file() and path.name not in (archive.name, temp.name, "manifest.json.tmp"):
                            bundle.write(path, arcname=path.name)
                os.replace(temp, archive)
            finally:
                temp.unlink(missing_ok=True)
            return archive


experiment_recorder = ExperimentRecorder()
