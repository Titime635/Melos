import os, sys, time, json, tempfile, pathlib, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"
import setlist.model
setlist.model.SETLISTS_FILE = pathlib.Path(tempfile.mkdtemp()) / "setlists.json"

# ---------------- faux audio : flux dont la fermeture peut se bloquer ----------------
import sounddevice as sd

class Audio:
    nux_present = True
    release = threading.Event()   # débloque les fermetures coincées
    hang_stop = False
    terminate_calls = 0

def devices():
    d = [{"name": "Micro PC", "max_input_channels": 2, "max_output_channels": 0},
         {"name": "Haut-parleurs PC", "max_input_channels": 0, "max_output_channels": 2}]
    if Audio.nux_present:
        d += [{"name": "Microphone (2- NUX NMP-03)", "max_input_channels": 2, "max_output_channels": 0},
              {"name": "Haut-parleurs (2- NUX NMP-03)", "max_input_channels": 0, "max_output_channels": 2}]
    return d

class FakeStream:
    def __init__(self, **kw): self.active = False
    def start(self): self.active = True
    def stop(self):
        if Audio.hang_stop:
            Audio.release.wait(15)   # comme PortAudio sous Windows quand l'interface vient d'être arrachée
        self.active = False
    def close(self): self.active = False

def term(): Audio.terminate_calls += 1
sd.query_devices = devices
sd.Stream = FakeStream
sd._terminate = term
sd._initialize = lambda: None
sd._initialized = 0   # sinon l'atexit de sounddevice boucle sur notre faux _terminate (le test ne se terminerait pas)

settings.update_settings({"loop": {**settings.load_settings()["loop"],
    "input_device_name": "Microphone (2- NUX NMP-03)", "output_device_name": "Haut-parleurs (2- NUX NMP-03)"}})

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit

app = QApplication([])

def pump(sec=0.1):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

def wait_until(cond, timeout=3.0, what=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond(): return
        time.sleep(0.005)
    raise AssertionError("timeout: " + what)

def saved():
    return json.loads(settings.SETTINGS_FILE.read_text(encoding="utf-8"))

from fake_keyboard import FakeKeyboard
from shortcuts import manager as manager_module
from shortcuts.manager import ShortcutManager, typing_in_app
from state.amp_state import AmpState
from midi.sender import MidiSender
from midi import protocol
from audio import portaudio_utils as pa
from audio import system_volume

def new_manager():
    fk = FakeKeyboard()
    m = ShortcutManager(backend=fk)
    trig = []
    m.action_triggered.connect(trig.append)
    return m, fk, trig

# ---------------- 1. les 3 modes ----------------
settings.update_settings({"shortcuts": {"mode": None, "enabled": False, "bindings": {}}})
m, fk, trig = new_manager()
assert m.mode == "off", "ancien réglage enabled=False -> désactivés"
m.shutdown()
settings.update_settings({"shortcuts": {"mode": None, "enabled": True, "bindings": {}}})
m, fk, trig = new_manager()
assert m.mode == "global", "ancien réglage enabled=True -> global"
assert [m.mode for _ in [m.cycle_mode()] ] == ["off"]
m.cycle_mode(); assert m.mode == "window"
m.cycle_mode(); assert m.mode == "global"
m.assign("loop_cycle", "f5")

m.set_mode("window")
m._is_app_active = lambda: False
fk.tap("f5"); pump(0.02)
assert trig == [], "mode fenêtre : rien tant que l'appli n'est pas au premier plan"
m._is_app_active = lambda: True
fk.tap("f5"); pump(0.02)
assert trig == ["loop_cycle"]
m.set_mode("global")
m._is_app_active = lambda: False
fk.tap("f5"); pump(0.02)
assert trig == ["loop_cycle", "loop_cycle"], "mode global : marche même en arrière-plan"
m.set_mode("off")
fk.tap("f5"); pump(0.02)
assert len(trig) == 2 and fk.registered() == []
m.set_mode("window")
assert saved()["shortcuts"]["mode"] == "window"
m.shutdown()
m2, _, _ = new_manager()
assert m2.mode == "window", "le mode est restauré au lancement"
m2.shutdown()
print("1. trois modes (désactivés / fenêtre active / global) : comportement, rotation, persistance, ancien réglage : OK")

# ---------------- 2. une touche liée n'agit plus sur l'appli (espace = minimiser) ----------------
m, fk, trig = new_manager()
m.set_mode("global")
w = QWidget(); lay = QVBoxLayout(w)
btn = QPushButton("b"); edit = QLineEdit()
lay.addWidget(btn); lay.addWidget(edit)
w.show(); w.activateWindow(); btn.setFocus(); pump(0.1)
clicks = []
btn.clicked.connect(lambda: clicks.append(1))

QTest.keyClick(btn, Qt.Key_Space)
assert clicks == [1], "sans raccourci lié, Espace actionne le bouton focalisé (comportement Qt normal)"
m.assign("loop_play", "space")
QTest.keyClick(btn, Qt.Key_Space)
assert clicks == [1], "Espace lié : le bouton focalisé (ex. 'réduire' de la barre de titre) ne doit plus réagir"
QTest.keyClick(btn, Qt.Key_Return)
assert clicks == [1, 1] or clicks == [1], "Entrée n'est pas liée : inchangé"
n = len(clicks)
m.set_mode("off")
QTest.keyClick(btn, Qt.Key_Space)
assert len(clicks) == n + 1, "désactivés : plus rien n'est avalé"
m.set_mode("window")
QTest.keyClick(btn, Qt.Key_Space)
assert len(clicks) == n + 1, "fenêtre active : avalé aussi"

def key(k, mods=Qt.NoModifier): return QKeyEvent(QEvent.KeyPress, k, mods)
m.assign("loop_play", None)
m.assign("loop_cycle", "ctrl+f5")
assert m.swallows(key(Qt.Key_F5, Qt.ControlModifier)) and not m.swallows(key(Qt.Key_F5))
assert not m.swallows(key(Qt.Key_F5, Qt.ControlModifier | Qt.ShiftModifier))
assert not m.swallows(key(Qt.Key_Control)), "une touche modificatrice seule n'est jamais avalée"
m.assign("loop_cycle", "left ctrl+f5")
assert m.swallows(key(Qt.Key_F5, Qt.ControlModifier)), "gauche/droite confondus"
m.assign("loop_cycle", None)

# saisie dans un champ de texte : la touche liée lui appartient
m.set_mode("global"); m.assign("loop_play", "space")
edit.setFocus(); pump(0.1)
if not typing_in_app():                     # certaines plateformes de test ne donnent pas le focus
    manager_module.typing_in_app = lambda: True
    globals()["typing_in_app"] = manager_module.typing_in_app
QTest.keyClick(edit, Qt.Key_Space)
assert edit.text() == " ", "on doit pouvoir taper un espace dans un champ de texte même si Espace est lié"
m._is_app_active = lambda: True
before = len(trig)
fk.tap("space"); pump(0.02)
assert len(trig) == before, "taper dans un champ de texte ne doit pas déclencher l'action"
manager_module.typing_in_app = lambda: False
fk.tap("space"); pump(0.02)
assert len(trig) == before + 1, "hors champ de texte : l'action se déclenche"
m.shutdown(); w.close()
print("2. touche liée : n'agit plus sur les boutons de l'appli, mais reste tapable dans les champs de texte : OK")
import importlib; importlib.reload(manager_module)
from shortcuts.manager import ShortcutManager, typing_in_app

# ---------------- 3. setlist : interrupteur partagé entre les deux vues (bug avant/après) ----------------
from setlist.model import Sequence, Step, save_sequences
save_sequences([Sequence("Morceau", [Step(2, "A"), Step(6, "B")])])
settings.update_settings({"setlist": {"active_sequence_name": "Morceau", "enabled": True},
                          "shortcuts": {"mode": "global", "enabled": True, "bindings": {}}})
from ui.main_window import MainWindow
import ui.main_window as mw
state = AmpState(); sender = MidiSender()
m, fk, trig = new_manager()
window = MainWindow(state, sender, m); window.show(); pump(0.15)
m.assign("nav_next", "f7"); m.assign("nav_previous", "f8")
dash, home = window.dashboard_interface, window.home_interface
assert dash.setlist_panel.is_navigation_active() and home.setlist_panel.is_navigation_active()
fk.tap("f7"); pump(0.05)
assert state.current_preset == 6, "setlist active : suivant = étape 2 (preset 7)"

dash.setlist_panel._enabled_switch.setChecked(False); pump(0.05)
assert not home.setlist_panel._enabled_switch.isChecked(), "l'interrupteur de l'autre vue doit suivre"
assert not state.setlist_enabled and saved()["setlist"]["enabled"] is False
seq = []
for _ in range(5):
    fk.tap("f7"); pump(0.03); seq.append(state.current_preset)
assert seq == [0, 1, 2, 3, 4], f"setlist coupée : suivant parcourt les presets un par un, pas 3<->7 : {seq}"
window.switchTo(home); pump(0.1)
assert window.active_view() is home and not home.setlist_panel.is_navigation_active()
seq = []
for _ in range(4):
    fk.tap("f8"); pump(0.03); seq.append(state.current_preset)
assert seq == [3, 2, 1, 0], f"onglet Classique, setlist coupée : précédent parcourt les presets : {seq}"
home.setlist_panel._enabled_switch.setChecked(True); pump(0.05)
assert dash.setlist_panel._enabled_switch.isChecked() and dash.setlist_panel.is_navigation_active()
print("3. setlist coupée : avant/après parcourent les presets, interrupteur partagé Dashboard/Classique : OK")

# ---------------- 4. volume batterie : plage utilisable ----------------
vals = [protocol.drum_level_from_percent(p) for p in range(101)]
assert vals[0] == 0 and vals[100] == protocol.DRUM_LEVEL_CC_CAP and vals == sorted(vals)
assert max(vals) < 40, "le plafond doit rester bien en dessous de ce qui est 'insupportable'"
assert vals[50] <= 12, "mi-course = volume modéré"
for v in range(protocol.DRUM_LEVEL_CC_CAP + 1):
    assert abs(protocol.drum_level_from_percent(protocol.drum_percent_from_level(v)) - v) <= 1
assert protocol.drum_percent_from_level(127) == 100 and protocol.drum_percent_from_level(0) == 0

settings.update_settings({"drum": {**settings.load_settings()["drum"], "level": 55}})
assert AmpState().drum_level == protocol.DRUM_LEVEL_CC_CAP, "ancienne valeur trop forte : ramenée au plafond"

from ui.drum_panel import DrumPanel
sent = []
class SpySender(MidiSender):
    def drum_set_level(self, level): sent.append(level)
st = AmpState(); dp = DrumPanel(st, SpySender()); dp.show(); pump(0.05)
assert dp._level_slider.value() == 100, "valeur sauvegardée plafonnée : le curseur démarre à fond"
dp._level_slider.setValue(99); dp._level_slider.setValue(100)
assert sent[-1] == protocol.DRUM_LEVEL_CC_CAP and st.drum_level == sent[-1]
dp._level_slider.setValue(50);  assert sent[-1] == vals[50] and dp._level_label.text() == "50%"
dp._level_slider.setValue(0);   assert sent[-1] == 0
st.on_drum_cc(protocol.CC_DRUMLEVEL, 20); pump(0.02)      # bouton physique de l'ampli
assert protocol.drum_level_from_percent(dp._level_slider.value()) == 20
n = len(sent); st.on_drum_cc(protocol.CC_DRUMLEVEL, 127); pump(0.02)
assert dp._level_slider.value() == 100 and len(sent) == n, "valeur hors plage reçue de l'ampli : curseur plafonné, rien renvoyé"
print("4. volume batterie : curseur 0-100 % sur la plage utilisable, anciennes valeurs plafonnées : OK")

# ---------------- 5. tuner du dashboard : pas de chevauchement ----------------
from ui.dashboard.compact.tuner_compact import CompactTunerPanel
tp = CompactTunerPanel(AmpState(), MidiSender())
tp.show()
for width in (tp.minimumWidth(), 240, 404):
    tp.resize(width, tp.minimumHeight()); pump(0.05)
    parts = {"micro": tp._toggle_btn, "note": tp._note_label, "reglages": tp._mode_btn, "ref": tp._calibrate_btn}
    rects = {k: v.geometry() for k, v in parts.items()}
    names = list(rects)
    for i, a in enumerate(names):
        assert tp.rect().contains(rects[a]), f"{a} déborde du module à {width}px : {rects[a]}"
        for b in names[i + 1:]:
            assert not rects[a].intersects(rects[b]), f"{a} chevauche {b} à {width}px : {rects[a]} / {rects[b]}"
    assert tp._gauge.geometry().top() >= max(r.bottom() for r in rects.values()), "jauge sous la rangée de boutons"
    assert tp._mode_btn.width() == tp._mode_btn.height(), "bouton carré : pas de flèche coincée dans un cadre étroit"
tp.grab().save(str(pathlib.Path(tempfile.gettempdir()) / "tuner_check.png"))
print("5. tuner compact : aucun chevauchement de la largeur mini à 404 px : OK")

# ---------------- 6. pop-up et indicateur de connexion ----------------
mw.POPUP_DURATION_MS = 400
def banner_alive():
    b = window._banner
    if b is None: return False
    try: return b.isVisible()
    except RuntimeError: return False
state.set_connected(False); pump(0.1)
assert banner_alive(), "pop-up affichée à la déconnexion"
wait_until(lambda: not banner_alive(), timeout=3, what="la pop-up 'Mighty déconnecté' doit disparaître seule")
state.set_connected(True); pump(0.1)
state.set_connected(False); pump(0.1)
item = window.navigationInterface.widget("connection")
assert item.text() == "Mighty déconnecté" and "déconnecté" in item.toolTip(), "l'état reste visible dans la barre"
assert wait_until(lambda: not banner_alive(), 3) is None
state.set_connected(True); pump(0.1)
assert item.text() == "Mighty connecté" and item.toolTip()
toggle = window.navigationInterface.widget("shortcuts_toggle")
assert toggle.toolTip() and "clic" in toggle.toolTip()
print("6. pop-up de déconnexion temporaire, indicateur + infobulles dans la barre : OK")

# ---------------- 7. icônes colorées ----------------
from ui import icons
def dominant(icon):
    img = icon.pixmap(32, 32).toImage()
    r = g = b = n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                r += c.red(); g += c.green(); b += c.blue(); n += 1
    assert n > 20, "icône vide"
    return r / n, g / n, b / n
r, g, b = dominant(icons.plug_icon(True));  assert g > r + 40 and g > b + 40, ("vert", r, g, b)
r, g, b = dominant(icons.plug_icon(False)); assert r > g + 60 and r > b + 60, ("rouge", r, g, b)
r, g, b = dominant(icons.toggle_icon("global")); assert g > r
r, g, b = dominant(icons.toggle_icon("window")); assert b > r
r, g, b = dominant(icons.toggle_icon("off"));    assert abs(r - g) < 15 and abs(g - b) < 15
assert not icons.keyboard_icon().isNull()
window.close()
print("7. icônes : prise verte / rouge, interrupteur vert / bleu / gris, clavier : OK")

# ---------------- 8. débranchement : rien ne bloque l'UI ----------------
from ui.loop_panel import LoopPanel
Audio.hang_stop = True; Audio.release.clear()
panel = LoopPanel(); pump(0.1)
assert panel._audio_ok
t0 = time.time()
panel.on_device_availability_changed(False, "NUX NMP-03")
assert time.time() - t0 < 0.5, "déconnexion pendant que la fermeture du flux se bloque : l'UI ne doit pas attendre"
assert pa.closing_in_progress()
t0 = time.time()
panel.stop()
assert time.time() - t0 < 0.5
assert pa.refresh_portaudio(time.monotonic(), timeout=0.3) == "stuck", "pas de réinitialisation de PortAudio tant qu'une fermeture est coincée"
Audio.hang_stop = False; Audio.release.set()
assert pa.wait_for_closes(3), "fermetures terminées après déblocage"
calls = Audio.terminate_calls
req = time.monotonic()
assert pa.refresh_portaudio(req) == "ok" and Audio.terminate_calls == calls + 1
assert pa.refresh_portaudio(req - 1) == "ok" and Audio.terminate_calls == calls + 1, "deux panneaux demandent en même temps : une seule réinitialisation"
Audio.release.clear()
p2 = LoopPanel(); pump(0.1)
assert pa.active_stream_count() >= 1 and pa.refresh_portaudio(time.monotonic()) == "busy", "jamais de réinitialisation avec un flux ouvert"
p2.stop(); pump(0.05)
assert pa.wait_for_closes(2) and pa.active_stream_count() == 0

# reconnexion complète avec fermeture lente de l'ancien flux
Audio.hang_stop = True; Audio.release.clear()
p3 = LoopPanel(); pump(0.1)
Audio.nux_present = False
p3.on_device_availability_changed(False, "NUX NMP-03"); pump(0.1)
assert not p3._audio_ok
Audio.nux_present = True
Audio.hang_stop = False; Audio.release.set()
t0 = time.time()
p3.on_device_availability_changed(True, "NUX NMP-03")
assert time.time() - t0 < 0.5, "la reconnexion ne bloque pas non plus"
wait_until(lambda: p3._audio_ok, timeout=6, what="flux relancé après reconnexion")
p3.stop()

# deux vues (Dashboard + Classique) qui se reconnectent : la seconde ne doit pas rester sans audio
Audio.hang_stop = False; Audio.release.set()
pa_a, pa_b = LoopPanel(), LoopPanel(); pump(0.1)
Audio.nux_present = False
for p_ in (pa_a, pa_b): p_.on_device_availability_changed(False, "NUX NMP-03")
pump(0.1)
Audio.nux_present = True
pa_a.on_device_availability_changed(True, "NUX NMP-03")
wait_until(lambda: pa_a._audio_ok, timeout=6, what="1re vue : audio revenu")   # son flux tourne avant que la 2e demande
pump(0.05)
pa_b.on_device_availability_changed(True, "NUX NMP-03")
wait_until(lambda: pa_b._audio_ok, timeout=6, what="2e vue : audio revenu malgré le flux déjà ouvert de la 1re")
pa_a.stop(); pa_b.stop()

# ports MIDI dont la fermeture se bloque
class HangPort:
    def __init__(self): self.closed = threading.Event()
    def close(self): Audio.release.wait(15); self.closed.set()
    def send(self, msg): pass
    def iter_pending(self): return []
Audio.release.clear()
s = MidiSender(); s._port = HangPort()
t0 = time.time(); s.detach(); assert time.time() - t0 < 0.3 and not s.is_open
from midi.listener import MidiListener
l = MidiListener(); l._port = HangPort()
t0 = time.time(); l.detach(); assert time.time() - t0 < 0.3 and not l.is_open
Audio.release.set()
print("8. débranchement : fermeture des flux audio et ports MIDI jamais bloquante, réinitialisation PortAudio protégée : OK")

# ---------------- 9. volume Windows de l'interface du Mighty ----------------
assert system_volume.set_output_volume_max("NUX NMP-03") == "ignoré (hors Windows)"
th = system_volume.apply_async("NUX NMP-03"); th.join(2); assert not th.is_alive()
calls = []
real = system_volume.apply_async
system_volume.apply_async = lambda kw: calls.append(kw)
Audio.hang_stop = False
pv = LoopPanel(); pump(0.1)
assert calls == ["NUX NMP-03"], "sortie du Mighty : le volume Windows est remis à fond"
assert pv._settings["loop"]["force_system_volume"] is True
pv._save_loop_settings()
assert saved()["loop"]["force_system_volume"] is True and saved()["loop"]["system_volume_keyword"] == "NUX NMP-03", "clés conservées à la sauvegarde"
calls.clear()
pv._output_combo.setCurrentText("Haut-parleurs PC"); pump(0.1)
assert calls == [], "sortie autre que le Mighty : le volume Windows n'est pas touché"
pv.stop()
settings.update_settings({"loop": {**settings.load_settings()["loop"], "force_system_volume": False,
                                   "output_device_name": "Haut-parleurs (2- NUX NMP-03)"}})
pv2 = LoopPanel(); pump(0.1)
assert calls == [], "réglage désactivé"
pv2.stop()
system_volume.apply_async = real
print("9. volume Windows du Mighty remis à fond (Windows + pycaw), désactivable, sans effet ailleurs : OK")

print("\nTOUS LES TESTS PASSENT")
