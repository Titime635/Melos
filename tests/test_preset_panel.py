"""Module Presets : numérotation 1-7 à l'écran / 0-6 en interne, présentation adaptative, renommage,
mise à jour en place, et carte de module compacte."""
import os, sys, time, tempfile, pathlib, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "app_settings.json"
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
app = QApplication([])
def pump(sec=0.1):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

import ui.preset_panel as pp
pp.NAMES_FILE = pathlib.Path(tempfile.mkdtemp()) / "preset_names.json"   # ne touche pas aux vrais noms
from state.amp_state import AmpState

class FakeSender:
    def __init__(self): self.sent = []
    def set_preset(self, i): self.sent.append(i)

state = AmpState(); sender = FakeSender()

# ---- 1. numérotation : affichage 1-7, backend 0-6 ----
assert [pp.display_number(i) for i in range(7)] == [1, 2, 3, 4, 5, 6, 7]
assert pp.default_name(0) == "Preset 1" and pp.default_name(6) == "Preset 7"
panel = pp.PresetPanel(state, sender)
panel.resize(440, 230); panel.show(); pump(0.1)
assert panel._buttons[0]._name == "Preset 1" and panel._buttons[6]._name == "Preset 7"
QTest.mouseClick(panel._buttons[2], Qt.LeftButton); pump(0.05)
assert sender.sent == [2], "le bouton affiché « 3 » envoie l'index 2 au backend"
assert state.current_preset == 2 and panel._buttons[2]._active and not panel._buttons[1]._active
print("1. affichage 1-7, backend 0-6 (le bouton « Preset 3 » envoie l'index 2) : OK")

# ---- 2. mise à jour en place (pas de recréation), y compris changement physique ----
before = dict(panel._buttons)
state.on_preset_changed(5); pump(0.05)
assert panel._buttons == before and all(a is b for a, b in zip(before.values(), panel._buttons.values()))
assert panel._buttons[5]._active and not panel._buttons[2]._active
print("2. changement de preset : boutons mis à jour en place : OK")

# ---- 3. choix de présentation selon la place : les noms restent tant que la grille tient ----
plan = pp.PresetPanel._plan
assert plan(440, 230) == ("grid", 4)               # 4+3
assert plan(440, 100) == ("grid", 4)
assert plan(250, 200) == ("grid", 3)              # étroit : 3 colonnes, toujours des noms
assert plan(150, 300)[0] == "grid" and plan(150, 300)[1] in (2, 1)
assert plan(440, 50) == ("numbers", 7)            # trop bas pour la grille : pastilles
assert plan(200, 36) == ("strip", 0)              # minuscule : ◀ nom ▶
# Monotonie : en rétrécissant, on ne repasse jamais d'un chiffre à un texte puis de nouveau à un chiffre
order = {"grid": 0, "numbers": 1, "strip": 2}
for fixed_w in (440, 300, 250, 200):
    seq = [order[plan(fixed_w, h)[0]] for h in range(300, 29, -1)]
    assert seq == sorted(seq), (fixed_w, seq)
for fixed_h in (300, 120, 60):
    seq = [order[plan(w, fixed_h)[0]] for w in range(600, 99, -1)]
    assert seq == sorted(seq), (fixed_h, seq)
print("3. présentation : noms tant que la grille tient, puis pastilles, puis « ◀ nom ▶ », jamais de va-et-vient : OK")

host = QWidget(); lay = QVBoxLayout(host); lay.setContentsMargins(0, 0, 0, 0)
panel.setParent(host); lay.addWidget(panel); host.show()
def at(w, h):
    host.resize(w, h); pump(0.1)
    return [i for i, b in panel._buttons.items() if b.isVisible()], panel._strip_btn.isVisible()
vis, strip = at(440, 240)
assert len(vis) == 7 and not strip and all(panel._buttons[i]._kind in ("card", "flat") for i in vis)
vis, strip = at(250, 260)
assert len(vis) == 7 and all(panel._buttons[i]._kind in ("card", "flat") for i in vis), "étroit : toujours des noms"
vis, strip = at(300, 90)
assert len(vis) == 7 and all(panel._buttons[i]._kind == "number" for i in vis)
vis, strip = at(200, panel.minimumSizeHint().height())
assert strip or len(vis) == 7
assert not hasattr(panel, "_rename_edit"), "la ligne de renommage a disparu (le crayon la remplace)"
print("4. le module change réellement de présentation en se redimensionnant : OK")

# ---- 4b. texte : plusieurs lignes aux espaces, police adaptée ----
from PySide6.QtGui import QFont, QFontMetrics, QImage, QPainter
img = QImage(120, 60, QImage.Format_ARGB32); img.fill(0)
pt = QPainter(img); f = QFont(); f.setBold(True)
from PySide6.QtCore import QRectF
pp.PresetButton._draw_fitted(pt, f, QRectF(4, 4, 110, 50), "Greenday The Clash Live", 20)
pt.end()
assert 9 <= f.pixelSize() <= 20 and f.pixelSize() < 20, "la police s'adapte au nom long"
box = QFontMetrics(f).boundingRect(0, 0, 110, 10000, int(Qt.AlignCenter | Qt.TextWordWrap), "Greenday The Clash Live")
assert box.height() > QFontMetrics(f).height() * 1.5, "le nom long passe sur plusieurs lignes"
print("4b. noms longs : retour à la ligne aux espaces et police réduite : OK")

# ---- 5. renommage : popup (crayon / double-clic) ; clés internes 0-6 ----
at(440, 240)
state.on_preset_changed(1); pump(0.05)
panel._open_rename_popup(); pump(0.05)
assert panel._rename_popup.isVisible() and "preset 2" in panel._popup_title.text() and panel._popup_edit.text() == ""
panel._popup_edit.setText("Greenday"); panel._on_popup_validated(); pump(0.05)
assert panel._names == {1: "Greenday"} and panel._buttons[1]._name == "Greenday" and panel._buttons[1]._custom
assert json.loads(pp.NAMES_FILE.read_text(encoding="utf-8")) == {"1": "Greenday"}
panel._open_rename_popup(); pump(0.05)
assert panel._popup_edit.text() == "Greenday"
panel._popup_edit.setText("Clash"); panel._on_popup_validated(); pump(0.05)
assert panel._names[1] == "Clash" and not panel._rename_popup.isVisible()
panel._buttons[1].double_clicked.emit(); pump(0.05)
assert panel._rename_popup.isVisible(); panel._rename_popup.hide()
state.on_preset_changed(0); panel._open_rename_popup(); panel._popup_edit.setText("   "); panel._on_popup_validated()
assert 0 not in panel._names, "un nom vide ne renomme rien"
print("5. renommage (crayon, double-clic), noms enregistrés par index interne : OK")

# ---- 6. carte de module compacte ----
from ui.module_card import HEADER_HEIGHT, VIEW_MARGINS
assert panel.headerView.height() == HEADER_HEIGHT == 30 and VIEW_MARGINS[0] <= 12
assert panel.chrome_height() == 30 + 1 + VIEW_MARGINS[1] + VIEW_MARGINS[3] < 60
assert panel.getTitle() == "Presets"
print("6. en-tête de module compact (~30 px) et marges serrées : OK")

print("\nPRESETS OK")
import sounddevice as _sd
_sd._initialized = 0