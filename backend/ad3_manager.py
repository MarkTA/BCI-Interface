"""Exclusive AD3 ownership for FastAPI operations and persistent digital tests."""
import logging
import threading
from waveforms import AD3, DEFAULT_AFE_GAIN_VV

log = logging.getLogger(__name__)


class AD3Manager:
    def __init__(self):
        self._lock = threading.RLock()
        self._device = None
        self._timer = None
        self._generation = 0
        self._status = {'active': False, 'mode': 'idle'}

    def _cancel_timer(self):
        self._generation += 1
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _close_device(self):
        device, self._device = self._device, None
        if device:
            device.close()

    def stop(self):
        with self._lock:
            self._cancel_timer()
            if self._device:
                try:
                    self._device.stop_digital()
                except Exception:
                    log.exception('AD3 digital stop failed')
                    self._status = {'active': True, 'mode': 'stop_failed'}
                    raise
            # Leave the SAME AD3 handle open to maintain driven LOW outputs.
            self._status = {'active': False, 'mode': 'idle', 'outputs_low': True}
            return dict(self._status)

    def _timeout(self, generation):
        with self._lock:
            if generation == self._generation:
                try:
                    self.stop()
                except Exception:
                    log.exception('AD3 digital automatic stop failed')

    def start(self, mode, **kwargs):
        with self._lock:
            # Cancel prior test, retaining the same device handle.
            self._cancel_timer()
            if self._device:
                self._device.stop_digital()
            else:
                self._device = AD3()
            try:
                if mode == 'states':
                    info = self._device.digital_states(kwargs['mask'])
                elif mode == 'pulse':
                    info = self._device.digital_pulse_train(
                        kwargs['channel'], kwargs['frequency_hz'], kwargs['width_us'])
                elif mode == 'comparators':
                    info = self._device.digital_comparator_simulation(
                        kwargs['sample_values_uv'], kwargs['duration_ms'],
                        kwargs['thresholds_mv'],
                        afe_gain=kwargs.get('afe_gain', DEFAULT_AFE_GAIN_VV),
                        sample_count=kwargs.get('sample_count', 1024),
                        bias_v=kwargs.get('bias_v', 1.6),
                    )
                else:
                    raise ValueError('Unknown digital mode')
                self._status = {'active': True, 'mode': mode, **info}
                if mode in ('pulse', 'comparators'):
                    duration = kwargs['duration_s']
                    generation = self._generation
                    self._timer = threading.Timer(duration, self._timeout, args=(generation,))
                    self._timer.daemon = True
                    self._timer.start()
                    self._status['duration_s'] = duration
                return dict(self._status)
            except Exception:
                log.exception('AD3 digital start failed')
                # Attempt to make outputs safe; preserve original error.
                try:
                    self._device.stop_digital()
                except Exception:
                    log.exception('AD3 cleanup after start failure failed')
                self._status = {'active': False, 'mode': 'error'}
                raise

    def capture_pulse_scope(self, sample_rate_hz=2_000_000.0, count=8192):
        with self._lock:
            if not self._device or self._status.get('mode') not in ('pulse', 'comparators') \
                    or not self._status.get('active'):
                raise RuntimeError('Start a pulse train or comparator simulation before capturing')
            return self._device.capture_pulse_scope(sample_rate_hz, count)

    def hardware_status(self):
        """Actual DWF digital instrument state, not just manager bookkeeping."""
        with self._lock:
            if not self._device:
                return {'state_name': 'device_closed'}
            return self._device.digital_output_status()

    def status(self):
        with self._lock:
            return dict(self._status)

    def run_temporary(self, fn):
        with self._lock:
            if self._status.get('active'):
                raise RuntimeError('AD3 digital test active; stop it before capturing or checking connection')
            # Close idle LOW-holding connection before opening temporary capture.
            if self._device:
                self._close_device()
            device = AD3()
            try:
                return fn(device)
            finally:
                device.close()


ad3_manager = AD3Manager()
