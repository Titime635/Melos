"""
Panneau setlist / séquences live.

Une séquence nommée = un morceau : une liste ordonnée d'étapes, chaque
étape = un preset (0-6) + un label facultatif ("Couplet", "Refrain"...).
On choisit la séquence active (ou aucune, via l'entrée "(aucune)"), on
avance dedans avec les boutons ou les raccourcis globaux (cf shortcuts/ et
l'onglet Raccourcis), en boucle une fois la fin atteinte. Un interrupteur "Setlist active" permet de garder sa position
dans la séquence sans que la navigation pilote le device — utile pour
naviguer/répéter sans reprendre la main sur le preset en cours.

Ce panneau connaît AmpState/MidiSender (contrairement à la loop station) :
avancer d'une étape doit réellement changer le preset sur le device, avec
la même mise à jour optimiste que preset_panel.py (pas d'écho matériel pour
une commande host, cf. docs/protocol_notes.md).

Séquence active et interrupteur sont restaurés/sauvegardés
via settings.py, comme le reste de l'appli.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    HeaderCardWidget, PushButton, LineEdit, BodyLabel, TitleLabel,
    TransparentToolButton, FluentIcon, SwitchButton,
)

from state.amp_state import AmpState
from midi.sender import MidiSender
from settings import load_settings, update_settings
from setlist.model import Sequence, Step, load_sequences, save_sequences
from setlist.player import SetlistPlayer
from ui.widgets import NoWheelSpinBox, NoWheelComboBox


class SetlistPanel(HeaderCardWidget):
    def __init__(self, state: AmpState, sender: MidiSender, parent=None):
        super().__init__(parent)
        self.setTitle("Setlist")

        self._state = state
        self._sender = sender
        self._settings = load_settings()

        self._player = SetlistPlayer()
        self._player.step_changed.connect(self._on_step_changed)
        self._player.sequence_changed.connect(self._refresh_all)

        self._build_ui()
        self._restore_settings()

    def _build_ui(self):
        layout = QVBoxLayout()
        self.viewLayout.addLayout(layout)

        # --- Choix / création de séquence ---
        seq_row = QHBoxLayout()
        self._sequence_combo = NoWheelComboBox()
        self._sequence_combo.currentIndexChanged.connect(self._on_sequence_selected)
        seq_row.addWidget(self._sequence_combo)

        self._new_name_edit = LineEdit()
        self._new_name_edit.setPlaceholderText("Nom du morceau...")
        seq_row.addWidget(self._new_name_edit)

        new_btn = PushButton("Nouvelle séquence")
        new_btn.clicked.connect(self._on_new_sequence)
        seq_row.addWidget(new_btn)

        delete_seq_btn = PushButton("Supprimer la séquence")
        delete_seq_btn.clicked.connect(self._on_delete_sequence)
        seq_row.addWidget(delete_seq_btn)
        self._delete_seq_btn = delete_seq_btn

        layout.addLayout(seq_row)

        # --- Interrupteur général : la navigation pilote (ou non) le device ---
        enabled_row = QHBoxLayout()
        enabled_row.addWidget(BodyLabel("Setlist active (pilote le preset du device) :"))
        self._enabled_switch = SwitchButton()
        self._enabled_switch.setOnText("Active")
        self._enabled_switch.setOffText("Coupée")
        self._enabled_switch.checkedChanged.connect(self._on_enabled_toggled)
        enabled_row.addWidget(self._enabled_switch)
        enabled_row.addStretch()
        layout.addLayout(enabled_row)

        # --- Étape courante, mise en avant ---
        self._current_step_label = TitleLabel("Aucune séquence active")
        self._current_step_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._current_step_label)

        nav_row = QHBoxLayout()
        prev_btn = PushButton("◀ Précédent")
        prev_btn.clicked.connect(self._player.previous_step)
        nav_row.addWidget(prev_btn)

        next_btn = PushButton("Suivant ▶")
        next_btn.clicked.connect(self._player.next_step)
        nav_row.addWidget(next_btn)
        layout.addLayout(nav_row)

        # Les touches Suivant / Précédent se règlent dans l'onglet Raccourcis
        layout.addWidget(BodyLabel("Touches Suivant / Précédent : onglet Raccourcis."))

        # --- Liste des étapes de la séquence active ---
        layout.addWidget(BodyLabel("Étapes :"))
        self._steps_layout = QVBoxLayout()
        self._steps_layout.setSpacing(4)
        layout.addLayout(self._steps_layout)

        add_step_row = QHBoxLayout()
        self._add_preset_spin = NoWheelSpinBox()
        self._add_preset_spin.setRange(1, 7)  # affiché 1-7, cohérent avec la numérotation des presets
        add_step_row.addWidget(BodyLabel("Preset"))
        add_step_row.addWidget(self._add_preset_spin)

        self._add_label_edit = LineEdit()
        self._add_label_edit.setPlaceholderText("Label (facultatif)")
        add_step_row.addWidget(self._add_label_edit)

        add_step_btn = PushButton("Ajouter une étape")
        add_step_btn.clicked.connect(self._on_add_step)
        add_step_row.addWidget(add_step_btn)
        layout.addLayout(add_step_row)

    # --- Restauration au lancement ---

    def _restore_settings(self):
        s = self._settings["setlist"]

        self._enabled_switch.blockSignals(True)
        self._enabled_switch.setChecked(s["enabled"])
        self._enabled_switch.blockSignals(False)

        sequences = load_sequences()
        self._player.set_sequences(sequences)  # déclenche _refresh_all via le signal

        active_name = s["active_sequence_name"]
        if active_name:
            for i, seq in enumerate(sequences):
                if seq.name == active_name:
                    self._player.set_active(i)  # renvoie aussi le preset de l'étape (si activée)
                    break

        self._refresh_all()  # couvre le cas où rien n'a été restauré

    def _save_setlist_settings(self):
        seq = self._player.active_sequence
        self._settings["setlist"] = {
            "active_sequence_name": seq.name if seq else None,
            "enabled": self._enabled_switch.isChecked(),
        }
        update_settings({"setlist": self._settings["setlist"]})  # seulement notre section (cf settings.py)

    # --- Séquences ---

    def _on_new_sequence(self):
        name = self._new_name_edit.text().strip()
        if not name:
            return
        sequences = list(self._player.sequences)
        sequences.append(Sequence(name=name, steps=[]))
        save_sequences(sequences)
        self._player.set_sequences(sequences)
        self._player.set_active(len(sequences) - 1)
        self._new_name_edit.clear()
        self._save_setlist_settings()

    def _on_delete_sequence(self):
        idx = self._player.active_index
        if idx is None:
            return
        sequences = list(self._player.sequences)
        del sequences[idx]
        save_sequences(sequences)
        self._player.set_sequences(sequences)
        self._player.set_active(None)
        self._save_setlist_settings()

    def _on_sequence_selected(self, index: int):
        # index 0 = "(aucune)" : permet explicitement de ne rien sélectionner
        if index <= 0:
            self._player.set_active(None)
        else:
            self._player.set_active(index - 1)
        self._save_setlist_settings()

    # --- Étapes ---

    def _on_add_step(self):
        seq = self._player.active_sequence
        if seq is None:
            return
        preset = self._add_preset_spin.value() - 1  # affiché 1-7 -> index 0-6
        label = self._add_label_edit.text().strip()
        seq.steps.append(Step(preset=preset, label=label))
        save_sequences(self._player.sequences)
        self._add_label_edit.clear()
        self._refresh_steps()
        if len(seq.steps) == 1:  # c'était vide avant : personne n'a encore activé l'étape 0
            self._player.refresh_current()

    def _on_delete_step(self, index: int):
        seq = self._player.active_sequence
        if seq is None or not (0 <= index < len(seq.steps)):
            return
        del seq.steps[index]
        save_sequences(self._player.sequences)
        self._player.notify_step_removed(index)  # recale l'étape courante + notifie
        self._refresh_steps()

    # --- Navigation : c'est ICI qu'on parle au device (le player, lui, ne connaît pas le MIDI) ---

    def _on_step_changed(self, _index: int):
        step = self._player.current_step()
        if step is not None and self._enabled_switch.isChecked():
            self._sender.set_preset(step.preset)
            self._state.on_preset_changed(step.preset)  # mise à jour optimiste, cf preset_panel.py
        self._refresh_current_step()

    def _on_enabled_toggled(self, checked: bool):
        self._save_setlist_settings()
        if checked:
            # Resynchronise immédiatement le device sur l'étape courante,
            # qu'on vient de réactiver après l'avoir mise en pause
            step = self._player.current_step()
            if step is not None:
                self._sender.set_preset(step.preset)
                self._state.on_preset_changed(step.preset)

    # --- Raccourcis clavier (cf shortcuts/router.py) ---

    def is_navigation_active(self) -> bool:
        """True si suivant/précédent doivent piloter la setlist : interrupteur sur
        "Active" ET une séquence avec au moins une étape sélectionnée."""
        return self._enabled_switch.isChecked() and self._player.current_step() is not None

    def navigate(self, direction: int):
        if direction > 0:
            self._player.next_step()
        else:
            self._player.previous_step()

    # --- Rafraîchissement UI ---

    def _refresh_all(self):
        self._sequence_combo.blockSignals(True)
        self._sequence_combo.clear()
        self._sequence_combo.addItem("(aucune)")
        for seq in self._player.sequences:
            self._sequence_combo.addItem(seq.name)
        self._sequence_combo.setCurrentIndex(
            self._player.active_index + 1 if self._player.active_index is not None else 0
        )
        self._sequence_combo.blockSignals(False)

        self._delete_seq_btn.setEnabled(self._player.active_index is not None)
        self._refresh_steps()
        self._refresh_current_step()

    def _refresh_current_step(self):
        seq = self._player.active_sequence
        step = self._player.current_step()
        if seq is None:
            self._current_step_label.setText("Aucune séquence active")
        elif step is None:
            self._current_step_label.setText(f"{seq.name} — aucune étape")
        else:
            position = f"{self._player.step_index + 1}/{len(seq.steps)}"
            label = f" — {step.label}" if step.label else ""
            paused = "" if self._enabled_switch.isChecked() else " [setlist coupée]"
            self._current_step_label.setText(
                f"{seq.name} [{position}] : Preset {step.preset + 1}{label}{paused}"
            )

    def _refresh_steps(self):
        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        seq = self._player.active_sequence
        if seq is None:
            self._steps_layout.addWidget(BodyLabel("(sélectionne ou crée une séquence)"))
            return
        if not seq.steps:
            self._steps_layout.addWidget(BodyLabel("(aucune étape — ajoute-en une ci-dessous)"))
            return

        for i, step in enumerate(seq.steps):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            marker = "▶ " if i == self._player.step_index else "   "
            text = f"{marker}{i + 1}. Preset {step.preset + 1}"
            if step.label:
                text += f" — {step.label}"
            row_layout.addWidget(BodyLabel(text))
            row_layout.addStretch()
            delete_btn = TransparentToolButton(FluentIcon.DELETE)
            delete_btn.clicked.connect(lambda checked=False, idx=i: self._on_delete_step(idx))
            row_layout.addWidget(delete_btn)
            self._steps_layout.addWidget(row)
