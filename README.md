# CortexSignals — BCI Experiment Console

Desktop experiment-control interface for the **CortexSignals** electrical engineering capstone project at Arizona State University. The console guides a user through preparing synthetic neural waveforms, configuring the analog front end and comparator thresholds, communicating with an FPGA, and reviewing experimental results.

> **Project status:** Active development / hardware integration. Some controls and workflows are still under validation. The console's current Start/Stop run state is an application-side configuration lock; it is not yet an FPGA acquisition command.

## Features

- Guided workflow for PCB setup, synthetic brainwaves, analog front-end validation, comparator configuration, and results.
- Synthetic waveform generation and CSV dataset upload.
- Digilent Analog Discovery 3 integration for waveform generation and measurements, using the WaveForms SDK.
- Eight DAC80508 threshold settings sent to the FPGA over USB UART; the backend sends each command sequentially and waits for its acknowledgment.
- Persistent serial connection with FPGA protocol verification and diagnostic messages.
- Run-control UI that prevents threshold changes during an active console run.
- Waveform visualization and experiment status indicators.

**In progress:** Receiving and displaying the FPGA's neural-event stream (`AA 02` plus an eight-byte payload). This is not yet included in the current interface.

## Technology

| Layer | Stack |
| --- | --- |
| Desktop shell | Electron |
| User interface | React, TypeScript, Vite |
| State management | Zustand |
| API and serial bridge | Python, FastAPI, WebSockets, pyserial |
| Signal processing | NumPy, Matplotlib |
| Measurement hardware | Digilent Analog Discovery 3 / WaveForms SDK |
| Digital hardware | DE10-Lite FPGA and DAC80508 comparator-threshold board |

## Repository layout

```text
bci-interface/
├── frontend/             # React / TypeScript UI
├── backend/              # FastAPI, datasets, AD3, UART bridge
│   └── requirements.txt
├── electron/             # Electron entry point and desktop integration
├── package.json          # Desktop packaging scripts
└── README.md
```

The layout above describes the full local application project. Keep your existing `frontend/`, `backend/`, and `electron/` directories together when publishing; do not upload just the `src/` folder.

## Development setup

### Requirements

- Node.js and npm (versions compatible with the project's existing lockfiles)
- Python 3.12 (the development environment used for the project)
- Windows for the existing Electron packaging workflow and hardware integration
- Optional for hardware tests: Analog Discovery 3 with Digilent WaveForms installed; DE10-Lite connected through a 3.3 V USB-to-UART adapter

### Backend

From the repository root, in PowerShell:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

The development API runs at `http://127.0.0.1:8000`.

### Frontend

In a second terminal, from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (typically `http://localhost:5173`). The frontend expects the backend at `127.0.0.1:8000`.

### Electron / distribution

The root `package.json` defines `npm run build:frontend`, `npm run package:win`, and `npm run package:portable`. Windows packaging also expects a separately built backend under `backend-dist/bci-backend`. Follow the project's existing build process for producing that backend executable before packaging. These packaging commands have not been independently verified as part of this README.

## FPGA communication

The console uses a WebSocket connection to its Python backend, which communicates with the FPGA over a USB serial adapter (typically **115200 baud**).

| Header | Direction | Purpose |
| --- | --- | --- |
| `AA 01` | Console → FPGA | Set a DAC threshold |
| `AA 81` | FPGA → Console | Threshold acknowledgment |
| `AA 02` | FPGA → Console | Neural event (planned console decoding) |

Thresholds are submitted together in the UI but transmitted **one at a time** by the backend; each command must be acknowledged before the next is sent. Threshold editing is locked while the console's run state is active.

James's FPGA event format uses a 64-bit, most-significant-byte-first payload with channel, timestamp, peak, trough, time-to-peak, and status flags. Event parsing/visualization is the next integration step. The FPGA HDL itself is maintained separately from this interface repository.

## Safety and limitations

- This is a **research/educational prototype**, not a medical device or a clinical diagnostic tool.
- Verify power rails, logic voltage compatibility, DAC outputs, and comparator thresholds before connecting hardware.
- A UART acknowledgment confirms the FPGA handled a command; it does **not** independently verify the analog voltage at a DAC output.
- Run-control currently governs the console's configuration workflow, not hardware-level acquisition enable/disable.

## Contributors

Developed as part of the ASU CortexSignals capstone team. This repository focuses on the experiment-control software; FPGA logic and PCB designs are separate project components.

## License

No open-source license has been selected yet. Unless a license is added, the repository should not be assumed to grant permission to reuse or redistribute its contents.
