"""Offline Phase 3 validation metric regression tests (no hardware required)."""

import json
import unittest

from event_matching import match_reference_to_fpga
from neural_reference import generate_reference_events
from validation_metrics import calculate_validation_metrics, NOT_AVAILABLE, PASS, FAIL


SYNC = {'mode': 'shared_origin', 'source': 'offline synthetic packet replay', 'uncertainty_us': 0}


def expected(*times, peak=2, trough=3, ttp=100):
    return [{'channel': 0, 'relative_onset_us': t, 'peak': peak, 'trough': trough,
             'time_to_peak_us': ttp, 'flags_mask': 0} for t in times]


def observed(*times, peak=2, trough=3, ttp=100):
    return [{'channel': 0, 'timestamp_us': int(t) % (1 << 24),
             'peak': peak, 'trough': trough, 'time_to_peak_us': ttp,
             'flags_mask': 0} for t in times]


def match(ref, obs, alignment=SYNC, tolerance_us=100):
    return match_reference_to_fpga(ref, obs, alignment=alignment,
                                   tolerance_us=tolerance_us)


def traffic(total, diagnostic=0, complete=True, source='raw FPGA TX line capture'):
    return {'total_uart_bytes': total, 'diagnostic_uart_bytes': diagnostic,
            'complete': complete, 'source': source}


def metrics(matched, *, complete=True, labels=None, seconds=1.0, transport=None, baseline=None):
    return calculate_validation_metrics(
        matched, capture_complete=complete, isolated_reference_indices=labels,
        run_duration_s=seconds, transport=transport, baseline=baseline)


class DetectionMetricTests(unittest.TestCase):
    def test_tp_fp_fn_precision_recall_and_f1(self):
        matched = match(expected(100, 1000, 2000), observed(100, 2000, 3000))
        output = metrics(matched, labels=[0, 1, 2])
        score = output['metrics']['detection']
        self.assertEqual(score['counts'], {'expected': 3, 'observed': 3,
                                           'tp': 2, 'fp': 1, 'fn': 1})
        self.assertAlmostEqual(score['precision'], 2 / 3)
        self.assertAlmostEqual(score['recall'], 2 / 3)
        self.assertAlmostEqual(score['f1'], 2 / 3)
        self.assertEqual(score['status'], FAIL)

    def test_exact_90_percent_f1_passes(self):
        ref = expected(*(100 + i * 1000 for i in range(10)))
        obs = observed(*(100 + i * 1000 for i in range(9)), 15_000)
        output = metrics(match(ref, obs))
        self.assertEqual(output['metrics']['detection']['f1'], .9)
        self.assertEqual(output['metrics']['detection']['status'], PASS)

    def test_no_observations_and_expected_spikes_is_zero_f1(self):
        output = metrics(match(expected(50, 1000), []))
        score = output['metrics']['detection']
        self.assertEqual(score['f1'], 0)
        self.assertEqual(score['recall'], 0)
        self.assertIsNone(score['precision'])
        self.assertEqual(score['status'], FAIL)

    def test_quiet_only_empty_run_has_undefined_f1(self):
        output = metrics(match([], []), labels=[], transport=traffic(0))
        score = output['metrics']['detection']
        self.assertIsNone(score['precision'])
        self.assertIsNone(score['recall'])
        self.assertIsNone(score['f1'])
        self.assertEqual(score['status'], NOT_AVAILABLE)
        self.assertEqual(output['metrics']['data_reduction']['status'], PASS)
        self.assertTrue(output['metrics']['data_reduction']['zero_operational_traffic'])
        self.assertIsNone(output['metrics']['data_reduction']['data_reduction_ratio'])
        json.dumps(output, allow_nan=False)

    def test_noise_only_false_trigger_means_f1_zero(self):
        output = metrics(match([], observed(100)))
        score = output['metrics']['detection']
        self.assertEqual(score['f1'], 0)
        self.assertIsNone(score['recall'])
        self.assertEqual(score['precision'], 0)
        self.assertEqual(score['status'], FAIL)

    def test_no_alignment_withholds_metrics_not_fake_zero(self):
        unmatched = match_reference_to_fpga(expected(100), observed(1000))
        result = metrics(unmatched, labels=[0], transport=traffic(10))
        self.assertEqual(result['matching_status'], 'alignment_required')
        self.assertIsNone(result['metrics']['detection']['f1'])
        self.assertEqual(result['metrics']['detection']['status'], NOT_AVAILABLE)
        self.assertEqual(result['metrics']['timestamp']['status'], NOT_AVAILABLE)
        self.assertIsNone(result['metrics']['timestamp']['statistics']['max_absolute_us'])
        self.assertEqual(result['overall_status'], NOT_AVAILABLE)

    def test_event_anchor_does_not_claim_acceptance(self):
        aligned = match(expected(1000), observed(501000), alignment={
            'mode': 'event_anchor', 'reference_index': 0, 'observed_index': 0})
        result = metrics(aligned, labels=[0], transport=traffic(10))
        self.assertEqual(result['metrics']['detection']['f1'], 1)
        self.assertEqual(result['metrics']['detection']['status'], NOT_AVAILABLE)
        self.assertEqual(result['metrics']['peak_accuracy']['status'], NOT_AVAILABLE)
        self.assertEqual(result['metrics']['time_to_peak']['status'], NOT_AVAILABLE)
        self.assertEqual(result['metrics']['timestamp']['status'], NOT_AVAILABLE)
        self.assertEqual(result['metrics']['data_reduction']['status'], PASS)
        self.assertFalse(result['accuracy_acceptance_eligible'])

    def test_unconfirmed_event_capture_disables_acceptance(self):
        result = metrics(match(expected(100), observed(100)), complete=False,
                         labels=[0], transport=traffic(10))
        for key in result['metrics']:
            self.assertEqual(result['metrics'][key]['status'], NOT_AVAILABLE)

    def test_counts_and_duplicate_indexes_are_checked(self):
        aligned = match(expected(100), observed(100))
        aligned['counts']['fn'] = 1
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            metrics(aligned)
        aligned = match(expected(100, 200), observed(100, 200))
        aligned['matches'][1]['observed_index'] = 0
        with self.assertRaisesRegex(ValueError, 'unique'):
            metrics(aligned)


class ClassificationTests(unittest.TestCase):
    def test_no_isolation_labels_does_not_claim_classification_accuracy(self):
        result = metrics(match(expected(100), observed(100)))
        peak = result['metrics']['peak_accuracy']
        self.assertEqual(peak['all_matched_accuracy'], 1)
        self.assertIsNone(peak['isolated_accuracy'])
        self.assertEqual(peak['status'], NOT_AVAILABLE)

    def test_only_explicit_isolated_subset_counts(self):
        aligned = match(expected(100, 2000, 4000), observed(100, 2000, 4000))
        aligned['matches'][1]['peak_match'] = False  # Non-isolated spike
        result = metrics(aligned, labels=[0, 2])
        peak = result['metrics']['peak_accuracy']
        self.assertEqual(peak['isolated_accuracy'], 1)
        self.assertAlmostEqual(peak['all_matched_accuracy'], 2 / 3)
        self.assertEqual(peak['isolated_matched_count'], 2)
        self.assertEqual(peak['status'], PASS)

    def test_combined_accuracy_means_both_peak_and_trough_correct(self):
        aligned = match(expected(100, 2000), observed(100, 2000))
        aligned['matches'][0]['peak_match'] = False
        aligned['matches'][1]['trough_match'] = False
        out = metrics(aligned, labels=[0, 1])
        joint = out['combined_feature_accuracy']
        self.assertEqual(joint['isolated_joint_accuracy'], 0)
        self.assertEqual(joint['all_matched_joint_accuracy'], 0)
        self.assertEqual(joint['status'], NOT_AVAILABLE)

    def test_classification_exact_90_percent_passes_and_below_fails(self):
        times = [i * 1000 + 100 for i in range(10)]
        aligned = match(expected(*times), observed(*times))
        aligned['matches'][0]['trough_match'] = False
        res = metrics(aligned, labels=list(range(10)))
        self.assertEqual(res['metrics']['trough_accuracy']['isolated_accuracy'], .9)
        self.assertEqual(res['metrics']['trough_accuracy']['status'], PASS)
        aligned['matches'][1]['trough_match'] = False
        res = metrics(aligned, labels=list(range(10)))
        self.assertEqual(res['metrics']['trough_accuracy']['status'], FAIL)

    def test_feature_coverage_missing_blocks_claim(self):
        aligned = match(expected(100, 1000), observed(100, 1000))
        aligned['matches'][1]['peak_match'] = None
        res = metrics(aligned, labels=[0, 1])
        self.assertEqual(res['metrics']['peak_accuracy']['isolated_accuracy'], 1)
        self.assertEqual(res['metrics']['peak_accuracy']['isolated_missing_features'], 1)
        self.assertEqual(res['metrics']['peak_accuracy']['status'], NOT_AVAILABLE)
        self.assertEqual(res['metrics']['trough_accuracy']['status'], PASS)

    def test_label_only_missed_event_is_not_a_classification_failure(self):
        aligned = match(expected(100, 2000), observed(100))
        res = metrics(aligned, labels=[1])
        self.assertEqual(res['metrics']['detection']['status'], FAIL)
        self.assertEqual(res['metrics']['peak_accuracy']['status'], NOT_AVAILABLE)
        self.assertEqual(res['metrics']['peak_accuracy']['isolated_matched_count'], 0)

    def test_duplicate_or_out_of_range_isolation_labels_rejected(self):
        aligned = match(expected(100), observed(100))
        for labels in [[0, 0], [1], [-1], [True]]:
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                metrics(aligned, labels=labels)


class TimingTests(unittest.TestCase):
    def test_strict_timestamp_under_100_us_passes(self):
        result = metrics(match(expected(1000, 2000), observed(1050, 2075)), labels=[0, 1])
        tm = result['metrics']['timestamp']
        self.assertEqual(tm['status'], PASS)
        self.assertEqual(tm['statistics']['count'], 2)
        self.assertEqual(tm['statistics']['mean_signed_us'], 62.5)
        self.assertEqual(tm['statistics']['mean_absolute_us'], 62.5)
        self.assertEqual(tm['statistics']['max_absolute_us'], 75)
        self.assertEqual(tm['statistics']['within_tolerance_percent'], 100)
        self.assertEqual(sum(tm['statistics']['absolute_error_bins'].values()), 2)

    def test_timestamp_exact_100_us_fails_even_when_match_is_allowed(self):
        result = metrics(match(expected(1000), observed(1100)), labels=[0])
        tm = result['metrics']['timestamp']
        self.assertEqual(tm['statistics']['within_tolerance_count'], 0)
        self.assertEqual(tm['status'], FAIL)

    def test_time_to_peak_error_strict_150_us(self):
        aligned = match(expected(1000, ttp=300), observed(1000, ttp=450))
        result = metrics(aligned, labels=[0])
        self.assertEqual(result['metrics']['time_to_peak']['status'], FAIL)
        self.assertEqual(result['metrics']['time_to_peak']['statistics']['max_absolute_us'], 150)
        aligned = match(expected(1000, ttp=300), observed(1000, ttp=449))
        self.assertEqual(metrics(aligned, labels=[0])['metrics']['time_to_peak']['status'], PASS)

    def test_signed_timing_errors_and_statistics(self):
        aligned = match(expected(1000, 2000, 3000), observed(975, 2000, 3030))
        tm = metrics(aligned)['metrics']['timestamp']['statistics']
        self.assertEqual(tm['min_signed_us'], -25)
        self.assertEqual(tm['max_signed_us'], 30)
        self.assertAlmostEqual(tm['mean_signed_us'], 5 / 3)
        self.assertEqual(tm['median_absolute_us'], 25)
        self.assertGreaterEqual(tm['p95_absolute_us'], 25)

    def test_uncertainty_beyond_target_is_inconclusive_not_fake_pass(self):
        alignment = {'mode': 'external_sync', 'source': 'independent scope pulse',
                     'uncertainty_us': 5, 'observed_minus_reference_us': 3000}
        result = metrics(match(expected(1000), observed(4098), alignment=alignment))
        tm = result['metrics']['timestamp']
        self.assertEqual(tm['max_possible_absolute_error_us'], 103)
        self.assertEqual(tm['best_case_max_absolute_error_us'], 93)
        self.assertEqual(tm['status'], NOT_AVAILABLE)
        self.assertIn('inconclusive', tm['reason'])

    def test_independent_sync_uncertainty_certifies_pass_when_small_enough(self):
        alignment = {'mode': 'external_sync', 'source': 'independent scope pulse',
                     'uncertainty_us': 4, 'observed_minus_reference_us': 3000}
        result = metrics(match(expected(1000), observed(4095), alignment=alignment))
        self.assertEqual(result['metrics']['timestamp']['status'], PASS)
        self.assertEqual(result['metrics']['timestamp']['max_possible_absolute_error_us'], 99)

    def test_known_clear_failure_despite_sync_uncertainty(self):
        alignment = {'mode': 'external_sync', 'source': 'independent scope pulse',
                     'uncertainty_us': 5, 'observed_minus_reference_us': 3000}
        result = metrics(match(expected(1000), observed(4110), alignment=alignment,
                               tolerance_us=150))
        self.assertEqual(result['metrics']['timestamp']['status'], FAIL)

    def test_time_to_peak_coverage_required(self):
        aligned = match(expected(100), observed(100))
        aligned['matches'][0]['time_to_peak_error_us'] = None
        result = metrics(aligned)
        self.assertEqual(result['metrics']['time_to_peak']['status'], NOT_AVAILABLE)

    def test_synthetic_shared_origin_is_not_hw_proof(self):
        out = metrics(match(expected(100), observed(100)), labels=[0])
        self.assertEqual(out['metrics']['timestamp']['status'], PASS)
        self.assertIn('offline synthetic', SYNC['source'])
        # The caller is still responsible for documenting test mode/hardware evidence.


class DataReductionTests(unittest.TestCase):
    def test_200_events_per_second_is_8x_fails(self):
        times = [100 + 1000 * i for i in range(200)]
        matched = match(expected(*times), observed(*times))
        result = metrics(matched, seconds=1, transport=traffic(2000))
        dr = result['metrics']['data_reduction']
        self.assertEqual(dr['baseline']['continuous_bit_rate_bps'], 160_000)
        self.assertEqual(dr['transmitted_line_bits_total'], 20_000)
        self.assertEqual(dr['operational_uart_bit_rate_bps'], 20_000)
        self.assertEqual(dr['data_reduction_ratio'], 8)
        self.assertEqual(dr['status'], FAIL)

    def test_exact_10x_passes_with_measured_capture(self):
        times = [100 + 1000 * i for i in range(160)]
        matched = match(expected(*times), observed(*times))
        res = metrics(matched, transport=traffic(1600))
        self.assertEqual(res['metrics']['data_reduction']['data_reduction_ratio'], 10)
        self.assertEqual(res['metrics']['data_reduction']['status'], PASS)

    def test_debug_bytes_separate_gross_vs_operational(self):
        times = [100 + 1000 * i for i in range(100)]
        matched = match(expected(*times), observed(*times))
        dr = metrics(matched, transport=traffic(2000, diagnostic=1000))['metrics']['data_reduction']
        self.assertEqual(dr['data_reduction_ratio'], 16)
        self.assertEqual(dr['gross_data_reduction_ratio'], 8)
        self.assertEqual(dr['diagnostic_bytes'], 1000)
        self.assertEqual(dr['status'], PASS)

    def test_status_packets_included_in_operational_rate(self):
        aligned = match(expected(1000), observed(1000))
        dr = metrics(aligned, transport=traffic(1000))['metrics']['data_reduction']
        self.assertEqual(dr['transmitted_bytes_total'], 1000)
        self.assertEqual(dr['operational_bytes_excluding_diagnostics'], 1000)

    def test_custom_sampling_baseline_and_duration(self):
        matched = match(expected(100), observed(100))
        dr = metrics(matched, seconds=2, transport=traffic(200), baseline={
            'sample_rate_hz': 20_000, 'sample_bits': 12, 'channels': 2,
        })['metrics']['data_reduction']
        self.assertEqual(dr['baseline']['continuous_bit_rate_bps'], 480_000)
        self.assertEqual(dr['operational_uart_bit_rate_bps'], 1000)
        self.assertEqual(dr['data_reduction_ratio'], 480)
        self.assertFalse(dr['baseline']['default_baseline'])

    def test_event_count_times_ten_is_only_estimate(self):
        matched = match(expected(100, 200), observed(100, 200))
        dr = metrics(matched)['metrics']['data_reduction']
        self.assertEqual(dr['estimated_minimum_neural_bytes_from_decoded_events'], 20)
        self.assertIsNone(dr['data_reduction_ratio'])
        self.assertEqual(dr['status'], NOT_AVAILABLE)

    def test_incomplete_measurement_source_diagnostics_and_missing_duration(self):
        matched = match(expected(100), observed(100))
        cases = [
            {'total_uart_bytes': 10, 'diagnostic_uart_bytes': 0, 'complete': False, 'source': 'scope'},
            {'total_uart_bytes': 10, 'diagnostic_uart_bytes': 0, 'complete': True},
            {'total_uart_bytes': 10, 'complete': True, 'source': 'scope'},
        ]
        for value in cases:
            with self.subTest(transport=value):
                self.assertEqual(metrics(matched, transport=value)['metrics']['data_reduction']['status'],
                                 NOT_AVAILABLE)
        self.assertEqual(metrics(matched, seconds=None, transport=traffic(10))[
            'metrics']['data_reduction']['status'], NOT_AVAILABLE)

    def test_inconsistent_total_bytes_refuses_acceptance(self):
        matched = match(expected(100, 200), observed(100, 200))
        dr = metrics(matched, transport=traffic(10))['metrics']['data_reduction']
        self.assertEqual(dr['status'], NOT_AVAILABLE)
        self.assertIn('less than', dr['reason'])

    def test_neural_bytes_cannot_be_reclassified_as_diagnostics(self):
        aligned = match(expected(100), observed(100))
        dr = metrics(aligned, transport=traffic(10, diagnostic=10))['metrics']['data_reduction']
        self.assertEqual(dr['status'], NOT_AVAILABLE)
        self.assertIn('cannot exclude', dr['reason'])

    def test_invalid_input_rejected_not_silently_coerced(self):
        matched = match(expected(100), observed(100))
        with self.assertRaises(ValueError):
            metrics(matched, seconds=-1)
        with self.assertRaises(ValueError):
            metrics(matched, transport=traffic(-10))
        with self.assertRaises(ValueError):
            metrics(matched, transport=traffic(100, diagnostic=101))
        with self.assertRaises(ValueError):
            metrics(matched, baseline={'sample_rate_hz': 10000, 'sample_bits': 16,
                                       'channels': 0})
        with self.assertRaises(ValueError):
            calculate_validation_metrics(matched, capture_complete='yes')


class EndToEndAndSummaryTests(unittest.TestCase):
    def test_real_neural_reference_integration_and_json_summary(self):
        pattern = {'words': [0, 0x10, 0x30, 0x10, 0] + [0] * 195}
        reference = generate_reference_events(pattern, sample_rate_hz=20_000,
                                              run_duration_ms=35, drain_duration_ms=4)
        accepted = reference['events']
        self.assertTrue(accepted)
        # Pretend the reference packets were received losslessly, with a common
        # synthetic FPGA epoch. This verifies module compatibility, not hardware.
        fpga = [{'channel': e['channel'], 'timestamp_us': e['timestamp_us'],
                 'peak': e['peak'], 'trough': e['trough'],
                 'time_to_peak_us': e['time_to_peak_us'],
                 'flags_mask': e['flags_mask']} for e in accepted]
        aligned = match(reference, fpga)
        output = metrics(aligned, labels=list(range(len(accepted))),
                         seconds=.039, transport=traffic(len(fpga) * 10))
        self.assertEqual(output['metrics']['detection']['f1'], 1)
        self.assertEqual(output['metrics']['peak_accuracy']['status'], PASS)
        self.assertEqual(output['metrics']['timestamp']['status'], PASS)
        self.assertEqual(output['metrics']['time_to_peak']['status'], PASS)
        self.assertEqual(output['metrics']['data_reduction']['status'], PASS)
        self.assertEqual(output['overall_status'], PASS)
        self.assertEqual(len(output['performance_summary']), 6)
        json.dumps(output, allow_nan=False)

    def test_mixed_pass_and_unavailable_yields_not_available_overall(self):
        aligned = match(expected(100), observed(100))
        out = metrics(aligned, labels=None, transport=traffic(10))
        self.assertEqual(out['overall_status'], NOT_AVAILABLE)
        self.assertEqual(out['metrics']['detection']['status'], PASS)


if __name__ == '__main__':
    unittest.main()
