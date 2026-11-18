"""BCI USB serial bridge: FastAPI/WebSocket <-> 3.3 V USB-UART <-> FPGA."""
import asyncio
from contextlib import suppress
from pathlib import Path

import serial
from serial.tools import list_ports
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="BCI FPGA Serial Bridge")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])

@app.get('/api/ports')
def ports():
    return [{"device": p.device, "description": p.description} for p in list_ports.comports()]

from serial_manager import serial_manager

@app.websocket('/ws')
async def bridge(ws: WebSocket):
    await ws.accept()
    mock = ws.query_params.get('mock') == '1'
    port = ws.query_params.get('port', '')
    try:
        baud = int(ws.query_params.get('baud', '115200'))
        if baud not in (9600, 115200, 921600):
            raise ValueError('Unsupported baud rate')
        async def emit(packet):
            await ws.send_json(packet)
        await serial_manager.connect(ws, port, baud, mock, emit)
    except (serial.SerialException, ValueError, RuntimeError, OSError) as exc:
        await ws.send_json({'type': 'error', 'message': str(exc)})
        await ws.close()
        return
    await ws.send_json({'type': 'status', 'message': 'Mock connected' if mock else f'Connected to {port} @ {baud}'})
    try:
        while True:
            message = await ws.receive_json()
            try:
                if message.get('type') == 'tx':
                    data = str(message.get('data', ''))
                    if len(data) > 4096:
                        raise ValueError('Message too long')
                    await serial_manager.send_text(data)
                elif message.get('type') == 'set_run_state':
                    active = message.get('active')
                    if type(active) is not bool:
                        raise ValueError('Run state must be boolean')
                    if active:
                        gpio_debug = message.get('gpio_debug', False)
                        if type(gpio_debug) is not bool:
                            raise ValueError('gpio_debug must be boolean')
                        if serial_manager.pending is not None:
                            raise ValueError('Wait for threshold updates to finish')
                        if serial_manager.run_active:
                            raise ValueError('Run is already active')
                        if mock:
                            raise ValueError('Physical run lock requires a real serial connection')
                        try:
                            # Do not arm or start AD3 until the FPGA ACKs its mode.
                            await serial_manager.set_gpio_debug(gpio_debug)
                        except Exception as exc:
                            await ws.send_json({'type': 'run_error', 'message':
                                                f'FPGA GPIO mode not confirmed: {exc}'})
                            continue
                        serial_manager.reset_diagnostics()
                        serial_manager.run_active = True
                        await ws.send_json({'type': 'run_state', 'data': 'running',
                                            'gpio_debug': gpio_debug,
                                            'message': ('GPIO debug enabled' if gpio_debug
                                                        else 'Neural events; GPIO debug disabled')})
                    else:
                        # Stop AD3 before disabling GPIO telemetry. Never leave the
                        # waveform running while changing/debugging the serial mode.
                        serial_manager.run_active = False
                        await serial_manager.flush_gpio_trace()
                        await serial_manager.flush_neural_events()
                        errors = []
                        try:
                            await asyncio.to_thread(ad3_manager.stop)
                        except (RuntimeError, OSError, ValueError) as exc:
                            errors.append(f'AD3 stop failed: {exc}')
                        try:
                            await serial_manager.set_gpio_debug(False)
                        except Exception as exc:
                            errors.append(f'GPIO debug disable not ACKed: {exc}')
                        await ws.send_json({'type': 'gpio_stats', **serial_manager.diagnostic_counts()})
                        await ws.send_json({'type': 'neural_stats', **serial_manager.neural_statistics()})
                        await ws.send_json({'type': 'run_state', 'data': 'stopped',
                                            'message': 'Run stopped' if not errors else '; '.join(errors)})
                        for error in errors:
                            await ws.send_json({'type': 'error', 'message': error})
                elif message.get('type') == 'set_thresholds':
                    voltages = message.get('thresholds')
                    if not isinstance(voltages, list) or len(voltages) != 8 or any(type(v) not in (int, float) for v in voltages):
                        raise ValueError('Provide eight numeric absolute DAC voltages')
                    request_id = message.get('request_id')
                    try:
                        results = await serial_manager.set_thresholds(voltages)
                    except Exception as exc:
                        await ws.send_json({'type': 'threshold_error', 'request_id': request_id, 'message': str(exc)})
                    else:
                        await ws.send_json({'type': 'threshold_complete', 'request_id': request_id, 'results': results})
            except (ValueError, serial.SerialException, OSError, ConnectionError) as exc:
                await ws.send_json({'type': 'error', 'message': str(exc)})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if serial_manager.owner is ws:
            serial_manager.run_active = False
            with suppress(Exception):
                await asyncio.to_thread(ad3_manager.stop)
            with suppress(Exception):
                await serial_manager.set_gpio_debug(False)
        await serial_manager.disconnect(ws)

# Waveform/oscilloscope milestone (independent of the FPGA serial bridge).
from fastapi import HTTPException
from pydantic import BaseModel, Field
from datasets import CustomParams, generate, list_datasets, load_dataset, preview

@app.get('/api/datasets')
def dataset_list():
    return {'datasets':list_datasets()}

@app.get('/api/datasets/{name}')
def dataset_get(name: str):
    try:
        return preview(load_dataset(name))
    except ValueError as e:
        raise HTTPException(404, str(e))

from fastapi import UploadFile, File
from datasets import save_uploaded_dataset

@app.post('/api/datasets/upload')
async def dataset_upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=422, detail='Choose a .csv file.')
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='CSV must be 10 MB or smaller.')
    try:
        return save_uploaded_dataset(file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post('/api/datasets/generate')
def dataset_generate(params: CustomParams):
    return generate(params)

class CaptureRequest(BaseModel):
    dataset: str
    mode: str = Field(default='mock', pattern='^(mock|ad3)$')
    channels: int = Field(default=1, ge=1, le=2)
    awg_peak_v: float = Field(default=1, ge=.01, le=2)

from ad3_manager import ad3_manager

@app.get('/api/ad3/connection')
def ad3_connection():
    try:
        result = ad3_manager.run_temporary(lambda device: device.check_readiness())
        return {'connected': True, 'ready': True, 'status': 'ready',
                'message': result['message'], 'warning': None}
    except (RuntimeError, OSError, ValueError) as exc:
        return {'connected': False, 'ready': False, 'status': 'unavailable',
                'message': str(exc), 'warning': str(exc)}

class DigitalStateRequest(BaseModel):
    mask: int = Field(ge=0, le=255)

class DigitalPulseRequest(BaseModel):
    channel: int = Field(default=4, ge=0, le=7)
    frequency_hz: float = Field(default=5, gt=0, le=10000, allow_inf_nan=False)
    width_us: float = Field(default=100, gt=0, le=1000000, allow_inf_nan=False)
    duration_s: float = Field(default=5, gt=0, le=60, allow_inf_nan=False)

@app.get('/api/ad3/digital/status')
def ad3_digital_status():
    return ad3_manager.status()

@app.post('/api/ad3/digital/state')
def ad3_digital_state(req: DigitalStateRequest):
    try:
        return ad3_manager.start('states', mask=req.mask)
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

@app.post('/api/ad3/digital/pulse')
def ad3_digital_pulse(req: DigitalPulseRequest):
    try:
        return ad3_manager.start('pulse', **req.model_dump())
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

# Dataset-driven comparator simulation. Thresholds arrive in DAC/React order:
# P1..P4, N1..N4; DIO order inside waveforms.py is N1..N4, P1..P4.
# Playback speed 1.0 preserves Kenny's recorded 5 ms neural waveform duration.
# GPIO debug is a *user declaration about the programmed FPGA bitstream*;
# we cannot introspect ENABLE_GPIO_DEBUG over the current UART protocol.
class ComparatorDatasetRequest(BaseModel):
    dataset: str = Field(min_length=1, max_length=60)
    thresholds_mv: list[float] = Field(min_length=8, max_length=8)
    playback_speed: float = Field(default=1.0, ge=0.01, le=1, allow_inf_nan=False)
    gpio_debug_enabled: bool = False  # FPGA runtime mode is set by UART before playback
    duration_s: float = Field(default=10, ge=1, le=60, allow_inf_nan=False)


def _prepare_comparator_dataset(req: ComparatorDatasetRequest):
    from waveforms import build_comparator_pattern, DEFAULT_AFE_GAIN_VV
    from math import isfinite

    names = ('P1', 'P2', 'P3', 'P4', 'N1', 'N2', 'N3', 'N4')
    if any(not isfinite(v) for v in req.thresholds_mv):
        raise ValueError('All eight thresholds must be finite')
    thresholds = dict(zip(names, req.thresholds_mv))
    data = load_dataset(req.dataset)  # Full CSV, never downsampled UI preview
    cycle_ms = data['duration_ms'] / req.playback_speed
    plan = build_comparator_pattern(
        data['amplitude_uv'], cycle_ms, thresholds,
        afe_gain=DEFAULT_AFE_GAIN_VV, sample_count=1024, bias_v=1.6,
    )
    edge_rate = sum(plan['expected_edges_per_cycle'].values()) * 1000.0 / cycle_ms
    return data, plan, thresholds, cycle_ms, edge_rate


def _reference_comparator_states(words):
    """Transition-compressed reference, one time-ordered FPGA/DIO mask per state."""
    return ([{'sample_index': 0, 'mask': words[0]}] +
            [{'sample_index': i, 'mask': state}
             for i, state in enumerate(words[1:], start=1)
             if state != words[i - 1]])


@app.post('/api/ad3/digital/comparators/preview')
def preview_comparator_dataset(req: ComparatorDatasetRequest):
    try:
        data, plan, _, cycle_ms, edge_rate = _prepare_comparator_dataset(req)
        return {
            'dataset': data['name'], 'source_duration_ms': data['duration_ms'],
            'cycle_duration_ms': cycle_ms, 'sample_count': plan['sample_count'],
            'sample_interval_us': cycle_ms * 1000 / plan['sample_count'],
            'playback_speed': req.playback_speed,
            'gpio_debug_enabled': req.gpio_debug_enabled,
            'afe_peak_mv': plan['afe_peak_mv'],
            'source_peak_uv': plan['source_peak_uv'],
            'afe_gain': plan['afe_gain'],
            'expected_edges_per_cycle': plan['expected_edges_per_cycle'],
            'reference_states': _reference_comparator_states(plan['words']),
            'expected_edges_per_second': edge_rate,
            'signal_range_mv': plan['signal_range_mv'],
            'warning': ('Predicted GPIO diagnostic throughput exceeds the '
                        'conservative 2000 edges/s limit at 115200 baud. '
                        'Use the 0.25x GPIO debug mode or reduce playback speed.'
                        if req.gpio_debug_enabled and edge_rate > 2000 else None),
        }
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post('/api/ad3/digital/comparators')
def start_comparator_dataset(req: ComparatorDatasetRequest):
    try:
        # The React Run/Stop state must already be active, so the UART reader
        # records events from the moment digital outputs begin toggling.
        if not serial_manager.run_active or serial_manager.mock or not serial_manager.device:
            raise ValueError('Connect physical FPGA UART and click Start run first')
        if serial_manager.gpio_debug_enabled is not req.gpio_debug_enabled:
            raise ValueError('FPGA GPIO reporting mode not confirmed by UART; start a new Run')
        data, plan, thresholds, cycle_ms, edge_rate = _prepare_comparator_dataset(req)
        if req.gpio_debug_enabled and edge_rate > 2000:
            raise ValueError(
                f'Predicted {edge_rate:.0f} transitions/s exceeds safe 115200-baud '
                'GPIO diagnostic capacity (~2000/s). Use 0.25x GPIO debug mode '
                'or reduce playback speed.'
            )
        if ad3_manager.status().get('active'):
            raise ValueError('AD3 output already active; stop it before starting a dataset')
        result = ad3_manager.start(
            'comparators', sample_values_uv=data['amplitude_uv'],
            duration_ms=cycle_ms, thresholds_mv=thresholds,
            afe_gain=plan['afe_gain'], sample_count=1024,
            bias_v=1.6, duration_s=req.duration_s,
        )
        return {**result, 'dataset': data['name'],
                'afe_gain': plan['afe_gain'],
                'afe_peak_mv': plan['afe_peak_mv'],
                'source_peak_uv': plan['source_peak_uv'],
                'source_duration_ms': data['duration_ms'],
                'playback_speed': req.playback_speed,
                'gpio_debug_enabled': req.gpio_debug_enabled,
                'reference_states': _reference_comparator_states(plan['words']),
                'warning': None,
                'expected_edges_per_second': edge_rate,
                'sample_interval_us': result['cycle_duration_ms'] * 1000 / result['sample_count']}
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/api/ad3/digital/scope')
def ad3_digital_scope():
    try:
        return ad3_manager.capture_pulse_scope()
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

@app.post('/api/ad3/digital/stop')
def ad3_digital_stop():
    try:
        return ad3_manager.stop()
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

@app.post('/api/capture')
def capture(req: CaptureRequest):
    try:
        dataset=load_dataset(req.dataset)
        if req.mode=='mock':
            # A deterministic DISPLAY ONLY mock trace: no physical I/O.
            import math
            points=min(2000,dataset['samples']); stride=max(1,dataset['samples']//points)
            times=dataset['time_ms'][::stride]
            signal=dataset['amplitude_uv'][::stride]
            peak=max((abs(v) for v in signal),default=1) or 1
            return {'time_ms':times,'channels':{
                'ch1':[round(req.awg_peak_v*(v/peak)*.30 + .003*math.sin(10*i),6) for i,v in enumerate(signal)],
                **({'ch2':[round(1.6+req.awg_peak_v*(v/peak)*.12,6) for v in signal]} if req.channels==2 else {})},
                'mode':'mock','note':'SIMULATED scope only. Not hardware measurements.'}
        result = ad3_manager.run_temporary(
            lambda device: device.play_and_capture(
                dataset['amplitude_uv'], dataset['duration_ms'],
                awg_peak_v=req.awg_peak_v, channels=req.channels
            )
        )
        return {'mode': 'ad3', **result}
    except (ValueError, RuntimeError, OSError) as e:
        raise HTTPException(400, str(e))


# Production: serve the compiled React app from the same localhost server.
# Development keeps Vite on :5173 and FastAPI on :8000.
import os
import sys
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

@app.get('/api/health')
def health():
    return {'ok': True, 'service': 'bci-interface'}

if getattr(sys, 'frozen', False):
    _static_dir = Path(sys._MEIPASS) / 'frontend-dist'
else:
    _static_dir = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
if _static_dir.is_dir():
    app.mount('/assets', StaticFiles(directory=_static_dir / 'assets'), name='assets')

    @app.get('/')
    def index():
        return FileResponse(_static_dir / 'index.html')

    @app.get('/{path:path}')
    def spa_fallback(path: str):
        # Only app routes reach here: API routes are registered above.
        if path.startswith(('api/', 'ws', 'assets/')):
            raise HTTPException(status_code=404, detail='Not found')
        return FileResponse(_static_dir / 'index.html')

if __name__ == '__main__':
    import uvicorn
    # Bind only to loopback. This service has device access and must not be exposed.
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('BCI_PORT', '8000')), log_level='warning')
