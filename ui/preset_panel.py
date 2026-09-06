"""
Panneau de contrôle des presets.

Affiche les 7 presets du Mighty Plug Pro sous forme de boutons, chacun
surmonté d'une pastille de couleur. Le preset actif est visuellement mis en
avant, et se met à jour tout seul que le changement vienne d'un clic ici ou
d'un appui physique sur le device (grâce à AmpState.preset_changed).

IMPORTANT (bug corrigé) : le device n'envoie PAS d'écho de confirmation
après une commande program_change initiée par l'hôte (confirmé
empiriquement, cf docs/protocol_notes.md — seuls les changements physiques
sont notifiés spontanément). Attendre cet écho pour rafraîchir l'UI (comme
le faisait la version précédente) bloquait donc l'affichage indéfiniment
pour tout clic logiciel. On met maintenant à jour l'état nous-mêmes juste
après avoir envoyé la commande ; les appuis physiques restent notifiés
normalement via listener -> state.
"""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame
from qfluentwidgets import HeaderCardWidget, PushButton, PrimaryPushButton, LineEdit

from state.amp_state import AmpState
from midi.sender import MidiSender
from midi.protocol import CHANNELS_COUNT

# Fichier à côté de ce module, indépendant du dossier de lancement de l'appli
# (avant : chemin relatif au cwd — si tu avais déjà des presets renommés,
# déplace l'ancien preset_names.json ici)
NAMES_FILE = Path(__file__).resolve().parent / "preset_names.json"

# Couleur associée à chaque preset (fournie par l'utilisateur)
PRESET_COLORS = {
    0: "#61D149",
    1: "#E98D32",
    2: "#EA5A53",
    3: "#2C75EE",
    4: "#46D1E6",
    5: "#DF74D6",
    6: "#FBB6F4",
}


class PresetPanel(HeaderCardWidget):
    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent)
        self.setTitle("Presets")

        self._state = state
        self._sender = sender
        self._buttons: dict[int, PushButton] = {}
        self._containers: dict[int, QWidget] = {}
        self._names: dict[int, str] = self._load_names()

        self._build_ui()
        self._refresh_active_button(state.current_preset)

        # Se met à jour tout seul quand le device notifie un changement,
        # que ce soit via un clic ici ou un appui physique sur le device
        self._state.preset_changed.connect(self._on_state_preset_changed)

    def _build_ui(self):
        layout = QVBoxLayout()
        self.viewLayout.addLayout(layout)

        self._grid = QGridLayout()
        self._grid.setSpacing(8)
        layout.addLayout(self._grid)

        for i in range(CHANNELS_COUNT):
            self._create_button(i, active=(i == self._state.current_preset))

        # Zone de renommage rapide du preset actif
        rename_row = QHBoxLayout()
        self._rename_edit = LineEdit()
        self._rename_edit.setPlaceholderText("Renommer le preset actif...")
        rename_btn = PushButton("Enregistrer")
        rename_btn.clicked.connect(self._on_rename_clicked)
        rename_row.addWidget(self._rename_edit)
        rename_row.addWidget(rename_btn)
        layout.addLayout(rename_row)

    def _create_button(self, index: int, active: bool):
        """Crée (ou remplace) le bouton d'un preset, avec sa pastille de
        couleur au-dessus. La pastille est un QFrame simple (pas un
        composant Fluent) : la styliser directement ne casse pas le thème,
        contrairement à un setStyleSheet sur un PushButton Fluent.
        """
        name = self._names.get(index, f"Preset {index}")
        button_cls = PrimaryPushButton if active else PushButton

        btn = button_cls(name)
        btn.setMinimumHeight(48)
        btn.clicked.connect(lambda checked=False, idx=index: self._on_button_clicked(idx))

        color = PRESET_COLORS.get(index, "#888888")
        color_bar = QFrame()
        color_bar.setFixedHeight(4)
        color_bar.setStyleSheet(f"background-color: {color}; border-radius: 2px;")

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)
        container_layout.addWidget(color_bar)
        container_layout.addWidget(btn)

        self._grid.addWidget(container, index // 4, index % 4)
        self._buttons[index] = btn
        self._containers[index] = container
        return btn

    def _on_button_clicked(self, index: int):
        self._sender.set_preset(index)
        # Pas d'écho matériel pour une commande initiée par l'hôte (cf.
        # docstring du module) : on met à jour l'état nous-mêmes.
        self._state.on_preset_changed(index)

    def _on_state_preset_changed(self, index: int):
        self._refresh_active_button(index)

    def _refresh_active_button(self, active_index: int):
        for i, old_container in list(self._containers.items()):
            self._grid.removeWidget(old_container)
            old_container.deleteLater()
            self._create_button(i, active=(i == active_index))

    def _on_rename_clicked(self):
        new_name = self._rename_edit.text().strip()
        if not new_name:
            return
        active = self._state.current_preset
        self._names[active] = new_name
        self._buttons[active].setText(new_name)
        self._save_names()
        self._rename_edit.clear()

    # --- Persistance des noms (simple JSON local, à côté du module) ---
    def _load_names(self) -> dict[int, str]:
        if NAMES_FILE.exists():
            try:
                raw = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
                return {int(k): v for k, v in raw.items()}
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}

    def _save_names(self):
        NAMES_FILE.write_text(
            json.dumps(self._names, ensure_ascii=False, indent=2), encoding="utf-8"
        )