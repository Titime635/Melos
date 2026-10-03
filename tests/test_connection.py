import os, sys, time, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tests"))
import mido
import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# ---------------- faux MIDI ----------------
class World:
    plugged = False
    in_name = "NUX NMP-03 0"
    out_name = "NUX NMP-03 1"
    other_in = ["Loopback 0"]
    other_out = ["Microsoft GS Wavetable Synth 0"]
    sent = []
    opened_in = []
    opened_out = []
    fail_send = False
    fail_read = False
    pending = []

W = World

class FakeIn:
    def __init__(self, name): self.name = name; self.closed = False; W.opened_in.append(self)
    def iter_pending(self):
        if W.fail_read: raise OSError("device removed")
        out, W.pending[:] = list(W.pending), []
        return out
    def close(self): self.closed = True

class FakeOut:
    def __init__(self, name): self.name = name; self.closed = False; W.opened_out.append(self)
    def send(self, msg):
        if W.fail_send: raise OSError("device removed")
        W.sent.append(msg)
    def close(self): self.closed = True

mido.get_input_names = lambda: W.other_in + ([W.in_name] if W.plugged else [])
mido.get_output_names = lambda: W.other_out + ([W.out_name] if W.plugged else [])
def open_input(name):
    if not W.plugged: raise OSError("no such port")
    return FakeIn(name)
def open_output(name):
    if not W.plugged: raise OSError("no such port")
    return FakeOut(name)
mido.open_input, mido.open_output = open_input, open_output

from PySide6.QtCore import QObject
from midi.connection_monitor import ConnectionMonitor
from midi.listener import MidiListener
from midi.sender import MidiSender
from midi.sync import DeviceSync, push_state
from state.amp_state import AmpState
from ui.main_window import MainWindow
from shortcuts.manager import ShortcutManager
from fake_keyboard import FakeKeyboard

app = QApplication([])

def wait_until(cond, timeout=3.0, what=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond(): return
        time.sleep(0.01)
    raise AssertionError("timeout: " + what)

def settle(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)

def boot():
    W.sent.clear(); W.opened_in.clear(); W.opened_out.clear()
    W.fail_send = W.fail_read = False
    state = AmpState()
    listener, sender = MidiListener(), MidiSender()
    monitor = ConnectionMonitor(listener, sender, poll_interval=0.05, settle_delay=0.05)
    listener.preset_changed.connect(state.on_preset_changed)
    listener.start()
    connected = monitor.try_connect()
    state.set_connected(connected)
    if connected: push_state(state, sender)
    sync = DeviceSync(state, sender)
    monitor.connected_changed.connect(state.set_connected, Qt.QueuedConnection)
    monitor.start()
    window = MainWindow(state, sender, ShortcutManager(backend=FakeKeyboard()))
    window.show()
    settle(0.1)
    return state, listener, sender, monitor, sync, window

def shutdown(listener, sender, monitor, window):
    monitor.stop(); listener.stop(); sender.close(); window.close()

def indicator_text(window):
    return window.navigationInterface.widget("connection").text()

def banner_alive(window):
    b = window._banner
    if b is None: return False
    try: return b.isVisible()
    except RuntimeError: return False

# ---------------- 1. lancement SANS Mighty ----------------
W.plugged = False
state, listener, sender, monitor, sync, window = boot()
assert state.connected is False
assert indicator_text(window) == "Mighty déconnecté", indicator_text(window)
assert banner_alive(window), "bandeau attendu au lancement sans Mighty"
print("1. lancement sans Mighty : OK (pas de crash, bandeau + indicateur)")

# ---------------- 2. édition hors connexion ----------------
sender.set_preset(3); sender.drum_set_level(40); sender.drum_set_eq(1, 2, 3); sender.tuner_enable(True)
state.set_drum_level(40); state.on_preset_changed(3)   # ce que font les panneaux
assert W.sent == []
print("2. envois hors connexion = no-op silencieux : OK")

# ---------------- 3. branchement à chaud ----------------
W.plugged = True
wait_until(lambda: state.connected, what="connexion détectée")
settle(0.15)
assert indicator_text(window) == "Mighty connecté"
assert not banner_alive(window), "bandeau doit disparaître"
kinds = [m.type for m in W.sent]
assert "program_change" in kinds and "sysex" in kinds, kinds
pc = [m for m in W.sent if m.type == "program_change"][0]
assert pc.program == 3, pc          # l'état édité hors connexion est repoussé
lvl = [m for m in W.sent if m.type == "control_change" and m.control == 79][0]
assert lvl.value == 40
pushes_1 = len([m for m in W.sent if m.type == "program_change"])
assert pushes_1 == 1, f"un seul push attendu, {pushes_1}"
print("3. branchement à chaud + resync de l'état édité hors ligne : OK")

# ---------------- 4. réception MIDI ----------------
W.pending.append(mido.Message("program_change", program=5))
wait_until(lambda: state.current_preset == 5, what="preset reçu")
print("4. réception MIDI après (re)connexion : OK")

# ---------------- 5. débranchement (port disparaît de la liste) ----------------
W.plugged = False
wait_until(lambda: not state.connected, what="déconnexion détectée")
settle(0.1)
assert indicator_text(window) == "Mighty déconnecté"
assert banner_alive(window)
assert all(p.closed for p in W.opened_in + W.opened_out), "ports non fermés"
sender.set_preset(1)  # ne doit pas lever
print("5. débranchement détecté (liste) + ports fermés : OK")

# ---------------- 6. rebranchement avec nom de port différent ----------------
W.in_name, W.out_name = "2- NUX NMP-03 4", "NUX NMP-03 7"
W.sent.clear()
W.plugged = True
wait_until(lambda: state.connected, what="reconnexion")
settle(0.15)
assert not banner_alive(window)
assert len([m for m in W.sent if m.type == "program_change"]) == 1, "doublon de push à la reconnexion"
assert W.opened_out[-1].name == "NUX NMP-03 7" and W.opened_in[-1].name == "2- NUX NMP-03 4"
print("6. reconnexion avec noms de ports différents, un seul push : OK")

# ---------------- 7. échec d'envoi (nom encore listé) ----------------
W.fail_send = True
sender.set_preset(2)   # ne doit pas lever, et tue le port
assert not sender.is_open
wait_until(lambda: not state.connected, what="déconnexion sur échec d'envoi")
W.fail_send = False
wait_until(lambda: state.connected, what="reconnexion après échec d'envoi")
print("7. échec d'envoi => déconnexion puis reconnexion auto : OK")

# ---------------- 8. échec de lecture ----------------
W.fail_read = True
wait_until(lambda: not state.connected, what="déconnexion sur échec de lecture")
W.fail_read = False
wait_until(lambda: state.connected, what="reconnexion après échec de lecture")
print("8. échec de lecture => déconnexion puis reconnexion auto : OK")

# ---------------- 9. cycles répétés : pas de handlers en double ----------------
W.pending.clear(); calls = []
state.preset_changed.connect(lambda i: calls.append(i))
for _ in range(3):
    W.plugged = False; wait_until(lambda: not state.connected)
    W.plugged = True;  wait_until(lambda: state.connected)
settle(0.1)
W.pending.append(mido.Message("program_change", program=6))
wait_until(lambda: calls, what="preset reçu après cycles")
settle(0.2)
assert calls == [6], f"handler appelé {len(calls)} fois : {calls}"
print("9. 3 cycles débranché/rebranché, message reçu exactement 1 fois : OK")

shutdown(listener, sender, monitor, window)

# ---------------- 10. lancement AVEC Mighty ----------------
W.plugged = True
W.in_name, W.out_name = "NUX NMP-03 0", "NUX NMP-03 1"
state, listener, sender, monitor, sync, window = boot()
assert state.connected is True
assert indicator_text(window) == "Mighty connecté"
assert window._banner is None
assert len([m for m in W.sent if m.type == "program_change"]) == 1
settle(0.3)
assert len([m for m in W.sent if m.type == "program_change"]) == 1, "double push au lancement"
print("10. lancement avec Mighty : connecté d'emblée, pas de bandeau, un seul push : OK")

# ---------------- 11. arrêt propre ----------------
t0 = time.time()
shutdown(listener, sender, monitor, window)
assert time.time() - t0 < 2, "arrêt trop lent"
print("11. arrêt propre (threads joints) : OK")
# ---------------- 12. une exception inattendue ne tue pas la surveillance ----------------
W.plugged = True
state, listener, sender, monitor, sync, window = boot()
real_link_lost = monitor._link_lost
boom = {"n": 0}
def flaky():
    boom["n"] += 1
    if boom["n"] == 1:
        raise RuntimeError("boom")
    return real_link_lost()
monitor._link_lost = flaky
wait_until(lambda: boom["n"] >= 2, what="surveillance toujours vivante après exception")
assert monitor.isRunning()
W.plugged = False
wait_until(lambda: not state.connected, what="déconnexion détectée après exception")
print("12. exception inattendue dans le thread : surveillance toujours active : OK")
shutdown(listener, sender, monitor, window)

print("\nTOUS LES TESTS PASSENT")
