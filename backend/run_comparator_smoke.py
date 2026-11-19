"""Real AD3 comparator simulation smoke test (NO React required).

Run with WaveForms GUI and the FastAPI backend stopped, e.g.:
    python run_comparator_smoke.py --scope --channel 0
    python run_comparator_smoke.py --scope --channel 6  # P3

This produces a 10 Hz sine-derived, 8-channel digital comparator simulation:
    DIO0..3 = N1..4, DIO4..7 = P1..4.
    Every channel should have two logic transitions per 100ms cycle.

Optional CH1 scope wiring: selected DIO (--channel 0..7) -> 1+, GND -> 1-.
Optional FPGA wiring: DIO0..7 -> FPGA comparator inputs with common GND.
Never connect an FPGA output pin to a driven AD3 DIO output.
"""
import argparse
import math
import time

from ad3_manager import ad3_manager


DIO_NAMES = ('N1', 'N2', 'N3', 'N4', 'P1', 'P2', 'P3', 'P4')


SIGNED_THRESHOLDS_MV = {
    'P1': 20, 'P2': 40, 'P3': 60, 'P4': 80,
    'N1': -20, 'N2': -40, 'N3': -60, 'N4': -80,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=8,
                        help='Output run duration, 3..60s (default: 8s)')
    parser.add_argument('--scope', action='store_true',
                        help='Capture 164ms of CH1 while the eight-channel simulation runs')
    parser.add_argument('--channel', type=int, choices=range(8), default=0,
                        metavar='{0..7}',
                        help='DIO output connected to CH1+ for --scope (default: 0/N1)')
    args = parser.parse_args()
    if not 3 <= args.seconds <= 60:
        parser.error('--seconds must be between 3 and 60')
    channel_name = DIO_NAMES[args.channel]

    # A single 100ms dataset cycle contains one 10Hz sine period.
    n_source = 1024
    source_uv = [100 * math.sin(2 * math.pi * i / (n_source - 1))
                 for i in range(n_source)]

    print('Opening AD3: close the WaveForms GUI and FastAPI first.')
    try:
        info = ad3_manager.start(
            'comparators', sample_values_uv=source_uv,
            duration_ms=100.0, thresholds_mv=SIGNED_THRESHOLDS_MV,
            afe_peak_mv=100.0, sample_count=1024,
            bias_v=1.6, duration_s=args.seconds,
        )
        print('Expected FPGA edge counts per repeating 100ms cycle:',
              info['expected_edges_per_cycle'])
        print(f'Expected FPGA raw transition rate: ~{sum(info["expected_edges_per_cycle"].values())*10:.0f} edges/s')
        time.sleep(0.2)
        print('Actual AD3 digital instrument:', ad3_manager.hardware_status())

        if args.scope:
            # All eight patterns continue to run simultaneously. --channel only
            # selects which physical DIO lead the user connects to CH1+.
            high_fraction = (info['high_samples_per_cycle'][channel_name]
                             / info['sample_count'])
            high_ms = high_fraction * info['cycle_duration_ms']
            print(f'Capturing {channel_name} (DIO{args.channel}) on CH1: '
                  f'connect DIO{args.channel} -> 1+, AD3 GND -> 1-.')
            print(f'Expected {channel_name} HIGH time per cycle: '
                  f'{high_ms:.3f} ms ({100 * high_fraction:.1f}% duty); '
                  f'{info["expected_edges_per_cycle"][channel_name]} edges/cycle.')
            result = ad3_manager.capture_pulse_scope(sample_rate_hz=100_000.0,
                                                     count=16384)
            print('Scope:', {key: result[key] for key in
                             ('min_v', 'max_v', 'pulse_width_us', 'edge_count', 'note')})
            print('Compare the measured CH1 waveform against the expected '
                  f'DIO{args.channel}/{channel_name} pattern; the scope is '
                  'not connected to other channels.')

        remaining = max(0, args.seconds - 0.2 - (0.25 if args.scope else 0))
        if remaining:
            time.sleep(remaining)
    finally:
        print('Stopping generator and driving LOW idle state...')
        try:
            print('Status:', ad3_manager.stop())
        except Exception as exc:
            print(f'WARNING: AD3 failed to stop cleanly: {exc}')
            raise


if __name__ == '__main__':
    main()
