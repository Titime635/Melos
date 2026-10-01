"""
État courant du Mighty Plug Pro, tenu à jour par les signaux du MidiListener
(et, pour le tuner et la batterie, par des méthodes appelées directement par
l'UI — voir set_tuner_requested / set_drum_* et les commentaires dans
ui/tuner_panel.py et ui/drum_panel.py : le device n'a pas d'écho fiable pour
les commandes initiées par l'host, donc l'UI ne peut pas se contenter
d'attendre une confirmation MIDI).

C'est la source de vérité unique que l'UI observe (pattern observer via
les Signal Qt). L'UI ne doit jamais lire le MIDI directement — elle lit
cet état, qui se met à jour tout seul en tâche de fond.

Le preset courant, les réglages batterie et le mode/état demandé du tuner
sont restaurés depuis app_settings.json au démarrage et sauvegardés à
chaque changement (cf settings.py). C'est main.py qui renvoie ensuite ces
valeurs au device au lancement (l'état ici ne fait que se souvenir, il ne
parle pas au MIDI).
"""

from PySide6.QtCore import QObject, Signal

from midi import protocol
from settings import load_settings, save_settings


class AmpState(QObject):
    preset_changed = Signal(int)
    tuner_updated = Signal()       # note/cent/enabled/requested ont changé, relire les attributs
    drum_updated = Signal()        # idem pour les réglages batterie
    connection_changed = Signal(bool)  # True when device connected, False when disconnected

    def __init__(self):
        super().__init__()
        self._settings = load_settings()

        self.current_preset: int = self._settings["current_preset"]
        self.connected: bool = False

        # Tuner
        # `tuner_requested` : demandé localement par l'UI, c'est la source de
        # vérité pour le on/off (cf ui/tuner_panel.py). CC 11 ne reflète pas
        # fiablement l'activation du tuner — en pratique il semble plutôt lié
        # à la détection d'un signal (silence -> 0, corde jouée -> 1), donc
        # inutilisable pour piloter un simple interrupteur on/off.
        t = self._settings["tuner"]
        self.tuner_requested: bool = t["requested"]
        self.tuner_mode: int = t["mode"]
        self.tuner_enabled: bool = False  # miroir brut de CC 11, gardé pour diagnostic
        self.tuner_note: int = 0
        self.tuner_cent: int = 0

        # Batterie (direct en CC, pas de SysEx) — restaurée depuis app_settings.json
        d = self._settings["drum"]
        self.drum_enabled: bool = d["enabled"]
        self.drum_style: int = d["style"]
        self.drum_level: int = d["level"]
        self.drum_bass: int = d["bass"]
        self.drum_middle: int = d["middle"]
        self.drum_treble: int = d["treble"]

    def _persist(self):
        self._settings["current_preset"] = self.current_preset
        self._settings["drum"] = {
            "enabled": self.drum_enabled,
            "style": self.drum_style,
            "level": self.drum_level,
            "bass": self.drum_bass,
            "middle": self.drum_middle,
            "treble": self.drum_treble,
        }
        self._settings["tuner"] = {
            "mode": self.tuner_mode,
            "requested": self.tuner_requested,
        }
        save_settings(self._settings)

    # --- Méthodes appelées par les signaux du MidiListener ---
    # (à connecter dans main.py : listener.preset_changed.connect(state.on_preset_changed))

    def on_preset_changed(self, index: int):
        self.current_preset = index
        self.preset_changed.emit(index)
        self._persist()

    def on_tuner_note(self, note: int):
        self.tuner_note = note
        self.tuner_updated.emit()

    def on_tuner_cent(self, cent: int):
        self.tuner_cent = cent
        self.tuner_updated.emit()

    def on_tuner_state(self, enabled: bool):
        self.tuner_enabled = enabled
        self.tuner_updated.emit()

    def set_tuner_requested(self, requested: bool):
        """Appelé par l'UI (pas par le MIDI) quand l'utilisateur bascule le
        switch — voir la note sur CC 11 plus haut."""
        self.tuner_requested = requested
        self.tuner_updated.emit()
        self._persist()

    def set_tuner_mode(self, mode: int):
        self.tuner_mode = mode
        self.tuner_updated.emit()
        self._persist()

    def on_drum_cc(self, control: int, value: int):
        """Route un CC batterie brut reçu du device (typiquement un
        changement physique) vers le bon attribut."""
        if control == protocol.CC_DRUMENABLE:
            self.drum_enabled = bool(value)
        elif control == protocol.CC_DRUMTYPE:
            self.drum_style = value
        elif control == protocol.CC_DRUMLEVEL:
            self.drum_level = value
        elif control == protocol.CC_DRUM_BASS:
            self.drum_bass = value
        elif control == protocol.CC_DRUM_MIDDLE:
            self.drum_middle = value
        elif control == protocol.CC_DRUM_TREBLE:
            self.drum_treble = value
        self.drum_updated.emit()
        self._persist()

    # --- Méthodes appelées par l'UI (mise à jour optimiste, cf. docstring) ---

    def set_drum_enabled(self, enabled: bool):
        self.drum_enabled = enabled
        self.drum_updated.emit()
        self._persist()

    def set_drum_style(self, style: int):
        self.drum_style = style
        self.drum_updated.emit()
        self._persist()

    def set_drum_level(self, level: int):
        self.drum_level = level
        self.drum_updated.emit()
        self._persist()

    def set_drum_eq(self, bass: int, middle: int, treble: int):
        self.drum_bass = bass
        self.drum_middle = middle
        self.drum_treble = treble
        self.drum_updated.emit()
        self._persist()

    def set_connected(self, connected: bool):
        """Set connection state and emit signal.

        Called by ConnectionMonitor when device presence changes.
        This is the single source of truth for connection state.
        """
        if self.connected != connected:
            self.connected = connected
            self.connection_changed.emit(connected)