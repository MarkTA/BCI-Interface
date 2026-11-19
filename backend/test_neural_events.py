"""Offline tests for James's AA 02 neural-event wire format and WebSocket batching."""
import asyncio
import unittest
import sys
import types
try:
    import serial
except ImportError:
    serial = types.ModuleType('serial')
    serial.SerialException = type('SerialException', (Exception,), {})
    serial.Serial = object
    serial_tools = types.ModuleType('serial.tools')
    list_ports = types.ModuleType('serial.tools.list_ports')
    list_ports.comports = lambda: []
    serial_tools.list_ports = list_ports
    serial.tools = serial_tools
    sys.modules.update({'serial': serial, 'serial.tools': serial_tools, 'serial.tools.list_ports': list_ports})

from serial_manager import SerialManager, decode_neural_event


def encode_event(channel=0, timestamp_us=1234, peak=4, trough=3,
                 time_to_peak_us=371, flags=0):
    value = ((channel & 3) << 62 | (timestamp_us & 0xffffff) << 38 |
             (peak & 7) << 35 | (trough & 7) << 32 |
             (time_to_peak_us & 0xfff) << 20 | (flags & 15) << 16)
    return b'\xaa\x02' + value.to_bytes(8, 'big')


class TestNeuralEventParser(unittest.TestCase):
    def test_from_real_fpga_log_timeout(self):
        p = bytes.fromhex('AA 02 2F A7 C7 24 17 34 00 00')
        event = decode_neural_event(p)
        self.assertEqual(event['channel'], 0)
        self.assertEqual(event['peak'], 4)
        self.assertEqual(event['trough'], 4)
        self.assertEqual(event['time_to_peak_us'], 371)
        self.assertTrue(event['flags']['timeout'])
        self.assertFalse(event['flags']['saturation'])
        self.assertEqual(event['flags_mask'], 4)
        self.assertEqual(event['raw_hex'], 'AA 02 2F A7 C7 24 17 34 00 00')

    def test_field_boundaries_and_flags(self):
        packet = encode_event(channel=2, timestamp_us=0xFFFFFF, peak=7, trough=6,
                              time_to_peak_us=4095, flags=15)
        result = decode_neural_event(packet)
        self.assertEqual(result['channel'], 2)
        self.assertEqual(result['timestamp_us'], 0xFFFFFF)
        self.assertEqual(result['peak'], 7)
        self.assertEqual(result['trough'], 6)
        self.assertEqual(result['time_to_peak_us'], 4095)
        self.assertTrue(all(result['flags'].values()))

    def test_bad_frame_rejected(self):
        for packet in (b'\xaa\x02', b'\xaa\x03'+bytes(8), bytes(10)):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                decode_neural_event(packet)

    def test_run_gating_counts_and_batched_emission(self):
        messages = []
        async def emit(message):
            messages.append(message)
        async def scenario():
            manager = SerialManager()
            manager.emit = emit
            packet = encode_event(peak=4, trough=2, flags=0xC)
            await manager.record_neural_event(packet)
            self.assertEqual(manager.neural_statistics()['received'], 0)
            manager.run_active = True
            for _ in range(100):
                await manager.record_neural_event(packet)
            await manager.flush_neural_events()
            self.assertEqual(manager.neural_statistics()['received'], 100)
            self.assertEqual(manager.neural_statistics()['timeouts'], 100)
            self.assertEqual(manager.neural_statistics()['saturations'], 100)
            self.assertEqual(manager.neural_statistics()['overlaps'], 0)
            count = sum(len(message['events']) for message in messages)
            self.assertEqual(count, 100)
            self.assertTrue(all(message['type'] == 'neural_events' for message in messages))
            self.assertLess(len(messages), 10)
            manager.run_active = False
            await manager.record_neural_event(packet)
            self.assertEqual(manager.neural_statistics()['received'], 100)
            manager.reset_diagnostics()
            self.assertEqual(manager.neural_statistics()['received'], 0)
            self.assertEqual(manager.neural_events_pending, [])
        asyncio.run(scenario())

if __name__ == '__main__':
    unittest.main()
