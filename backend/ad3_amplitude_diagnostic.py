"""AD3 W1 -> Scope 1+ loopback amplitude diagnostic.

Run from the BCI application's backend directory:
    python ..\ad3_amplitude_diagnostic.py
or copy this script into backend and run:
    python ad3_amplitude_diagnostic.py

Close WaveForms GUI and stop FastAPI before starting. Connect W1 -> 1+, 1- -> GND.
This script makes no edits to the BCI app. Output is stopped and device closed on exit.
"""
import ctypes as C
import math
import statistics
import time

# Import the BCI application's existing SDK wrapper (same directory as backend/waveforms.py).
from waveforms import AD3, DWFError

CHANNEL = C.c_int(0)  # W1 and Scope CH1 use zero-based indexing
CARRIER = C.c_int(0)
FUNCTION_SINE = 1
FUNCTION_CUSTOM = 30
FREQUENCY_HZ = 1000.0
SAMPLE_RATE_HZ = 1_000_000.0
SCOPE_SAMPLES = 8192


def get_amplitude(device):
    amplitude = C.c_double()
    device._call('FDwfAnalogOutNodeAmplitudeGet', device.h, CHANNEL, CARRIER,
                 C.byref(amplitude))
    return amplitude.value


def measure(device):
    device._call('FDwfAnalogInConfigure', device.h, C.c_int(1), C.c_int(1))
    state = C.c_byte()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        device._call('FDwfAnalogInStatus', device.h, C.c_int(1), C.byref(state))
        if state.value == 2:  # DwfStateDone
            break
        time.sleep(0.005)
    else:
        raise DWFError('Scope acquisition timed out')
    values = (C.c_double * SCOPE_SAMPLES)()
    device._call('FDwfAnalogInStatusData', device.h, CHANNEL, values,
                 C.c_int(SCOPE_SAMPLES))
    samples = list(values)
    minimum = min(samples)
    maximum = max(samples)
    rms = math.sqrt(statistics.fmean(v * v for v in samples))
    return minimum, maximum, maximum - minimum, rms


def configure_scope(device):
    device._call('FDwfAnalogInReset', device.h)
    device._call('FDwfAnalogInChannelEnableSet', device.h, CHANNEL, C.c_int(1))
    device._call('FDwfAnalogInChannelRangeSet', device.h, CHANNEL, C.c_double(5.0))
    device._call('FDwfAnalogInChannelOffsetSet', device.h, CHANNEL, C.c_double(0.0))
    device._call('FDwfAnalogInFrequencySet', device.h, C.c_double(SAMPLE_RATE_HZ))
    device._call('FDwfAnalogInBufferSizeSet', device.h, C.c_int(SCOPE_SAMPLES))
    device._call('FDwfAnalogInTriggerSourceSet', device.h, C.c_int(0))  # none
    device._call('FDwfAnalogInConfigure', device.h, C.c_int(1), C.c_int(0))


def configure_generator(device, mode, peak):
    # Start each test from exactly the same WaveGen reset state.
    device._call('FDwfAnalogOutReset', device.h, CHANNEL)
    device._call('FDwfAnalogOutNodeEnableSet', device.h, CHANNEL, CARRIER,
                 C.c_int(1))
    if mode == 'custom':
        minimum, maximum = C.c_int(), C.c_int()
        device._call('FDwfAnalogOutNodeDataInfo', device.h, CHANNEL, CARRIER,
                     C.byref(minimum), C.byref(maximum))
        count = min(1024, maximum.value)
        if count < max(16, minimum.value):
            raise DWFError(f'Custom data buffer unsupported: {minimum.value}..{maximum.value}')
        # Same expected output as built-in sine: ±peak volts.
        points = (C.c_double * count)(
            *(math.sin(2.0 * math.pi * i / count) for i in range(count))
        )
        device._call('FDwfAnalogOutNodeFunctionSet', device.h, CHANNEL,
                     CARRIER, C.c_int(FUNCTION_CUSTOM))
        device._call('FDwfAnalogOutNodeDataSet', device.h, CHANNEL,
                     CARRIER, points, C.c_int(count))
    else:
        device._call('FDwfAnalogOutNodeFunctionSet', device.h, CHANNEL,
                     CARRIER, C.c_int(FUNCTION_SINE))
    device._call('FDwfAnalogOutNodeFrequencySet', device.h, CHANNEL, CARRIER,
                 C.c_double(FREQUENCY_HZ))
    device._call('FDwfAnalogOutNodeAmplitudeSet', device.h, CHANNEL, CARRIER,
                 C.c_double(peak))
    device._call('FDwfAnalogOutNodeOffsetSet', device.h, CHANNEL, CARRIER,
                 C.c_double(0.0))
    readback = get_amplitude(device)
    device._call('FDwfAnalogOutConfigure', device.h, CHANNEL, C.c_int(1))
    time.sleep(0.15)
    return readback


def main():
    print('AD3 W1 -> CH1 loopback | 1 kHz sine | 5 V scope input range')
    print('Expected Vpp is 2 x requested peak for both built-in and custom sine.')
    print('Stop FastAPI and close WaveForms GUI before running.\n')
    with_device = AD3()
    try:
        # Disable auto-configuration so all changes are applied explicitly.
        with_device._call('FDwfDeviceAutoConfigureSet', with_device.h, C.c_int(0))
        configure_scope(with_device)
        print(f"{'mode':<10} {'set peak':>9} {'readback':>9} {'min V':>10} {'max V':>10} {'Vpp':>10} {'ratio':>8} {'RMS V':>10}")
        for mode in ('sine', 'custom'):
            for peak in (1.0, 0.5, 0.25):
                readback = configure_generator(with_device, mode, peak)
                vmin, vmax, vpp, rms = measure(with_device)
                print(f'{mode:<10} {peak:>9.3f} {readback:>9.3f} {vmin:>10.4f} '
                      f'{vmax:>10.4f} {vpp:>10.4f} {vpp/(2*peak):>8.3f} {rms:>10.4f}')
        print('\nratio = measured Vpp / expected Vpp. A good result is near 1.000.')
    finally:
        with_device.close()
        print('WaveGen stopped, AD3 closed.')


if __name__ == '__main__':
    main()
