# Milestone 4 — Guided Console (Zustand + TanStack Query)

This **replaces the frontend of the Milestone 3 starter**, retaining its FastAPI endpoints, waveform CSV generator, mock/AD3 single capture, serial WebSocket console, and Electron/PyInstaller packaging. It is source code. It has **not been Windows-installer-built or AD3-tested in this environment**.

## What's implemented

1. **PCB Setup** — manual hardware checklist; photo and verified power instructions are marked as placeholders.
2. **Synthetic Brainwaves** — available CSV datasets via TanStack Query; waveform preview; custom generation through Kenny's existing Python generator.
3. **Analog Conditioning** — notes for probe placement and DIP-switch settings; single CH1 / CH1+CH2 mock or SDK hardware capture; reusable scope.
4. **Neural Events** — editable eight thresholds relative to 1.6 V; nominal voltage and DAC code preview. Simulation setting is local only; **no physical DAC writes** are performed. Serial status directs the user to Step 5.
5. **Data Output** — USB–UART serial terminal (mock or actual COM port), save log as text, print view, session JSON snapshot, reused scope capture. **No autonomous Run operation or binary packet decoder yet.**

Also includes tab navigation, Back/Continue, shared status, signal-path indicator, collapsible (clearly placeholder) contributor descriptions, and About dialog.

**State separation:** Zustand stores persistent editable preferences and transient capture/connection metadata. TanStack Query retrieves and caches REST resources. High-frequency samples are **not** continuously dispatched through Zustand; the existing backend returns a single decimated capture. Eventually use a dedicated waveform ring buffer for streaming.

## Development

Install Python and Node on the *development* workstation:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

In a separate terminal from `frontend`:

```powershell
npm install
npm run dev
```

## Windows installer

The existing Windows script now uses absolute paths for PyInstaller input data so that `--specpath build/python` cannot relocate the `datasets` directory resolution:

```powershell
.\scripts\build-windows.ps1
```

This script remains the packaging entrypoint. Run it on Windows with working npm/Python. The final installer is under `release/`.

## Test checklist

- Start in mock mode. Navigate all five tabs; check that state persists when you go Back and Continue.
- Step 2: select `positive_then_negative`, then generate a unique custom CSV and confirm the preview changes.
- Step 3: run mock CH1 and CH1+CH2 captures, then navigate to Step 5; the same capture should be displayed.
- Step 4: edit +5 mV, observe the computed DAC code and Modified badge, save simulation thresholds. Physical mode deliberately cannot send threshold commands.
- Step 5: connect mock serial; send `PING` with newline; confirm an echo. Export log and JSON session.
- Only after confirming voltage levels and cabling, test a physical USB-UART adapter and real AD3. The built-in Arduino D0/D1 are FPGA GPIO, not automatically UART unless the HDL assigns UART RX/TX.

## Safety and current boundaries

- The hardware setup description, team section writeups, probe labels and DIP-switch table are explicit placeholders. Get the final PCB mapping from Slava and the AFE assembly documentation.
- The AD3 SDK control remains an **unverified initial implementation**; WaveGen peak amplitude must go through the designed attenuator, never directly into a microvolt-level stage.
- A terminal socket being open does not demonstrate that the FPGA responded; mock echo is not FPGA validation.
- The 64-bit FPGA event format is not yet decoded; binary transmission over the existing text-decoding WebSocket may lose raw byte fidelity. Agree on a framed protocol before handling those packets.
- Full experiment automation, streaming scope, physical DAC writes, threshold replay and event correlation are subsequent milestones.
- FastAPI binds to localhost with no authentication. Do not expose the API outside localhost or browse untrusted pages while hardware access is enabled.
