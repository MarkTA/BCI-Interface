"""Offline preview and UART trace packaging tests; no AD3 or FPGA required."""
import asyncio
import sys
import types
import unittest

try:
    import serial
except ImportError:
    # Only used in environments without pyserial, not in production.
    serial = types.ModuleType('serial')
    serial.SerialException = type('SerialException', (Exception,), {})
    serial.Serial = object
    serial_tools = types.ModuleType('serial.tools')
    list_ports = types.ModuleType('serial.tools.list_ports')
    list_ports.comports = lambda: []
    serial_tools.list_ports = list_ports
    serial.tools = serial_tools
    sys.modules.update({'serial': serial, 'serial.tools': serial_tools,
                        'serial.tools.list_ports': list_ports})

from fastapi.testclient import TestClient
import main
from serial_manager import SerialManager


class TestGpioSequencePreview(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.base = {
            'dataset': 'negative_then_positive',
            'thresholds_mv': [5, 10, 20, 40, -5, -10, -20, -40],
            'playback_speed': 0.25,
            'duration_s': 10,
        }

    def test_reference_sequence_negative_then_positive(self):
        result = self.client.post('/api/ad3/digital/comparators/preview', json=self.base)
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        trace = body['reference_states']
        self.assertEqual(len(trace), 17)
        self.assertEqual(trace[0], {'sample_index': 0, 'mask': 0})
        self.assertIn(0x0F, [row['mask'] for row in trace])
        self.assertIn(0xF0, [row['mask'] for row in trace])
        self.assertLess(next(i for i, row in enumerate(trace) if row['mask'] == 0x0F),
                        next(i for i, row in enumerate(trace) if row['mask'] == 0xF0))
        self.assertEqual(set(body['expected_edges_per_cycle'].values()), {2})

    def test_reference_sequence_positive_then_negative_reverses_order(self):
        body = self.client.post('/api/ad3/digital/comparators/preview',
                                json={**self.base, 'dataset': 'positive_then_negative'}).json()
        trace = [row['mask'] for row in body['reference_states']]
        # P4 never fires for an 80 µV positive lobe at 385×: P1–P3 do.
        self.assertIn(0x70, trace)
        self.assertNotIn(0xF0, trace)
        self.assertLess(trace.index(0x70), trace.index(0x0F))

    def test_no_spike_reference_remains_constant(self):
        body = self.client.post('/api/ad3/digital/comparators/preview',
                                json={**self.base, 'dataset': 'no_spike'}).json()
        self.assertEqual(body['reference_states'], [{'sample_index': 0, 'mask': 0}])

    def test_trace_sends_ordered_batched_reports(self):
        messages = []
        async def emit(data):
            messages.append(data)
        manager = SerialManager()
        manager.emit = emit
        manager.gpio_trace_pending.extend([[0, 0], [1, 0], [3, 0], [0, 15]])
        asyncio.run(manager.flush_gpio_trace())
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['type'], 'gpio_trace')
        self.assertEqual(messages[0]['states'], [[0, 0], [1, 0], [3, 0], [0, 15]])
        self.assertEqual(manager.gpio_trace_pending, [])
        manager.gpio_trace_pending.append([15, 0])
        manager.reset_diagnostics()
        self.assertEqual(manager.gpio_trace_pending, [])


if __name__ == '__main__':
    unittest.main()
