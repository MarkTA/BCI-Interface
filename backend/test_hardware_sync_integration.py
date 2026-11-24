"""Proves hardware-marker alignment takes precedence over the UI's old 0/0 event anchor."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from experiment_recording import ExperimentRecorder
from validation_orchestrator import validate_recorded_run


class HardwareSyncIntegrationTests(unittest.TestCase):
    def test_hardware_marker_replaces_frontend_auto_anchor(self):
        with tempfile.TemporaryDirectory() as dirname:
            recorder = ExperimentRecorder(dirname)
            run_id = recorder.start(port='COM6', baud=115200, gpio_debug=False)['run_id']
            words = bytes([0] * 256 + [0x10] * 256 + [0] * 512)
            recorder.begin_playback(configuration={'dataset': 'reference_test', 'requested_duration_s': 1},
                                    dataset_bytes=b'time_us,amplitude_uv\n0,0\n', comparator_words=words)
            recorder.playback_started({'sample_rate_hz': 204800.0, 'sample_count': 1024,
                                       'cycle_duration_ms': 5.0})
            run = recorder._run
            run['playback']['start_confirmed_elapsed_us'] = 100_000
            run['playback']['stop_elapsed_us'] = 1_100_000
            run['playback']['status'] = 'stopped'
            run['playback']['host_playback_duration_s'] = 1.0
            recorder.finish(reason='stopped')
            path = Path(dirname) / run_id
            raw_events = [{"host_rx_elapsed_us": 500_000, "channel": 0,
                           "timestamp_us": 1300, "peak": 1, "trough": 0, "time_to_peak_us": 0,
                           "flags_mask": 0}]
            (path / 'fpga_events.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in raw_events))
            markers = [
                {'pattern_edge_index': 0, 'timestamp_us': 1000},
                {'pattern_edge_index': 64, 'timestamp_us': 321000},
                {'pattern_edge_index': 128, 'timestamp_us': 641000},
            ]
            (path / 'fpga_sync_markers.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in markers))
            result = validate_recorded_run(recorder, run_id,
                alignment={'mode': 'event_anchor', 'reference_index': 0, 'observed_index': 0}, save=False)
            self.assertEqual(result['hardware_sync']['status'], 'ALIGNED')
            self.assertEqual(result['matching']['alignment']['mode'], 'external_sync')
            self.assertEqual(result['matching']['alignment']['observed_minus_reference_us'], 1000)

    def test_marker_missing_index_zero_is_not_certified(self):
        with self.assertRaisesRegex(ValueError, 'marker missing'):
            from sync_protocol import derive_hardware_alignment
            derive_hardware_alignment([{'pattern_edge_index': 64, 'timestamp_us': 321000}], 5000)
