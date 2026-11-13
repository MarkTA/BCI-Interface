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
                    if active and serial_manager.pending is not None:
                        raise ValueError('Wait for threshold updates to finish')
                    if active and mock:
                        raise ValueError('Physical run lock requires a real serial connection')
                    serial_manager.run_active = active
                    await ws.send_json({'type': 'run_state', 'data': 'running' if active else 'stopped',
                                        'message': 'Threshold configuration locked' if active else 'Threshold configuration unlocked'})
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

@app.get('/api/ad3/connection')
def ad3_connection():
    from waveforms import AD3

    device = None
    try:
        try:
            device = AD3()
        except (RuntimeError, OSError, ValueError) as exc:
            return {
                'connected': False,
                'ready': False,
                'status': 'unavailable',
                'message': str(exc),
                'warning': 'Unable to open AD3. Check USB and close WaveForms desktop.',
            }

        try:
            result = device.check_readiness()
            return {
                'connected': True,
                'ready': True,
                'status': 'ready',
                'message': result['message'],
                'warning': None,
            }
        except (RuntimeError, OSError, ValueError) as exc:
            return {
                'connected': True,
                'ready': False,
                'status': 'warning',
                'message': str(exc),
                'warning': (
                    'AD3 opened, but scope acquisition failed. Check USB power, '
                    'cable, and port; also close WaveForms desktop.'
                ),
            }
    finally:
        if device is not None:
            device.close()


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
        from waveforms import AD3
        device=AD3()
        try:
            result=device.play_and_capture(dataset['amplitude_uv'],dataset['duration_ms'],
                              awg_peak_v=req.awg_peak_v,channels=req.channels)
            return {'mode':'ad3',**result}
        finally:
            device.close()
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
