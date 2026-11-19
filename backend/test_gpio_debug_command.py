"""Software-only tests for the versioned UART GPIO command and ACK."""
import asyncio
import sys
import types
import unittest

try:
    import serial
except ImportError:
    serial = types.ModuleType('serial')
    serial.SerialException = type('SerialException', (Exception,), {})
    serial.Serial = object
    sys.modules['serial'] = serial

from fpga_protocol import encode_gpio_debug, decode_gpio_debug_ack, xor_checksum, encode_threshold
from serial_manager import SerialManager


class ProtocolTests(unittest.TestCase):
    def test_enable_disable(self):
        self.assertEqual(encode_gpio_debug(0x2A, True), bytes.fromhex('AA 04 2A 00 00 01 2F'))
        self.assertEqual(encode_gpio_debug(0x2B, False), bytes.fromhex('AA 04 2B 00 00 00 2F'))
        self.assertTrue(decode_gpio_debug_ack(bytes.fromhex('AA 84 2A 01 AF'), 0x2A, True))
        self.assertFalse(decode_gpio_debug_ack(bytes.fromhex('AA 84 2B 00 AF'), 0x2B, False))

    def test_reject_corrupted_ack_or_wrong_sequence(self):
        for raw, seq, mode in (
            ('AA 84 2A 01 AE', 0x2A, True),
            ('AA 84 2B 01 AF', 0x2A, True),
            ('AA 84 2A 00 AE', 0x2A, True),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_gpio_debug_ack(bytes.fromhex(raw), seq, mode)

    def test_threshold_packet_unchanged(self):
        expected = bytes.fromhex('AA 01 07 03 12 34 23')
        self.assertEqual(encode_threshold(7, 3, 0x1234), expected)

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            encode_gpio_debug(256, True)
        with self.assertRaises(ValueError):
            encode_gpio_debug(5, 1)


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ack_required_before_mode_changes(self):
        manager = SerialManager()
        sent = []
        class FakeSerial:
            def write(self, packet):
                sent.append(packet)
                seq = packet[2]
                mode = packet[5]
                body = bytes((0x84, seq, mode))
                ack = b'\xAA' + body + bytes((xor_checksum(body),))
                loop.call_soon_threadsafe(manager.pending_debug.set_result, ack)
        loop = asyncio.get_running_loop()
        manager.device = FakeSerial()
        await manager.set_gpio_debug(True)
        self.assertTrue(manager.gpio_debug_enabled)
        await manager.set_gpio_debug(False)
        self.assertFalse(manager.gpio_debug_enabled)
        self.assertEqual(sent[0][1], 0x04)
        self.assertEqual(sent[1][1], 0x04)

    async def test_reject_mode_change_during_run(self):
        manager = SerialManager()
        manager.device = object()
        manager.run_active = True
        with self.assertRaises(RuntimeError):
            await manager.set_gpio_debug(True)


if __name__ == '__main__':
    unittest.main()
