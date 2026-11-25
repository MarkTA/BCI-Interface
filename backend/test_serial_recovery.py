"""Transport-loss regression tests without physical FTDI hardware."""
import asyncio
import sys
import types
import unittest
from unittest.mock import Mock, patch

try:
    import serial
except ImportError:
    serial = types.ModuleType('serial')
    serial.SerialException = type('SerialException', (Exception,), {})
    serial.Serial = object
    sys.modules['serial'] = serial

from serial_manager import SerialManager


class SerialRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_failure_reports_fault_and_rejects_all_pending_commands(self):
        manager = SerialManager()
        manager.device = Mock()
        manager.device.read.side_effect = serial.SerialException('USB removed')
        manager.run_active = True
        messages = []
        async def emit(message):
            messages.append(message)
        manager.emit = emit
        pending = [asyncio.get_running_loop().create_future() for _ in range(4)]
        (manager.pending, manager.pending_debug, manager.pending_sync_arm,
         manager.pending_capture) = pending
        with patch('serial_manager.experiment_recorder.mark_incomplete') as incomplete:
            await manager._reader()
            incomplete.assert_called_once()
        self.assertTrue(manager.reader_failed)
        self.assertEqual(messages[0]['type'], 'serial_fault')
        self.assertIn('USB removed', messages[0]['message'])
        for future in pending:
            with self.assertRaisesRegex(ConnectionError, 'USB removed'):
                await future

    async def test_idle_fault_does_not_mark_a_recording_incomplete(self):
        manager = SerialManager()
        manager.device = Mock()
        manager.device.read.side_effect = OSError('USB removed')
        with patch('serial_manager.experiment_recorder.mark_incomplete') as incomplete:
            await manager._reader()
            incomplete.assert_not_called()
        self.assertTrue(manager.reader_failed)

    async def test_disconnect_releases_port_even_if_driver_close_fails(self):
        manager = SerialManager()
        owner = object()
        manager.owner = owner
        manager.device = Mock()
        manager.device.close.side_effect = OSError('USB removed')
        await manager.disconnect(owner)
        self.assertIsNone(manager.owner)
        self.assertIsNone(manager.device)
        await manager.connect(object(), '', 115200, True, None)
        self.assertFalse(manager.reader_failed)
        await manager.disconnect(manager.owner)
