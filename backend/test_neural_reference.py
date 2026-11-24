"""Deterministic offline checks for neural_reference.py against event_fsm.sv."""
import unittest
from neural_reference import generate_reference_events
from waveforms import build_comparator_pattern

LIMITS = {f'P{i}': float(i * 10) for i in range(1, 5)} | \
         {f'N{i}': float(-i * 10) for i in range(1, 5)}


def simulate(words, *, us_per_sample=100, duration_ms=3.0, packet_done_cycles=1,
             drain_duration_ms=0, saturation_words=None, **kwargs):
    return generate_reference_events(
        {'words': words}, sample_rate_hz=1_000_000 / us_per_sample,
        run_duration_ms=duration_ms, packet_done_cycles=packet_done_cycles,
        drain_duration_ms=drain_duration_ms, saturation_words=saturation_words, **kwargs,
    )


class ReferenceEventTests(unittest.TestCase):
    def test_positive_then_negative_and_first_dominant_peak(self):
        # 100 us steps; P levels 1->3->1, then N levels 1->4.
        words = [0, 0x10, 0x70, 0x10, 0x00, 0x01, 0x0f] + [0] * 13
        result = simulate(words, duration_ms=2.0)
        self.assertEqual(result['event_count'], 1)
        event = result['events'][0]
        self.assertEqual(event['relative_onset_us'], 100)
        self.assertEqual((event['peak'], event['trough']), (3, 4))
        self.assertEqual(event['time_to_peak_us'], 500)
        self.assertEqual(event['flags_mask'], 0)
        self.assertEqual(event['timestamp_us'], 100)
        self.assertTrue(event['expected_packet_hex'].startswith('AA 02'))

    def test_no_event_and_no_false_end_flush(self):
        self.assertEqual(simulate([0], duration_ms=20)['events'], [])
        result = simulate([0xf0], duration_ms=1)
        self.assertEqual(result['events'], [])
        self.assertTrue(result['incomplete_event'])
        with_drain = simulate([0xf0], duration_ms=1, drain_duration_ms=1)
        self.assertEqual(with_drain['event_count'], 1)
        self.assertEqual(with_drain['events'][0]['peak'], 4)

    def test_quiet_return_resumes_tracking_without_dropping_event(self):
        # Idle 0, P1 at 100us, quiet 200..400us; P4 at 400us -> resumes
        # before F+500.02us quiet deadline; finally goes quiet at 500us.
        words = [0, 0x10, 0, 0, 0xf0, 0, 0, 0, 0, 0, 0]
        result = simulate(words, duration_ms=2)
        self.assertEqual(result['event_count'], 1)
        event = result['events'][0]
        self.assertEqual(event['peak'], 4)
        # State was S2 at 400us, so S1 first tracks P4 at clock 400us+20ns.
        self.assertEqual(event['time_to_peak_us'], 300)

    def test_quiet_boundary_25000_clocks_plus_one(self):
        # Each sample is one 50MHz clock, precision 20ns.
        # Active at edge0, inactive at edge1. QUIET entered at edge1.
        # Activity reappears at 25003, after packet generation at 25002
        # (quiet timer marks completion at 25001, consumed at 25002).
        samples = [0x10, 0] + [0] * 25001 + [0x10] + [0] * 1000
        result = simulate(samples, us_per_sample=0.02,
                          duration_ms=0.540, packet_done_cycles=1)
        self.assertGreaterEqual(result['event_count'], 1)
        self.assertAlmostEqual(result['events'][0]['relative_end_us'], 500.04, places=2)

    def test_timeout_sets_flag_and_forces_packet(self):
        result = simulate([0xf0], duration_ms=4)
        self.assertEqual(result['event_count'], 1)
        event = result['events'][0]
        self.assertTrue(event['flags']['timeout'])
        self.assertEqual(event['peak'], 4)
        self.assertAlmostEqual(event['relative_end_us'], 2500.02)

    def test_invalid_overlap_saturation_latched_and_cleared(self):
        # P2 without P1 is invalid; positive & negative overlap; sat pulses.
        words = [0, 0x20, 0x31, 0, 0, 0, 0, 0, 0, 0]
        sat = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0]
        result = simulate(words, duration_ms=2.5, saturation_words=sat)
        e = result['events'][0]
        self.assertEqual(e['peak'], 2)
        self.assertEqual(e['trough'], 1)
        self.assertEqual(e['flags_mask'], 11)  # saturation 8 | overlap 2 | invalid 1
        self.assertTrue(e['flags']['invalid_sequence'])
        self.assertTrue(e['flags']['overlap'])
        self.assertTrue(e['flags']['saturation'])

    def test_ttp_uses_earlier_peak_when_threshold_counts_tie(self):
        words = [0, 0x10, 0x30, 0, 0x01, 0x03, 0, 0, 0, 0, 0]
        event = simulate(words, duration_ms=2)['events'][0]
        self.assertEqual((event['peak'], event['trough']), (2, 2))
        self.assertEqual(event['time_to_peak_us'], 100)

    def test_refractory_gates_repeated_pulses(self):
        # One 1ms AD3 cycle, two short pulses separated by 100us.
        # First packet completes at ~700us, refractory lasts to ~800us;
        # second pulse (300us) occurs while tracking first; not independent.
        words = [0x10, 0, 0x10, 0, 0, 0, 0, 0, 0, 0]
        result = simulate(words, duration_ms=5)
        self.assertGreater(result['event_count'], 0)
        # A long packet transmit hold reduces the number of events dramatically.
        slow = simulate(words, duration_ms=5, packet_done_cycles=45_000)
        self.assertLess(slow['event_count'], result['event_count'])

    def test_timestamp_wrap_and_24_bit_field(self):
        event = simulate([0, 0x10, 0, 0, 0, 0, 0, 0, 0, 0],
                         duration_ms=2, initial_timestamp_us=(1 << 24) - 50)['events'][0]
        self.assertEqual(event['timestamp_us'], 50)

    def test_waveform_builder_integration(self):
        pattern = build_comparator_pattern(
            [0, 100, 0, -100, 0], 5, LIMITS, afe_gain=385, sample_count=1024,
        )
        result = generate_reference_events(
            pattern, sample_rate_hz=1024 * 1000 / 5,
            run_duration_ms=25, packet_done_cycles=1,
        )
        self.assertGreater(result['event_count'], 0)
        self.assertEqual(result['configuration']['samples_per_cycle'], 1024)
        self.assertEqual(result['configuration']['quiet_confirmation_us'], 500)

    def test_return_on_completion_edge_prevents_quiet_packet(self):
        # Threshold comes back exactly on the edge that would read the
        # registered quiet_complete bit: S2 prioritizes activity over quiet.
        # F = clock1, completion would be F+25001 = clock25002.
        words = [0x10, 0] + [0] * 25000 + [0x30] + [0] * 1000
        result = simulate(words, us_per_sample=0.02, duration_ms=0.540)
        # The first event stays open instead of being emitted at 500.04 us.
        self.assertEqual(result['event_count'], 0)
        self.assertTrue(result['incomplete_event'])

    def test_time_to_peak_rounded_at_50_clock_boundary(self):
        # First threshold begins at edge0; higher threshold at edge49 or50.
        # Verilog stores event_time_us + 1 only if the divider was at 49.
        at_49 = [0x10] * 49 + [0x30] + [0] * 26000
        at_50 = [0x10] * 50 + [0x30] + [0] * 26000
        e49 = simulate(at_49, us_per_sample=0.02,
                       duration_ms=0.54)['events'][0]
        e50 = simulate(at_50, us_per_sample=0.02,
                       duration_ms=0.54)['events'][0]
        self.assertEqual(e49['time_to_peak_us'], 0)
        self.assertEqual(e50['time_to_peak_us'], 1)

    def test_expected_packet_matches_documented_decoder_layout(self):
        event = simulate([0, 0x30, 0, 0, 0, 0, 0, 0, 0, 0],
                         duration_ms=2)['events'][0]
        packet = bytes.fromhex(event['expected_packet_hex'])
        self.assertEqual(packet[:2], b'\xaa\x02')
        payload = int.from_bytes(packet[2:], 'big')
        self.assertEqual((payload >> 62) & 3, event['channel'])
        self.assertEqual((payload >> 38) & 0xFFFFFF, event['timestamp_us'])
        self.assertEqual((payload >> 35) & 7, event['peak'])
        self.assertEqual((payload >> 32) & 7, event['trough'])
        self.assertEqual((payload >> 20) & 0xFFF, event['time_to_peak_us'])
        self.assertEqual((payload >> 16) & 15, event['flags_mask'])
        self.assertEqual(payload & 0xFFFF, 0)

    def test_unnatural_masks_and_arguments_rejected(self):
        with self.assertRaisesRegex(ValueError, 'eight-bit'):
            simulate([0x100])
        with self.assertRaisesRegex(ValueError, 'sample_rate_hz'):
            generate_reference_events({'words': [0]}, sample_rate_hz=0, run_duration_ms=2)
        with self.assertRaisesRegex(ValueError, 'packet_done_cycles'):
            simulate([0], packet_done_cycles=0)
        with self.assertRaisesRegex(ValueError, 'saturation_words'):
            simulate([0, 1], saturation_words=[1])


class ActiveTopLevelTransportTests(unittest.TestCase):
    """Transport modeled from the active bci_de10_uart_top -> FIFO path."""

    def test_default_mode_uses_fifo_not_uart_done_for_packet_done(self):
        from neural_reference import UART_PACKET_CLOCKS
        self.assertEqual(UART_PACKET_CLOCKS, 43_450)
        result = simulate([0x10, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                          duration_ms=2, packet_done_cycles=None)
        self.assertEqual(result['event_count'], 2)
        first = result['events'][0]
        self.assertAlmostEqual(first['packet_done_offset_us'] - first['relative_end_us'],
                               0.02, places=6)  # One FPGA clock to FIFO acceptance.
        self.assertAlmostEqual(first['uart_end_offset_us'] - first['uart_take_offset_us'],
                               869.0, places=6)  # 43,450 clocks / 50 MHz.
        self.assertEqual(result['configuration']['transport_mode'], 'fpga_fifo_uart')

    def test_low_event_rate_fifo_does_not_change_features(self):
        words = [0, 0x10, 0x30, 0] + [0] * 16
        fifo = simulate(words, duration_ms=5, packet_done_cycles=None)
        fixed = simulate(words, duration_ms=5, packet_done_cycles=1)
        self.assertEqual(fifo['event_count'], fixed['event_count'])
        for a, b in zip(fifo['events'], fixed['events']):
            for key in ('timestamp_us', 'peak', 'trough', 'time_to_peak_us',
                        'flags_mask', 'expected_packet_hex', 'packet_done_offset_us'):
                self.assertEqual(a[key], b[key])
        self.assertEqual(fifo['uart_max_fifo_depth'], 1)
        self.assertEqual(fifo['fifo_stall_us'], 0)

    def test_backpressure_stalls_fsm_when_eight_entry_fifo_is_full(self):
        # 620us period => 1613 potentially reportable events/sec. Shared UART
        # can drain only ~1151 packets/sec, so the eight-entry FIFO fills.
        words = [0x10] + [0] * 30
        result = simulate(words, us_per_sample=20, duration_ms=100,
                          packet_done_cycles=None, drain_duration_ms=3)
        self.assertEqual(result['uart_max_fifo_depth'], 8)
        self.assertGreater(result['fifo_stall_us'], 0)
        self.assertGreater(result['event_count'], result['uart_completed_count'])
        self.assertLessEqual(result['uart_fifo_pending_count'], 8)
        self.assertEqual(result['uart_dequeued_count'] + result['uart_fifo_pending_count'],
                         result['event_count'])

    def test_sync_latency_delays_first_input_by_two_fpga_clocks(self):
        basic = simulate([0x10, 0, 0, 0, 0, 0, 0, 0, 0, 0], duration_ms=2,
                         packet_done_cycles=None)
        synced = simulate([0x10, 0, 0, 0, 0, 0, 0, 0, 0, 0], duration_ms=2,
                          packet_done_cycles=None, sync_latency_clocks=2)
        self.assertAlmostEqual(synced['events'][0]['relative_onset_us'] -
                               basic['events'][0]['relative_onset_us'], 0.04)


if __name__ == '__main__':
    unittest.main()
