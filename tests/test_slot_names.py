"""Noms d'emplacements partagés (Dashboard / Classique / setlist / éditeur) : un seul SlotNames, noms de la bibliothèque."""
import os, sys, time, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"
from PySide6.QtWidgets import QApplication
app = QApplication([])
def pump(sec=0.15):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

import ui.preset_panel as pp
tmp = pathlib.Path(tempfile.mkdtemp())
pp.NAMES_FILE = tmp / "preset_names.json"
import test_editor as te
from editor.service import EditorService
from state.amp_state import AmpState

amp, bank, lib, links, wb = te.make_env(str(tmp / "env"))
svc = EditorService(bank, wb)
bank.refresh_from_amp()
wb.import_slot(0, "Clean Fender")
pp.NAMES_FILE.write_text('{"2": "Solo"}', encoding="utf-8")

names = pp.SlotNames(svc, lib)
assert names.name(0) == ("Clean Fender", True)          # lié à la bibliothèque : son nom
assert names.name(1) == ("Preset 2", False)             # ni lié ni nommé
assert names.name(2) == ("Solo", True)                  # ancien nom perso
print("1. noms : bibliothèque > ancien nom perso > « Preset N » : OK")

class Sender:
    def set_preset(self, i): pass
state = AmpState()
panel = pp.PresetPanel(state, Sender(), names=names)
panel.resize(440, 230); panel.show(); pump()
assert panel._buttons[0]._name == "Clean Fender" and panel._buttons[2]._name == "Solo"

# renommer le preset actif depuis le panneau : la bibliothèque suit
state.on_preset_changed(0); pump()
changed = []
names.changed.connect(lambda: changed.append(1))
panel._rename_active("Crunch Marshall"); pump()
assert lib.entries()[0].name == "Crunch Marshall" and panel._buttons[0]._name == "Crunch Marshall" and changed
print("2. renommer depuis le Dashboard renomme le preset de la bibliothèque : OK")

# renommer dans la bibliothèque (comme l'éditeur) : le panneau suit sans rien faire
changed.clear()
lib.update(lib.entries()[0].id, name="Clean Final"); pump()
assert panel._buttons[0]._name == "Clean Final" and changed
print("3. renommage côté éditeur répercuté dans le panneau : OK")

# emplacement sans lien : le nom perso reste dans le fichier historique
state.on_preset_changed(1); pump()
panel._rename_active("Lead"); pump()
assert pp.SlotNames._load_legacy().get(1) == "Lead" and panel._buttons[1]._name == "Lead"
assert lib.entries()[0].name == "Clean Final"
print("4. emplacement hors bibliothèque : nom perso historique : OK")

# modification de la copie de travail : pastille « à renvoyer »
eid = lib.entries()[0].id
changed.clear()
wb.edit(eid, lambda p: setattr(p, "master", 77), "test", "t"); pump()
assert names.state(0)[0] == "ahead" and panel._buttons[0]._flag == "ahead" and "À renvoyer" in panel._buttons[0].toolTip()
assert panel._buttons[1]._flag is None
print("5. pastille « à renvoyer » sur l'emplacement concerné : OK")

# réinitialisation des noms perso
pp.NAMES_FILE.write_text("{}", encoding="utf-8"); panel.reload_names(); pump()
assert panel._buttons[2]._name == "Preset 3" and panel._buttons[0]._name == "Clean Final"
print("6. reset des noms perso : la bibliothèque garde ses noms : OK")

# setlist : le nom du preset sert de titre quand l'étape n'a pas de label
from ui.setlist_panel import StepsView
from setlist.model import Step
v = StepsView(names=names)
assert v._step_title(Step(preset=0, label="")) == "Clean Final" and v._step_title(Step(preset=0, label="Refrain")) == "Refrain"
assert StepsView()._step_title(Step(preset=3, label="")) == "Preset 4"
print("7. setlist : titre = label sinon nom du preset : OK")
print("test_slot_names OK")
