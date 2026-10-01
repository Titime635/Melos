# Mighty Control

Python-based performance software for the NUX Mighty Plug Pro, turning the amp into a complete stage and studio ecosystem. It features a synchronized looper, automatic preset changes, and an integrated workflow designed for live performance and music creation.

## Status

**V1 complete.** All core modules are implemented and tested against the real device.

## Features (V1)

- **Presets** — 7 presets, color-coded, one-click switching, custom naming
- **Tuner** — real-time note/cents display, manual zero calibration, chromatic/guitar/bass modes
- **Drum accompaniment & EQ** — 67 styles, volume, bass/mid/treble
- **Loop station** — multi-track looping (base + independently deletable overdub tracks), adjustable volume, repeat count (finite or infinite), overdub pass limit, audio count-in before the first take
- **Setlist** — named per-song sequences of preset steps, loop-around navigation, configurable global hotkeys (work without window focus), an enable/disable toggle to pause device control without losing your place
- **Persistent settings** — every setting above survives a restart and is pushed back to the device on launch

## Stack

- Python 3.12 (required — `python-rtmidi` has no PyPI wheel beyond 3.12)
- PySide6 + PySide6-Fluent-Widgets (UI)
- `mido` / `python-rtmidi` (MIDI)
- `sounddevice` (loop station audio)
- `keyboard` (global hotkeys for the setlist)

## Getting started

```bash
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

> On Windows, call `.venv\Scripts\python.exe` directly rather than activating the venv — PowerShell's execution policy blocks the activation script on some machines.

## Project structure

```
mighty_control/
├── main.py                 # entry point: wires MIDI/state/UI, pushes restored settings to the device
├── settings.py              # single JSON settings file (app_settings.json)
├── docs/protocol_notes.md   # empirically verified MIDI/SysEx protocol
├── midi/                    # protocol constants, listener (QThread), sender
├── state/amp_state.py       # single source of truth the UI observes
├── audio/loop_engine.py     # multi-track loop station engine (sounddevice callback)
├── setlist/                 # sequences, playback/navigation, global hotkeys
└── ui/                      # Fluent-widgets panels (presets, tuner, drums, loop, setlist)
```

## Roadmap

- **V2 — UX & reliability**: customizable drag/resize dashboard (invisible snap grid, Figma-style alignment guides, free resizing), a clearly separate edit/performance mode (locked layout on stage), saveable named workspaces, starter layout presets (Live/Studio/Edit), keyboard shortcuts, loop/drum quantization, live connection status
- **V3 — Sheet music & preset editing**: Songsterr-based interactive tab view synced to a YouTube video and MIDI track playback (no Premium subscription), embedded or rebuilt Mighty Editor, preset changes linked to positions on the tab, waveform-based loop visualizer
- **V4 — Hardware & pro audio**: Arduino foot controller, raw + re-amped recording, advanced tab editing (loop/speed/transpose/markers/comments, multi-instrument tracks), a dedicated "Music mode" with a song timeline
- **V5 — AI**: orchestration through JARVIS

## Known protocol quirks

- Presets send no confirmation echo for host-issued commands — the UI updates optimistically instead of waiting on the device.
- Tuner CC 11 most likely reflects signal detection rather than enable state — the on/off switch is driven by a local flag instead.
- The tuner's cent zero isn't factory-calibrated (defaults to ~52, not 0) — use "Set as reference" while playing an in-tune string.
- The Plug Pro has no hardware looper — looping is entirely software-side (`sounddevice`).

See `docs/protocol_notes.md` for the full empirically verified MIDI/SysEx reference.