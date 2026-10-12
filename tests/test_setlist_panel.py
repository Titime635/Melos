"""Module Setlist refondu : mode Jeu (étape courante + 2 suivantes), mode Édition, interrupteur, densité."""
import os, sys, time, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"
import setlist.model
setlist.model.SETLISTS_FILE = pathlib.Path(tempfile.mkdtemp()) / "setlists.json"
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
app = QApplication([])
def pump(sec=0.1):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

from state.amp_state import AmpState
from setlist.model import Sequence, Step, save_sequences
from ui.setlist_panel import SetlistPanel

save_sequences([Sequence("Hotel California", [Step(0, "Intro"), Step(2, "Couplet"), Step(3, "Refrain"), Step(5, "")])])
state = AmpState(); sender = MagicMock()
p = SetlistPanel(state, sender); p.resize(520, 330); p.show(); pump(0.2)
p._sequence_combo.setCurrentIndex(1)
pump(0.1)
assert p._player.active_sequence is not None and p._player.current_step().preset == 0
v = p._steps_view
assert v.next_count() == 2, v.next_count()
print("1. séquence chargée : étape courante + 2 suivantes visibles : OK")

p._enabled_switch.setChecked(True); sender.reset_mock()
p.navigate(+1); pump(0.05)
assert p._player.current_step().preset == 2 and sender.set_preset.call_args[0][0] == 2
p._enabled_switch.setChecked(False); sender.reset_mock()
p.navigate(+1); pump(0.05)
assert not sender.set_preset.called and not p.is_navigation_active()
print("2. interrupteur : navigation pilote le preset seulement quand actif : OK")

p.resize(520, 200); pump(0.1); assert v.next_count() <= 1 and not p._top_w.isVisible()
p.resize(300, p._base_height() + 4); pump(0.1); assert v.next_count() == 0
print("3. densité : suivantes puis choix de séquence masqués quand c'est petit : OK")

p.resize(520, 400); p._set_editing(True); pump(0.1)
assert p._edit_w.isVisible() and not p._play_w.isVisible()
p._on_add_step(); pump(0.05)
assert len(p._player.active_sequence.steps) == 5
p._set_editing(False); pump(0.1); assert p._play_w.isVisible()
print("4. édition dans le module (ajout d'étape) puis retour au jeu : OK")

p.close()
p2 = SetlistPanel(state, sender); p2.resize(200, 70); p2.show(); pump(0.1)
print("\nSETLIST OK")
