"""Offline integration checks for Phase 5 orchestration and run APIs."""
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from experiment_recording import ExperimentRecorder
from validation_orchestrator import validate_recorded_run
# Match the original project's hardware-free test arrangement.
import sys
import types
try:
    import serial
except ImportError:
    serial = types.ModuleType('serial')
    serial.SerialException = type('SerialException', (Exception,), {})
    serial.Serial = object
    tools = types.ModuleType('serial.tools')
    list_ports = types.ModuleType('serial.tools.list_ports')
    list_ports.comports = lambda: []
    tools.list_ports = list_ports
    serial.tools = tools
    sys.modules.update({'serial': serial, 'serial.tools': tools,
                        'serial.tools.list_ports': list_ports})
import main


class ValidationOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.recorder = ExperimentRecorder(self.workspace.name)
        self.run_id = self.recorder.start(port='COM6', baud=115200, gpio_debug=False)['run_id']
        self.sample_rate_hz = 204800.0
        self.words = bytes([0] * 256 + [0x10] * 256 + [0] * 512)
        self.csv = b'time_us,amplitude_uv\n0,0\n'
        self.recorder.begin_playback(
            configuration={'dataset': 'reference_test', 'requested_duration_s': 1},
            dataset_bytes=self.csv, comparator_words=self.words,
        )
        self.recorder.playback_started({'sample_rate_hz': self.sample_rate_hz,
                                        'sample_count': len(self.words),
                                        'cycle_duration_ms': 5.0})
        # Deterministic one second simulated host playback observation window.
        run = self.recorder._run
        run['playback']['start_confirmed_elapsed_us'] = 100_000
        run['playback']['stop_elapsed_us'] = 1_100_000
        run['playback']['status'] = 'stopped'
        run['playback']['host_playback_duration_s'] = 1.0
        directory = Path(self.workspace.name) / self.run_id
        (directory / 'fpga_events.jsonl').write_text('', encoding='utf-8')
        self.recorder.finish(reason='stopped')
        self.directory = directory

    def test_default_does_not_invent_alignment_or_hardware_pass(self):
        result = validate_recorded_run(self.recorder, self.run_id)
        self.assertEqual(result['input_snapshots']['sample_rate_hz'], self.sample_rate_hz)
        self.assertEqual(result['input_snapshots']['playback_duration_s_host_observed'], 1.0)
        self.assertGreater(result['reference']['event_count'], 0)
        self.assertEqual(result['matching']['status'], 'alignment_required')
        self.assertIsNone(result['matching']['counts']['tp'])
        self.assertFalse(result['validation']['capture_complete'])
        self.assertEqual(result['validation']['metrics']['detection']['status'], 'NOT_AVAILABLE')
        self.assertEqual(result['validation']['metrics']['data_reduction']['status'], 'NOT_AVAILABLE')
        self.assertEqual(json.loads((self.directory / 'validation.json').read_text())['run_id'], self.run_id)

    def test_event_anchor_is_exploratory_only(self):
        reference = validate_recorded_run(self.recorder, self.run_id, save=False)['reference']
        first = reference['events'][0]
        raw = int(first['timestamp_us'])
        self.assertGreaterEqual(raw, 0)
        event = {'host_rx_elapsed_us': 500_000, 'channel': 0,
                 'timestamp_us': raw + 12, 'peak': first['peak'],
                 'trough': first['trough'], 'time_to_peak_us': first['time_to_peak_us'],
                 'flags_mask': first['flags_mask']}
        (self.directory / 'fpga_events.jsonl').write_text(json.dumps(event) + '\n')
        result = validate_recorded_run(self.recorder, self.run_id, alignment={
            'mode': 'event_anchor', 'reference_index': 0, 'observed_index': 0})
        self.assertEqual(result['matching']['status'], 'exploratory')
        self.assertGreaterEqual(result['matching']['counts']['tp'], 1)
        self.assertEqual(result['validation']['metrics']['detection']['status'], 'NOT_AVAILABLE')
        self.assertEqual(result['validation']['metrics']['timestamp']['status'], 'NOT_AVAILABLE')

    def test_sha256_mismatch_is_rejected_without_overwrite(self):
        (self.directory / 'validation.json').write_text('old')
        (self.directory / 'comparator_pattern.bin').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            validate_recorded_run(self.recorder, self.run_id)
        self.assertEqual((self.directory / 'validation.json').read_text(), 'old')

    def test_requires_independent_capture_verification_evidence(self):
        with self.assertRaisesRegex(ValueError, 'verification evidence'):
            validate_recorded_run(self.recorder, self.run_id, full_event_capture_verified=True)

    def test_excludes_pre_playback_events_and_does_not_assume_complete_rx(self):
        early = {'host_rx_elapsed_us': 1, 'channel': 0, 'timestamp_us': 20}
        (self.directory / 'fpga_events.jsonl').write_text(json.dumps(early) + '\n')
        result = validate_recorded_run(self.recorder, self.run_id)
        self.assertEqual(result['input_snapshots']['pre_playback_events_excluded'], 1)
        self.assertEqual(result['matching']['counts']['observed'], 0)

    def test_bad_jsonl_is_rejected(self):
        (self.directory / 'fpga_events.jsonl').write_text('not json\n')
        with self.assertRaisesRegex(ValueError, 'Malformed fpga_events'):
            validate_recorded_run(self.recorder, self.run_id)

    def test_api_validate_and_fetch(self):
        with patch.object(main, 'experiment_recorder', self.recorder):
            client = TestClient(main.app)
            post = client.post(f'/api/runs/{self.run_id}/validate', json={})
            self.assertEqual(post.status_code, 200, post.text)
            self.assertEqual(post.json()['validation']['overall_status'], 'NOT_AVAILABLE')
            get = client.get(f'/api/runs/{self.run_id}/validation')
            self.assertEqual(get.status_code, 200)
            self.assertEqual(get.json()['run_id'], self.run_id)
            zipped = client.get(f'/api/runs/{self.run_id}/export')
            self.assertEqual(zipped.status_code, 200)
            self.assertIn(b'validation.json', zipped.content)

    def test_api_rejects_bad_run(self):
        with patch.object(main, 'experiment_recorder', self.recorder):
            client = TestClient(main.app)
            missing = '0' * 32
            self.assertEqual(client.post(f'/api/runs/{missing}/validate', json={}).status_code, 404)
            self.assertEqual(client.get(f'/api/runs/{missing}/validation').status_code, 404)


if __name__ == '__main__':
    unittest.main()
