"""Annuler / rétablir par page : réglages des modules, agencement du Dashboard, raccourcis."""
import os, sys, time, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"
import setlist.model
setlist.model.SETLISTS_FILE = pathlib.Path(tempfile.mkdtemp()) / "setlists.json"
import sounddevice as sd
sd.query_devices = lambda: [
    {"name": "Micro PC", "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Haut-parleurs PC", "max_input_channels": 0, "max_output_channels": 2},
]
class FakeStream:
    def __init__(self, **kw): self.active = False
    def start(self): self.active = True
    def stop(self): self.active = False
    def close(self): self.active = False
sd.Stream = FakeStream

from unittest.mock import MagicMock
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from fake_keyboard import FakeKeyboard
from shortcuts.manager import ShortcutManager
from state.amp_state import AmpState
from state.undo import UndoStack
from ui.main_window import MainWindow
from shortcuts.manager import typing_in_app
app = QApplication([])
def pump(sec=0.1):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

# ---- 1. pile : fusion des glissements, undo / redo, nouvelle action vide le redo ----
log = []
st = UndoStack(lambda kind, v: log.append(v) or True)
st.record("s", "bpm", 100, 101); st.record("s", "bpm", 101, 105); st.record("s", "bpm", 105, 110)
assert len(st._undo) == 1 and st._undo[0].before == 100 and st._undo[0].after == 110
st.record("s", "bpm", 110, 100)                       # retour au départ : l'entrée disparaît
assert not st.can_undo()
st.record("s", "x", 1, 2); time.sleep(0.01); st._undo[-1].t = 0   # n'est plus fusionnable
st.record("s", "y", 5, 6)
assert st.undo().key == "y" and log[-1] == 5
assert st.undo().key == "x" and log[-1] == 1 and not st.can_undo()
assert st.redo().key == "x" and log[-1] == 2
st.record("s", "z", 0, 1); assert not st.can_redo()
print("1. pile d'annulation : fusion, undo, redo : OK")

# ---- 2. fenêtre complète ----
state = AmpState(); sender = MagicMock()
kb = FakeKeyboard()
mgr = ShortcutManager(backend=kb)
win = MainWindow(state, sender, mgr); win.resize(1150, 800); win.show(); pump(0.4)
T = state.transport
def goto(page):
    win.stackedWidget.setCurrentWidget(page); pump(0.5)
    assert win.stackedWidget.currentWidget() is page

def press(key, mods=Qt.ControlModifier):
    QTest.keyClick(win, key, mods); pump(0.05)

T.set(bpm=100); pump(0.05)
win._play_stack._undo.clear(); win._play_stack._redo.clear()
for v in (101, 110, 120): T.set(bpm=v)
T.set(beats=3); win._play_stack._undo[-1].t = 0
T.set(sync_drums=not T.sync_drums)
press(Qt.Key_Z)                                       # annule la synchro batterie
press(Qt.Key_Z); assert T.beats == 4, T.beats           # annule la mesure
press(Qt.Key_Z); assert T.bpm == 100, T.bpm            # annule le glissement (une seule entrée)
press(Qt.Key_Y); assert T.bpm == 120
press(Qt.Key_Z); press(Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)  # Ctrl+Maj+Z = rétablir
assert T.bpm == 120
print("2. Ctrl+Z / Ctrl+Y / Ctrl+Maj+Z sur le tempo : OK")

# ---- 3. batterie : l'ordre MIDI est renvoyé ----
sender.reset_mock()
base = state.drum_style
state.set_drum_style(base + 3); win._play_stack._undo[-1].t = 0
press(Qt.Key_Z)
assert state.drum_style == base
sender.drum_set_style.assert_called_with(base)
print("3. style de batterie annulé (état + MIDI) : OK")

# ---- 4. tempo verrouillé par une boucle : annulation refusée, entrée conservée ----
win._play_stack._undo.clear(); win._play_stack._redo.clear()
T.set(bpm=90)
win._loop_engine._tracks.append(object())               # une boucle existe
txt = win.undo_redo(False)
assert T.bpm == 90 and "boucle" in txt, (T.bpm, txt)
win._loop_engine._tracks.clear()
win.undo_redo(False); assert T.bpm != 90
print("4. tempo verrouillé par la boucle : refus puis annulation possible : OK")

# ---- 5. "bars" (réglé par la boucle) n'est pas annulable ----
win._play_stack._undo.clear(); T.set(bars=3)
assert not win._play_stack.can_undo()
print("5. longueur auto de la boucle non enregistrée : OK")

# ---- 6. agencement du Dashboard : seulement sur le Dashboard ----
dash = win.dashboard_interface
goto(dash)
dash.save_layout(); win._play_stack._undo.clear(); win._play_stack._redo.clear(); pump(0.1)
dash._dock_area._on_delete_requested(dash._dock_area._docks["setlist"]); dash.save_layout()
assert win._play_stack.can_undo() and "setlist" in dash._dock_area.hidden_modules
goto(win.home_interface)
win.undo_redo(False)                                    # sur Classique : ne touche pas à l'agencement
assert "setlist" in dash._dock_area.hidden_modules
goto(dash)
win.undo_redo(False); pump(0.1)
assert "setlist" not in dash._dock_area.hidden_modules, "module rajouté par l'annulation"
assert settings.load_settings()["dashboard"]["hidden"] == []
win.undo_redo(True); pump(0.1)
assert "setlist" in dash._dock_area.hidden_modules
print("6. agencement du Dashboard annulé / rétabli (Dashboard uniquement) : OK")

# ---- 7. page Raccourcis : sa propre pile ----
goto(dash)
n_play = len(win._play_stack._undo)
goto(win.shortcuts_interface)
assert mgr.assign("nav_next", "f5", 0) is None
assert len(win._play_stack._undo) == n_play and win._shortcuts_stack.can_undo()
assert mgr.assign("nav_next", "f6", 1) is None
win.undo_redo(False); assert mgr.keys_for("nav_next") == ["f5", ""], mgr.keys_for("nav_next")
win.undo_redo(False); assert mgr.keys_for("nav_next") == ["", ""]
win.undo_redo(True); assert mgr.keys_for("nav_next")[0] == "f5"
old = mgr.mode; new = "global" if old != "global" else "off"
mgr.set_mode(new); assert win._shortcuts_stack.can_undo()
win.undo_redo(False); assert mgr.mode == old, (mgr.mode, old)
assert T.bpm is not None and len(win._play_stack._undo) == n_play, "la pile du jeu n'a pas bougé"
print("7. raccourcis : pile séparée, touches et mode annulés / rétablis : OK")

# ---- 8. aucune annulation pendant la saisie ou la capture ----
goto(dash)
T.set(bpm=77); win._play_stack._undo[-1].t = 0
win.activateWindow(); pump(0.1)
spin = dash._loop_panel._bars_spin; spin.setFocus(); pump(0.1)
assert typing_in_app(), "le SpinBox a le focus"
assert win.undo_redo(False) == "" and T.bpm == 77
spin.clearFocus(); win.setFocus()
mgr._capturing = True
assert win.undo_redo(False) == "" and T.bpm == 77
mgr._capturing = False
print("8. champ de saisie / capture de touche : Ctrl+Z laissé tranquille : OK")

win.close(); pump(0.1)
print("\nUNDO OK")
import sounddevice as _sd
_sd._initialized = 0