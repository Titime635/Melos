"""
Page "Raccourcis" : choix du mode (désactivés / fenêtre active / global) + une ligne par action avec deux
emplacements de touche indépendants (touche actuelle, "Définir" / "+ Ajouter" pour capturer, corbeille).

Pendant une capture, les raccourcis existants sont suspendus (cf
shortcuts/manager.py) : appuie sur la combinaison voulue, Échap annule.
Une touche déjà utilisée par une autre action est refusée (pas de vol
silencieux). Aucune touche par défaut : tout est à définir ici.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea
from qfluentwidgets import (
    HeaderCardWidget, PushButton, BodyLabel, StrongBodyLabel, SegmentedWidget,
    TransparentToolButton, FluentIcon,
)

from shortcuts.actions import ACTIONS, BY_ID, GROUPS
from shortcuts.manager import MAX_KEYS, MODE_GLOBAL, MODE_OFF, MODE_WINDOW, ShortcutManager, key_parts, risk_note

NO_KEY_TEXT = "—"

MODE_LABELS = {MODE_OFF: "Désactivés", MODE_WINDOW: "Fenêtre active", MODE_GLOBAL: "Global"}
MODE_HELP = {
    MODE_OFF: "Aucune touche n'est écoutée : le clavier se comporte normalement partout.",
    MODE_WINDOW: "Les touches ne déclenchent l'action que quand cette fenêtre est au premier plan.",
    MODE_GLOBAL: "Les touches marchent même quand une autre fenêtre a le focus (navigateur, partition...).",
}


def display_key(key: str | None) -> str:
    """"ctrl+f5" -> "Ctrl + F5" ; "a" -> "A"."""
    if not key:
        return NO_KEY_TEXT
    return " + ".join(p.title() if len(p) > 3 else p.upper() for p in key_parts(key))


class ShortcutsInterface(QScrollArea):
    def __init__(self, manager: ShortcutManager, parent=None):
        super().__init__(parent)
        self.setObjectName("ShortcutsInterface")  # requis par FluentWindow pour la navigation
        self._manager = manager
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # --- Général ---
        general = HeaderCardWidget()
        general.setTitle("Raccourcis clavier globaux")
        general_layout = QVBoxLayout()
        general.viewLayout.addLayout(general_layout)

        mode_row = QHBoxLayout()
        mode_row.addWidget(BodyLabel("Mode :"))
        self._mode_switcher = SegmentedWidget()
        for mode, label in MODE_LABELS.items():
            self._mode_switcher.addItem(mode, label, lambda _checked=False, m=mode: manager.set_mode(m))
        self._mode_switcher.setCurrentItem(manager.mode)
        mode_row.addWidget(self._mode_switcher)
        mode_row.addStretch()
        general_layout.addLayout(mode_row)

        self._mode_help = BodyLabel(MODE_HELP[manager.mode])
        self._mode_help.setWordWrap(True)
        general_layout.addWidget(self._mode_help)

        info = BodyLabel(
            "Les touches liées sont réservées à l'appli tant que les raccourcis sont actifs. "
            "Elles pilotent la vue affichée (Dashboard ou Classique)."
        )
        info.setWordWrap(True)
        general_layout.addWidget(info)

        self._status = BodyLabel(manager.last_error and f"⚠ {manager.last_error}")
        self._status.setWordWrap(True)
        general_layout.addWidget(self._status)
        layout.addWidget(general)

        # --- Une carte par groupe d'actions ---
        # Emplacement 1 : _key_labels / _set_buttons / _clear_buttons ; emplacement 2 : les mêmes avec "2"
        self._key_labels: dict[str, BodyLabel] = {}
        self._set_buttons: dict[str, PushButton] = {}
        self._clear_buttons: dict[str, TransparentToolButton] = {}
        self._key_labels2: dict[str, BodyLabel] = {}
        self._set_buttons2: dict[str, PushButton] = {}
        self._clear_buttons2: dict[str, TransparentToolButton] = {}
        for group in GROUPS:
            card = HeaderCardWidget()
            card.setTitle(group)
            rows = QVBoxLayout()
            rows.setSpacing(6)
            card.viewLayout.addLayout(rows)
            for action in (a for a in ACTIONS if a.group == group):
                rows.addLayout(self._build_row(action.id, action.label))
            layout.addWidget(card)

        layout.addStretch()
        self.setWidget(content)

        manager.bindings_changed.connect(self._refresh)
        manager.mode_changed.connect(self._on_mode_changed)
        manager.capture_result.connect(self._on_capture_result)
        manager.error.connect(self._on_error)
        self._refresh()

    def _build_row(self, action_id: str, label: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(BodyLabel(label), stretch=1)
        for slot, (labels, sets, clears) in enumerate((
                (self._key_labels, self._set_buttons, self._clear_buttons),
                (self._key_labels2, self._set_buttons2, self._clear_buttons2))):
            key_label = StrongBodyLabel(NO_KEY_TEXT)
            key_label.setFixedWidth(110)
            key_label.setAlignment(Qt.AlignCenter)
            row.addWidget(key_label)
            labels[action_id] = key_label

            set_btn = PushButton("Définir" if slot == 0 else "+ Ajouter")
            set_btn.setFixedWidth(96)
            set_btn.clicked.connect(lambda _checked=False, aid=action_id, sl=slot: self._on_set_clicked(aid, sl))
            row.addWidget(set_btn)
            sets[action_id] = set_btn

            clear_btn = TransparentToolButton(FluentIcon.DELETE)
            clear_btn.setToolTip("Retirer la touche")
            clear_btn.clicked.connect(lambda _checked=False, aid=action_id, sl=slot: self._on_clear_clicked(aid, sl))
            row.addWidget(clear_btn)
            clears[action_id] = clear_btn
            if slot == 0:
                row.addSpacing(12)
        return row

    # --- Actions utilisateur ---

    def _on_set_clicked(self, action_id: str, slot: int = 0):
        self._set_busy(True)
        self._status.setText(f"Appuie sur la touche pour « {BY_ID[action_id].label} » (Échap pour annuler)…")
        self._manager.start_capture(action_id, slot)

    def _on_clear_clicked(self, action_id: str, slot: int = 0):
        self._manager.assign(action_id, None, slot)
        self._status.setText("")

    # --- Réactions au manager ---

    def _on_capture_result(self, action_id: str, key: str, error: str):
        self._set_busy(False)
        label = BY_ID[action_id].label
        if error:
            self._status.setText(f"⚠ « {label} » : {error}")
        elif key:
            note = risk_note(key)
            text = f"✓ « {label} » : {display_key(key)}"
            self._status.setText(text + (f"\n⚠ {note}" if note else ""))
        else:
            self._status.setText("Capture annulée.")
        self._refresh()

    def _on_error(self, message: str):
        self._status.setText(f"⚠ {message}")

    def _on_mode_changed(self, mode: str):
        self._mode_switcher.setCurrentItem(mode)  # n'appelle pas le callback du clic
        self._mode_help.setText(MODE_HELP[mode])

    def _set_busy(self, busy: bool):
        for btn in (*self._set_buttons.values(), *self._set_buttons2.values()):
            btn.setEnabled(not busy)

    def _refresh(self):
        for action_id in self._key_labels:
            keys = self._manager.keys_for(action_id)
            for slot, (labels, sets, clears) in enumerate((
                    (self._key_labels, self._set_buttons, self._clear_buttons),
                    (self._key_labels2, self._set_buttons2, self._clear_buttons2))):
                key = keys[slot] or None
                labels[action_id].setText(display_key(key))
                clears[action_id].setEnabled(key is not None)
                if slot == 1:
                    sets[action_id].setText("Changer" if key else "+ Ajouter")