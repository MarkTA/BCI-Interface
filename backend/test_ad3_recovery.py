"""SDK failure recovery tests; no physical instrument is needed."""
import unittest
from unittest.mock import Mock, patch
from ad3_manager import AD3Manager
from waveforms import DWFError


class TestAD3Recovery(unittest.TestCase):
    def setUp(self):
        self.manager = AD3Manager()
        self.device = Mock()
        self.manager._device = self.device
        self.manager._status = {'active': True, 'mode': 'comparators'}
        self.manager.on_comparator_failed = Mock()
        self.manager.on_comparator_stopped = Mock()
        self.addCleanup(self.manager._cancel_timer)

    def test_normal_stop_retains_handle_and_drives_low(self):
        status = self.manager.stop()
        self.assertEqual(status, {'active': False, 'mode': 'idle', 'outputs_low': True})
        self.assertIs(self.manager._device, self.device)
        self.device.close.assert_not_called()
        self.manager.on_comparator_stopped.assert_called_once_with('manual')

    def test_failed_stop_releases_stale_handle_and_allows_retry(self):
        self.device.stop_digital.side_effect = DWFError('Digital Out config failed')
        self.device.close.side_effect = DWFError('Close configure failed')
        with self.assertRaisesRegex(DWFError, 'Digital Out config failed'):
            self.manager.stop()
        status = self.manager.status()
        self.assertFalse(status['active'])
        self.assertFalse(status['outputs_low'])
        self.assertEqual(status['mode'], 'recovery_required')
        self.assertIsNone(self.manager._device)
        self.manager.on_comparator_failed.assert_called_once()
        self.manager.on_comparator_stopped.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'recovery required'):
            self.manager.start('states', mask=0)
        fresh = Mock()
        with patch('ad3_manager.AD3', return_value=fresh):
            self.assertTrue(self.manager.stop()['outputs_low'])
        fresh.stop_digital.assert_called_once()
        self.assertEqual(self.manager.status()['mode'], 'idle')

    def test_unplugged_device_stays_in_recovery_not_running(self):
        self.device.stop_digital.side_effect = DWFError('USB disconnected')
        with self.assertRaises(DWFError):
            self.manager.stop()
        with patch('ad3_manager.AD3', side_effect=DWFError('No available AD3')):
            with self.assertRaises(DWFError):
                self.manager.stop()
        self.assertEqual(self.manager.status()['mode'], 'recovery_required')
        self.assertFalse(self.manager.status()['active'])
        self.assertFalse(self.manager.status()['outputs_low'])

    def test_start_failure_in_previous_handle_stop_is_recoverable(self):
        self.manager._status = {'active': False, 'mode': 'idle'}
        self.device.stop_digital.side_effect = DWFError('Digital Out config failed')
        with self.assertRaises(DWFError):
            self.manager.start('states', mask=0)
        self.assertIsNone(self.manager._device)
        self.assertEqual(self.manager.status()['mode'], 'recovery_required')
        self.device.digital_states.assert_not_called()

    def test_auto_timeout_failure_marks_recording_failed(self):
        self.device.stop_digital.side_effect = DWFError('Digital Out config failed')
        self.manager._timeout(self.manager._generation)
        self.assertEqual(self.manager.status()['mode'], 'recovery_required')
        self.assertFalse(self.manager.status()['active'])
        self.manager.on_comparator_failed.assert_called_once()
        self.manager.on_comparator_stopped.assert_not_called()

    def test_readiness_after_recovery_keeps_low_holding_handle(self):
        self.manager.stop()
        self.device.check_readiness.return_value = {'ready': True}
        self.assertTrue(self.manager.check_readiness()['ready'])
        self.device.check_readiness.assert_called_once()
        self.device.close.assert_not_called()
        self.assertIs(self.manager._device, self.device)
        self.assertTrue(self.manager.status()['outputs_low'])

    def test_readiness_failure_invalidates_retained_handle(self):
        self.manager.stop()
        self.device.check_readiness.side_effect = DWFError('Scope acquisition timed out')
        with self.assertRaisesRegex(DWFError, 'Scope acquisition timed out'):
            self.manager.check_readiness()
        self.device.close.assert_called_once()
        self.assertIsNone(self.manager._device)
        self.assertEqual(self.manager.status()['mode'], 'recovery_required')
        self.assertFalse(self.manager.status()['outputs_low'])

    def test_readiness_refuses_active_playback_and_recovery(self):
        with self.assertRaisesRegex(RuntimeError, 'digital test active'):
            self.manager.check_readiness()
        self.manager._status = {'active': False, 'mode': 'recovery_required'}
        with self.assertRaisesRegex(RuntimeError, 'recovery required'):
            self.manager.check_readiness()
        self.device.check_readiness.assert_not_called()
        self.device.close.assert_not_called()

    def test_initial_readiness_uses_temporary_handle(self):
        self.manager._device = None
        self.manager._status = {'active': False, 'mode': 'idle'}
        self.device.check_readiness.return_value = {'ready': True}
        with patch('ad3_manager.AD3', return_value=self.device):
            self.assertTrue(self.manager.check_readiness()['ready'])
        self.device.close.assert_called_once()
        self.assertIsNone(self.manager._device)


if __name__ == '__main__':
    unittest.main()
