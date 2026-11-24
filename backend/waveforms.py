"""CortexSignals AD3 adapter: analog loopback and digital comparator simulation.

Analog play_and_capture preserves the previous 1024-point custom playback,
8192-point scope, and 150ms settling delay. No phase synchronization.

Digital comparator simulation drives synchronized, repeating custom patterns
on DIO0..7 (N1..N4, P1..P4) with one hardware start. Stop uses LOW idle.
Close the Digilent WaveForms GUI before opening this SDK device.
"""

import ctypes as C
import math
import os
from pathlib import Path
import sys
import time
from collections.abc import Mapping, Sequence


class DWFError(RuntimeError):
    pass



# These labels are *FPGA/DIO* order, not DAC80508 channel order.
# DAC order is P1..P4, N1..N4; DIO0..DIO7 are N1..N4, P1..P4.
DEFAULT_AFE_GAIN_VV = 385.0  # Approximate, calibrated AFE voltage gain; adjust after PCB measurements.

COMPARATOR_DIO = {"N1": 0, "N2": 1, "N3": 2, "N4": 3,
                  "P1": 4, "P2": 5, "P3": 6, "P4": 7}


def build_comparator_pattern(
    sample_values_uv: Sequence[float], duration_ms: float,
    thresholds_mv: Mapping[str, float], afe_gain: float = DEFAULT_AFE_GAIN_VV,
    sample_count: int = 1024, bias_v: float = 1.6,
) -> dict:
    """Prepare ONE repeating cycle of eight synchronized comparator outputs.

    The dataset is a zero-centered waveform in microvolts. Preserve its actual
    sample amplitudes; do NOT independently peak-normalize each CSV. Model the
    post-AFE excursion from bias using the nominal, calibrated voltage gain:
        signal_mv = sample_uv * afe_gain / 1000.
    The digital simulator bypasses the physical analog AFE and AWG; it models
    ideal comparators only. Update DEFAULT_AFE_GAIN_VV after AFE calibration.

    thresholds_mv are SIGNED millivolt offsets from bias, keyed P1..P4 and
    N1..N4. For example P1=+20, N1=-20 gives 1.620V / 1.580V.
    A DIO bit is HIGH for a triggered comparator (positive above threshold,
    negative below threshold), matching the uploaded schematic.

    No hardware is touched by this function. DIO bit 0=N1, ..., bit 7=P4.
    """
    if sample_values_uv is None or len(sample_values_uv) < 2:
        raise ValueError("Dataset must contain at least two samples")
    if not isinstance(thresholds_mv, Mapping) or set(thresholds_mv) != set(COMPARATOR_DIO):
        raise ValueError("thresholds_mv must have exactly P1..P4 and N1..N4")
    if type(sample_count) is not int or not 16 <= sample_count <= 32768:
        raise ValueError("sample_count must be 16..32768")
    if not math.isfinite(float(duration_ms)) or not 1 <= float(duration_ms) <= 1000:
        raise ValueError("duration_ms must be between 1 and 1000 ms")
    if not math.isfinite(float(bias_v)) or not 0 < bias_v < 3.3:
        raise ValueError("bias_v must be between 0 and 3.3 V")
    if not math.isfinite(float(afe_gain)) or afe_gain <= 0:
        raise ValueError("afe_gain must be positive and finite (V/V)")

    thresholds = {}
    for name, value in thresholds_mv.items():
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError(f"{name}: threshold must be a finite number of mV")
        if (name[0] == "P" and value < 0) or (name[0] == "N" and value > 0):
            raise ValueError(f"{name}: positive P thresholds must be >=0 mV, negative N <=0 mV")
        if not 0 <= bias_v + value / 1000 <= 3.3:
            raise ValueError(f"{name}: threshold is outside the 0..3.3 V DAC range")
        thresholds[name] = float(value)

    src = [float(value) for value in sample_values_uv]
    if not all(math.isfinite(value) for value in src):
        raise ValueError("Dataset contains a non-finite sample")
    source_peak = max(abs(value) for value in src)
    source_min, source_max = min(src), max(src)
    afe_peak_mv = source_peak * afe_gain / 1000
    # Never silently clip a modeled AFE output: that would produce misleading
    # comparator results. A zero-only CSV is a valid negative control.
    if bias_v + source_min * afe_gain / 1_000_000 < 0 or \
            bias_v + source_max * afe_gain / 1_000_000 > 3.3:
        raise ValueError("CSV amplitude × AFE gain exceeds the modeled 0–3.3 V supply rails")

    words = []
    min_signal_mv, max_signal_mv = math.inf, -math.inf
    # Same endpoint-inclusive linear interpolation as existing analog playback.
    for i in range(sample_count):
        pos = i * (len(src) - 1) / (sample_count - 1)
        left = min(int(pos), len(src) - 2)
        fraction = pos - left
        signal_mv = (src[left] * (1 - fraction) + src[left + 1] * fraction) * afe_gain / 1000
        min_signal_mv = min(min_signal_mv, signal_mv)
        max_signal_mv = max(max_signal_mv, signal_mv)
        word = 0
        for name, bit in COMPARATOR_DIO.items():
            limit = thresholds[name]
            active = signal_mv < limit if name[0] == "N" else signal_mv > limit
            if active:
                word |= 1 << bit
        words.append(word)

    edges = {}
    highs = {}
    loop_edges = {}
    for name, bit in COMPARATOR_DIO.items():
        states = [(word >> bit) & 1 for word in words]
        interior = sum(a != b for a, b in zip(states, states[1:]))
        wrap = int(states[-1] != states[0])
        edges[name] = interior + wrap
        highs[name] = sum(states)
        loop_edges[name] = wrap

    return {
        "words": words,
        "sample_count": sample_count,
        "duration_ms": float(duration_ms),
        "afe_peak_mv": float(afe_peak_mv),  # Derived from CSV, not a user input
        "afe_gain": float(afe_gain),
        "source_peak_uv": source_peak,
        "signal_range_mv": [round(min_signal_mv, 5), round(max_signal_mv, 5)],
        "bias_v": float(bias_v),
        "thresholds_mv": thresholds,
        "expected_edges_per_cycle": edges,
        "high_samples_per_cycle": highs,
        "loop_boundary_edges": loop_edges,
    }


def pack_channel_bits(words: Sequence[int], channel: int) -> bytes:
    """DWF custom pattern: one bit per time sample, bit 0 FIRST in each byte."""
    if channel not in range(9):
        raise ValueError("channel must be 0..8")
    packed = bytearray((len(words) + 7) // 8)
    for index, mask in enumerate(words):
        if mask & (1 << channel):
            packed[index // 8] |= 1 << (index % 8)
    return bytes(packed)


class AD3:
    def __init__(self):
        if sys.platform == "win32":
            # Prefer an installed SDK DLL, including installations whose SDK
            # directory has not been added to the process DLL search path.
            roots = [
                os.environ.get("ProgramFiles", r"C:\Program Files"),
                os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            ]
            candidates = [
                Path(root) / "Digilent" / "WaveFormsSDK" / "lib" / "x64" / "dwf.dll"
                for root in roots
            ]
            # Some WaveForms versions place the SDK alongside the application.
            candidates += [
                Path(root) / "Digilent" / "WaveForms3" / "dwf.dll"
                for root in roots
            ]
            library_name = next(
                (str(candidate) for candidate in candidates if candidate.is_file()),
                "dwf.dll",
            )
        elif sys.platform.startswith("linux"):
            library_name = "libdwf.so"
        else:
            library_name = "libdwf.dylib"

        try:
            self.dwf = C.cdll.LoadLibrary(library_name)
        except OSError as exc:
            raise DWFError(
                f"Cannot load WaveForms SDK library: {library_name}. "
                "Install Digilent WaveForms and restart the application. "
                f"Details: {exc}"
            ) from exc

        self.h = C.c_int(0)
        self._call("FDwfDeviceOpen", C.c_int(-1), C.byref(self.h))
        if not self.h.value:
            raise DWFError("No available AD3; close WaveForms GUI and check USB")

    def _call(self, function_name, *args):
        fn = getattr(self.dwf, function_name)
        fn.restype = C.c_int
        if not fn(*args):
            message = C.create_string_buffer(512)
            self.dwf.FDwfGetLastErrorMsg(message)
            raise DWFError(
                f"{function_name}: {message.value.decode(errors='replace')}"
            )

    def _digital_clock_hz(self):
        clock = C.c_double()
        self._call("FDwfDigitalOutInternalClockInfo", self.h, C.byref(clock))
        if clock.value <= 0:
            raise DWFError("Invalid digital output clock")
        return clock.value

    def digital_low(self):
        """Stop the pattern generator and select driven LOW idle for DIO0..7.

        Do not start a pulse generator to emulate a static LOW. WaveForms SDK
        defines DwfDigitalOutIdleLow=1 for enabled push-pull outputs.
        """
        self._call("FDwfDeviceAutoConfigureSet", self.h, C.c_int(0))
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(0))
        for channel in range(9):
            ch = C.c_int(channel)
            self._call("FDwfDigitalOutEnableSet", self.h, ch, C.c_int(1))
            self._call("FDwfDigitalOutOutputSet", self.h, ch, C.c_int(0))  # push-pull
            self._call("FDwfDigitalOutIdleSet", self.h, ch, C.c_int(1))  # idle LOW
        # Apply the newly programmed idle levels, but do not start generation.
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(0))

    def digital_states(self, mask: int):
        """Hold the selected DIOs HIGH and all others LOW without pulse timing.

        The pattern generator is STOPPED; WaveForms drives the configured
        DwfDigitalOutIdleLow/High states from enabled push-pull output pins.
        """
        if type(mask) is not int or not 0 <= mask <= 255:
            raise ValueError("mask must be an integer from 0 to 255")
        self._call("FDwfDeviceAutoConfigureSet", self.h, C.c_int(0))
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(0))
        for channel in range(9):
            ch = C.c_int(channel)
            high = (mask >> channel) & 1
            self._call("FDwfDigitalOutEnableSet", self.h, ch, C.c_int(1))
            self._call("FDwfDigitalOutOutputSet", self.h, ch, C.c_int(0))  # PP
            self._call("FDwfDigitalOutIdleSet", self.h, ch,
                       C.c_int(2 if high else 1))  # HIGH or LOW while stopped
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(0))
        return {"mask": mask, "negative": mask & 15, "positive": (mask >> 4) & 15}

    def digital_pulse_train(self, channel: int, frequency_hz: float, width_us: float):
        """Generate hardware-timed active-high pulses; all other DIO pins low.

        DWF pulse counter units are divider ticks. Counter0 is LOW time,
        Counter1 is HIGH time, and initial state is LOW.
        """
        if type(channel) is not int or not 0 <= channel <= 7:
            raise ValueError("channel must be DIO0..DIO7")
        if not math.isfinite(frequency_hz) or frequency_hz <= 0:
            raise ValueError("frequency_hz must be positive and finite")
        if not math.isfinite(width_us) or width_us <= 0:
            raise ValueError("width_us must be positive and finite")
        period_s = 1 / frequency_hz
        width_s = width_us * 1e-6
        if width_s >= period_s:
            raise ValueError("Pulse width must be shorter than the period")
        clock_hz = self._digital_clock_hz()
        # The digital pulse HIGH/LOW counters are limited to 16-bit values on
        # this hardware. ctypes.c_uint only describes the API argument width;
        # it does NOT imply the underlying hardware counters are 32-bit.
        # Scale the clock so that *each* counter fits into 0xFFFF ticks.
        max_counter = 0xFFFF
        divider = max(1, math.ceil(clock_hz * max(width_s, period_s - width_s) / max_counter))
        if divider > 0xFFFFFFFF:
            raise ValueError("Frequency is too low for the digital output divider")
        tick_s = divider / clock_hz
        high = round(width_s / tick_s)
        period = round(period_s / tick_s)
        low = period - high
        if not 1 <= high <= max_counter or not 1 <= low <= max_counter:
            raise ValueError(
                f"Pulse timing cannot be represented using 16-bit counters "
                f"at {tick_s * 1e6:.3f} us resolution"
            )
        print(
            f"[AD3 digital] DIO{channel}: requested={frequency_hz:g} Hz, "
            f"{width_us:g} us; clock={clock_hz:g} Hz, divider={divider}, "
            f"LOW={low} ticks, HIGH={high} ticks; "
            f"actual={1 / (period * tick_s):.6f} Hz, {high * tick_s * 1e6:.3f} us",
            flush=True,
        )
        self.digital_low()
        ch = C.c_int(channel)
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(0))
        # Reassert the complete output configuration after digital_low().
        self._call("FDwfDigitalOutEnableSet", self.h, ch, C.c_int(1))
        self._call("FDwfDigitalOutOutputSet", self.h, ch, C.c_int(0))  # push-pull
        self._call("FDwfDigitalOutTypeSet", self.h, ch, C.c_int(0))  # pulse
        self._call("FDwfDigitalOutDividerSet", self.h, ch, C.c_uint(divider))
        self._call("FDwfDigitalOutCounterInitSet", self.h, ch, C.c_int(0), C.c_uint(1))
        self._call("FDwfDigitalOutCounterSet", self.h, ch, C.c_uint(low), C.c_uint(high))
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(1))
        return {"channel": channel, "frequency_hz": 1 / (period * tick_s),
                "width_us": high * tick_s * 1e6, "clock_hz": clock_hz,
                "divider": divider, "low_ticks": low, "high_ticks": high}

    def digital_comparator_simulation(
        self, sample_values_uv, duration_ms, thresholds_mv,
        afe_gain=DEFAULT_AFE_GAIN_VV, sample_count=1024, bias_v=1.6,
    ):
        """Repeat an 8-channel digital pattern simulating the AFE comparators.

        The sample DATA is stored in each DIO's independent custom-pattern
        buffer; all channels receive the SAME divider and are started with a
        SINGLE FDwfDigitalOutConfigure call, keeping them synchronized.
        This is a hardware-timed repeating pattern, not a Python-driven stream.
        """
        # Validate entirely before modifying hardware; resample after querying
        # each channel's actual hardware-supported custom buffer size.
        build_comparator_pattern(
            sample_values_uv, duration_ms, thresholds_mv, afe_gain,
            sample_count, bias_v,
        )

        self._call("FDwfDeviceAutoConfigureSet", self.h, C.c_int(0))
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(0))
        self._call("FDwfDigitalOutReset", self.h)
        self._call("FDwfDigitalOutTriggerSourceSet", self.h, C.c_int(0))  # none
        self._call("FDwfDigitalOutWaitSet", self.h, C.c_double(0.0))
        self._call("FDwfDigitalOutRunSet", self.h, C.c_double(0.0))  # continuous
        self._call("FDwfDigitalOutRepeatSet", self.h, C.c_int(0))  # infinite

        capacities = []
        divider_bounds = []
        for channel in range(9):
            ch = C.c_int(channel)
            self._call("FDwfDigitalOutEnableSet", self.h, ch, C.c_int(1))
            self._call("FDwfDigitalOutOutputSet", self.h, ch, C.c_int(0))  # push-pull
            self._call("FDwfDigitalOutIdleSet", self.h, ch, C.c_int(1))  # idle LOW
            self._call("FDwfDigitalOutTypeSet", self.h, ch, C.c_int(1))  # CUSTOM
            max_bits = C.c_uint()
            self._call("FDwfDigitalOutDataInfo", self.h, ch, C.byref(max_bits))
            capacities.append(max_bits.value)
            minimum, maximum = C.c_uint(), C.c_uint()
            self._call("FDwfDigitalOutDividerInfo", self.h, ch,
                       C.byref(minimum), C.byref(maximum))
            divider_bounds.append((minimum.value, maximum.value))

        n = min(sample_count, *capacities)
        if n < 16:
            raise DWFError(f"Insufficient AD3 digital custom memory: {capacities}")
        plan = build_comparator_pattern(
            sample_values_uv, duration_ms, thresholds_mv, afe_gain, n, bias_v,
        )
        clock = self._digital_clock_hz()
        requested_rate_hz = n * 1000.0 / duration_ms
        divider = round(clock / requested_rate_hz)
        if divider < 1 or divider > 0xFFFFFFFF:
            raise DWFError("Waveform duration is outside the digital clock divider range")
        if any(not low <= divider <= high for low, high in divider_bounds):
            raise DWFError(f"AD3 does not support divider {divider}; bounds {divider_bounds}")
        actual_rate = clock / divider
        actual_duration_ms = 1000 * n / actual_rate

        sync_words = [word | (1 << 8) if index == 0 else word
                      for index, word in enumerate(plan["words"])]
        for channel in range(9):
            ch = C.c_int(channel)
            self._call("FDwfDigitalOutDividerSet", self.h, ch, C.c_uint(divider))
            packed = pack_channel_bits(sync_words, channel)
            data = (C.c_ubyte * len(packed)).from_buffer_copy(packed)
            self._call("FDwfDigitalOutDataSet", self.h, ch, data, C.c_uint(n))

        # Exactly one start after all nine buffers are loaded. No digital_low()
        # or DigitalOutReset() after writing data; either would destroy it.
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(1))
        print(
            f"[AD3 comparator] 8 comparator channels + DIO8 sync, "
            f"{n} samples/cycle, rate={actual_rate:.3f} Hz, "
            f"period={actual_duration_ms:.6f} ms, divider={divider}, "
            f"CSV peak={plan['source_peak_uv']:g} uV, gain={afe_gain:g}x, "
            f"modeled AFE peak={plan['afe_peak_mv']:.3f} mV, bias={bias_v:g} V; "
            f"edges/cycle={plan['expected_edges_per_cycle']}",
            flush=True,
        )
        return {
            "channels": {**COMPARATOR_DIO, "SYNC": 8},
            "sync": {"channel": 8, "sample_index": 0, "pulse_samples": 1,
                     "repeats_each_cycle": True, "marker_decimation": 64},
            "sample_count": n,
            "clock_hz": clock,
            "divider": divider,
            "sample_rate_hz": actual_rate,
            "cycle_duration_ms": actual_duration_ms,
            "bias_v": plan["bias_v"],
            "afe_peak_mv": plan["afe_peak_mv"],
            "afe_gain": plan["afe_gain"],
            "source_peak_uv": plan["source_peak_uv"],
            "signal_range_mv": plan["signal_range_mv"],
            "thresholds_mv": plan["thresholds_mv"],
            "expected_edges_per_cycle": plan["expected_edges_per_cycle"],
            "high_samples_per_cycle": plan["high_samples_per_cycle"],
            "loop_boundary_edges": plan["loop_boundary_edges"],
            "repeats": True,
            "note": "Expected counts are software predictions, NOT measured AD3/FPGA edges.",
        }

    def capture_pulse_scope(self, sample_rate_hz=2_000_000.0, count=8192):
        """Free-running CH1 scope capture while digital outputs remain running.

        Wiring: selected DIO -> Scope 1+, Scope 1- -> GND.
        No analog WaveGen or digital reset.
        """
        if type(count) is not int or count < 1024 or count > 16384:
            raise ValueError("Unsupported scope sample count")
        if not math.isfinite(sample_rate_hz) or not 1_000 <= sample_rate_hz <= 50_000_000:
            raise ValueError("Unsupported scope sample rate")
        self._call("FDwfDeviceAutoConfigureSet", self.h, C.c_int(0))
        self._call("FDwfAnalogInReset", self.h)
        self._call("FDwfAnalogInChannelEnableSet", self.h, C.c_int(0), C.c_int(1))
        self._call("FDwfAnalogInChannelEnableSet", self.h, C.c_int(1), C.c_int(0))
        self._call("FDwfAnalogInChannelRangeSet", self.h, C.c_int(0), C.c_double(50.0))
        self._call("FDwfAnalogInChannelOffsetSet", self.h, C.c_int(0), C.c_double(0.0))
        self._call("FDwfAnalogInFrequencySet", self.h, C.c_double(sample_rate_hz))
        self._call("FDwfAnalogInBufferSizeSet", self.h, C.c_int(count))
        # Trigger source 0 = None (free-running acquisition)
        self._call("FDwfAnalogInTriggerSourceSet", self.h, C.c_int(0))
        self._call("FDwfAnalogInTriggerChannelSet", self.h, C.c_int(0))
        self._call("FDwfAnalogInTriggerTypeSet", self.h, C.c_int(0))  # edge
        self._call("FDwfAnalogInTriggerConditionSet", self.h, C.c_int(0))
        self._call("FDwfAnalogInTriggerLevelSet", self.h, C.c_double(1.65))
        self._call("FDwfAnalogInTriggerPositionSet", self.h, C.c_double(0.0))
        self._call("FDwfAnalogInTriggerAutoTimeoutSet", self.h, C.c_double(0.0))
        try:
            self._call("FDwfAnalogInConfigure", self.h, C.c_int(1), C.c_int(1))
            state = C.c_byte()
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                self._call("FDwfAnalogInStatus", self.h, C.c_int(1), C.byref(state))
                if state.value == 2:
                    break
                time.sleep(0.002)
            else:
                raise DWFError("Scope trigger timed out: check DIO-to-CH1+ wiring and active pulses")
            raw = (C.c_double * count)()
            self._call("FDwfAnalogInStatusData", self.h, C.c_int(0), raw, C.c_int(count))
            samples = list(raw)
            if not all(math.isfinite(v) for v in samples):
                raise DWFError("Non-finite scope samples")
            # Fixed CMOS threshold (1.65 V) avoids counting analog noise
            # as a digital transition when the line is flat near ground.
            lo, hi = min(samples), max(samples)
            crossings = []
            if lo < 0.8 and hi > 2.4:
                threshold = 1.65
                for i in range(1, len(samples)):
                    a, b = samples[i-1], samples[i]
                    if (a < threshold <= b) or (a >= threshold > b):
                        frac = (threshold-a)/(b-a) if b != a else 0
                        crossings.append(((i-1+frac)/sample_rate_hz, b > a))
            widths = [(crossings[i+1][0] - crossings[i][0]) * 1e6
                      for i in range(len(crossings)-1)
                      if crossings[i][1] and not crossings[i+1][1]]
            return {
                "sample_rate_hz": sample_rate_hz,
                "time_us": [round((i-count//2)*1e6/sample_rate_hz, 3) for i in range(count)],
                "voltage_v": [round(v, 5) for v in samples],
                "min_v": round(min(samples), 5), "max_v": round(max(samples), 5),
                "pulse_width_us": round(widths[0], 3) if widths else None,
                "edge_count": len(crossings),
                "note": ("Free-running CH1 capture; pulse widths refer to a recorded HIGH interval. "
                         "Counts are measured rising/falling edges in this window, "
                         "not an FPGA diagnostic count." if crossings else
                         "No complete 0-to-3.3 V digital transition identified in this free-running CH1 window.")
            }
        finally:
            self._call("FDwfAnalogInConfigure", self.h, C.c_int(0), C.c_int(0))

    def digital_output_status(self):
        """Query the hardware pattern-generator state (3 means Running)."""
        state = C.c_byte()
        self._call("FDwfDigitalOutStatus", self.h, C.byref(state))
        states = {0: "ready", 1: "armed", 2: "done", 3: "running",
                  4: "config", 5: "prefill", 7: "wait"}
        return {"state": state.value, "state_name": states.get(state.value, "unknown")}

    def stop_digital(self):
        """Stop the active pattern and drive all eight outputs LOW.

        Keep the device handle open: closing it immediately can release DIO pins.
        """
        self._call("FDwfDigitalOutConfigure", self.h, C.c_int(0))
        self._call("FDwfDigitalOutReset", self.h)
        self.digital_low()

    def close(self):
        if not self.h.value:
            return
        try:
            self._call("FDwfDigitalOutConfigure", self.h, C.c_int(0))
        finally:
            try:
                self._call("FDwfAnalogOutConfigure", self.h, C.c_int(0), C.c_int(0))
            finally:
                try:
                    self._call("FDwfDeviceClose", self.h)
                finally:
                    self.h.value = 0

    def check_readiness(self):
        """Verify a short free-running CH1 acquisition without enabling WaveGen.

        This tests basic acquisition functionality, not the AD3 power rails
        or every hardware subsystem.
        """
        count = 1024
        sample_rate_hz = 1_000_000.0
        self._call("FDwfDeviceAutoConfigureSet", self.h, C.c_int(0))
        self._call("FDwfAnalogInReset", self.h)
        self._call("FDwfAnalogInChannelEnableSet", self.h, C.c_int(0), C.c_int(1))
        self._call("FDwfAnalogInChannelEnableSet", self.h, C.c_int(1), C.c_int(0))
        self._call("FDwfAnalogInChannelRangeSet", self.h, C.c_int(0), C.c_double(5.0))
        self._call("FDwfAnalogInChannelOffsetSet", self.h, C.c_int(0), C.c_double(0.0))
        self._call("FDwfAnalogInFrequencySet", self.h, C.c_double(sample_rate_hz))
        self._call("FDwfAnalogInBufferSizeSet", self.h, C.c_int(count))
        self._call("FDwfAnalogInTriggerSourceSet", self.h, C.c_int(0))

        try:
            self._call("FDwfAnalogInConfigure", self.h, C.c_int(1), C.c_int(1))
            state = C.c_byte()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                self._call("FDwfAnalogInStatus", self.h, C.c_int(1), C.byref(state))
                if state.value == 2:  # DwfStateDone
                    break
                time.sleep(0.005)
            else:
                raise DWFError(
                    "AD3 scope acquisition timed out during readiness check"
                )

            samples = (C.c_double * count)()
            self._call(
                "FDwfAnalogInStatusData", self.h, C.c_int(0), samples, C.c_int(count)
            )
            if not all(math.isfinite(value) for value in samples):
                raise DWFError("AD3 scope returned non-finite samples")
            return {
                "ready": True,
                "message": "AD3 scope acquisition successful",
                "sample_count": count,
                "sample_rate_hz": sample_rate_hz,
            }
        finally:
            # Do not mask the original diagnostic failure if stopping fails.
            try:
                self._call("FDwfAnalogInConfigure", self.h, C.c_int(0), C.c_int(0))
            except DWFError:
                pass

    def play_and_capture(
        self,
        sample_values_uv,
        duration_ms,
        awg_peak_v=1.0,
        sample_rate_hz=1_000_000,
        channels=1,
    ):
        """Play a peak-normalized dataset at its requested duration; capture CH1/CH2.

        sample_rate_hz remains unused in this controlled test.
        """
        if not math.isfinite(awg_peak_v) or not 0.01 <= awg_peak_v <= 2.0:
            raise ValueError("awg_peak_v must be between 0.01 and 2.0 V")
        if not math.isfinite(float(duration_ms)) or not 1 <= duration_ms <= 100:
            raise ValueError("duration_ms must be between 1 and 100 ms")
        if channels not in (1, 2):
            raise ValueError("channels must be 1 or 2")
        if sample_values_uv is None or len(sample_values_uv) < 2:
            raise ValueError("Dataset must contain at least two waveform samples")
        if not all(math.isfinite(float(value)) for value in sample_values_uv):
            raise ValueError("Dataset contains a non-finite sample")

        ch = C.c_int(0)
        carrier = C.c_int(0)
        count = 8192
        scope_hz = 1_000_000.0
        # One full custom waveform buffer is one cycle. Preserve dataset duration.
        frequency_hz = 1000.0 / float(duration_ms)

        # Exactly the same scope configuration as the passing diagnostic.
        self._call("FDwfDeviceAutoConfigureSet", self.h, C.c_int(0))
        self._call("FDwfAnalogInReset", self.h)
        for index in (0, 1):
            scope_channel = C.c_int(index)
            enabled = index < channels
            self._call("FDwfAnalogInChannelEnableSet", self.h, scope_channel, C.c_int(int(enabled)))
            if enabled:
                self._call("FDwfAnalogInChannelRangeSet", self.h, scope_channel, C.c_double(5.0))
                self._call("FDwfAnalogInChannelOffsetSet", self.h, scope_channel, C.c_double(0.0))
        self._call("FDwfAnalogInFrequencySet", self.h, C.c_double(scope_hz))
        self._call("FDwfAnalogInBufferSizeSet", self.h, C.c_int(count))
        self._call("FDwfAnalogInTriggerSourceSet", self.h, C.c_int(0))
        self._call("FDwfAnalogInConfigure", self.h, C.c_int(1), C.c_int(0))

        # Keep Step 4 hardware settings and dataset resampling unchanged.
        self._call("FDwfAnalogOutReset", self.h, ch)
        self._call("FDwfAnalogOutNodeEnableSet", self.h, ch, carrier, C.c_int(1))
        minimum, maximum = C.c_int(), C.c_int()
        self._call(
            "FDwfAnalogOutNodeDataInfo", self.h, ch, carrier,
            C.byref(minimum), C.byref(maximum),
        )
        n = min(1024, maximum.value)
        if n < max(16, minimum.value):
            raise DWFError(
                f"Custom WaveGen buffer unsupported: {minimum.value}..{maximum.value}"
            )
        # Preserve the full CSV shape when adapting to the 1024-sample AWG
        # buffer. Include both endpoints and interpolate linearly.
        src = [float(v) for v in sample_values_uv]
        values = []
        for i in range(n):
            pos = i * (len(src) - 1) / (n - 1)
            left = min(int(pos), len(src) - 2)
            frac = pos - left
            values.append(src[left] * (1.0 - frac) + src[left + 1] * frac)
        peak_uv = max(abs(v) for v in values)
        if peak_uv <= 0:
            raise ValueError("Dataset is all zero: cannot normalize peak")
        normalized = [max(-1.0, min(1.0, v / peak_uv)) for v in values]
        points = (C.c_double * n)(*normalized)
        self._call("FDwfAnalogOutNodeFunctionSet", self.h, ch, carrier, C.c_int(30))
        self._call(
            "FDwfAnalogOutNodeDataSet", self.h, ch, carrier, points, C.c_int(n)
        )
        print(
            f"[AD3 step 5] Uploaded {n} dataset points from {len(src)} CSV samples "
            f"(source peak={peak_uv:.3f} uV, "
            f"normalized range={min(points):+.4f}..{max(points):+.4f}); "
            f"requested amplitude={awg_peak_v:.3f} V peak; "
            f"duration={duration_ms:g} ms, playback frequency={frequency_hz:.3f} Hz",
            flush=True,
        )
        self._call("FDwfAnalogOutNodeFrequencySet", self.h, ch, carrier, C.c_double(frequency_hz))
        self._call("FDwfAnalogOutNodeAmplitudeSet", self.h, ch, carrier, C.c_double(awg_peak_v))
        self._call("FDwfAnalogOutNodeOffsetSet", self.h, ch, carrier, C.c_double(0.0))
        self._call("FDwfAnalogOutConfigure", self.h, ch, C.c_int(1))

        try:
            # Retain the known-good 150 ms settling time.
            time.sleep(0.15)

            self._call("FDwfAnalogInConfigure", self.h, C.c_int(1), C.c_int(1))
            state = C.c_byte()
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                self._call("FDwfAnalogInStatus", self.h, C.c_int(1), C.byref(state))
                if state.value == 2:  # DwfStateDone
                    break
                time.sleep(0.005)
            else:
                raise DWFError("AD3 scope acquisition timed out")

            traces = {}
            for index in range(channels):
                scope_channel = C.c_int(index)
                raw = (C.c_double * count)()
                self._call("FDwfAnalogInStatusData", self.h, scope_channel, raw, C.c_int(count))
                samples = list(raw)
                traces[f"ch{index + 1}"] = [round(x, 6) for x in samples]
                vmin, vmax = min(samples), max(samples)
                vpp = vmax - vmin
                print(
                    f"[AD3 step 5] CH{index + 1}: "
                    f"min={vmin:.4f} V, max={vmax:.4f} V, Vpp={vpp:.4f} V",
                    flush=True,
                )

            expected_vpp = (max(normalized) - min(normalized)) * awg_peak_v
            ch1 = traces["ch1"]
            actual_vpp = max(ch1) - min(ch1)
            print(
                f"[AD3 step 5] CH1 ratio to WaveGen expected Vpp "
                f"({expected_vpp:.4f} V): {actual_vpp / expected_vpp:.3f}",
                flush=True,
            )
            if channels == 2:
                ch2 = traces["ch2"]
                ch2_vpp = max(ch2) - min(ch2)
                print(
                    f"[AD3 step 5] CH2/CH1 Vpp ratio: "
                    f"{ch2_vpp / actual_vpp:.4f}",
                    flush=True,
                )

            return {
                "time_ms": [round(1000.0 * i / scope_hz, 6) for i in range(count)],
                "channels": traces,
                "sample_rate_hz": scope_hz,
                "note": (
                    f"AD3 STEP 5: selected dataset at {frequency_hz:.3f} Hz "
                    f"(one {duration_ms:g} ms cycle); "
                    f"{channels} scope channel(s), 8192 samples at 1 MS/s; "
                    "free-running, not phase-synchronized."
                ),
            }
        finally:
            self._call("FDwfAnalogOutConfigure", self.h, ch, C.c_int(0))
