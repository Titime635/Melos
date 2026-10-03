import os, sys, time, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "s.json"
settings.save_settings({**settings.load_settings(), "loop": {**settings.load_settings()["loop"],
    "input_device_name": "Microphone (2- NUX NMP-03)", "output_device_name": "Haut-parleurs (2- NUX NMP-03)"}})

import sounddevice as sd
class Env:
    nux_present = True
    streams = []
    terminate_calls = 0
def devices():
    d = [{"name": "Micro intégré", "max_input_channels": 2, "max_output_channels": 0},
         {"name": "Haut-parleurs PC", "max_input_channels": 0, "max_output_channels": 2}]
    if Env.nux_present:
        d += [{"name": "Microphone (2- NUX NMP-03)", "max_input_channels": 2, "max_output_channels": 0},
              {"name": "Haut-parleurs (2- NUX NMP-03)", "max_input_channels": 0, "max_output_channels": 2}]
    return d
sd.query_devices = devices
class FakeStream:
    def __init__(self, **kw): self.kw = kw; self.active = False; Env.streams.append(self)
    def start(self): self.active = True
    def stop(self): self.active = False
    def close(self): self.active = False
sd.Stream = FakeStream
def term(): Env.terminate_calls += 1
sd._terminate = term; sd._initialize = lambda: None

from PySide6.QtWidgets import QApplication
app = QApplication([])
from ui.loop_panel import LoopPanel
def pump(sec):
    t0 = time.time()
    while time.time() - t0 < sec: app.processEvents(); time.sleep(0.01)

p = LoopPanel(); pump(0.1)
assert Env.streams[-1].active and p._audio_ok
assert p._input_combo.currentText() == "Microphone (2- NUX NMP-03)"
print("a. démarrage sur l'interface du Mighty : OK")

p._engine._state = "recording"; p._engine._record_chunks = [1]
Env.nux_present = False
p.on_device_availability_changed(False, "NUX NMP-03"); pump(0.1)
assert not Env.streams[-1].active and not p._audio_ok
assert p._engine.state == "idle" and p._engine._record_chunks == []
assert "déconnectée" in p._status_label.text()
print("b. déconnexion pendant un enregistrement : flux coupé, prise annulée, message : OK")

n = len(Env.streams)
p.on_device_availability_changed(True, "NUX NMP-03"); pump(0.2)
assert not p._audio_ok, "interface pas encore listée : doit réessayer"
Env.nux_present = True
pump(2.0)
assert p._audio_ok and Env.streams[-1].active and len(Env.streams) > n
assert p._input_combo.currentText() == "Microphone (2- NUX NMP-03)"
assert Env.terminate_calls >= 2
print("c. retour de l'audio après quelques tentatives : flux relancé sur la bonne interface : OK")

# interface non-Mighty sélectionnée : ignorer la déconnexion
p._input_combo.blockSignals(True); p._output_combo.blockSignals(True)
p._input_combo.setCurrentText("Micro intégré"); p._output_combo.setCurrentText("Haut-parleurs PC")
p._input_combo.blockSignals(False); p._output_combo.blockSignals(False)
p._start_engine()
p.on_device_availability_changed(False, "NUX NMP-03"); pump(0.1)
assert p._audio_ok and Env.streams[-1].active
print("d. interface audio autre que le Mighty : déconnexion MIDI ignorée : OK")

# déconnexion puis reconnexion rapide : une seule chaîne de tentatives
p2 = LoopPanel(); p2.stop = p2.stop
Env.nux_present = False
p2.on_device_availability_changed(False, "NUX NMP-03")
p2.on_device_availability_changed(True, "NUX NMP-03")
g = p2._restore_generation
p2.on_device_availability_changed(False, "NUX NMP-03")
assert p2._restore_generation == g + 1
print("e. génération de tentatives invalidée à chaque changement : OK")
print("\nAUDIO OK")
