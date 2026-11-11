"""Test du service Qt de l'éditeur (nécessite PySide6 ; boucle d'évènements hors écran)."""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QCoreApplication

from editor.service import EditorService
from test_editor import make_bank


def wait_for(app, cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return cond()


def test_build_editor(tmp):
    """build_editor assemble sender/listener réels : on les remplace par des doublures."""
    import types
    sys.modules["paths"] = types.SimpleNamespace(SETTINGS_FILE=Path(tmp) / "app_settings.json")

    class L:
        def __init__(self):
            self.h = []

        def add_raw_handler(self, fn):
            self.h.append(fn)

    class S:
        is_open = True

    from editor.setup import build_editor
    svc, lib = build_editor(S(), L())
    assert (Path(tmp) / "preset_library").is_dir() and lib.entries() == []
    svc.shutdown()


def test_midi_transport():
    import threading
    import mido
    from editor import wire
    from editor.amp_io import AmpIO, MidiTransport
    from editor.preset import Preset

    class L:
        def add_raw_handler(self, fn):
            self.fn = fn

    class S:
        is_open = True

        def __init__(self, listener):
            self.l = listener
            self.sent = []

        def send_sysex(self, d):
            self.sent.append(list(d))
            if d[3] == wire.SYX_PRESET:       # l'« ampli » répond depuis un autre thread, comme le listener
                data = wire.HEADER + [0x0B, 2, d[5]] + list(Preset.default().data)
                threading.Timer(0.02, lambda: self.l.fn(mido.Message("sysex", data=data))).start()
            return True

        def send_cc(self, c, v):
            return True

        def set_preset(self, n):
            return True

    l = L()
    s = S(l)
    io = AmpIO(MidiTransport(s, l), cc_pause=0)
    assert io.read_slot(2) == Preset.default() and s.sent[0] == wire.HEADER + [0x0B, 2, 2]


def main():
    app = QCoreApplication.instance() or QCoreApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        amp, io, bank = make_bank(tmp)
        svc = EditorService(bank)
        events, errors, busy = [], [], []
        svc.slot_updated.connect(events.append)
        svc.failed.connect(errors.append)
        svc.busy_changed.connect(busy.append)
        loaded = []
        svc.loaded.connect(lambda: loaded.append(1))

        svc.on_connection_changed(True)
        assert wait_for(app, lambda: loaded and busy[-1:] == [False]), (loaded, busy)
        svc.edit(0, lambda p: p.set_param(3, 0, 91))
        assert wait_for(app, lambda: not svc.busy and amp.edit.param(3, 0) == 91)
        assert bank.slots[0].dirty and 0 in events
        svc.on_amp_preset_changed(2)
        amp.pc(2)
        svc.save(0)
        assert wait_for(app, lambda: not svc.busy and amp.flash[0].param(3, 0) == 91), errors
        steps = []
        svc.kit_progress.connect(lambda n, t, s: steps.append((n, t, s)))
        svc.load_kit({3: amp.flash[5].copy(), 4: amp.flash[0].copy()})
        assert wait_for(app, lambda: steps and steps[-1][2] == -1), steps
        assert not errors, errors
        svc.shutdown()
        test_build_editor(tmp)
        test_midi_transport()
    print("test_editor_service OK")


if __name__ == "__main__":
    main()
