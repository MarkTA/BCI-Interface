"""Load Kenny's time(ms),amplitude(µV) CSVs, or generate new ones using his functions."""
import csv
import math
import os
import shutil
import sys
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from signals.generate_waveform import generate_waveform_separated

ROOT = Path(__file__).resolve().parent
# PyInstaller's bundled resources can be read-only. Store user-created CSVs
# outside the installation directory and seed presets on first launch.
BUNDLED_DATASETS = (Path(sys._MEIPASS) / 'datasets') if getattr(sys, 'frozen', False) else (ROOT / 'datasets')
if getattr(sys, 'frozen', False):
    DATASETS = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'BCI Experiment Console' / 'datasets'
    DATASETS.mkdir(parents=True, exist_ok=True)
    for source in BUNDLED_DATASETS.glob('*.csv'):
        if source.name != 'custom.csv' and not (DATASETS / source.name).exists():
            shutil.copy2(source, DATASETS / source.name)
else:
    DATASETS = BUNDLED_DATASETS
    DATASETS.mkdir(exist_ok=True)

class CustomParams(BaseModel):
    name: str = Field(default='custom', pattern=r'^[A-Za-z0-9_-]{1,50}$')
    sample_rate_hz: int = Field(default=1000000, ge=1000, le=2_000_000)
    duration_ms: float = Field(default=5.0, ge=.5, le=100)
    positive_uv: float = Field(default=80, ge=-1000, le=1000)
    negative_uv: float = Field(default=-120, ge=-1000, le=1000)
    rise1_ms: float = Field(default=.3, gt=0, le=50)
    fall1_ms: float = Field(default=.25, gt=0, le=50)
    rise2_ms: float = Field(default=.25, gt=0, le=50)
    fall2_ms: float = Field(default=1, gt=0, le=50)
    spacing_ms: float = Field(default=0, ge=0, le=50)
    offset_ms: float = Field(default=.5, ge=0, le=50)
    noise_uv: float = Field(default=0, ge=0, le=500)
    seed: int = Field(default=1234, ge=0, le=2**31-1)

    @model_validator(mode='after')
    def check_duration(self):
        pulse = self.rise1_ms+self.fall1_ms+self.spacing_ms+self.rise2_ms+self.fall2_ms
        if self.offset_ms+pulse > self.duration_ms:
            raise ValueError('Offset + both pulse phases + spacing must fit within duration.')
        if self.duration_ms*self.sample_rate_hz/1000 > 200_000:
            raise ValueError('Limit: 200,000 samples per dataset.')
        return self

def list_datasets():
    return [p.stem for p in sorted(DATASETS.glob('*.csv'))]

def load_dataset(name):
    if not name or name not in list_datasets():
        raise ValueError('Unknown dataset')
    path = DATASETS / (name + '.csv')
    t, amplitudes = [], []
    with path.open(newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ['time','amplitude']:
            raise ValueError('Expected time,amplitude header')
        for row in reader:
            t.append(float(row['time'])); amplitudes.append(float(row['amplitude']))
            if len(t)>200_000:raise ValueError('Dataset is too large')
    if len(t)<2 or any(not math.isfinite(v) for v in t+amplitudes):
        raise ValueError('Invalid dataset values')
    dt = t[1]-t[0]
    if dt<=0 or any(abs(t[i]-(t[0]+i*dt)) > max(1e-5, dt*0.01) for i in range(len(t))):
        raise ValueError('Only uniformly sampled datasets supported')
    return {'name':name, 'time_ms':t, 'amplitude_uv':amplitudes,
            'duration_ms':round(dt*len(t),6), 'sample_rate_hz':round(1000/dt), 'samples':len(t)}

def preview(data, max_points=1400):
    step=max(1,math.ceil(data['samples']/max_points))
    return {k:v for k,v in data.items() if k not in ('time_ms','amplitude_uv')} | {
       'time_ms':data['time_ms'][::step], 'amplitude_uv':data['amplitude_uv'][::step],
       'preview_step':step, 'note':'Time in ms, amplitude in µV'}

def generate(p: CustomParams):
    # Kenny's function writes CSV in CWD, so run it in a controlled temporary dir
    # without changing global process working directory: recreate only the file export
    # by suppressing the source function's side-effect via a local function replacement.
    import signals.generate_waveform as g
    old = g.export_waveform_csv
    try:
        g.export_waveform_csv = lambda *args, **kwargs: None
        t, y, _, meta = generate_waveform_separated(
            p.sample_rate_hz,p.positive_uv,p.negative_uv,
            p.rise1_ms,p.fall1_ms,p.rise2_ms,p.fall2_ms,
            p.duration_ms,p.offset_ms,p.noise_uv,p.seed,'biphasic',p.name,p.spacing_ms)
    finally:
        g.export_waveform_csv = old
    target=DATASETS/(p.name+'.csv')
    with target.open('w', newline='') as file:
        writer=csv.writer(file);writer.writerow(['time','amplitude'])
        writer.writerows((f'{x:.6f}',f'{v:.6f}') for x,v in zip(t,y))
    return preview(load_dataset(p.name))


def save_uploaded_dataset(filename: str, content: bytes):
    """Validate a user CSV and save it in the same format as generated datasets."""
    import io
    import re

    if not filename.lower().endswith('.csv'):
        raise ValueError('Choose a .csv file.')
    name = Path(filename).name[:-4].strip().replace(' ', '_')
    name = re.sub(r'\s+', '_', name)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', name):
        raise ValueError('Filename must contain 1–50 letters, numbers, underscores or hyphens.')
    if len(content) > 10 * 1024 * 1024:
        raise ValueError('CSV must be 10 MB or smaller.')
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('CSV must be UTF-8 encoded.') from exc

    reader = csv.reader(io.StringIO(text, newline=''))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError('CSV is empty.')
    header = [cell.strip() for cell in header]
    if header not in (['time_ms', 'amplitude_uv'], ['time', 'amplitude']):
        raise ValueError('Expected header: time_ms,amplitude_uv')

    times, amplitudes = [], []
    for row_number, row in enumerate(reader, 2):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != 2 or any(not cell.strip() for cell in row):
            raise ValueError(f'Row {row_number}: expected two numeric values.')
        try:
            t, a = (float(cell.strip()) for cell in row)
        except ValueError as exc:
            raise ValueError(f'Row {row_number}: invalid numeric value.') from exc
        if not math.isfinite(t) or not math.isfinite(a):
            raise ValueError(f'Row {row_number}: values must be finite.')
        if times and t <= times[-1]:
            raise ValueError(f'Row {row_number}: time must strictly increase.')
        times.append(t)
        amplitudes.append(a)
        if len(times) > 200_000:
            raise ValueError('Maximum 200,000 samples per dataset.')

    if len(times) < 2:
        raise ValueError('Include at least two waveform samples.')
    dt = times[1] - times[0]
    for i in range(2, len(times)):
        if abs((times[i] - times[i-1]) - dt) > max(1e-9, dt * 0.001):
            raise ValueError(f'Row {i+1}: sampling intervals must be uniform (within 0.1%).')
    sample_rate = 1000 / dt
    if not 1000 <= sample_rate <= 2_000_000:
        raise ValueError('Sample rate must be between 1,000 and 2,000,000 Hz.')

    target = DATASETS / f'{name}.csv'
    # Exclusive creation prevents silently overwriting existing presets.
    try:
        with target.open('x', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['time', 'amplitude'])
            writer.writerows(zip(times, amplitudes))
    except FileExistsError as exc:
        raise ValueError(f'Dataset "{name}" already exists. Rename the CSV and try again.') from exc
    try:
        return preview(load_dataset(name))
    except Exception:
        target.unlink(missing_ok=True)
        raise
