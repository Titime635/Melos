import os, sys, time, json, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"
import setlist.model
setlist.model.SETLISTS_FILE = pathlib.Path(tempfile.mkdtemp()) / "setlists.json"

# ---------------- faux audio (cf test_audio.py) ----------------
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

from PySide6.QtWidgets import QApplication
from fake_keyboard import FakeKeyboard
from shortcuts import manager as manager_module
from shortcuts.manager import ShortcutManager, risk_note, normalize_key
from shortcuts.router import ActionRouter
from state.amp_state import AmpState
from midi.sender import MidiSender

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

def new_manager(fake=None, **kw):
    fake = fake or FakeKeyboard()
    m = ShortcutManager(backend=fake, **kw)
    triggered = []
    m.action_triggered.connect(triggered.append)
    return m, fake, triggered

# ---------------- 1. départ à vide ----------------
m, fake, trig = new_manager()
assert m.enabled and m.bindings() == {} and fake.registered() == []
print("1. aucune touche par défaut, rien d'enregistré : OK")

# ---------------- 2. association, persistance, rechargement ----------------
assert m.assign("loop_cycle", "F5") is None
assert m.binding_for("loop_cycle") == "f5" and fake.registered() == ["f5"]
assert saved()["shortcuts"]["bindings"] == {"loop_cycle": "f5"}
m.shutdown()
m2, fake2, trig2 = new_manager()
assert m2.bindings() == {"loop_cycle": "f5"} and fake2.registered() == ["f5"]
print("2. association persistée et restaurée au lancement : OK")

# ---------------- 3. conflit ----------------
err = m2.assign("nav_next", "f5")
assert err and "déjà utilisée" in err and m2.binding_for("nav_next") is None
assert m2.assign("loop_cycle", "f5") is None          # re-valider sa propre touche = pas un conflit
print("3. touche déjà prise refusée, pas de vol silencieux : OK")

# ---------------- 4. déclenchement + anti-répétition ----------------
fake2.tap("f5")
assert trig2 == ["loop_cycle"]
fake2.press("f5"); fake2.press("f5"); fake2.press("f5")   # touche maintenue : répétition auto de Windows
assert trig2 == ["loop_cycle", "loop_cycle"], trig2
fake2.release("f5"); fake2.tap("f5")
assert len(trig2) == 3
print("4. un appui = une action, la touche maintenue ne répète pas : OK")

# ---------------- 5. interrupteur ----------------
changes = []
m2.enabled_changed.connect(changes.append)
m2.set_enabled(False)
assert fake2.registered() == [] and saved()["shortcuts"]["enabled"] is False and changes == [False]
fake2.tap("f5"); assert len(trig2) == 3
m2.set_enabled(True)
assert fake2.registered() == ["f5"] and changes == [False, True]
fake2.tap("f5"); assert len(trig2) == 4
print("5. interrupteur : désenregistre / ré-enregistre, persisté : OK")

# ---------------- 6. touche refusée par le système ----------------
fake2.reject.add("bizarre")
err = m2.assign("loop_record", "bizarre")
assert err and "impossible d'assigner" in err and m2.binding_for("loop_record") is None
assert "loop_record" not in saved()["shortcuts"]["bindings"]
assert fake2.registered() == ["f5"]
print("6. touche refusée par le backend : annulée, rien de sauvegardé : OK")

# ---------------- 7. maintien (effacer la boucle) ----------------
m2.shutdown()
m3, fake3, trig3 = new_manager(hold_seconds_override=0.15)
m3.assign("loop_clear", "f9")
fake3.press("f9"); pump(0.05); fake3.release("f9"); pump(0.25)
assert trig3 == [], "relâché trop tôt : ne doit rien faire"
fake3.press("f9"); fake3.press("f9"); pump(0.35)     # maintenu + répétitions auto
assert trig3 == ["loop_clear"], trig3
pump(0.2); assert trig3 == ["loop_clear"], "un seul déclenchement par maintien"
fake3.release("f9")
fake3.press("f9"); pump(0.35); assert trig3 == ["loop_clear", "loop_clear"]
fake3.release("f9")
m3.set_enabled(False); fake3.press("f9"); pump(0.25); assert len(trig3) == 2
print("7. action à maintenir : trop court = rien, maintenu = une seule fois : OK")
m3.shutdown()

# ---------------- 8. capture d'une touche ----------------
settings.update_settings({"shortcuts": {"enabled": True, "bindings": {}}})   # repart d'un état propre (7 a coupé l'interrupteur)
m4, fake4, trig4 = new_manager()
m4.assign("loop_cycle", "f5")
results = []
m4.capture_result.connect(lambda a, k, e: results.append((a, k, e)))
m4.start_capture("preset_1")
assert fake4.registered() == [], "raccourcis suspendus pendant la capture"
fake4.user_presses_in_capture("Ctrl+F1")
wait_until(lambda: results, what="résultat de capture")
assert results[-1] == ("preset_1", "ctrl+f1", ""), results
assert m4.binding_for("preset_1") == "ctrl+f1" and fake4.registered() == ["ctrl+f1", "f5"]
# Échap annule
m4.start_capture("preset_2"); fake4.user_presses_in_capture("esc")
wait_until(lambda: len(results) == 2, what="annulation")
assert results[-1] == ("preset_2", "", "") and m4.binding_for("preset_2") is None
assert fake4.registered() == ["ctrl+f1", "f5"]
# touche déjà prise
m4.start_capture("preset_2"); fake4.user_presses_in_capture("f5")
wait_until(lambda: len(results) == 3, what="conflit")
assert results[-1][1] == "" and "déjà utilisée" in results[-1][2]
assert fake4.registered() == ["ctrl+f1", "f5"]
# délai dépassé
manager_module.CAPTURE_TIMEOUT_S = 0.2
m4.start_capture("preset_3")
wait_until(lambda: len(results) == 4, what="délai")
assert "délai" in results[-1][2] and fake4.registered() == ["ctrl+f1", "f5"] and not m4.capturing
fake4.user_presses_in_capture("x")   # débloque le thread de capture resté en attente
pump(0.1)
assert m4.binding_for("preset_3") is None, "un résultat tardif ne doit pas être appliqué"
print("8. capture : OK, Échap, conflit, délai dépassé (raccourcis suspendus puis rétablis) : OK")
m4.shutdown()

# ---------------- 9. migration des anciennes touches de la setlist ----------------
settings.update_settings({"shortcuts": {"enabled": True, "bindings": {}},
                          "setlist": {**settings.load_settings()["setlist"], "next_key": "f7", "previous_key": "F8"}})
m5, fake5, _ = new_manager()
assert m5.bindings() == {"nav_next": "f7", "nav_previous": "f8"}, m5.bindings()
s = saved()
assert s["setlist"]["next_key"] is None and s["setlist"]["previous_key"] is None
assert s["shortcuts"]["bindings"] == {"nav_next": "f7", "nav_previous": "f8"}
m5.shutdown()
print("9. anciennes touches Suivant/Précédent de la setlist migrées : OK")

# ---------------- 10. avertissement touche de saisie ----------------
assert risk_note("a") and risk_note("space") and risk_note("5")
assert risk_note("f5") is None and risk_note("ctrl+a") is None and risk_note("alt+1") is None
assert normalize_key("Ctrl + F5") == "ctrl+f5"
print("10. avertissement sur les touches de saisie : OK")

# ---------------- 11. non-régression : les sauvegardes ne s'écrasent plus ----------------
settings.update_settings({"shortcuts": {"enabled": True, "bindings": {"loop_cycle": "f5"}}})
state = AmpState()                                         # copie des réglages prise ICI...
settings.update_settings({"loop": {**settings.load_settings()["loop"], "volume": 0.5}})  # ...changée ensuite
state.on_preset_changed(2)                                 # AmpState sauvegarde
s = saved()
assert s["loop"]["volume"] == 0.5, "le volume du looper a été écrasé par AmpState"
assert s["shortcuts"]["bindings"] == {"loop_cycle": "f5"}, "les raccourcis ont été écrasés"
assert s["current_preset"] == 2
print("11. une sauvegarde d'AmpState n'écrase plus loop/raccourcis : OK")

# ---------------- 12. routeur ----------------
class StubSender:
    def __init__(self): self.presets = []
    def set_preset(self, i): self.presets.append(i)
class StubLoop:
    def __init__(self): self.actions = []
    def run_shortcut(self, a): self.actions.append(a)
class StubSetlist:
    def __init__(self, active): self.active = active; self.moves = []
    def is_navigation_active(self): return self.active
    def navigate(self, d): self.moves.append(d)
class StubView:
    def __init__(self, active): self.loop_panel = StubLoop(); self.setlist_panel = StubSetlist(active)

sender, view = StubSender(), StubView(False)
state = AmpState()
router = ActionRouter(state, sender, lambda: view)
router.handle("preset_3");  assert sender.presets == [2] and state.current_preset == 2
router.handle("preset_9");  assert sender.presets == [2], "preset inexistant ignoré"
state.current_preset = 6;   router.handle("nav_next");     assert state.current_preset == 0, "suivant : en boucle"
router.handle("nav_previous"); assert state.current_preset == 6, "précédent : en boucle"
view.setlist_panel.active = True
before = list(sender.presets)
router.handle("nav_next"); router.handle("nav_previous")
assert view.setlist_panel.moves == [1, -1] and sender.presets == before, "setlist active : elle prend la main"
for a in ("loop_cycle", "loop_record", "loop_overdub", "loop_play", "loop_clear"):
    router.handle(a)
assert view.loop_panel.actions == ["loop_cycle", "loop_record", "loop_overdub", "loop_play", "loop_clear"]
print("12. routeur : presets, suivant/précédent fusionnés (setlist si active), looper : OK")

# ---------------- 13. LoopPanel.run_shortcut sur le vrai moteur ----------------
from ui.loop_panel import LoopPanel
p = LoopPanel(); pump(0.1)
assert p._audio_ok
e = p._engine
p.run_shortcut("loop_overdub"); p.run_shortcut("loop_clear"); p.run_shortcut("loop_play")
assert e.state == "idle", "hors état valide : rien ne se passe"
p.run_shortcut("loop_cycle");  assert e.state == "recording"
e._record_chunks = [np.zeros((4800, 2), dtype="float32")]       # ce que le callback audio aurait capté
p.run_shortcut("loop_cycle");  assert e.state == "playing" and e.track_count == 1
p.run_shortcut("loop_cycle");  assert e.state == "overdubbing"
p.run_shortcut("loop_cycle");  assert e.state == "playing" and e.track_count == 2
p.run_shortcut("loop_play");   assert e.state == "stopped", "Play/Stop : stoppe pendant la lecture"
p.run_shortcut("loop_play");   assert e.state == "playing", "Play/Stop : relance"
p.run_shortcut("loop_overdub"); assert e.state == "overdubbing"
p.run_shortcut("loop_play");   assert e.state == "overdubbing", "Play/Stop sans effet pendant un overdub"
p.run_shortcut("loop_overdub"); assert e.state == "playing" and e.track_count == 3
e.stop();                       assert e.state == "stopped"
p.run_shortcut("loop_cycle");  assert e.state == "playing", "touche cyclique : relance depuis stopped"
p.run_shortcut("loop_record"); assert e.state == "playing", "enregistrer : sans effet pendant la lecture"
p.run_shortcut("loop_clear");  assert e.state == "idle" and e.track_count == 0
e._set_state("counting_in"); p.run_shortcut("loop_cycle"); assert e.state == "counting_in"
e._set_state("idle")
p.run_shortcut("loop_record"); assert e.state == "recording"
e._record_chunks = [np.zeros((4800, 2), dtype="float32")]
p.run_shortcut("loop_record"); assert e.state == "playing"
p._audio_ok = False
p.run_shortcut("loop_clear");  assert e.state == "playing", "audio coupé : raccourcis ignorés"
print("13. looper : touche cyclique, touches séparées, Play/Stop, garde-fous : OK")
p.stop()

# ---------------- 14. fenêtre complète ----------------
from ui.main_window import MainWindow
from setlist.model import Sequence, Step
settings.update_settings({"shortcuts": {"enabled": True, "bindings": {}}})
state = AmpState(); sender = MidiSender()
mgr, fk, _ = new_manager()
window = MainWindow(state, sender, mgr); window.show(); pump(0.1)
mgr.assign("preset_5", "f6"); mgr.assign("nav_next", "f7"); mgr.assign("nav_previous", "f8")
fk.tap("f6"); pump(0.05)
assert state.current_preset == 4, state.current_preset
fk.tap("f7"); pump(0.05)
assert state.current_preset == 5, "suivant sans setlist = preset suivant"
dash, home = window.dashboard_interface, window.home_interface
dash.setlist_panel._player.set_sequences([Sequence("Morceau", [Step(2, ""), Step(5, "")])])
dash.setlist_panel._player.set_active(0); pump(0.05)
assert state.current_preset == 2 and dash.setlist_panel.is_navigation_active()
fk.tap("f7"); pump(0.05)
assert dash.setlist_panel._player.step_index == 1 and state.current_preset == 5, "suivant = étape de la setlist"
fk.tap("f8"); pump(0.05)
assert dash.setlist_panel._player.step_index == 0 and state.current_preset == 2
# bascule sur l'onglet Classique : les raccourcis visent SA setlist/SA loop station
window.switchTo(home); pump(0.1)
assert window.active_view() is home
assert not home.setlist_panel.is_navigation_active()
fk.tap("f7"); pump(0.05)
assert state.current_preset == 3 and dash.setlist_panel._player.step_index == 0, "Classique : pas de setlist, preset +1"
# sur la page Raccourcis on garde la dernière vue de jeu
window.switchTo(window.shortcuts_interface); pump(0.1)
assert window.active_view() is home
window.switchTo(dash); pump(0.1)
assert window.active_view() is dash
# interrupteur rapide dans la barre de navigation
toggle = window.navigationInterface.widget("shortcuts_toggle")
assert toggle.text() == "Raccourcis actifs"
toggle.clicked.emit(True); pump(0.05)
assert not mgr.enabled and toggle.text() == "Raccourcis coupés" and fk.registered() == []
toggle.clicked.emit(True); pump(0.05)
assert mgr.enabled and toggle.text() == "Raccourcis actifs" and "f6" in fk.registered()
print("14. fenêtre : presets, suivant/précédent, vue pilotée suit l'onglet, interrupteur nav : OK")

# ---------------- 15. page Raccourcis ----------------
page = window.shortcuts_interface
page._on_set_clicked("preset_2")
assert not page._set_buttons["preset_2"].isEnabled(), "boutons Définir bloqués pendant la capture"
fk.user_presses_in_capture("f2")
wait_until(lambda: mgr.binding_for("preset_2") == "f2", what="capture via l'UI")
assert page._key_labels["preset_2"].text() == "F2" and page._set_buttons["preset_2"].isEnabled()
assert "✓" in page._status.text() and "⚠" not in page._status.text(), page._status.text()
page._on_set_clicked("preset_3"); fk.user_presses_in_capture("a")      # touche de saisie : avertissement
wait_until(lambda: mgr.binding_for("preset_3") == "a", what="capture touche de saisie")
assert "⚠" in page._status.text() and page._key_labels["preset_3"].text() == "A"
page._on_set_clicked("preset_4"); fk.user_presses_in_capture("f2")     # déjà prise
wait_until(lambda: "déjà utilisée" in page._status.text(), what="message de conflit")
assert mgr.binding_for("preset_4") is None and page._set_buttons["preset_4"].isEnabled()
page._on_clear_clicked("preset_3"); pump(0.05)
assert mgr.binding_for("preset_3") is None and page._key_labels["preset_3"].text() == "—"
assert saved()["shortcuts"]["bindings"].get("preset_3") is None
print("15. page Raccourcis : capture, avertissement, conflit, effacement : OK")

# ---------------- 16. arrêt propre ----------------
t0 = time.time()
window.close(); pump(0.1)
assert fk.registered() == [], "touches non désenregistrées à la fermeture"
assert time.time() - t0 < 2
print("16. fermeture : touches désenregistrées : OK")
print("\nTOUS LES TESTS PASSENT")
