# Mighty Control

Python-based performance software for the NUX Mighty Plug Pro, turning the amp into a complete stage and studio ecosystem. It features a synchronized looper, automatic preset changes, and an integrated workflow designed for live performance and music creation.

## Status

**V1 complete.** All core modules are implemented and tested against the real device.

## Features (V1)

- **Presets** — 7 presets, color-coded, one-click switching, custom naming
- **Tuner** — real-time note/cents display, manual zero calibration, chromatic/guitar/bass modes
- **Drum accompaniment & EQ** — 67 styles, volume, bass/mid/treble
- **Loop station** — multi-track looping (base + independently deletable overdub tracks), adjustable volume, repeat count (finite or infinite), overdub pass limit, audio count-in before the first take
- **Setlist** — named per-song sequences of preset steps, loop-around navigation (buttons or global shortcuts), an enable/disable toggle to pause device control without losing your place
- **Persistent settings** — every setting above survives a restart and is pushed back to the device on launch

## Stack

- Python 3.12 (required — `python-rtmidi` has no PyPI wheel beyond 3.12)
- PySide6 + PySide6-Fluent-Widgets (UI)
- `mido` / `python-rtmidi` (MIDI)
- `sounddevice` (loop station audio)
- `keyboard` (global keyboard shortcuts)

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
├── midi/                    # protocol constants, listener (QThread), sender, connection monitor, state sync
├── state/amp_state.py       # single source of truth the UI observes
├── audio/loop_engine.py     # multi-track loop station engine (sounddevice callback)
├── setlist/                 # sequences and playback/navigation
├── shortcuts/               # global keyboard shortcuts: action catalogue, key manager, action router
└── ui/                      # Fluent-widgets panels (presets, tuner, drums, loop, setlist) + shortcuts page
```

## Roadmap

- **V2 — UX & reliability**: customizable drag/resize dashboard (invisible snap grid, Figma-style alignment guides, free resizing), a clearly separate edit/performance mode (locked layout on stage), saveable named workspaces, starter layout presets (Live/Studio/Edit), keyboard shortcuts, loop/drum quantization, live connection status
- **V3 — Sheet music & preset editing**: Songsterr-based interactive tab view synced to a YouTube video and MIDI track playback (no Premium subscription), embedded or rebuilt Mighty Editor, preset changes linked to positions on the tab, waveform-based loop visualizer
- **V4 — Hardware & pro audio**: Arduino foot controller, raw + re-amped recording, advanced tab editing (loop/speed/transpose/markers/comments, multi-instrument tracks), a dedicated "Music mode" with a song timeline
- **V5 — AI**: orchestration through JARVIS

## Connection handling

- The app starts with or without the Mighty plugged in. A navigation-bar indicator always shows the connection state, and a banner stays up while disconnected.
- Modules stay editable while disconnected; the app state is pushed back to the amp on (re)connection, exactly as at launch.
- The loop station follows the amp's USB audio interface: stream stopped (in-progress take cancelled, existing tracks kept) on disconnection, restarted on reconnection.

## Keyboard shortcuts

- Global (work while another window has focus) with an on/off switch, in the navigation bar and on the **Raccourcis** page. **No default keys**: you pick them on that page (Échap cancels a capture; a key already used by another action is refused).
- Actions: presets 1–7, next/previous, and the loop station — one cyclic key (record → play → overdub) **and** separate keys (record, overdub, play/stop, clear). Clear only fires when its key is **held ~1 s**.
- Next/previous follow the setlist when it is active (switch on + a sequence with steps), otherwise they step through the presets (wrapping).
- Shortcuts drive the view you are looking at (Dashboard or Classique have separate loop stations and setlists); on the Raccourcis page they keep driving the last one visited.
- A single bare letter/digit/Space/Enter fires everywhere while the switch is on — the page warns about it; prefer F-keys or a Ctrl/Alt combination.

## Known protocol quirks

- MIDI port names aren't stable on Windows (`NUX NMP-03 0`, `2- NUX NMP-03`...) — ports are found by keyword, never by exact name.
- Presets send no confirmation echo for host-issued commands — the UI updates optimistically instead of waiting on the device.
- Tuner CC 11 most likely reflects signal detection rather than enable state — the on/off switch is driven by a local flag instead.
- The tuner's cent zero isn't factory-calibrated (defaults to ~52, not 0) — use "Set as reference" while playing an in-tune string.
- The Plug Pro has no hardware looper — looping is entirely software-side (`sounddevice`).

See `docs/protocol_notes.md` for the full empirically verified MIDI/SysEx reference.