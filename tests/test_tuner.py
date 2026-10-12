"""Module Tuner : accordages, analyse vs corde cible, session (cordes accordées, son), interface."""
import os, sys, time, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
app = QApplication([])
def pump(sec=0.1):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

from midi import protocol, tunings
from state.amp_state import AmpState
from ui.tuner_panel import TunerPanel

# ---- 1. accordages ----
assert len(tunings.TUNINGS) == 23 and all(len(v.split()) == 6 for v in tunings.TUNINGS.values())
mid = lambda n: [s.midi for s in tunings.strings_of(n)]
assert mid("Standard") == [40, 45, 50, 55, 59, 64]
assert mid("Eb standard") == [39, 44, 49, 54, 58, 63]
assert mid("Drop D") == [38, 45, 50, 55, 59, 64]
assert mid("DADDAD") == [38, 45, 50, 50, 57, 62]
assert mid("New Standard Tuning") == [36, 43, 50, 57, 64, 67]
assert all(mid(n) == sorted(mid(n)) for n in tunings.TUNINGS)
print("1. 23 accordages, octaves attribuées (E2 A2 D3 G3 B3 E4...) : OK")

# ---- 2. analyse (classe de hauteur 0-11, Do = 0) ----
PC = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
r = tunings.analyze(PC["A"], 8.0, "Standard", None)
assert (r.label, r.string, round(r.cents)) == ("A", 1, 8) and not r.fallback
r = tunings.analyze(PC["G#"], 60.0, "Standard", None); assert r.label == "A" and round(r.cents) == -40, r
r = tunings.analyze(PC["D#"], 0, "Eb standard", None); assert r.label == "Eb" and r.string == 0 and r.in_tune
r = tunings.analyze(PC["F"], 0, "DADDAD", None); assert r.fallback and r.label == "F" and r.string is None
r = tunings.analyze(PC["E"], -30.0, "Standard", 5); assert r.string == 5 and r.label == "E" and round(r.cents) == -30
# deux cordes de même note : la préférée, sinon la première pas accordée
assert tunings.analyze(PC["E"], 0, "Standard", None).string == 0
assert tunings.analyze(PC["E"], 0, "Standard", None, tuned={0}).string == 5
assert tunings.analyze(PC["E"], 0, "Standard", None, tuned={0}, prefer=0).string == 0
# décodage du CC 12 de l'ampli mesuré : 0 = La, 7 = Mi, 5 = Ré, 10 = Sol, 2 = Si
assert [protocol.tuner_pitch_class(v) for v in (7, 0, 5, 10, 2)] == [PC[n] for n in "EADGB"]
print("2. analyse par classe de hauteur, cordes jumelles, décodage du CC 12 (0 = La) : OK")

# ---- 3. session : lissage, validation d'une corde, son ----
t = [0.0]
state = AmpState(); sess = state.tuner; sess._clock = lambda: t[0]
chimes = []; sess.play_chime = lambda: chimes.append(1)
state.set_tuner_requested(True); sess.reset()
zero = state.tuner_cent_zero
def send(note, raw):
    state.on_tuner_note(note); state.on_tuner_cent(raw)
send(0, zero + 20)   # CC12 = 0 : La
assert sess.reading.string == 1 and sess.signal is False   # le signal est évalué au tick
for _ in range(8): send(0, zero + 20)
sess.tick(); assert sess.signal and sess.reading.string == 1 and abs(sess.reading.cents - 20) < 3, sess.reading
for _ in range(16):
    t[0] += 0.05; send(0, zero + 1); sess.tick()
assert 1 in sess.tuned and chimes == [1]
for _ in range(10):
    t[0] += 0.05; send(0, zero); sess.tick()
assert chimes == [1], "un seul son par corde"
state.set_tuner_options(sound=False)
for _ in range(20):
    t[0] += 0.05; send(5, zero); sess.tick()   # CC12 = 5 : Ré
assert 2 in sess.tuned and chimes == [1], "son désactivé"
for _ in range(10):
    t[0] += 0.05; send(0, zero + 20); sess.tick()
assert 1 not in sess.tuned, "corde déréglée : à refaire"
t[0] += 2.0; sess.tick(); assert not sess.signal
sess.set_tuning("Drop D"); assert state.tuner_tuning == "Drop D" and not sess.tuned
print("3. session : lissage, corde validée, un seul son, son coupable, déréglage, fin de signal : OK")

# ---- 4. interface ----
state = AmpState(); sender = MagicMock(); sess = state.tuner; state.set_tuner_requested(False)
p = TunerPanel(state, sender); p.resize(380, 340); p.show(); pump(0.2)
p._power.setChecked(True); pump(0.05)
assert state.tuner_requested
sender.tuner_enable.assert_called_with(on=True, mode=0, ref_pitch=10)
assert p._chips_w.isVisible() and p._tuning_w.isVisible()
p._chips[3].click(); assert sess.selected == 3
p._chips[3].click(); assert sess.selected is None, "recliquer = retour en auto"
p._tuning_buttons["Drop D"].click(); pump(0.05)
assert state.tuner_tuning == "Drop D" and p._tuning_buttons["Drop D"].isChecked() and p._chips[0]._label == "D"
p._choose_tuning("DADGAD", close=True); pump(0.05)
assert p._more_btn.text() == "DADGAD" and p._more_btn.isChecked() and not any(b.isChecked() for b in p._tuning_buttons.values())
p._ref_spin.setValue(442); sender.tuner_enable.assert_called_with(on=True, mode=0, ref_pitch=12)
assert AmpState().tuner_tuning == "DADGAD" and AmpState().tuner_ref_hz == 442
# deux vues : même session, même état
q = TunerPanel(state, sender); q.show(); pump(0.05)
p._chips[1].click(); pump(0.05)
assert q._chips[1].selected
print("4. interface : activation, cordes (auto / manuel), accordages, « … », référence, deux vues : OK")

# ---- 4b. décalage de note (correction) ----
sess.set_tuning("Standard"); state.set_tuner_options(note_shift=1); sess.reset()
state.on_tuner_cent(state.tuner_cent_zero); state.on_tuner_note(6)   # (6 + 9 + 1) % 12 = 4 = Mi
for _ in range(6): state.on_tuner_cent(state.tuner_cent_zero)
assert sess.reading.label == "E" and sess.reading.string == 0, sess.reading
assert "CC12 = 6" in p._raw_label.text() and "→ E" in p._raw_label.text()
state.set_tuner_options(note_shift=0)
print("4b. décalage de note + valeurs brutes affichées : OK")

# ---- 4c. zéro propre à une note ----
state.set_tuner_requested(True); sess.reset(); state.set_tuner_options(note_shift=0, cent_zero_notes={})
state.on_tuner_note(2)            # Si (CC12 = 2)
state.on_tuner_cent(state.tuner_cent_zero + 10)
sess.signal = True
assert round(sess.calibrated_cents()) == 10
p._on_set_zero()
assert state.tuner_cent_zero_notes == {11: state.tuner_cent_zero + 10}
state.on_tuner_cent(state.tuner_cent_zero + 10); assert round(sess.calibrated_cents()) == 0
state.on_tuner_note(0); state.on_tuner_cent(state.tuner_cent_zero + 3)   # le La garde le zéro général
assert round(sess.calibrated_cents()) == 3
assert AmpState().tuner_cent_zero_notes == {11: state.tuner_cent_zero + 10}
p._on_reset_calibration(); assert state.tuner_cent_zero_notes == {}
print("4c. zéro propre à chaque note (le Si +10 calibré sans toucher les autres) : OK")

# ---- 5. densité ----
p.resize(380, 340); pump(0.1); assert p._chips_w.isVisible() and p._tuning_w.isVisible()
p.resize(380, p._base_height() + 80); pump(0.1); assert p._chips_w.isVisible() and not p._tuning_w.isVisible()
p.resize(380, p._base_height() + 5); pump(0.1); assert not p._chips_w.isVisible()
print("5. densité : accordages puis cordes masqués quand c'est petit : OK")

p.close(); q.close()
print("\nTUNER OK")