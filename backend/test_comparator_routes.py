"""No-AD3 integration tests for dataset-to-comparator REST endpoints."""
import unittest
from unittest.mock import patch
# In the project's normal venv, pyserial comes from requirements.txt.
# The CI/no-device environment may lack it; stub only for REST tests.
import sys
import types
try:
    import serial
except ImportError:
    serial = types.ModuleType("serial")
    serial.SerialException = type("SerialException", (Exception,), {})
    serial.Serial = object
    tools = types.ModuleType("serial.tools")
    list_ports = types.ModuleType("serial.tools.list_ports")
    list_ports.comports = lambda: []
    tools.list_ports = list_ports
    serial.tools = tools
    sys.modules.update({"serial": serial, "serial.tools": tools,
                        "serial.tools.list_ports": list_ports})
from fastapi.testclient import TestClient

import main


class TestComparatorRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.base = {
            "dataset": "positive_then_negative",
            "thresholds_mv": [5, 10, 20, 40, -5, -10, -20, -40],
            "playback_speed": 0.25,
            "duration_s": 8,
        }

    def test_kenny_csv_preview_uses_actual_samples(self):
        r = self.client.post('/api/ad3/digital/comparators/preview', json=self.base)
        self.assertEqual(r.status_code, 200, r.text)
        x = r.json()
        self.assertEqual(x['dataset'], self.base['dataset'])
        self.assertEqual(x['source_duration_ms'], 5)
        self.assertEqual(x['cycle_duration_ms'], 20)
        self.assertEqual(x['sample_count'], 1024)
        self.assertEqual(x['expected_edges_per_second'], 700)  # P4 below threshold at nominal gain
        self.assertIsNone(x['warning'])
        self.assertEqual(x['expected_edges_per_cycle']['P1'], 2)
        self.assertEqual(x['expected_edges_per_cycle']['N4'], 2)

    def test_csv_peaks_are_distinct(self):
        large = self.client.post('/api/ad3/digital/comparators/preview',
                                 json={**self.base, 'dataset': 'large_spike'})
        small = self.client.post('/api/ad3/digital/comparators/preview',
                                 json={**self.base, 'dataset': 'small_spike'})
        self.assertEqual(large.status_code, 200, large.text)
        self.assertEqual(small.status_code, 200, small.text)
        self.assertAlmostEqual(large.json()['source_peak_uv'], 392)
        self.assertAlmostEqual(small.json()['source_peak_uv'], 51)
        self.assertAlmostEqual(large.json()['afe_peak_mv'], 392 * 385 / 1000)
        self.assertAlmostEqual(small.json()['afe_peak_mv'], 51 * 385 / 1000)
        self.assertGreater(large.json()['afe_peak_mv'], small.json()['afe_peak_mv'])

    def test_no_spike_is_valid_negative_control(self):
        r = self.client.post('/api/ad3/digital/comparators/preview', json={**self.base, 'dataset': 'no_spike'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['expected_edges_per_second'], 0)

    def test_full_speed_warns_and_is_blocked_when_gpio_debug_enabled(self):
        req = {**self.base, 'playback_speed': 1}
        req['gpio_debug_enabled'] = True
        r = self.client.post('/api/ad3/digital/comparators/preview', json=req)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['expected_edges_per_second'], 2800)
        self.assertIn('throughput', r.json()['warning'])
        with patch.object(main.serial_manager, 'gpio_debug_enabled', req['gpio_debug_enabled']), \
             patch.object(main.serial_manager, 'run_active', True), \
             patch.object(main.serial_manager, 'mock', False), \
             patch.object(main.serial_manager, 'device', object()):
            r = self.client.post('/api/ad3/digital/comparators', json=req)
        self.assertEqual(r.status_code, 400)
        self.assertIn('capacity', r.json()['detail'])

    def test_full_speed_allowed_when_gpio_debug_disabled(self):
        req = {**self.base, 'playback_speed': 1.0, 'gpio_debug_enabled': False}
        preview = self.client.post('/api/ad3/digital/comparators/preview', json=req)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertIsNone(preview.json()['warning'])
        self.assertEqual(preview.json()['cycle_duration_ms'], 5)
        fake_info = {
            'cycle_duration_ms': 5.00001,
            'sample_rate_hz': 1024 * 1000 / 5.00001,
            'sample_count': 1024,
            'expected_edges_per_cycle': {'N1': 2},
            'active': True, 'mode': 'comparators',
        }
        with patch.object(main.serial_manager, 'gpio_debug_enabled', req['gpio_debug_enabled']), \
             patch.object(main.serial_manager, 'run_active', True), \
             patch.object(main.serial_manager, 'mock', False), \
             patch.object(main.serial_manager, 'device', object()), \
             patch.object(main.ad3_manager, 'status', return_value={'active': False}), \
             patch.object(main.ad3_manager, 'start', return_value=fake_info) as start:
            response = self.client.post('/api/ad3/digital/comparators', json=req)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['playback_speed'], 1.0)
        self.assertEqual(start.call_args.kwargs['duration_ms'], 5)

    def test_start_rejects_without_physical_uart(self):
        r = self.client.post('/api/ad3/digital/comparators', json=self.base)
        self.assertEqual(r.status_code, 400)
        self.assertIn('FPGA UART', r.json()['detail'])

    def test_start_passes_signed_thresholds_and_full_dataset(self):
        fake_info = {
            'cycle_duration_ms': 20.0001,
            'sample_rate_hz': 1024 * 1000 / 20.0001,
            'sample_count': 1024, 'expected_edges_per_cycle': {'N1': 2},
            'active': True, 'mode': 'comparators',
        }
        with patch.object(main.serial_manager, 'gpio_debug_enabled', False), \
             patch.object(main.serial_manager, 'run_active', True), \
             patch.object(main.serial_manager, 'mock', False), \
             patch.object(main.serial_manager, 'device', object()), \
             patch.object(main.ad3_manager, 'status', return_value={'active': False}), \
             patch.object(main.ad3_manager, 'start', return_value=fake_info) as start:
            r = self.client.post('/api/ad3/digital/comparators', json=self.base)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['dataset'], 'positive_then_negative')
        self.assertEqual(start.call_args.args[0], 'comparators')
        self.assertEqual(start.call_args.kwargs['thresholds_mv']['P1'], 5)
        self.assertEqual(start.call_args.kwargs['thresholds_mv']['N1'], -5)
        self.assertEqual(len(start.call_args.kwargs['sample_values_uv']), 5000)
        self.assertEqual(start.call_args.kwargs['duration_ms'], 20)

    def test_wrong_sign_rejected(self):
        req = {**self.base, 'thresholds_mv': [-5, 10, 20, 40, -5, -10, -20, -40]}
        r = self.client.post('/api/ad3/digital/comparators/preview', json=req)
        self.assertEqual(r.status_code, 422)
        self.assertIn('positive P', r.json()['detail'])


if __name__ == '__main__':
    unittest.main()
