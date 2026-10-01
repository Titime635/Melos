"""
Panneau du tuner.

Active/désactive le tuner via SysEx (protocol.build_tuner_sysex) et affiche
la note détectée + l'écart en cents (CC 12 / CC 72).

IMPORTANT (bug corrigé) : CC 11 ("état") ne reflète pas de façon fiable
l'activation/désactivation du tuner — en pratique il semble plutôt lié à la
détection d'un signal (il ne passe à 1 qu'en jouant une corde). L'utiliser
pour piloter le switch causait un comportement incohérent (interrupteur qui
retombe "coupé" au repos, qu'il faut "réveiller" en jouant, y compris pour
le désactiver). Le switch reflète donc maintenant une demande locale
(`AmpState.tuner_requested`), mise à jour immédiatement au clic — il n'y a
pas de confirmation matérielle fiable pour ce toggle (contrairement aux
presets), donc c'est notre meilleure source de vérité disponible.

Le zéro exact du CC 72 n'est pas confirmé empiriquement (plage observée
35-69, cf docs/protocol_notes.md). Un bouton "Définir comme référence"
permet de capturer la valeur brute courante comme zéro, à faire en jouant
une corde déjà accordée avec un accordeur externe. En attendant calibration,
on part du milieu de la plage observée (~52) plutôt que 0, qui donnait un
décalage systématique de +40/+50 cents constaté sur toutes les cordes.
"""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
from qfluentwidgets import HeaderCardWidget, SwitchButton, PushButton, BodyLabel, TitleLabel

from state.amp_state import AmpState
from midi.sender import MidiSender
from midi.protocol import note_name, TUNER_REF_PITCH_440HZ
from ui.widgets import NoWheelComboBox

# Fichier à côté de ce module, indépendant du dossier de lancement de l'appli
# (avant : chemin relatif au cwd, source probable d'incohérence de calibration)
CALIBRATION_FILE = Path(__file__).resolve().parent / "tuner_calibration.json"

# Milieu de la plage observée empiriquement (35-69) — meilleure estimation
# disponible tant que l'utilisateur n'a pas calibré manuellement
DEFAULT_CENT_ZERO = 52

# (label affiché, valeur du champ `mode` dans le SysEx)
TUNER_MODES = [
    ("Chromatique", 0),
    ("Guitare compensée", 1),
    ("Guitare standard", 2),
    ("Basse", 3),
]


def load_tuner_offset() -> int:
    """Partagé avec ui/dashboard/compact/tuner_compact.py : les deux vues
    doivent rester calibrées pareil, un seul fichier, un seul point de lecture."""
    if CALIBRATION_FILE.exists():
        try:
            raw = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
            return int(raw.get("cent_zero_offset", DEFAULT_CENT_ZERO))
        except (json.JSONDecodeError, ValueError):
            return DEFAULT_CENT_ZERO
    return DEFAULT_CENT_ZERO


def save_tuner_offset(offset: int):
    CALIBRATION_FILE.write_text(
        json.dumps({"cent_zero_offset": offset}), encoding="utf-8"
    )


class CentsGauge(QWidget):
    """Jauge horizontale minimale : aiguille centrée, verte dans la tolérance.

    Peint au QPainter (pas de setStyleSheet) donc aucun conflit avec le QSS
    du thème Fluent, clair ou sombre.
    """

    TOLERANCE_CENTS = 5
    DISPLAY_RANGE = 50  # cents affichés aux extrémités de la jauge (clampé)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cents = 0
        self._active = False

    def set_cents(self, cents: int, active: bool):
        self._cents = max(-self.DISPLAY_RANGE, min(self.DISPLAY_RANGE, cents))
        self._active = active
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        mid_y = h // 2

        painter.setPen(QPen(QColor("#888888"), 2))
        painter.drawLine(10, mid_y, w - 10, mid_y)

        painter.setPen(QPen(QColor("#aaaaaa"), 2))
        painter.drawLine(w // 2, mid_y - 12, w // 2, mid_y + 12)

        if not self._active:
            painter.end()
            return

        ratio = self._cents / self.DISPLAY_RANGE
        x = int(w / 2 + ratio * (w / 2 - 20))

        in_tune = abs(self._cents) <= self.TOLERANCE_CENTS
        color = QColor("#2ecc71") if in_tune else QColor("#e67e22")

        painter.setPen(QPen(color, 4))
        painter.drawLine(x, 8, x, h - 8)
        painter.end()


class TunerPanel(HeaderCardWidget):
    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent)
        self.setTitle("Tuner")

        self._state = state
        self._sender = sender
        self._cent_offset = self._load_offset()

        self._build_ui()

        self._state.tuner_updated.connect(self._refresh)
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout()
        self.viewLayout.addLayout(layout)

        top_row = QHBoxLayout()
        self._switch = SwitchButton()
        self._switch.setOnText("Actif")
        self._switch.setOffText("Coupé")
        self._switch.checkedChanged.connect(self._on_toggle)
        top_row.addWidget(self._switch)

        self._mode_combo = NoWheelComboBox()
        for label, _ in TUNER_MODES:
            self._mode_combo.addItem(label)
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(self._mode_index_for(self._state.tuner_mode))
        self._mode_combo.blockSignals(False)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        top_row.addWidget(self._mode_combo)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._note_label = TitleLabel("--")
        self._note_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._note_label)

        self._gauge = CentsGauge()
        layout.addWidget(self._gauge)

        cal_row = QHBoxLayout()
        self._cent_label = BodyLabel("-- cents")
        cal_row.addWidget(self._cent_label)
        cal_row.addStretch()
        calibrate_btn = PushButton("Définir comme référence (0 cent)")
        calibrate_btn.clicked.connect(self._on_calibrate)
        cal_row.addWidget(calibrate_btn)
        layout.addLayout(cal_row)

    # --- Actions utilisateur ---

    def _on_toggle(self, checked: bool):
        mode = TUNER_MODES[self._mode_combo.currentIndex()][1]
        self._sender.tuner_enable(on=checked, mode=mode, ref_pitch=TUNER_REF_PITCH_440HZ)
        # Pas de confirmation matérielle fiable pour ce toggle (cf. note en
        # tête de fichier) : on fait confiance à la commande qu'on vient
        # d'envoyer plutôt que d'attendre un CC qui reflète autre chose.
        self._state.set_tuner_requested(checked)

    def _on_mode_changed(self, _index: int):
        mode = TUNER_MODES[self._mode_combo.currentIndex()][1]
        self._state.set_tuner_mode(mode)
        # Si le tuner est déjà actif, on renvoie l'activation avec le nouveau mode
        if self._switch.isChecked():
            self._sender.tuner_enable(on=True, mode=mode, ref_pitch=TUNER_REF_PITCH_440HZ)

    @staticmethod
    def _mode_index_for(mode_value: int) -> int:
        for i, (_, value) in enumerate(TUNER_MODES):
            if value == mode_value:
                return i
        return 0

    def _on_calibrate(self):
        self._cent_offset = self._state.tuner_cent
        self._save_offset()
        self._refresh()

    # --- Réaction à l'état (source de vérité = AmpState) ---

    def _refresh(self):
        active = self._state.tuner_requested

        self._switch.blockSignals(True)
        self._switch.setChecked(active)
        self._switch.blockSignals(False)

        if not active:
            self._note_label.setText("--")
            self._cent_label.setText("-- cents")
            self._gauge.set_cents(0, active=False)
            return

        self._note_label.setText(note_name(self._state.tuner_note))

        relative_cents = self._state.tuner_cent - self._cent_offset
        sign = "+" if relative_cents > 0 else ""
        self._cent_label.setText(f"{sign}{relative_cents} cents")
        self._gauge.set_cents(relative_cents, active=True)

    # --- Persistance du décalage de calibration ---

    def _load_offset(self) -> int:
        return load_tuner_offset()

    def _save_offset(self):
        save_tuner_offset(self._cent_offset)