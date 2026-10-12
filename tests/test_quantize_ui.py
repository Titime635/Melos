"""Tempo / quantification côté appli : protocole SysEx, synchro vers la batterie, panneaux partagés,
démarrage de la batterie calé sur la mesure, verrouillage de la grille."""
import os, sys, time, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"
import numpy as np
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

from audio.loop_engine import LoopEngine
from PySide6.QtWidgets import QApplication
app = QApplication([])
def pump(sec=0.1):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

from midi import protocol
from midi.sender import MidiSender
from midi.sync import DeviceSync, push_state
from state.amp_state import AmpState
from ui.loop_panel import LoopPanel
from ui.drum_panel import DrumPanel

# ---- 1. le SysEx de tempo ----
d = protocol.build_drum_sysex(True, 5, 20, 10, 11, 12, 120)
assert d == [0x43, 0x58, 0x70, 0x19, 1, 1, 5, 20, 10, 11, 12, 0, 120], d
d = protocol.build_drum_sysex(False, 0, 0, 0, 0, 0, 200)
assert d[-2:] == [1, 72], d                      # 200 = 1*128 + 72
assert protocol.build_drum_sysex(False, 0, 0, 0, 0, 0, 999)[-2:] == [1, 112]   # plafonné à 240
assert protocol.build_drum_sysex(False, 0, 0, 0, 0, 0, 5)[-2:] == [0, 40]      # plancher à 40
print("1. SysEx tempo : 2 octets 7 bits, plage 40-240 : OK")

# ---- faux port MIDI ----
class FakePort:
    def __init__(self): self.sent = []
    def send(self, msg): self.sent.append(msg)
    def close(self): raise AssertionError("jamais fermé")
sender = MidiSender(); port = FakePort(); sender._port = port
state = AmpState()
sync = DeviceSync(state, sender)

def sysex_sent():
    return [m for m in port.sent if m.type == "sysex" and m.data[3] == protocol.SYX_DRUM]

# ---- 2. changement de tempo -> batterie (regroupé) ----
state.set_drum_style(7); state.set_drum_level(12)
for bpm in (101, 102, 103, 110):
    state.transport.set(bpm=bpm)
pump(0.5)
sx = sysex_sent()
assert len(sx) == 1, len(sx)                      # un seul envoi pour la rafale
assert list(sx[0].data)[-2:] == [0, 110] and sx[0].data[6] == 7 and sx[0].data[7] == 12
print("2. tempo -> SysEx batterie (regroupé, avec les réglages courants) : OK")

# ---- 3. renvoyé à la reconnexion ----
port.sent.clear(); push_state(state, sender)
assert len(sysex_sent()) == 1 and list(sysex_sent()[0].data)[-1] == 110
print("3. push_state renvoie aussi le tempo : OK")

# ---- 4. panneaux partagés et persistés ----
from ui.tempo_panel import TempoPanel
a = LoopPanel(state.transport); b = LoopPanel(state.transport); pump(0.2)
ta = TempoPanel(state.transport); tb = TempoPanel(state.transport)
ta.attach_loop_panel(a); tb.attach_loop_panel(b)
ta._bpm_slider.setValue(90); pump(0.05)
assert tb._bpm_slider.value() == 90 and b._engine._bpm == 90 and a._engine._bpm == 90
ta._unit_combo.setCurrentIndex(2); ta._beats_spin.setValue(6); pump(0.05)       # 6/8
assert (tb._beats_spin.value(), tb._unit_combo.currentText()) == (6, "8")
a._bars_spin.setValue(4); a._quantize_switch.setChecked(False); ta._click_switch.setChecked(True); pump(0.05)
assert b._bars_spin.value() == 4 and not b._quantize_switch.isChecked() and b._engine._click_on and tb._click_switch.isChecked()
state2 = AmpState()
t = state2.transport
assert (t.bpm, t.beats, t.unit, t.bars, t.quantize, t.click) == (90, 6, 8, 4, False, True)
print("4. tempo / signature / options partagés entre vues et persistés : OK")

# ---- 5. grille figée tant qu'une boucle existe ----
a._engine._tracks = [np.zeros((1000, 2), dtype="float32")]; a._refresh_tracks(); ta._poll.stop()
ta.show(); pump(0.05); ta._poll_engine()
assert not ta._bpm_slider.isEnabled() and not ta._beats_spin.isEnabled() and not ta._unit_combo.isEnabled()
a._engine._tracks = []; ta._poll_engine()
assert ta._bpm_slider.isEnabled()
# tap tempo : 4 appuis à 0,5 s => 120 BPM
import time as _t
fake_now = [100.0]
import ui.tempo_panel as tp
tp.time.monotonic = lambda: fake_now[0]
for _ in range(5):
    ta._on_tap(); fake_now[0] += 0.5
assert state.transport.bpm == 120, state.transport.bpm
print("5. tempo / mesure verrouillés tant qu'une boucle existe ; tap tempo : OK")

# ---- 6. batterie : départ calé sur la mesure ----
state3 = AmpState(); state3.transport.set(quantize=True, click=False, sync_drums=True, bars=0)
sender3 = MidiSender(); port3 = FakePort(); sender3._port = port3
loop = LoopPanel(state3.transport); drums = DrumPanel(state3, sender3); drums.set_sync(loop); pump(0.2)
e = loop._engine
e._clock = 12345            # le flux est factice : on fait avancer l'horloge nous-mêmes

def cc77():
    return [m.value for m in port3.sent if m.type == "control_change" and m.control == protocol.CC_DRUMENABLE]

drums._switch.setChecked(True); pump(0.05)
assert e._drum_hook is not None and cc77() == [] and not state3.drum_enabled and drums._switch.isChecked()
# on laisse le callback réel tourner : le crochet doit déclencher l'ordre MIDI
def run(n):
    done = 0
    while done < n:
        k = min(256, n - done); ind = np.zeros((k, 2), dtype="float32"); out = np.zeros((k, 2), dtype="float32")
        e._callback(ind, out, k, None, None); done += k
run(600); pump(0.1)
assert cc77() == [1] and state3.drum_enabled and e._external_ref
assert e._grid_origin == 12345 + 0          # sans repère : départ tout de suite, grille ancrée sur ce départ
# coupure
drums._switch.setChecked(False); pump(0.05)
assert cc77() == [1, 0] and not state3.drum_enabled and not e._external_ref
print("6. batterie : ordre MIDI émis par le callback, repère de phase posé puis retiré : OK")

# ---- 7. synchro coupée : démarrage immédiat ----
state3.transport.set(sync_drums=False); pump(0.05)
drums._switch.setChecked(True); pump(0.05)
assert cc77() == [1, 0, 1] and e._drum_hook is None
drums._switch.setChecked(False); pump(0.05)
print("7. 'Caler la batterie' coupé : démarrage immédiat : OK")

# ---- 8. annulation avant la mesure ----
state3.transport.set(sync_drums=True, click=True); pump(0.05)
run(5000)
drums._switch.setChecked(True); pump(0.05)
assert e._drum_hook is not None
drums._switch.setChecked(False); pump(0.05)
assert e._drum_hook is None
run(100000); pump(0.1)
assert cc77()[3:] and all(v == 0 for v in cc77()[3:]), cc77()   # jamais de « marche » après l'annulation
print("8. démarrage annulé avant la mesure : pas d'ordre MIDI : OK")

# ---- 9. boutons : attente affichée puis annulation ----
loop2 = LoopPanel(state3.transport); pump(0.2)
e2 = loop2._engine; e2._clock = 0
e2.set_click(True)
loop2._on_record_clicked(); pump(0.05)
assert e2.pending_action == "record" and loop2._record_btn.text() == "Annuler"
assert "attente de la mesure" in loop2._status_label.text()
loop2._on_record_clicked(); pump(0.05)
assert e2.pending_action == "" and loop2._record_btn.text() == "Enregistrer"
print("9. Rec en attente de la mesure : bouton « Annuler » : OK")

# ---- 10. touches de transport, pistes, barre de position ----
loop3 = LoopPanel(state3.transport); pump(0.2)
e3 = loop3._engine; e3._clock = 0
e3.set_quantize(False); state3.transport.set(quantize=False, click=False, bars=1); pump(0.05)
loop3._on_record_clicked(); pump(0.05)
assert loop3._record_btn.text() == "Stop"
k = 0
while e3.state == "recording" and k < 2000:
    ind = np.zeros((256, 2), dtype="float32"); out = np.zeros((256, 2), dtype="float32")
    e3._callback(ind, out, 256, None, None); k += 1
for _ in range(3):
    e3._callback(np.zeros((256, 2), dtype="float32"), np.zeros((256, 2), dtype="float32"), 256, None, None)
pump(0.1)
assert e3.state == "playing" and loop3._play_btn.text() == "Stop" and e3.loop_bars == 1
snap = e3.snapshot(); assert snap["bars"] == 1 and snap["active"] and 0 <= snap["beat"] < 4
# volume / muet par piste
assert e3.track_gain(0) == 1.0
loop3._tracks_layout.itemAt(0).widget()._slider.setValue(50); pump(0.02)
assert abs(e3.track_gain(0) - 0.5) < 1e-6
loop3._tracks_layout.itemAt(0).widget()._toggle_mute(); pump(0.02)
assert e3.track_muted(0)
e3._tracks[0][:] = 1.0
out = np.zeros((256, 2), dtype="float32"); e3._callback(np.zeros((256, 2), dtype="float32"), out, 256, None, None)
assert np.all(out[:, 0] == 0), "piste muette = silence"
loop3._tracks_layout.itemAt(0).widget()._toggle_mute()
out = np.zeros((256, 2), dtype="float32"); e3._callback(np.zeros((256, 2), dtype="float32"), out, 256, None, None)
assert abs(out[0, 0] - 0.5) < 1e-6, out[0, 0]
loop3._on_play_clicked(); pump(0.05)          # Stop (non quantifié)
assert e3.state == "stopped" and loop3._play_btn.text() == "Play"
print("10. transport (Rec/Stop/Play), barre de position, volume et muet par piste : OK")

# ---- 11. densité adaptative ----
from PySide6.QtWidgets import QWidget
host = QWidget(); host.resize(700, 800)
loop3.setParent(host); host.show()
loop3.setGeometry(0, 0, 480, 600); pump(0.1)
assert loop3._chips_w.isVisible() and loop3._volume_w.isVisible() and loop3._tracks_scroll.isVisible()
loop3.setGeometry(0, 0, 480, loop3._base_height() + 5); pump(0.1)
assert not loop3._chips_w.isVisible() and not loop3._tracks_scroll.isVisible() and loop3._record_btn.isVisible()
assert loop3.minimumSizeHint().height() == loop3._base_height()
loop3.setGeometry(0, 0, 250, 600); pump(0.1)
assert loop3._record_btn.text() == "" and loop3._record_btn.toolTip()
print("11. module adaptatif : sections masquées selon la place, touches compactes si étroit : OK")

# ---- 12. module Tempo : mesures rapides, −/+, mesure perso, verrouillage, popups ----
st = AmpState(); tr = st.transport
tr.set(bpm=100, beats=4, unit=4, click=False)
shared = LoopEngine()
v1 = LoopPanel(st.transport, shared); v2 = LoopPanel(st.transport, shared); pump(0.2)
assert v1.engine is v2.engine is shared
assert isinstance(shared._stream, FakeStream), "le flux n'est ouvert qu'une fois, par la 1re vue"
n_streams = []
orig_init = FakeStream.__init__
tw = TempoPanel(st.transport); tw.attach_loop_panel(v1); tw.show(); pump(0.1)
assert tw._bpm_slider.minimum() == 40 and tw._bpm_slider.maximum() == 240
tw._plus_btn.click(); tw._plus_btn.click(); tw._minus_btn.click(); pump(0.05)
assert tr.bpm == 101 and tw._bpm_label.text() == "101"
for (beats, unit), btn in tw._sig_buttons.items():
    btn.click(); pump(0.02)
    assert (tr.beats, tr.unit) == (beats, unit) and btn.isChecked(), ((beats, unit), (tr.beats, tr.unit), btn.isChecked(), btn.isEnabled())
    assert sum(b.isChecked() for b in tw._sig_buttons.values()) == 1 and not tw._sig_more.isChecked()
tw._beats_spin.setValue(5); tw._unit_combo.setCurrentIndex(UNITS_IDX := 1); pump(0.05)   # 5/4
assert (tr.beats, tr.unit) == (5, 4) and tw._sig_more.isChecked() and tw._sig_more.text() == "5/4"
assert not any(b.isChecked() for b in tw._sig_buttons.values())
tw._toggle_custom_signature(); assert tw._custom_popup.isVisible(); tw._toggle_custom_signature()
tw._toggle_settings(); assert tw._settings_popup.isVisible()
tw._sync_drums_switch.setChecked(False); tw._drum_latency_spin.setValue(35); pump(0.05)
assert not tr.sync_drums and tr.drum_latency_ms == 35
tw._toggle_settings(); assert not tw._settings_popup.isVisible()
tw._click_switch.click(); pump(0.05)
assert tr.click and shared._click_on                      # un seul moteur pour les deux vues
shared._tracks = [np.zeros((1000, 2), dtype="float32")]; tw._poll_engine()
assert not tw._bpm_slider.isEnabled() and not tw._minus_btn.isEnabled() and not tw._sig_more.isEnabled() \
    and not any(b.isEnabled() for b in tw._sig_buttons.values()) and not tw._tap_btn.isEnabled()
shared._tracks = []; tw._poll_engine()
assert tw._bpm_slider.isEnabled() and tw._sig_more.isEnabled()
print("12. module Tempo (slider, −/+, mesures rapides, mesure perso, métronome, engrenage) + moteur partagé : OK")

# ---- 13. décompte : pastilles allumées au fil du décompte ----
shared._external_ref = False
shared._set_state("counting_in")
v1._poll_engine()
assert v1._count_in_switch._marker >= -1
shared._set_state("idle"); v1._poll_engine()
assert v1._count_in_switch._marker == -1
assert hasattr(v1, "_quantize_switch") and v1._settings_popup is not None
print("13. bouton Décompte / Caler dans l'engrenage : OK")

# ---- 14. les volets restent dans la fenêtre ; cliquer à côté d'un champ de texte le quitte ----
from PySide6.QtCore import Qt as _Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit
from ui.focus_guard import FocusGuard
host2 = QWidget(); host2.resize(520, 420); host2.move(100, 100)
lay2 = __import__("PySide6.QtWidgets", fromlist=["QHBoxLayout"]).QHBoxLayout(host2)
st2 = AmpState(); tp2 = TempoPanel(st2.transport); lay2.addStretch(); lay2.addWidget(tp2)
tp2.setMinimumWidth(240)
edit_box = QLineEdit(); lay2.insertWidget(0, edit_box)
host2.show(); pump(0.2)
tp2._sig_more.click(); pump(0.1)                      # le bouton « ⋯ » est tout à droite de la fenêtre
pop = tp2._custom_popup
assert pop.isVisible()
win = host2.frameGeometry()
assert pop.x() >= win.left() and pop.x() + pop.width() <= win.right(), (pop.geometry(), win)
pop.hide()
tp2._toggle_settings(); pump(0.1)
assert tp2._settings_popup.x() + tp2._settings_popup.width() <= win.right()
tp2._settings_popup.hide()
guard = FocusGuard(); app.installEventFilter(guard)
edit_box.setFocus(); pump(0.05)
assert app.focusWidget() is edit_box
QTest.mouseClick(tp2._bpm_label, _Qt.LeftButton); pump(0.05)
assert app.focusWidget() is not edit_box, "clic à côté : le champ de texte perd le focus"
edit_box.setFocus(); pump(0.05)
QTest.mouseClick(edit_box, _Qt.LeftButton); pump(0.05)
assert app.focusWidget() is edit_box, "clic dans le champ : le focus reste"
app.removeEventFilter(guard); host2.close()
print("14. volets contenus dans la fenêtre ; clic hors d'un champ de texte = on le quitte : OK")

# ---- 15. curseur : la poignée suit la valeur même posée avec les signaux bloqués ----
st3 = AmpState(); st3.transport.set(bpm=165)
tp3 = TempoPanel(st3.transport); tp3.resize(420, 300); tp3.show(); pump(0.2)
sl = tp3._bpm_slider
expect = (165 - 40) / 200 * sl.grooveLength
assert abs(sl.handle.x() - expect) <= 2, (sl.handle.x(), expect)
st3.transport.set(bpm=60); pump(0.05)              # changement venu de l'extérieur (_refresh bloque les signaux)
expect = (60 - 40) / 200 * sl.grooveLength
assert abs(sl.handle.x() - expect) <= 2, (sl.handle.x(), expect)
print("15. curseur de tempo : la poignée suit la valeur (tap, autre vue...) : OK")

# ---- 16. module Tempo trop petit : le métronome se réduit à son icône, à droite du BPM ----
tp3.close(); host3 = QWidget(); host3.resize(500, 500); tp3 = TempoPanel(st3.transport); tp3.setParent(host3); host3.show()
tp3.setGeometry(0, 0, 420, 330); pump(0.15)
assert tp3._actions_w.isVisible() and not tp3._click_mini.isVisible()
tp3.setGeometry(0, 0, 420, tp3.minimumSizeHint().height() + 6); pump(0.15)
assert not tp3._actions_w.isVisible() and tp3._click_mini.isVisible(), (tp3.height(), tp3._base_height(), tp3._actions_w.isVisible(), tp3._click_mini.isVisible(), tp3._sig_w.isVisible())
mini_x = tp3._click_mini.mapTo(tp3, tp3._click_mini.rect().topLeft()).x()
assert mini_x > tp3._bpm_label.mapTo(tp3, tp3._bpm_label.rect().topRight()).x() + 20, "calé à droite du BPM"
assert tp3._dots.isVisible(), "points de tempo toujours visibles"
dc = tp3._dots.mapTo(tp3, tp3._dots.rect().center()).x()
assert abs(dc - tp3.width() / 2) <= 3, "points centrés"
assert tp3._dots.y() > tp3._bpm_w.y() + tp3._bpm_w.height() - 2, "points sous le BPM"
st3.transport.set(click=False); pump(0.05)
tp3._click_mini.click(); pump(0.05)
assert st3.transport.click and tp3._click_switch.isChecked() and tp3._click_mini.isChecked()
tp3._click_mini.click(); pump(0.05)
assert not st3.transport.click
host3.close()
print("16. Tempo trop petit : métronome en icône seule, à droite du BPM : OK")

# ---- 17. l'agencement du Dashboard est enregistré et restauré ----
from unittest.mock import MagicMock
from ui.dashboard_interface import DashboardInterface
st4 = AmpState()
d1 = DashboardInterface(st4, MagicMock()); d1.resize(1150, 800); d1.show(); pump(0.3)
assert settings.load_settings()["dashboard"]["state"] is None
d1._dock_area._on_delete_requested(d1._dock_area._docks["setlist"])       # supprime un module
d1._dock_area.resize_docks(["presets", "loop"], [300, 780], _Qt.Horizontal); pump(0.1)
d1.save_layout()
cfg = settings.load_settings()["dashboard"]
assert cfg["state"] and cfg["hidden"] == ["setlist"], cfg["hidden"]
d2 = DashboardInterface(st4, MagicMock()); d2.resize(1150, 800); d2.show(); pump(0.3)
assert list(d2._dock_area.hidden_modules) == ["setlist"], "le module supprimé reste supprimé"
w_presets = d2._dock_area.module_geometry("presets").width()
assert abs(w_presets - d1._dock_area.module_geometry("presets").width()) < 40, w_presets
d2._dock_area.restore_module("setlist"); d2.save_layout()
assert settings.load_settings()["dashboard"]["hidden"] == []
d1.stop(); d2.stop(); d1.close(); d2.close()
print("17. agencement du Dashboard enregistré (modules supprimés + tailles) et restauré : OK")

print("\nUI QUANTIFICATION OK")
import sounddevice as _sd
_sd._initialized = 0