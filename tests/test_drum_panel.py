"""Module Batterie : 75 styles par catégorie, sélecteur, favoris, MIDI, densité."""
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

from midi import drum_styles as ds
from midi import protocol
from state.amp_state import AmpState
from ui.drum_panel import DrumPanel, StyleItem

# ---- 1. données ----
assert ds.STYLE_COUNT == 75 and len(ds.CATEGORIES) == 11
assert ds.style_info(0)[1:] == ("4/4 4th", 1) and ds.style_info(13)[0].key == "ROCK" and ds.style_info(13)[1] == "Hard Rock"
assert ds.style_info(74)[1:] == ("ELEC-TECH", 75) and ds.style_info(22)[1] == "Slow Blues"
assert sum(len(ds.raws_of(c.key)) for c in ds.CATEGORIES) == 75
print("1. 75 styles, 11 catégories, numéros affichés 1-75 : OK")

state = AmpState(); sender = MagicMock()
p = DrumPanel(state, sender); p.resize(380, 300); p.show(); pump(0.2)

# ---- 2. choix d'un style : CC brut = numéro affiché - 1, état mis à jour ----
p._open_picker(); pump(0.1)
assert p._picker.isVisible()
p._picker._select_tab("JAZZ"); pump(0.05)
items = p._picker._scroll.widget().findChildren(StyleItem)
assert len(items) == 7
walking = next(i for i in items if ds.style_info(i.raw)[1] == "Walking")
walking.chosen.emit(walking.raw); pump(0.05)
assert state.drum_style == walking.raw == 47 and not p._picker.isVisible()   # n° 48
sender.drum_set_style.assert_called_with(47)
print("2. sélecteur : style choisi (n° 48, CC 47) envoyé et mémorisé : OK")

# ---- 3. favoris : persistance, onglet Favoris ----
p._toggle_favorite(47); p._toggle_favorite(0); p._toggle_favorite(0)
assert state.drum_favorites == [47]
assert settings.load_settings()["drum"]["favorites"] == [47]
p._open_picker(); p._picker._select_tab("FAV"); pump(0.05)
assert [i.raw for i in p._picker._scroll.widget().findChildren(StyleItem)] == [47]
p._picker.hide()
assert AmpState().drum_favorites == [47]
print("3. favoris ajoutés / retirés, sauvegardés, onglet Favoris : OK")

# ---- 4. volume / EQ / interrupteur inchangés ----
sender.reset_mock()
p._level_slider.setValue(50); sender.drum_set_level.assert_called_with(protocol.drum_level_from_percent(50))
p._bass_slider.setValue(40); assert sender.drum_set_eq.call_args[0][0] == 40
p._switch.setChecked(True); pump(0.05); assert state.drum_enabled
sender.drum_enable.assert_called_with(True)
print("4. volume, EQ et interrupteur : OK")

# ---- 5. réception d'un style depuis l'ampli : la tuile suit ----
state.on_drum_cc(protocol.CC_DRUMTYPE, 70); pump(0.05)
assert p._tile._raw == 70
print("5. changement venu de l'ampli reflété : OK")

# ---- 6. densité ----
p.resize(380, 300); pump(0.1); assert p._level_w.isVisible() and p._eq_w.isVisible()
p.resize(380, p._base_height() + 60); pump(0.1); assert p._level_w.isVisible() and not p._eq_w.isVisible()
p.resize(380, p._base_height() + 4); pump(0.1); assert not p._level_w.isVisible()
print("6. densité : EQ puis volume masqués quand c'est petit : OK")

# ---- 7. raccourci : bascule de la batterie ----
sender.reset_mock()
state.set_drum_enabled(False); p._refresh()
p.toggle_enabled(); assert state.drum_enabled and p._switch.isChecked(); sender.drum_enable.assert_called_with(True)
p.toggle_enabled(); assert not state.drum_enabled and not p._switch.isChecked(); sender.drum_enable.assert_called_with(False)
class Sync:
    def __init__(self): self.cb = None; self.stopped = 0
    def request_drum_start(self, cb): self.cb = cb; return True      # looper quantifié : le départ attend la mesure
    def drum_stopped(self): self.stopped += 1
sync = Sync(); p.set_sync(sync); sender.reset_mock()
p.toggle_enabled(); assert p._pending_start and not state.drum_enabled and p._switch.isChecked()
p.toggle_enabled(); assert not p._pending_start and not p._switch.isChecked() and sync.stopped >= 1   # 2e appui : annule l'attente
sender.drum_enable.assert_called_with(False)
print("7. raccourci batterie : bascule, départ en attente annulable : OK")

p.close()
print("\nBATTERIE OK")