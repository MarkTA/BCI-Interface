# BCI Experiment Console — UI refinement

This update uses the existing Milestone 4 React/Zustand/TanStack architecture and the **Stage 5 known-good AD3 adapter** (`backend/waveforms.py`).

- CH1 and CH2 are always acquired; each has a separate scope plot with independently auto-scaled voltage Y-axis. Time axes share the same hardware acquisition buffer. Both plots appear in AFE and Results tabs.
- Acquisition mode, channel selection and WaveGen peak controls were removed from the user interface.
- AD3 test button calls `GET /api/ad3/connection` and opens/closes the device. Backend online does not imply AD3 connected.
- Gain selector has all 8 truth-table entries from the supplied DIP reference; CSS-based visual updates the three switch positions. **It does not change physical hardware.**
- The backend still uses fixed **1 V peak** for W1, inherited from the validated Stage 5 tests. This is **not suitable for direct injection to a microvolt-level AFE** without the appropriate attenuator.
- No new gain calculations were added to the UI.

## Development

Open terminal one: `cd backend`, activate `.venv`, then `uvicorn main:app --reload`.

Open terminal two: `cd frontend`, then `npm install` and `npm run dev`.

Check AD3 wiring and stop WaveForms GUI. Use the Test AD3 connection button.
