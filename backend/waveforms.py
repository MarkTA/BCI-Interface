"""Minimal AD3 loopback adapter — Step 5: add optional simultaneous CH2 capture.

This intentionally reproduces the successful standalone amplitude diagnostic.
Uses the dataset supplied by the existing FastAPI endpoint. Restores its
playback duration while preserving the known-good 1024-point custom waveform,
8192-point scope capture at 1 MS/s, and 150 ms settling delay.
Single-buffer capture remains untriggered; timing is not phase-synchronized.
Both channels use the same scope acquisition clock.

Loopback: W1 -> 1+ and optionally 2+; 1- and 2- -> GND. Disconnect the AFE.
Close Digilent WaveForms before testing.
"""

import ctypes as C
import math
import os
from pathlib import Path
import sys
import time


class DWFError(RuntimeError):
    pass


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

    def close(self):
        if not self.h.value:
            return
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
