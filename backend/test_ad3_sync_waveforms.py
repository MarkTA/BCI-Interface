"""Offline tests: does NOT need an AD3 or Digilent SDK installed."""
import ctypes as C
import math
import unittest

from waveforms import AD3, COMPARATOR_DIO, build_comparator_pattern, pack_channel_bits

THRESHOLDS = {
    'P1': 20.0, 'P2': 40.0, 'P3': 60.0, 'P4': 80.0,
    'N1': -20.0, 'N2': -40.0, 'N3': -60.0, 'N4': -80.0,
}


class TestComparatorModel(unittest.TestCase):
    def test_signed_polarities_and_dio_mapping(self):
        # Source points are µV, with a 1000× test gain giving +/-100mV.
        p = build_comparator_pattern(
            [-100, -50, 0, +50, +100], 100, THRESHOLDS,
            sample_count=17, afe_gain=1000,
        )
        self.assertEqual(p['words'][0], 0b00001111)   # all N triggered
        self.assertEqual(p['words'][4], 0b00000011)   # N1/N2 at -50mV
        self.assertEqual(p['words'][8], 0)            # all below threshold
        self.assertEqual(p['words'][12], 0b00110000)  # P1/P2 at +50mV
        self.assertEqual(p['words'][16], 0b11110000)  # all P triggered
        self.assertEqual(COMPARATOR_DIO['N1'], 0)
        self.assertEqual(COMPARATOR_DIO['P4'], 7)
        self.assertEqual(p['loop_boundary_edges']['N1'], 1)

    def test_source_amplitude_preserved_across_datasets(self):
        limits = {'P1': 5, 'P2': 10, 'P3': 20, 'P4': 40,
                  'N1': -5, 'N2': -10, 'N3': -20, 'N4': -40}
        large = build_comparator_pattern([0, 100, 0, -100, 0], 5, limits,
                                         afe_gain=385, sample_count=1024)
        small = build_comparator_pattern([0, 20, 0, -20, 0], 5, limits,
                                         afe_gain=385, sample_count=1024)
        self.assertAlmostEqual(large['afe_peak_mv'], 38.5)
        self.assertAlmostEqual(small['afe_peak_mv'], 7.7)
        self.assertGreater(large['expected_edges_per_cycle']['P3'], 0)
        self.assertEqual(small['expected_edges_per_cycle']['P3'], 0)
        self.assertEqual(small['expected_edges_per_cycle']['P4'], 0)

    def test_zero_dataset_and_rail_guard(self):
        zero = build_comparator_pattern([0, 0], 5, THRESHOLDS)
        self.assertEqual(zero['afe_peak_mv'], 0)
        self.assertEqual(sum(zero['expected_edges_per_cycle'].values()), 0)
        with self.assertRaisesRegex(ValueError, 'supply rails'):
            build_comparator_pattern([-10000, 10000], 5, THRESHOLDS)

    def test_pack_bits_are_lsb_first_across_time(self):
        data = [0b00000001, 0b10000000, 0b00000001, 0b00000000,
                0b00000001, 0, 0, 0, 0b10000001]
        self.assertEqual(pack_channel_bits(data, 0), bytes([0b00010101, 1]))
        self.assertEqual(pack_channel_bits(data, 7), bytes([0b00000010, 1]))

    def test_reject_wrong_sign_and_bad_values(self):
        bad = dict(THRESHOLDS)
        bad['N1'] = 20
        with self.assertRaisesRegex(ValueError, 'negative N'):
            build_comparator_pattern([-1, 1], 10, bad)
        bad['N1'] = -20
        bad['P2'] = -20
        with self.assertRaisesRegex(ValueError, 'positive P'):
            build_comparator_pattern([-1, 1], 10, bad)
        zeros = build_comparator_pattern([0, 0], 10, THRESHOLDS)
        self.assertEqual(sum(zeros['expected_edges_per_cycle'].values()), 0)
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            build_comparator_pattern([0, math.nan], 10, THRESHOLDS)


class FakeAD3(AD3):
    """Mocks raw SDK calls and records exact bytes (not physical hardware behavior)."""
    def __init__(self):
        self.h = C.c_int(42)
        self.calls = []
        self.buffers = {}

    def _call(self, name, *args):
        self.calls.append((name, args))
        if name == 'FDwfDigitalOutDataInfo':
            C.cast(args[-1], C.POINTER(C.c_uint)).contents.value = 2048
        if name == 'FDwfDigitalOutDividerInfo':
            C.cast(args[-2], C.POINTER(C.c_uint)).contents.value = 1
            C.cast(args[-1], C.POINTER(C.c_uint)).contents.value = 10000000
        if name == 'FDwfDigitalOutInternalClockInfo':
            C.cast(args[-1], C.POINTER(C.c_double)).contents.value = 100_000_000.0
        if name == 'FDwfDigitalOutDataSet':
            channel = args[1].value
            n = args[3].value
            self.buffers[channel] = bytes(args[2])
            assert len(self.buffers[channel]) == (n + 7) // 8


class TestHardwareOrchestration(unittest.TestCase):
    def test_single_start_and_all_channel_buffers(self):
        fake = FakeAD3()
        samples = [100 * math.sin(2 * math.pi * i / 1024) for i in range(1024)]
        info = fake.digital_comparator_simulation(samples, 100, THRESHOLDS,
                                                  afe_gain=1000, sample_count=1024)
        self.assertEqual(info['sample_count'], 1024)
        self.assertEqual(info['divider'], 9766)
        self.assertEqual(len(fake.buffers), 9)
        self.assertEqual(len(fake.buffers[0]), 128)
        self.assertEqual(fake.buffers[8], bytes([1]) + bytes(127))
        self.assertEqual(info['sync']['sample_index'], 0)
        starts = [i for i, (name, args) in enumerate(fake.calls)
                  if name == 'FDwfDigitalOutConfigure' and args[1].value == 1]
        self.assertEqual(len(starts), 1)
        data_write_indexes = [i for i, (name, _) in enumerate(fake.calls)
                              if name == 'FDwfDigitalOutDataSet']
        self.assertEqual(len(data_write_indexes), 9)
        self.assertLess(max(data_write_indexes), starts[0])
        self.assertGreater(info['expected_edges_per_cycle']['P1'], 0)
        self.assertGreater(info['expected_edges_per_cycle']['N1'], 0)


if __name__ == '__main__':
    unittest.main()
