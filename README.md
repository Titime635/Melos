# Mighty Control

Python-based performance software for the NUX Mighty Plug Pro, turning the amp into a complete stage and studio ecosystem. It features a synchronized looper, automatic preset changes, and an integrated workflow designed for live performance and music creation.

## Status

**V1 and V2 complete, V3 in progress.** The **Partition** tab (Songsterr tabs synced with the original recording or played by a MIDI synthesizer) works; next up are preset-change markers on the score, then the Mighty Editor. A few device-side details (tuner reference byte, drum tempo SysEx) are still being validated on real hardware.

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
- **Partition (sheet music)** — search a song by name (or paste a Songsterr link) and get its tablature, scrolling and highlighting the current bar in sync with the music; see [Partition tab](#partition-tab) below
- **Persistent settings** — everything survives a restart and is pushed back to the device on launch

## Stack

- Python 3.12 (required — `python-rtmidi` has no PyPI wheel beyond 3.12)
- PySide6 + PySide6-Fluent-Widgets (UI)
- `mido` / `python-rtmidi` (MIDI)
- `sounddevice` (loop station audio)
- `keyboard` (global keyboard shortcuts)
- QtWebEngine (part of PySide6) hosting [alphaTab](https://alphatab.net) for score rendering and MIDI synthesis
- `python-mpv` + `mpv-2.dll` (libmpv) for the original audio, with `yt-dlp` resolving the stream

## Getting started

```bash
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tools\setup_deps.py
.venv\Scripts\python.exe main.py
```

`tools\setup_deps.py` is the one extra step after a clone or a pull on a new computer: it downloads the large files that are **not in git** (see [Files not in git](#files-not-in-git)). It only fetches what is missing (`--force` re-downloads everything), and `main.py` prints a warning at startup if something is absent.

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
├── tabs/                    # Partition tab back end (see below): Songsterr client + parser, alphaTex export, lyrics,
│   │                        #   video sync, stem mixer, mpv player (own process), local web server
│   ├── web/tab_view.html    # the score page (alphaTab): layout, cursor, MIDI synthesizer, mixer, JS<->Python bridge
│   └── vendor/              # downloaded, not in git: alphaTab, Bravura font, soundfonts (.sf2)
├── shortcuts/               # keyboard shortcuts: action catalogue, key manager, action router
├── ui/                      # Fluent-widgets modules, Dashboard, Settings, Raccourcis and Partition pages
├── tools/                   # setup_deps.py and the fetch_*.py download scripts, codec/mpv checks, Songsterr probe
└── tests/                   # headless test scripts (fake audio/MIDI)
```

## Roadmap

- **V1 — Core** ✅ presets, setlist, drums, loop station, persistence
- **V2 — UX & reliability** ✅ dashboard, keyboard shortcuts, loop/drum quantization and looper auto-length, live connection status, module redesigns, per-page undo/redo, Settings page
- **V3 — Sheet music & preset editing** *(in progress)*: ✅ Songsterr tab view synced to the original recording, ✅ solo/mute of instruments, ✅ lyrics, ✅ MIDI synthesis of the score with soundfont choice and instrument variants; to do: preset changes linked to positions on the tab, embedded or rebuilt Mighty Editor, waveform-based loop visualizer
- **V4 — Hardware & pro audio**: Arduino foot controller, raw + re-amped recording, advanced tab editing (loop/speed/transpose/markers/comments, multi-instrument tracks), a dedicated "Music mode" with a song timeline
- **V5 — AI**: orchestration through JARVIS

## Partition tab

Personal use: tablatures belong to Songsterr and their authors; they are cached locally (`tabs_cache/`) and never redistributed. Songsterr's endpoints are undocumented and may change (`tools/songsterr_probe.py` re-probes them). No audio is downloaded or stored.

- **Search** — type a song name in the field (a result list opens under it, mouse or arrows + Enter) or paste a Songsterr link.
- **Score** — rendered by alphaTab inside QtWebEngine in two passes (natural bar widths, then a fit to the window); one instrument at a time, switched from the track list without interrupting the sound. The current bar follows the music; lyrics are placed under the notes of every track, aligned on the vocal line.
- **Two sound sources, one switch (Original / Synthèse)**; position and play state are kept when switching.
  - *Original* — the real recording, played by mpv audio-only in a separate process (own controls bar: play, seek, speed 0.25×–1.5×, volume). Songsterr publishes several videos synchronised on the same bars (full mix, isolated instruments, backing track): the track list's **solo / mute** buttons pick the video that matches, and are only enabled for combinations that exist. *Association des pistes* lets you map an audio stem to an instrument by hand (remembered per song).
  - *Synthèse* — the whole score played by alphaTab's synthesizer (all instruments, not only the displayed one). **Solo / mute / volume per instrument** (remembered per song), metronome, count-in, loop (drag over bars to select a range, otherwise the whole song), speed, click on the score to seek, and **Export MIDI**. A **soundfont menu** appears when several `.sf2` banks are installed; **GeneralUser GS** is the default, Sonivox the light fallback.
  - *Instrument variants* — each track uses the General MIDI program of its first Songsterr sound (distortion, overdriven, clean... are different programs), and sound changes made mid-song (`trackSoundAutomations`) are applied at the right beat. Drum accents and ghost notes are kept.

## Files not in git

Too big or reproducible, so they are in `.gitignore` and installed by `tools\setup_deps.py` (or by each script alone):

| File | Size | Script | Used for |
|---|---|---|---|
| `mpv-2.dll` (repo root) | ~115 MB | `tools\fetch_libmpv.py` | original audio (libmpv, Windows 64-bit, shinchiro builds) |
| `tabs/vendor/alphatab/` (alphaTab 1.8.4, Bravura font, Sonivox soundfont) | ~5 MB | `tools\fetch_alphatab.py` | score rendering and synthesizer |
| `tabs/vendor/alphatab/soundfont/GeneralUser-GS.sf2` | ~32 MB | `tools\fetch_soundfonts.py` | better synthesis sounds (optional) |

Other local files that are also ignored: `app_settings.json`, `setlists.json`, `tabs_cache/`, `web_profile/` (QtWebEngine profile), `probe_out/`, `melos_lyrics.txt` and the `*.log` files. To add another `.sf2` bank, drop it in `tabs/vendor/alphatab/soundfont/`: it shows up in the soundfont menu.

## Third-party components

[alphaTab](https://alphatab.net) (MPL-2.0), Bravura font (SIL OFL), Sonivox soundfont bundled with alphaTab, [GeneralUser GS](https://github.com/mrbumpy409/GeneralUser-GS) by S. Christian Collins (its own free-use license), [mpv](https://mpv.io) / libmpv, Songsterr data for personal use.

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