"""Page Réglages : audio (périphériques, tampon, actualisation), port MIDI, thème, raccourcis, données, diagnostic."""
import faulthandler; faulthandler.dump_traceback_later(60, exit=True)
import os, sys, time, tempfile, pathlib, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

TMP = pathlib.Path(tempfile.mkdtemp())
import paths
paths.SETTINGS_FILE = TMP / "app_settings.json"
paths.PRESET_NAMES_FILE = TMP / "preset_names.json"
paths.SETLISTS_FILE = TMP / "setlists.json"
paths.LOG_FILE = TMP / "melos_debug.log"
import settings
settings.SETTINGS_FILE = paths.SETTINGS_FILE

import mido
MIDI = {"in": ["Loopback 0", "NUX NMP-03 0"], "out": ["GS Wavetable 0", "NUX NMP-03 1"]}
mido.get_input_names = lambda: list(MIDI["in"])
mido.get_output_names = lambda: list(MIDI["out"])
class FakePort:
    def __init__(self, name): self.name = name
    def iter_pending(self): return []
    def send(self, m): pass
    def close(self): pass
mido.open_input = mido.open_output = lambda name: FakePort(name)

import sounddevice as sd
DEV = [{"name": "Micro PC", "max_input_channels": 2, "max_output_channels": 0},
       {"name": "Haut-parleurs PC", "max_input_channels": 0, "max_output_channels": 2},
       {"name": "Microphone (NUX NMP-03)", "max_input_channels": 2, "max_output_channels": 0},
       {"name": "Haut-parleurs (NUX NMP-03)", "max_input_channels": 0, "max_output_channels": 2}]
sd.query_devices = lambda: list(DEV)
STREAMS = []
class FakeStream:
    def __init__(self, **kw): self.kw = kw; self.active = False; STREAMS.append(self)
    def start(self): self.active = True
    def stop(self): self.active = False
    def close(self): self.active = False
sd.Stream = FakeStream
sd._terminate = lambda: None; sd._initialize = lambda: None

from unittest.mock import MagicMock
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import isDarkTheme
from fake_keyboard import FakeKeyboard
from midi.connection_monitor import ConnectionMonitor
from shortcuts.manager import ShortcutManager
from state.amp_state import AmpState
from ui.main_window import MainWindow
from settings import load_settings, update_settings
app = QApplication([])
def pump(sec=0.1):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

mon = ConnectionMonitor(MagicMock(), MagicMock())
mon.list_ports = lambda: (list(MIDI["in"]), list(MIDI["out"]))
applied = []
mon.apply_preferences = lambda: (mon.reload_preferences(), applied.append(dict(mon.__dict__.get("mode") and {"m": mon.mode})))
state = AmpState(); sender = MagicMock()
mgr = ShortcutManager(backend=FakeKeyboard())
win = MainWindow(state, sender, mgr, mon); win.resize(1150, 900); win.show(); pump(0.4)
S = win.settings_interface
def goto(page):
    win.stackedWidget.setCurrentWidget(page); pump(0.5)

# la page existe dans la navigation
goto(S); assert win.stackedWidget.currentWidget() is S
print("1. page Réglages dans la navigation : OK")

# ---- 2. audio ----
assert S._in_combo.count() == 2 and S._out_combo.count() == 2
assert S._block_combo.count() == 5
assert STREAMS[-1].active and STREAMS[-1].kw["blocksize"] == 256
n = len(STREAMS)
S._in_combo.setCurrentIndex(1); pump(0.1)
assert len(STREAMS) > n and STREAMS[-1].kw["device"][0] == 2 and STREAMS[-1].active
assert load_settings()["loop"]["input_device_name"] == "Microphone (NUX NMP-03)"
S._out_combo.setCurrentIndex(1); pump(0.1)
assert STREAMS[-1].kw["device"] == (2, 3)
S._block_combo.setCurrentIndex(1); pump(0.1)          # 128
assert STREAMS[-1].kw["blocksize"] == 128 and load_settings()["loop"]["blocksize"] == 128
# les deux vues du looper suivent (pas de combos, même moteur)
assert not hasattr(win.dashboard_interface.loop_panel, "_input_combo")
assert win.dashboard_interface.loop_panel._audio is win.home_interface.loop_panel._audio is win._audio
# le panneau looper n'écrase pas la sélection quand il enregistre ses propres réglages
win.dashboard_interface.loop_panel._repeat_spin.setValue(3); pump(0.1)
lp = load_settings()["loop"]
assert lp["input_device_name"] == "Microphone (NUX NMP-03)" and lp["blocksize"] == 128 and lp["repeat_target"] == 3
print("2. entrée / sortie / tampon : flux relancé, mémorisé, non écrasé par le looper : OK")

# ---- 3. actualisation ----
DEV.append({"name": "Interface USB", "max_input_channels": 2, "max_output_channels": 2})
S._refresh_btn.click(); pump(0.4)
assert S._in_combo.count() == 3 and S._out_combo.count() == 3
assert S._in_combo.currentText() == "Microphone (NUX NMP-03)", "la sélection est conservée"
assert STREAMS[-1].active and S._refresh_btn.isEnabled()
print("3. bouton Actualiser : nouvelle interface listée, sélection gardée, flux relancé : OK")

# ---- 4. MIDI ----
assert S._midi_mode.currentRouteKey() == "auto" and not S._midi_in.isEnabled()
assert mon.mode == "auto"
S._midi_mode.setCurrentItem("manual"); S._on_midi_mode("manual"); pump(0.05)
assert S._midi_in.isEnabled() and S._midi_in.currentText() == "NUX NMP-03 0"   # préselection du Mighty
cfg = load_settings()["midi"]
assert cfg["mode"] == "manual" and cfg["input_name"] == "NUX NMP-03 0" and mon.mode == "manual"
S._midi_in.setCurrentIndex(0); pump(0.05)
assert load_settings()["midi"]["input_name"] == "Loopback 0" and mon.manual_in == "Loopback 0"
MIDI["in"].remove("Loopback 0"); S._fill_midi()
assert "(absent)" in S._midi_in.currentText()
S._on_midi_mode("auto"); assert load_settings()["midi"]["mode"] == "auto" and mon.mode == "auto"
print("4. port MIDI auto / manuel, port absent signalé : OK")

# ---- 5. moniteur réel : choix manuel respecté, reconnexion forcée ----
MIDI["in"][:] = ["Loopback 0", "NUX NMP-03 0", "NUX NMP-03 2"]; MIDI["out"][:] = ["NUX NMP-03 1", "NUX NMP-03 3"]
update_settings({"midi": {"mode": "manual", "input_name": "NUX NMP-03 2", "output_name": "NUX NMP-03 3"}})
listener, snd = MagicMock(), MagicMock()
real = ConnectionMonitor(listener, snd, poll_interval=0.02, settle_delay=0.01)
assert real.try_connect() and real.current_ports == ("NUX NMP-03 2", "NUX NMP-03 3")
update_settings({"midi": {"mode": "auto", "input_name": None, "output_name": None}})
real.apply_preferences(); assert real._tick() is True and not real.connected     # lien refermé
assert real._tick() is True and real.connected and real.current_ports == ("NUX NMP-03 0", "NUX NMP-03 1")
update_settings({"midi": {"mode": "manual", "input_name": "absent", "output_name": "absent"}})
real.apply_preferences(); real._tick(); real._tick()
assert not real.connected                                                      # port manuel introuvable : pas de repli
print("5. moniteur : port manuel respecté, reconnexion forcée, pas de repli silencieux : OK")

# ---- 6. thème ----
S._on_theme("dark"); pump(0.1)
assert load_settings()["ui"]["theme"] == "dark" and isDarkTheme()
S._on_theme("light"); pump(0.1)
assert load_settings()["ui"]["theme"] == "light" and not isDarkTheme()
S._on_theme("auto")
assert load_settings()["ui"]["theme"] == "auto"
print("6. thème clair / sombre / Windows : OK")

# ---- 7. raccourcis ----
assert "Mode actuel" in S._shortcuts_mode.text()
mgr.set_mode("window"); assert "Fenêtre active" in S._shortcuts_mode.text()
S.open_shortcuts_requested.emit(); pump(0.5)
assert win.stackedWidget.currentWidget() is win.shortcuts_interface
goto(S)
print("7. mode des raccourcis affiché + lien vers la page : OK")

# ---- 8. export / import ----
S._confirm = lambda *a: True
state.set_drum_style(12); update_settings({"transport": {**load_settings()["transport"], "bpm": 133}})
paths.PRESET_NAMES_FILE.write_text(json.dumps({"0": "Clean"}))
import ui.preset_panel as pp
pp.NAMES_FILE.write_text(json.dumps({"0": "Clean"}))
out = TMP / "export.json"
assert S.export_settings(str(out))
bundle = json.loads(out.read_text(encoding="utf-8"))
assert bundle["format"] == "melos-settings" and bundle["settings"]["transport"]["bpm"] == 133 and bundle["preset_names"] == {"0": "Clean"}
update_settings({"transport": {**load_settings()["transport"], "bpm": 90}}); pp.NAMES_FILE.write_text("{}")
assert S.import_settings(str(out)); pump(0.2)
assert load_settings()["transport"]["bpm"] == 133 and json.loads(pp.NAMES_FILE.read_text()) == {"0": "Clean"}
assert win.dashboard_interface.preset_panel._names == {0: "Clean"}
bad = TMP / "bad.json"; bad.write_text('{"x": 1}')
before = load_settings()
assert not S.import_settings(str(bad)) and load_settings() == before
bad.write_text("pas du json"); assert not S.import_settings(str(bad))
print("8. export / import : aller-retour, noms rechargés, fichier invalide refusé : OK")

# ---- 9. réinitialisations ----
d = win.dashboard_interface
default = d._default_layout
d._dock_area.resize_docks(["presets", "loop"], [300, 780], Qt.Horizontal); pump(0.6)
d.save_layout(); pump(0.1)
moved = d._dock_area.layout_snapshot()
assert moved != default, "le test doit d'abord changer l'agencement"
goto(win.dashboard_interface); moved_loop = d._dock_area.module_geometry("loop").width()
assert moved_loop > 740, moved_loop
win._play_stack._undo.clear()
S.reset("dashboard"); pump(0.3)
w_of = lambda: {m: d._dock_area.module_geometry(m) for m in ("presets", "loop", "tempo", "tuner")}
after = w_of()
assert d._dock_area.layout_snapshot() != moved
win.undo_redo(False); pump(0.3)
assert d._dock_area.layout_snapshot() != after, "Ctrl+Z annule la réinitialisation"
assert abs(d._dock_area.module_geometry("loop").width() - moved_loop) <= 3
goto(S)
S._confirm = lambda *a: False
pp.NAMES_FILE.write_text(json.dumps({"1": "Lead"}))
assert not S.reset("names") and json.loads(pp.NAMES_FILE.read_text()) == {"1": "Lead"}       # refus : rien ne bouge
S._confirm = lambda *a: True
assert S.reset("names") and json.loads(pp.NAMES_FILE.read_text()) == {}
assert win.dashboard_interface.preset_panel._names == {}
paths.SETLISTS_FILE.write_text('{"sequences": []}')
update_settings({"transport": {**load_settings()["transport"], "bpm": 77}, "ui": {"theme": "dark"}})
assert S.reset("all"); pump(0.2)
assert load_settings()["transport"]["bpm"] == 100 and load_settings()["ui"]["theme"] == "auto"
assert paths.SETLISTS_FILE.read_text() == '{"sequences": []}'
print("9. réinitialiser Dashboard / noms / tout (avec confirmation, setlists conservées) : OK")

# ---- 10. diagnostic ----
opened = []
S._open_path = lambda p: opened.append(str(p)) or True
S._open_folder(); assert opened[-1] == str(paths.SETTINGS_FILE.parent)
assert not S.open_log()                                    # pas encore de log
paths.LOG_FILE.write_text("log"); assert S.open_log() and opened[-1] == str(paths.LOG_FILE)
text = S.copy_report()
assert QApplication.clipboard().text() == text
for needle in ("PySide6", "mido", "Entrées :", "NUX NMP-03 1", "Haut-parleurs (NUX NMP-03)", "Tampon", "Python"):
    assert needle in text, needle
print("10. dossier, log, rapport copié (versions, ports MIDI, périphériques audio) : OK")

# ---- 11. Ctrl+Z sans effet sur la page Réglages ----
goto(S)
assert win.undo_redo(False) == "" and win.undo_redo(True) == ""
print("11. annuler / rétablir inactif sur la page Réglages : OK")

print("\nSETTINGS PAGE OK")
import sounddevice as _sd
_sd._initialized = 0
