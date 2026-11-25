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
        self.on_comparator_stopped = None  # Optional thread-safe run recorder hook
        self.on_comparator_failed = None

    def _cancel_timer(self):
        self._generation += 1
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _close_device(self):
        device, self._device = self._device, None
        if device:
            device.close()

    def _recover_from_device_error(self, exc, *, comparator_active=False):
        # A failed SDK call is not evidence that the pins are LOW. Release
        # the stale handle and end the logical session, but require a fresh
        # successful stop before another output test is allowed.
        self._cancel_timer()
        try:
            self._close_device()
        except Exception:
            log.exception('Failed to close Analog Discovery after SDK error')
        self._status = {'active': False, 'mode': 'recovery_required',
                        'outputs_low': False, 'error': str(exc)}
        if comparator_active and self.on_comparator_failed:
            try:
                self.on_comparator_failed(str(exc))
            except Exception:
                log.exception('Run recorder failed during AD3 recovery')

    def stop(self, *, reason="manual"):
        with self._lock:
            was_comparator_active = (self._status.get("active") and
                                     self._status.get("mode") == "comparators")
            self._cancel_timer()
            try:
                if self._status.get('mode') == 'recovery_required' and not self._device:
                    self._device = AD3()  # Retry with a fresh SDK handle.
                if self._device:
                    self._device.stop_digital()
            except Exception as exc:
                log.exception('AD3 digital stop failed')
                self._recover_from_device_error(exc, comparator_active=was_comparator_active)
                raise
            # Leave the SAME AD3 handle open to maintain driven LOW outputs.
            self._status = {'active': False, 'mode': 'idle', 'outputs_low': self._device is not None}
            if was_comparator_active and self.on_comparator_stopped:
                try:
                    self.on_comparator_stopped(reason)
                except Exception:
                    # Recorder failure must never prevent the safe AD3 stop.
                    log.exception('Run recorder failed during AD3 stop')
            return dict(self._status)

    def _timeout(self, generation):
        with self._lock:
            if generation == self._generation:
                try:
                    self.stop(reason="auto_timeout")
                except Exception:
                    log.exception('AD3 digital automatic stop failed')

    def start(self, mode, **kwargs):
        with self._lock:
            if self._status.get('mode') == 'recovery_required':
                raise RuntimeError('Analog Discovery recovery required; retry Stop before starting')
            was_comparator_active = (self._status.get('active') and
                                     self._status.get('mode') == 'comparators')
            self._cancel_timer()
            try:
                if self._device:
                    self._device.stop_digital()
                else:
                    self._device = AD3()
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
            except Exception as exc:
                log.exception('AD3 digital start failed')
                self._recover_from_device_error(
                    exc, comparator_active=was_comparator_active)
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

    def check_readiness(self):
        """Run the same acquisition check without releasing idle LOW outputs."""
        with self._lock:
            if self._status.get('active'):
                raise RuntimeError('AD3 digital test active; stop it before checking connection')
            if self._status.get('mode') == 'recovery_required':
                raise RuntimeError('Analog Discovery recovery required; retry Stop before checking connection')
            if self._device is None:
                return self.run_temporary(lambda device: device.check_readiness())
            try:
                # Recovery has already stopped the outputs. AnalogIn readiness
                # uses the existing SDK handle and does not start WaveGen or DIO.
                return self._device.check_readiness()
            except Exception as exc:
                self._recover_from_device_error(exc)
                raise

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
