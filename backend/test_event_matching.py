"""Offline Phase-2 tests for event_matching.py; requires no hardware."""

import json
import unittest

from event_matching import match_reference_to_fpga, TIMESTAMP_MODULUS_US
from neural_reference import generate_reference_events


SYNC = {'mode': 'shared_origin', 'source': 'synthetic replay, common timestamp origin',
        'uncertainty_us': 0.0}


def expected(*times, channel=0, **features):
    return [{'channel': channel, 'relative_onset_us': t, 'timestamp_us': int(t) % TIMESTAMP_MODULUS_US,
             **features} for t in times]


def observed(*times, channel=0, **features):
    return [{'channel': channel, 'timestamp_us': int(t) % TIMESTAMP_MODULUS_US,
             **features} for t in times]


class EventMatchingTests(unittest.TestCase):
    def test_unsynchronized_run_withholds_tp_fp_fn_and_no_misleading_misses(self):
        result = match_reference_to_fpga(expected(100, 200), observed(2000100, 2000200))
        self.assertEqual(result['status'], 'alignment_required')
        self.assertEqual(result['counts']['expected'], 2)
        self.assertEqual(result['counts']['observed'], 2)
        self.assertIsNone(result['counts']['tp'])
        self.assertIsNone(result['counts']['fn'])
        self.assertEqual(result['matches'], [])
        self.assertFalse(result['absolute_timestamp_accuracy_available'])

    def test_external_offset_matching_with_missing_extra_and_features(self):
        ref = expected(100, 1000, 2000, peak=4, trough=2, time_to_peak_us=200, flags_mask=0)
        fpga = observed(5000100, 5002008, 5003000,
                        peak=4, trough=2, time_to_peak_us=200, flags_mask=0)
        # The first two observations correspond to reference indices 0,2.
        # 5003000 is an extra detection. Note offset is independently specified.
        aligned = {'mode': 'external_sync', 'observed_minus_reference_us': 5_000_000,
                   'uncertainty_us': 3.0, 'source': 'independent scope trigger measurement'}
        result = match_reference_to_fpga(ref, fpga, alignment=aligned)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['counts'], dict(expected=3, observed=3, tp=2, fp=1, fn=1))
        self.assertEqual([(m['reference_index'], m['observed_index']) for m in result['matches']],
                         [(0, 0), (2, 1)])
        self.assertEqual([m['timestamp_error_us'] for m in result['matches']], [0.0, 8.0])
        self.assertEqual(result['false_negatives'][0]['reference_index'], 1)
        self.assertEqual(result['false_positives'][0]['observed_index'], 2)
        self.assertTrue(result['absolute_timestamp_accuracy_available'])
        self.assertEqual(result['alignment']['uncertainty_us'], 3.0)

    def test_100_us_boundary_inclusive(self):
        result = match_reference_to_fpga(expected(1000), observed(1100), alignment=SYNC)
        self.assertEqual(result['counts']['tp'], 1)
        self.assertEqual(result['matches'][0]['timestamp_error_us'], 100.0)
        beyond = match_reference_to_fpga(expected(1000), observed(1101), alignment=SYNC)
        self.assertEqual(beyond['counts']['tp'], 0)
        self.assertEqual((beyond['counts']['fp'], beyond['counts']['fn']), (1, 1))

    def test_one_observation_cannot_match_twice_prefers_closest_match(self):
        result = match_reference_to_fpga(expected(0, 100), observed(95),
                                         alignment=SYNC, tolerance_us=100)
        self.assertEqual(result['counts'], dict(expected=2, observed=1, tp=1, fp=0, fn=1))
        self.assertEqual(result['matches'][0]['reference_index'], 1)
        self.assertEqual(result['matches'][0]['timestamp_error_us'], -5.0)

    def test_optimal_cardinality_not_just_nearest_first(self):
        # Matching expected 50->obs 45 instead of expected 0->45 would make
        # expected 0 impossible to pair with obs -40. Optimal has 2 pairs.
        ref = expected(0, 50)
        obs = observed(45, 60)  # different scenario: both can be paired
        result = match_reference_to_fpga(ref, obs, alignment=SYNC, tolerance_us=50)
        self.assertEqual(result['counts']['tp'], 2)
        self.assertEqual([(x['reference_index'], x['observed_index']) for x in result['matches']],
                         [(0, 0), (1, 1)])

    def test_duplicate_events_leave_one_false_positive(self):
        result = match_reference_to_fpga(expected(1000), observed(1000, 1000), alignment=SYNC)
        self.assertEqual((result['counts']['tp'], result['counts']['fp'], result['counts']['fn']), (1, 1, 0))
        self.assertEqual(result['false_positives'][0]['observed_index'], 1)

    def test_multiple_channels_never_cross_match(self):
        ref = expected(100, channel=0) + expected(200, channel=1)
        fpga = observed(100, channel=1) + observed(200, channel=0)
        result = match_reference_to_fpga(ref, fpga, alignment=SYNC, tolerance_us=10)
        self.assertEqual((result['counts']['tp'], result['counts']['fp'], result['counts']['fn']), (0, 2, 2))

    def test_wraparound_is_unwrapped_in_packet_order_across_channels(self):
        modulo = TIMESTAMP_MODULUS_US
        offset = modulo - 110
        ref = expected(10, channel=0) + expected(140, channel=1)
        fpga = [dict(channel=0, timestamp_us=modulo - 100),
                dict(channel=1, timestamp_us=30)]
        result = match_reference_to_fpga(
            ref, fpga,
            alignment={'mode': 'external_sync', 'source': 'hardware sync pulse',
                       'observed_minus_reference_us': offset, 'uncertainty_us': 2},
        )
        self.assertEqual(result['counts']['tp'], 2)
        self.assertEqual(result['matches'][1]['observed_unwrapped_us'], modulo + 30)
        self.assertEqual([m['timestamp_error_us'] for m in result['matches']], [0.0, 0.0])

    def test_nonzero_timestamp_epoch_can_be_supplied_by_independent_measurement(self):
        modulo = TIMESTAMP_MODULUS_US
        result = match_reference_to_fpga(
            expected(100), observed(100),
            alignment={'mode': 'external_sync', 'source': 'known FPGA tick epoch',
                       'observed_minus_reference_us': modulo,
                       'uncertainty_us': 1, 'initial_wrap_count': 1},
        )
        self.assertEqual(result['counts']['tp'], 1)
        self.assertEqual(result['matches'][0]['observed_unwrapped_us'], float(modulo + 100))

    def test_prefers_preunwrapped_timestamp_if_available(self):
        modulo = TIMESTAMP_MODULUS_US
        fpga = [{'channel': 0, 'timestamp_us': 100, 'unwrapped_timestamp_us': modulo + 100}]
        aligned = {'mode': 'external_sync', 'source': 'external epoch counter',
                   'uncertainty_us': 1, 'observed_minus_reference_us': modulo}
        result = match_reference_to_fpga(expected(100), fpga, alignment=aligned)
        self.assertEqual(result['counts']['tp'], 1)

    def test_rejects_small_backward_timestamp_jump_as_possible_reset(self):
        with self.assertRaisesRegex(ValueError, 'moves backward'):
            match_reference_to_fpga(expected(10, 20), observed(500, 490), alignment=SYNC)

    def test_event_anchor_exploratory_only_even_with_perfect_matches(self):
        result = match_reference_to_fpga(
            expected(100, 200), observed(9000100, 9000200),
            alignment={'mode': 'event_anchor', 'reference_index': 0, 'observed_index': 0},
        )
        self.assertEqual(result['status'], 'exploratory')
        self.assertEqual(result['counts']['tp'], 2)
        self.assertIsNone(result['matches'][0]['timestamp_error_us'])
        self.assertFalse(result['absolute_timestamp_accuracy_available'])
        self.assertTrue(result['warnings'])

    def test_wrong_event_anchor_channel_rejected(self):
        with self.assertRaisesRegex(ValueError, 'same neural channel'):
            match_reference_to_fpga(expected(100, channel=0), observed(300, channel=1),
                                    alignment={'mode': 'event_anchor', 'reference_index': 0,
                                               'observed_index': 0})

    def test_peak_trough_ttp_and_flags_are_comparisons_not_matching_criteria(self):
        ref = expected(100, peak=4, trough=3, time_to_peak_us=150, flags_mask=0)
        fpga = observed(102, peak=1, trough=3, time_to_peak_us=155, flags_mask=4)
        result = match_reference_to_fpga(ref, fpga, alignment=SYNC)
        match = result['matches'][0]
        self.assertEqual(result['counts']['tp'], 1)
        self.assertFalse(match['peak_match'])
        self.assertTrue(match['trough_match'])
        self.assertEqual(match['time_to_peak_error_us'], 5)
        self.assertFalse(match['flags_match'])

    def test_empty_datasets_and_no_event_baseline(self):
        result = match_reference_to_fpga([], [], alignment=SYNC)
        self.assertEqual(result['counts'], dict(expected=0, observed=0, tp=0, fp=0, fn=0))
        result = match_reference_to_fpga([], observed(1000), alignment=SYNC)
        self.assertEqual(result['counts'], dict(expected=0, observed=1, tp=0, fp=1, fn=0))

    def test_invalid_args_and_unreliable_alignments_rejected(self):
        with self.assertRaisesRegex(ValueError, 'relative_onset_us'):
            match_reference_to_fpga([{'channel': 0, 'timestamp_us': 30}], observed(30), alignment=SYNC)
        with self.assertRaisesRegex(ValueError, 'requires a documented'):
            match_reference_to_fpga(expected(30), observed(30),
                                    alignment={'mode': 'shared_origin', 'uncertainty_us': 0})
        with self.assertRaisesRegex(ValueError, 'uncertainty_us'):
            match_reference_to_fpga(expected(30), observed(30),
                                    alignment={'mode': 'shared_origin', 'source': 'test'})
        with self.assertRaisesRegex(ValueError, 'unwrapped timestamp is inconsistent'):
            match_reference_to_fpga(expected(30),
                                    [{'channel': 0, 'timestamp_us': 30, 'unwrapped_timestamp_us': 31}],
                                    alignment=SYNC)
        with self.assertRaisesRegex(ValueError, 'tolerance_us'):
            match_reference_to_fpga(expected(100), observed(100), alignment=SYNC,
                                    tolerance_us=float('nan'))
        with self.assertRaisesRegex(ValueError, 'candidate event pairs'):
            match_reference_to_fpga(expected(0, 1, 2), observed(0, 1, 2),
                                    alignment=SYNC, max_candidate_pairs=4)

    def test_json_serializable_and_unmodified_input(self):
        ref = expected(100)
        obs = observed(100)
        result = match_reference_to_fpga(ref, obs, alignment=SYNC)
        json.dumps(result, allow_nan=False)
        self.assertEqual(ref[0]['relative_onset_us'], 100)
        self.assertEqual(obs[0]['timestamp_us'], 100)

    def test_full_reference_model_packets_predict_self_consistent_matches(self):
        # Exercise an actual Phase-1.1 reference model result with packet
        # fields extracted from its expected 64-bit AA 02 frame.
        source = generate_reference_events(
            {'words': [0, 0x10, 0x30] + [0] * 17},
            sample_rate_hz=20_000, run_duration_ms=6, drain_duration_ms=2,
        )
        self.assertGreater(source['event_count'], 1)
        captured = []
        for event in source['events']:
            if event['uart_end_offset_us'] is None or event['uart_end_offset_us'] >= 8_000:
                continue
            packet = bytes.fromhex(event['expected_packet_hex'])
            payload = int.from_bytes(packet[2:], 'big')
            captured.append({
                'channel': (payload >> 62) & 3,
                'timestamp_us': (payload >> 38) & 0xFFFFFF,
                'peak': (payload >> 35) & 7,
                'trough': (payload >> 32) & 7,
                'time_to_peak_us': (payload >> 20) & 0xFFF,
                'flags_mask': (payload >> 16) & 15,
            })
        # Match only packets actually completed on UART during the capture;
        # the model may hold an unfinished packet at the trailing boundary.
        expected_transmitted = [e for e in source['events']
                                if e['uart_end_offset_us'] is not None
                                and e['uart_end_offset_us'] < 8_000]
        result = match_reference_to_fpga(expected_transmitted, captured, alignment=SYNC)
        self.assertEqual(result['counts']['tp'], len(captured))
        self.assertEqual(result['counts']['fp'], 0)
        self.assertEqual(result['counts']['fn'], 0)
        self.assertTrue(all(m['peak_match'] and m['trough_match']
                            and m['time_to_peak_error_us'] == 0 for m in result['matches']))


if __name__ == '__main__':
    unittest.main()
