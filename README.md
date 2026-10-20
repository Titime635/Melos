# Mighty Control

Python-based performance software for the NUX Mighty Plug Pro, turning the amp into a complete stage and studio ecosystem. It features a synchronized looper, automatic preset changes, and an integrated workflow designed for live performance and music creation.

## Status

**V1 and V2 complete.** Next up: V3 (sheet music & preset editing). A few device-side details (tuner reference byte, drum tempo SysEx) are still being validated on real hardware.

## Features

- **Dashboard** — free-form docking layout (drag, resize, remove and re-add modules), a separate Edit / Performance mode, adaptive modules that shrink their content to the space they get, layout saved automatically. The **Classique** tab keeps the old stacked view.
- **Presets** — 7 color-coded presets, one-click switching, custom names, same-size labels that fall back to numbers when space runs out
- **Tuner** — one module: arc gauge with a huge detected note, ♭ ← | → ♯ needle and cents readout; Standard / Eb standard / Drop D plus 23 six-string tunings; a string row that is always visible (click a string for manual mode, none selected = auto); the note turns green with an optional chime once tuned; reference pitch, calibration (zero, scale, per-note zero) and note shift in the module's gear popup
- **Drum accompaniment & EQ** — 75 styles in 11 categories (tabs + favorites, custom vector icons), volume, bass/mid/treble
- **Tempo** — BPM, time signature (4/4, 6/8, 12/8, 3/4 or custom), click, beat dots; shared by the looper and the drums
- **Loop station** — multi-track looping (base + independently deletable overdub tracks), quantization (Rec / Overdub / Stop wait for the next bar, following the drums when they run), auto-length (stop after N bars), audio count-in of one full bar (waits for the next bar when a bar is in progress), latency compensation, volume, repeat count, overdub pass limit
- **Setlist** — named per-song sequences of preset steps, Play / Edit modes, a view of the current step plus the next two, loop-around navigation, an enable/disable toggle to pause device control without losing your place
- **Undo / redo** — Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z, per page: on the Dashboard they revert module settings and layout changes, on the Raccourcis page they revert shortcut changes
- **Réglages (Settings) page** — what is not already in a module's own settings:
  - looper audio: input, output, refresh button, **audio API** (WASAPI / MME / ...), WASAPI exclusive mode, buffer size, and the latency PortAudio actually reports
  - MIDI port: automatic (finds the Mighty) or manual choice
  - theme: light, dark or follow Windows
  - shortcut mode with a link to the Raccourcis page
  - open the settings folder, export / import all settings, reset (Dashboard layout, preset names, or everything)
  - diagnostic report to copy (versions, MIDI ports, audio devices) and the log file
- **Persistent settings** — everything survives a restart and is pushed back to the device on launch

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

Tests are plain Python scripts (no pytest), run headless:

```bash
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe tests\test_audio.py
```

## Project structure

```
melos/
├── main.py                  # entry point: wires MIDI/state/UI, pushes restored settings to the device
├── settings.py              # single JSON settings file (app_settings.json)
├── paths.py                 # data and log file locations
├── diagnostics.py           # diagnostic report (Settings page)
├── docs/protocol_notes.md   # empirically verified MIDI/SysEx protocol
├── midi/                    # protocol constants, listener (QThread), sender, connection monitor, state sync, drum styles, tunings
├── state/                   # AmpState (single source of truth), transport (tempo/quantize), tuner session, undo stacks
├── audio/                   # loop engine (sounddevice callback), audio device/API/buffer config, PortAudio helpers
├── setlist/                 # sequences and playback/navigation
├── shortcuts/               # keyboard shortcuts: action catalogue, key manager, action router
├── ui/                      # Fluent-widgets modules, Dashboard, Settings and Raccourcis pages
└── tests/                   # headless test scripts (fake audio/MIDI)
```

## Roadmap

- **V1 — Core** ✅ presets, setlist, drums, loop station, persistence
- **V2 — UX & reliability** ✅ dashboard, keyboard shortcuts, loop/drum quantization and looper auto-length, live connection status, module redesigns, per-page undo/redo, Settings page
- **V3 — Sheet music & preset editing**: Songsterr-based interactive tab view synced to a YouTube video and MIDI track playback (no Premium subscription), embedded or rebuilt Mighty Editor, preset changes linked to positions on the tab, waveform-based loop visualizer
- **V4 — Hardware & pro audio**: Arduino foot controller, raw + re-amped recording, advanced tab editing (loop/speed/transpose/markers/comments, multi-instrument tracks), a dedicated "Music mode" with a song timeline
- **V5 — AI**: orchestration through JARVIS

## Connection handling

- The app starts with or without the Mighty plugged in. A navigation-bar indicator always shows the connection state, and a banner appears while disconnected.
- Modules stay editable while disconnected; the app state is pushed back to the amp on (re)connection, exactly as at launch.
- The MIDI port is found by keyword by default; the Settings page can pin a specific input/output instead (no silent fallback if the chosen port is missing).
- The loop station follows the amp's USB audio interface: stream stopped (in-progress take cancelled, existing tracks kept) on disconnection, restarted on reconnection.

## Audio latency

The stream asks for the device's **low** latency (PortAudio's default is the "high" one, 100 ms+ per direction with MME). On Windows, **WASAPI** (selected automatically when available) is much faster than MME; WASAPI exclusive mode goes lower still but takes the sound card away from other apps. The Settings page shows the latency PortAudio reports for the open stream. The looper's "latency compensation" only shifts the *recorded* content of takes — it never moves the click, the display or the drums.

## Keyboard shortcuts

- Three modes — off, active window only, or global (work while another window has focus) — switchable from the navigation bar and the **Raccourcis** page. **No default keys**: you pick them on that page (Échap cancels a capture; a key already used by another action is refused).
- Actions: presets 1–7, next/previous, the loop station — one cyclic key (record → play → overdub) **and** separate keys (record, overdub, play/stop, clear) — plus **drums on/off** and **metronome on/off**. Clear only fires when its key is **held ~1 s**.
- Next/previous follow the setlist when it is active (switch on + a sequence with steps), otherwise they step through the presets (wrapping).
- Shortcuts drive the view you are looking at (Dashboard and Classique have separate loop stations and setlists); on the Raccourcis page they keep driving the last one visited.
- A single bare letter/digit/Space/Enter fires everywhere while shortcuts are on — the page warns about it; prefer F-keys or a Ctrl/Alt combination.

## Known protocol quirks

- MIDI port names aren't stable on Windows (`NUX NMP-03 0`, `2- NUX NMP-03`...) — ports are found by keyword, never by exact name (unless pinned manually in Settings).
- Presets send no confirmation echo for host-issued commands — the UI updates optimistically instead of waiting on the device.
- Tuner CC 12 is the pitch class counted from A (0 = A, 5 = D, 7 = E, 10 = G, 2 = B), without octave; CC 72 ≈ 50 when in tune (cents, with a small per-note offset on some notes, e.g. B); CC 71 always reads 0; CC 11 reflects signal detection rather than the enable state — the on/off switch is driven by a local flag instead.
- The Plug Pro has no hardware looper — looping is entirely software-side (`sounddevice`).

See `docs/protocol_notes.md` for the full empirically verified MIDI/SysEx reference.