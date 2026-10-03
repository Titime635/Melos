"""
Page "Raccourcis" : interrupteur global + une ligne par action (touche
actuelle, "Définir" pour capturer une touche, "Effacer").

Pendant une capture, les raccourcis existants sont suspendus (cf
shortcuts/manager.py) : appuie sur la combinaison voulue, Échap annule.
Une touche déjà utilisée par une autre action est refusée (pas de vol
silencieux). Aucune touche par défaut : tout est à définir ici.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea
from qfluentwidgets import (
    HeaderCardWidget, PushButton, BodyLabel, StrongBodyLabel, SwitchButton,
    TransparentToolButton, FluentIcon,
)

from shortcuts.actions import ACTIONS, BY_ID, GROUPS
from shortcuts.manager import ShortcutManager, key_parts, risk_note

NO_KEY_TEXT = "—"


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

        switch_row = QHBoxLayout()
        switch_row.addWidget(BodyLabel("Raccourcis actifs :"))
        self._switch = SwitchButton()
        self._switch.setOnText("Actifs")
        self._switch.setOffText("Coupés")
        self._switch.setChecked(manager.enabled)
        self._switch.checkedChanged.connect(manager.set_enabled)
        switch_row.addWidget(self._switch)
        switch_row.addStretch()
        general_layout.addLayout(switch_row)

        info = BodyLabel(
            "Les touches fonctionnent même quand la fenêtre n'est pas au premier plan. "
            "Coupe l'interrupteur pour taper normalement. "
            "Elles pilotent la vue affichée (Dashboard ou Classique)."
        )
        info.setWordWrap(True)
        general_layout.addWidget(info)

        self._status = BodyLabel(manager.last_error and f"⚠ {manager.last_error}")
        self._status.setWordWrap(True)
        general_layout.addWidget(self._status)
        layout.addWidget(general)

        # --- Une carte par groupe d'actions ---
        self._key_labels: dict[str, BodyLabel] = {}
        self._set_buttons: dict[str, PushButton] = {}
        self._clear_buttons: dict[str, TransparentToolButton] = {}
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
        manager.enabled_changed.connect(self._on_enabled_changed)
        manager.capture_result.connect(self._on_capture_result)
        manager.error.connect(self._on_error)
        self._refresh()

    def _build_row(self, action_id: str, label: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(BodyLabel(label), stretch=1)

        key_label = StrongBodyLabel(NO_KEY_TEXT)
        key_label.setMinimumWidth(110)
        row.addWidget(key_label)
        self._key_labels[action_id] = key_label

        set_btn = PushButton("Définir")
        set_btn.clicked.connect(lambda _checked=False, aid=action_id: self._on_set_clicked(aid))
        row.addWidget(set_btn)
        self._set_buttons[action_id] = set_btn

        clear_btn = TransparentToolButton(FluentIcon.DELETE)
        clear_btn.setToolTip("Retirer la touche")
        clear_btn.clicked.connect(lambda _checked=False, aid=action_id: self._on_clear_clicked(aid))
        row.addWidget(clear_btn)
        self._clear_buttons[action_id] = clear_btn
        return row

    # --- Actions utilisateur ---

    def _on_set_clicked(self, action_id: str):
        self._set_busy(True)
        self._status.setText(f"Appuie sur la touche pour « {BY_ID[action_id].label} » (Échap pour annuler)…")
        self._manager.start_capture(action_id)

    def _on_clear_clicked(self, action_id: str):
        self._manager.assign(action_id, None)
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

    def _on_enabled_changed(self, enabled: bool):
        self._switch.blockSignals(True)
        self._switch.setChecked(enabled)
        self._switch.blockSignals(False)

    def _set_busy(self, busy: bool):
        for btn in self._set_buttons.values():
            btn.setEnabled(not busy)

    def _refresh(self):
        bindings = self._manager.bindings()
        for action_id, label in self._key_labels.items():
            key = bindings.get(action_id)
            label.setText(display_key(key))
            self._clear_buttons[action_id].setEnabled(key is not None)
