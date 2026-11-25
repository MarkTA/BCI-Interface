"""Hardware-independent run recording tests (including real FastAPI routes)."""
import asyncio
import json
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import zipfile

# CI can run without pyserial, like the project's original test suite.
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

from fastapi.testclient import TestClient
from experiment_recording import ExperimentRecorder
from fpga_protocol import xor_checksum
from serial_manager import decode_neural_event, SerialManager
from ad3_manager import AD3Manager
import experiment_recording
import serial_manager
import main


def make_event(timestamp=1000, peak=3, trough=2):
    value = (timestamp << 38) | (peak << 35) | (trough << 32) | (120 << 20)
    return b'\xaa\x02' + value.to_bytes(8, 'big')


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.recorder = ExperimentRecorder(self.temp.name)

    def _start_playback(self):
        source = b'time,amplitude\n0,0\n1,100\n'
        pattern = bytes([0, 16, 240, 0] * 256)
        self.recorder.begin_playback(configuration={'dataset': 'demo', 'requested_duration_s': 5},
                                     dataset_bytes=source, comparator_words=pattern)
        self.recorder.playback_started({'sample_count': 1024, 'sample_rate_hz': 204800})
        return source, pattern

    def test_record_raw_packet_and_decoded_events_persist(self):
        run = self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        source, pattern = self._start_playback()
        neural1 = make_event()
        neural2 = make_event(2000, peak=1, trough=4)
        gpio = bytes.fromhex('AA 03 0F 03')
        # Include noise and an incomplete header; these must NOT vanish from raw log.
        raw = b'\x00' + neural1 + gpio + neural2 + b'\xaa'
        self.recorder.record_rx_chunk(raw[:11])
        self.recorder.record_packet(neural1, decoded_event=decode_neural_event(neural1))
        self.recorder.record_rx_chunk(raw[11:])
        self.recorder.record_packet(gpio)
        self.recorder.record_packet(neural2, decoded_event=decode_neural_event(neural2))
        self.recorder.record_host_tx(b'help', purpose='ascii_terminal')
        self.recorder.playback_stopped('auto_timeout')
        info = self.recorder.finish(reason='stopped')
        self.assertEqual(info['status'], 'completed')
        self.assertTrue(info['capture']['host_capture_complete'])
        self.assertEqual(info['capture']['raw_rx_bytes'], len(raw))
        self.assertEqual(info['capture']['raw_rx_line_bits_8n1'], len(raw) * 10)
        self.assertEqual(info['capture']['neural_event_count'], 2)
        self.assertEqual(info['capture']['neural_packet_bytes'], 20)
        self.assertEqual(info['capture']['gpio_report_bytes'], 4)
        self.assertEqual(info['capture']['unframed_or_unparsed_bytes'], 2)
        self.assertEqual(info['capture']['host_tx_bytes'], 4)
        self.assertEqual(info['playback']['stop_reason'], 'auto_timeout')
        self.assertEqual(info['playback']['source_csv_sha256'], sha256(source).hexdigest())
        self.assertEqual(info['playback']['comparator_pattern_sha256'], sha256(pattern).hexdigest())
        base = Path(self.temp.name) / run['run_id']
        self.assertEqual((base / 'uart_rx.bin').read_bytes(), raw)
        self.assertEqual((base / 'playback_window_uart_rx.bin').read_bytes(), raw)
        self.assertEqual((base / 'dataset.csv').read_bytes(), source)
        self.assertEqual((base / 'comparator_pattern.bin').read_bytes(), pattern)
        events = [json.loads(line) for line in (base / 'fpga_events.jsonl').read_text().splitlines()]
        self.assertEqual([e['timestamp_us'] for e in events], [1000, 2000])
        self.assertEqual(events[0]['peak'], 3)
        self.assertEqual(events[1]['trough'], 4)
        self.assertTrue(all(e['playback_window'] for e in events))
        packets = [json.loads(line) for line in (base / 'uart_packets.jsonl').read_text().splitlines()]
        self.assertEqual([p['kind'] for p in packets], ['neural_event', 'gpio_report', 'neural_event'])
        self.assertEqual(self.recorder.get_run(run['run_id']), info)
        archive = self.recorder.make_archive(run['run_id'])
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.read('uart_rx.bin'), raw)
            self.assertEqual(z.read('dataset.csv'), source)
            self.assertEqual(json.loads(z.read('manifest.json'))['status'], 'completed')
        self.assertEqual(len(self.recorder.list_runs()), 1)

    def test_interrupted_capture_is_not_certified(self):
        self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        self._start_playback()
        self.recorder.record_rx_chunk(make_event())
        info = self.recorder.finish(reason='websocket_disconnected')
        self.assertFalse(info['capture']['host_capture_complete'])
        self.assertEqual(info['status'], 'interrupted')
        self.assertIn('websocket_disconnected', info['errors'][0])

    def test_failed_disk_recording_cannot_be_certified(self):
        self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        self._start_playback()
        self.recorder.mark_incomplete('Reader failure')
        self.recorder.playback_stopped()
        out = self.recorder.finish(reason='stopped')
        self.assertEqual(out['status'], 'incomplete')
        self.assertFalse(out['capture']['host_capture_complete'])

    def test_no_playback_has_no_false_hardware_result(self):
        self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        out = self.recorder.finish(reason='stopped')
        self.assertEqual(out['status'], 'no_playback')
        self.assertEqual(out['playback']['status'], 'not_started')

    def test_failed_playback_preserves_files_and_errors(self):
        self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        self._start_playback()
        self.recorder.playback_failed('AD3 disconnected')
        out = self.recorder.finish(reason='stopped')
        self.assertEqual(out['status'], 'failed')
        self.assertFalse(out['capture']['host_capture_complete'])
        self.assertIn('AD3 disconnected', out['errors'][0])

    def test_overlapping_runs_and_duplicate_playback_rejected(self):
        self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        with self.assertRaises(RuntimeError):
            self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        self._start_playback()
        with self.assertRaises(RuntimeError):
            self._start_playback()
        self.recorder.playback_stopped()
        self.recorder.finish(reason='stopped')
        self.assertIsNotNone(self.recorder.start(port='COM6', baud=115200, gpio_debug=False))
        self.recorder.finish(reason='stopped')

    def test_bad_id_and_export_running_rejected(self):
        run = self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        with self.assertRaises(RuntimeError):
            self.recorder.make_archive(run['run_id'])
        for bad in ('../secrets', 'a' * 32 + '/../other', '', 'xyz'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.recorder.get_run(bad)
        self.recorder.finish(reason='stopped')
        with self.assertRaises(FileNotFoundError):
            self.recorder.make_archive('0' * 32)

    def test_host_tx_separate_from_rx_bit_rate(self):
        self.recorder.start(port='COM6', baud=115200, gpio_debug=True)
        self.recorder.record_host_tx(b'\xaa\x04\x01', purpose='gpio_debug')
        self.recorder.record_rx_chunk(b'\xaa\x03\x0f\x0f')
        self.recorder.record_packet(b'\xaa\x03\x0f\x0f')
        out = self.recorder.finish(reason='stopped')
        self.assertEqual(out['capture']['raw_rx_line_bits_8n1'], 40)
        self.assertEqual(out['capture']['host_tx_bytes'], 3)

    def test_metadata_counts_include_all_rates_and_no_ui_truncation(self):
        self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        self._start_playback()
        for i in range(500):
            packet = make_event(timestamp=1000 + i * 100)
            self.recorder.record_rx_chunk(packet)
            self.recorder.record_packet(packet, decoded_event=decode_neural_event(packet))
        self.recorder.playback_stopped()
        out = self.recorder.finish(reason='stopped')
        self.assertEqual(out['capture']['neural_event_count'], 500)
        self.assertEqual(out['capture']['raw_rx_bytes'], 5000)
        directory = self.recorder._path(out['run_id'])
        self.assertEqual(len((directory / 'fpga_events.jsonl').read_text().splitlines()), 500)

    def test_snapshot_while_live_and_directory_is_user_writable(self):
        info = self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        self.assertEqual(self.recorder.get_run(info['run_id'])['status'], 'recording')
        self.assertEqual(self.recorder.list_runs()[0]['run_id'], info['run_id'])
        self.recorder.finish(reason='stopped')

    def test_actual_dio_pattern_replaces_nominal_if_capacity_differs(self):
        run = self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        self._start_playback()
        actual = bytes([1, 2, 4, 8] * 128)
        self.recorder.replace_actual_pattern(actual)
        self.recorder.playback_stopped()
        out = self.recorder.finish(reason='stopped')
        self.assertEqual(out['playback']['pattern_sample_count'], 512)
        self.assertTrue(out['playback']['pattern_recomputed_for_ad3_capacity'])
        self.assertEqual(out['playback']['comparator_pattern_sha256'], sha256(actual).hexdigest())
        self.assertEqual((self.recorder._path(run['run_id']) / 'comparator_pattern.bin').read_bytes(), actual)

    def test_background_ad3_auto_timeout_callback_is_captured(self):
        manager = AD3Manager()
        stop_observed = threading.Event()
        reasons = []

        class FakeAD3:
            def digital_comparator_simulation(self, *args, **kwargs):
                return {'sample_count': 1024}
            def stop_digital(self):
                stop_observed.set()

        manager._device = FakeAD3()
        self.recorder.start(port='COM6', baud=115200, gpio_debug=False)
        self._start_playback()
        manager.on_comparator_stopped = self.recorder.playback_stopped
        manager.start('comparators', sample_values_uv=[0, 1], duration_ms=5,
                      thresholds_mv={}, duration_s=.025)
        self.assertTrue(stop_observed.wait(timeout=2))
        # Stop event is set inside stop_digital before the callback is executed.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and self.recorder.get_run(self.recorder.active_run_id)['playback']['stop_reason'] != 'auto_timeout':
            time.sleep(.005)
        out = self.recorder.finish(reason='stopped')
        self.assertEqual(out['status'], 'completed')
        self.assertEqual(out['playback']['stop_reason'], 'auto_timeout')


class FakeUART:
    """Device with real background reader but deterministic protocol ACKs."""
    instances = []

    def __init__(self, port, baudrate, timeout, write_timeout):
        self.rx = queue.Queue()
        self.closed = False
        self.port = port
        self.baudrate = baudrate
        FakeUART.instances.append(self)

    def read(self, size):
        try:
            return self.rx.get(timeout=.04)
        except queue.Empty:
            return b''

    def write(self, payload):
        if payload[:2] == b'\xaa\x04':
            seq, mode = payload[2], payload[5]
            body = bytes((0x84, seq, mode))
            self.rx.put(b'\xaa' + body + bytes((xor_checksum(body),)))
        return len(payload)

    def close(self):
        self.closed = True


class RestAndWebsocketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.recorder = ExperimentRecorder(self.temp.name)
        self.original_recorder = main.experiment_recorder
        self.original_manager = main.serial_manager
        main.serial_manager = SerialManager()  # fresh WS owner per test
        self.original_hook = main.ad3_manager.on_comparator_stopped
        main.experiment_recorder = self.recorder
        serial_manager.experiment_recorder = self.recorder
        main.ad3_manager.on_comparator_stopped = self.recorder.playback_stopped
        self.addCleanup(self._restore)
        FakeUART.instances.clear()

    def _restore(self):
        main.experiment_recorder = self.original_recorder
        main.serial_manager = self.original_manager
        serial_manager.experiment_recorder = self.original_recorder
        main.ad3_manager.on_comparator_stopped = self.original_hook

    def test_run_arm_playback_record_stop_and_rest_export(self):
        status = {'active': False, 'mode': 'idle'}
        fake_ad3_info = {
            'active': True, 'mode': 'comparators',
            'cycle_duration_ms': 5, 'sample_rate_hz': 204800,
            'sample_count': 1024,
        }

        def ad3_start(*args, **kwargs):
            status.update(fake_ad3_info)
            return fake_ad3_info

        def ad3_stop():
            if status['active']:
                self.recorder.playback_stopped('manual')
            status.update({'active': False, 'mode': 'idle'})
            return status.copy()

        with patch.object(serial_manager.serial, 'Serial', FakeUART), \
                patch.object(main.ad3_manager, 'status', side_effect=lambda: status.copy()), \
                patch.object(main.ad3_manager, 'start', side_effect=ad3_start), \
                patch.object(main.ad3_manager, 'stop', side_effect=ad3_stop):
            with TestClient(main.app) as client, client.websocket_connect('/ws?port=COM6') as ws:
                first = ws.receive_json()
                self.assertEqual(first['type'], 'status', first)
                ws.send_json({'type': 'set_run_state', 'active': True, 'gpio_debug': False})
                # gpio_mode acknowledgment precedes run_state.
                self.assertEqual(ws.receive_json()['type'], 'gpio_mode')
                armed = ws.receive_json()
                self.assertEqual(armed['data'], 'running')
                run_id = armed['run_id']
                req = {'dataset': 'positive_then_negative',
                       'thresholds_mv': [5, 10, 20, 40, -5, -10, -20, -40],
                       'duration_s': 2, 'playback_speed': 1, 'gpio_debug_enabled': False}
                started = client.post('/api/ad3/digital/comparators', json=req)
                self.assertEqual(started.status_code, 200, started.text)
                self.assertEqual(started.json()['recording_run_id'], run_id)
                fpga = FakeUART.instances[-1]
                fpga.rx.put(make_event(1200))
                next_msg = ws.receive_json()
                self.assertEqual(next_msg['type'], 'neural_events')
                self.assertEqual(next_msg['events'][0]['timestamp_us'], 1200)
                ws.send_json({'type': 'set_run_state', 'active': False})
                messages = [ws.receive_json() for _ in range(4)]
                self.assertEqual(messages[-1]['type'], 'run_state')
                self.assertEqual(messages[-1]['data'], 'stopped')
                self.assertEqual(messages[-1]['recording_status'], 'completed')
                report = client.get(f'/api/runs/{run_id}')
                self.assertEqual(report.status_code, 200)
                info = report.json()
                self.assertEqual(info['capture']['neural_event_count'], 1)
                self.assertEqual(info['playback']['config']['dataset'], req['dataset'])
                self.assertEqual(info['playback']['ad3_info']['sample_rate_hz'], 204800)
                self.assertEqual(len(client.get('/api/runs').json()['runs']), 1)
                archive = client.get(f'/api/runs/{run_id}/export')
                self.assertEqual(archive.status_code, 200)
                self.assertEqual(archive.headers['content-type'], 'application/zip')
                self.assertEqual(client.get('/api/runs/../../etc/passwd').status_code, 404)

    def test_ad_start_failure_finalizes_recording_without_closing_uart(self):
        from waveforms import DWFError
        status = {'active': False, 'mode': 'idle'}
        raw = 'FDwfDeviceOpen: No connected device found FDwfDeviceOpenEx'

        def ad3_start(*args, **kwargs):
            status.update({'mode': 'recovery_required', 'outputs_low': False, 'error': raw})
            raise DWFError(raw)

        counters = dict(generated=0, queued=0, transmitted=0, fifo_stall_cycles=0)
        with patch.object(serial_manager.serial, 'Serial', FakeUART), \
                patch.object(main.serial_manager, 'arm_hardware_sync', return_value=True), \
                patch.object(main.serial_manager, 'request_capture_counters', return_value=counters), \
                patch.object(main.ad3_manager, 'status', side_effect=lambda: status.copy()), \
                patch.object(main.ad3_manager, 'start', side_effect=ad3_start), \
                patch.object(main.ad3_manager, 'stop') as stop:
            with TestClient(main.app) as client, client.websocket_connect('/ws?port=COM6') as ws:
                self.assertEqual(ws.receive_json()['type'], 'status')
                ws.send_json({'type': 'set_run_state', 'active': True, 'gpio_debug': False})
                self.assertEqual(ws.receive_json()['type'], 'gpio_mode')
                armed = ws.receive_json()
                self.assertEqual(armed['data'], 'running')
                run_id = armed['run_id']
                req = {'dataset': 'positive_then_negative',
                       'thresholds_mv': [5, 10, 20, 40, -5, -10, -20, -40],
                       'duration_s': 2, 'playback_speed': 1, 'gpio_debug_enabled': False}
                result = client.post('/api/ad3/digital/comparators', json=req)
                self.assertEqual(result.status_code, 400)
                self.assertIn(raw, result.json()['detail'])
                ws.send_json({'type': 'set_run_state', 'active': False})
                for _ in range(10):
                    packet = ws.receive_json()
                    if packet['type'] == 'run_state':
                        break
                self.assertEqual(packet['data'], 'stopped')
                self.assertEqual(packet['recording_status'], 'failed')
                self.assertTrue(any(raw in err for err in packet['errors']))
                self.assertFalse(main.serial_manager.run_active)
                self.assertFalse(FakeUART.instances[-1].closed)
                stop.assert_not_called()  # no repeated attempt to open unplugged AD
                manifest = client.get(f'/api/runs/{run_id}').json()
                self.assertEqual(manifest['status'], 'failed')
                self.assertFalse(manifest['capture']['host_capture_complete'])
                self.assertEqual(ws.receive_json()['type'], 'error')
                # Same physical UART session can arm again after AD recovery.
                status.update({'mode': 'idle', 'error': None})
                ws.send_json({'type': 'set_run_state', 'active': True, 'gpio_debug': False})
                self.assertEqual(ws.receive_json()['type'], 'gpio_mode')
                self.assertEqual(ws.receive_json()['data'], 'running')
                self.assertEqual(len(FakeUART.instances), 1)
                ws.send_json({'type': 'set_run_state', 'active': False})
                for _ in range(10):
                    packet = ws.receive_json()
                    if packet['type'] == 'run_state':
                        break
                self.assertEqual(packet['data'], 'stopped')

    def test_recorder_directory_unwritable_prevents_arming(self):
        with patch.object(serial_manager.serial, 'Serial', FakeUART), \
                patch.object(self.recorder, 'start', side_effect=OSError('disk full')):
            with TestClient(main.app) as client, client.websocket_connect('/ws?port=COM6') as ws:
                first = ws.receive_json()
                self.assertEqual(first['type'], 'status', first)
                ws.send_json({'type': 'set_run_state', 'active': True, 'gpio_debug': False})
                self.assertEqual(ws.receive_json()['type'], 'gpio_mode')
                self.assertEqual(ws.receive_json()['type'], 'gpio_mode')  # rollback ACK
                failed = ws.receive_json()
                self.assertEqual(failed['type'], 'run_error')
                self.assertIn('disk full', failed['message'])
                self.assertFalse(main.serial_manager.run_active)


if __name__ == '__main__':
    unittest.main()
