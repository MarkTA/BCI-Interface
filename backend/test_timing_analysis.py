"""Offline relative-timing and conservative-reduction regression tests."""
import unittest
from event_matching import match_reference_to_fpga
from timing_analysis import analyze_relative_timing
from validation_metrics import calculate_validation_metrics, FAIL, NOT_AVAILABLE


def ref(times):
    return [{'relative_onset_us': float(t), 'channel': 0, 'peak': 3, 'trough': 4,
             'time_to_peak_us': 653} for t in times]


def obs(times):
    return [{'timestamp_us': int(t) % (1 << 24), 'channel': 0, 'peak': 3,
             'trough': 4, 'time_to_peak_us': 653} for t in times]


class RelativeTimingTests(unittest.TestCase):
    def test_exact_matching_periods_have_zero_drift(self):
        m = match_reference_to_fpga(ref([100, 5100, 10100]), obs([200, 5200, 10200]),
                                    alignment={'mode': 'event_anchor', 'reference_index': 0, 'observed_index': 0})
        r = analyze_relative_timing(m)
        self.assertEqual(r['consecutive_pairs'], 2)
        self.assertEqual(r['relative_clock_error_ppm'], 0)
        self.assertEqual(r['max_absolute_interval_error_us'], 0)
        self.assertEqual(r['cumulative_relative_drift_us'], 0)
        self.assertEqual(r['type'], 'diagnostic_only')

    def test_period_drift_and_counter_wrap(self):
        m = match_reference_to_fpga(ref([100, 5100, 10100]),
                                    obs([(1 << 24) - 100, (1 << 24) + 4901, (1 << 24) + 9902]),
                                    alignment={'mode': 'event_anchor', 'reference_index': 0, 'observed_index': 0})
        r = analyze_relative_timing(m)
        self.assertEqual(r['consecutive_pairs'], 2)
        self.assertEqual(r['cumulative_relative_drift_us'], 2)
        self.assertAlmostEqual(r['relative_clock_error_ppm'], 200)

    def test_missing_pair_not_misclassified_as_interval(self):
        m = match_reference_to_fpga(ref([100, 5100, 10100]), obs([200, 10200]),
                                    alignment={'mode': 'event_anchor', 'reference_index': 0, 'observed_index': 0})
        r = analyze_relative_timing(m)
        self.assertEqual(r['consecutive_pairs'], 0)

    def test_unaligned_results_have_no_false_relative_claim(self):
        m = match_reference_to_fpga(ref([100, 5100]), obs([200, 5200]))
        r = analyze_relative_timing(m)
        self.assertIsNone(r['relative_clock_error_ppm'])


class ConservativeReductionTests(unittest.TestCase):
    def test_known_neural_packets_prove_fail_without_complete_tx(self):
        m = match_reference_to_fpga(ref([]), obs([i * 5000 for i in range(201)]))
        result = calculate_validation_metrics(m, run_duration_s=1.05,
            observed_neural_packets_verified=True, duration_upper_bound_s=1.06)
        ratio = result['metrics']['data_reduction']
        self.assertEqual(ratio['status'], FAIL)
        self.assertLess(ratio['data_reduction_upper_bound_ratio'], 10)
        self.assertIn('≤', result['performance_summary'][-1]['value'])

    def test_no_packet_crosscheck_means_unverified(self):
        m = match_reference_to_fpga(ref([]), obs([i * 5000 for i in range(201)]))
        result = calculate_validation_metrics(m, run_duration_s=1.05,
            observed_neural_packets_verified=False, duration_upper_bound_s=1.06)
        self.assertEqual(result['metrics']['data_reduction']['status'], NOT_AVAILABLE)

    def test_bound_exactly_at_target_does_not_fail(self):
        m = match_reference_to_fpga(ref([]), obs([i * 5000 for i in range(160)]))
        result = calculate_validation_metrics(m, run_duration_s=1,
            observed_neural_packets_verified=True, duration_upper_bound_s=1)
        self.assertEqual(result['metrics']['data_reduction']['status'], NOT_AVAILABLE)

    def test_all_matched_agreement_shown_without_isolation_claim(self):
        m = match_reference_to_fpga(ref([100, 5100]), obs([200, 5200]),
            alignment={'mode': 'event_anchor', 'reference_index': 0, 'observed_index': 0})
        result = calculate_validation_metrics(m)
        row = result['performance_summary'][1]
        self.assertEqual(row['value'], 1)
        self.assertEqual(row['status'], NOT_AVAILABLE)
        self.assertIn('all matches', row['name'])


if __name__ == '__main__':
    unittest.main()
