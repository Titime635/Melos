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
from midi.drum_styles import clamp_raw
from settings import load_settings, update_settings
from state.transport_state import TransportState
from state.tuner_session import TunerSession


def _legacy_cent_zero() -> int:
    """Ancien fichier de calibration du tuner (ui/tuner_calibration.json), sinon le milieu de la plage observée."""
    import json
    from pathlib import Path
    try:
        raw = json.loads((Path(__file__).resolve().parent.parent / "ui" / "tuner_calibration.json").read_text("utf-8"))
        return int(raw["cent_zero_offset"])
    except Exception:
        return 50   # hypothèse : le CC 72 va de 0 à 100 autour de 50 (= juste)


class AmpState(QObject):
    preset_changed = Signal(int)
    tuner_updated = Signal()       # note/cent/enabled/requested ont changé, relire les attributs
    drum_updated = Signal()        # idem pour les réglages batterie
    connection_changed = Signal(bool)  # le Mighty vient d'être (dé)connecté
    setlist_enabled_changed = Signal(bool)  # interrupteur "setlist active" (partagé Dashboard / Classique)

    def __init__(self):
        super().__init__()
        self._settings = load_settings()

        self.current_preset: int = self._settings["current_preset"]
        # Interrupteur "setlist active" : un seul état pour les deux vues (Dashboard et Classique ont
        # chacune leur SetlistPanel). Sinon l'une restait allumée quand on coupait l'autre, et les
        # raccourcis suivant/précédent (qui suivent la setlist si elle est active) se mettaient à
        # parcourir la séquence au lieu des presets.
        self.setlist_enabled: bool = bool(self._settings["setlist"]["enabled"])
        # Connexion au Mighty : mise à jour par le ConnectionMonitor (cf
        # midi/connection_monitor.py), jamais persistée. Hors connexion l'UI
        # continue d'éditer cet état ; il est repoussé au device à la reconnexion.
        self.connected: bool = False

        # Tempo / signature / quantification (partagé par les loop stations et la batterie)
        self.transport = TransportState(self)

        # Tuner
        # `tuner_requested` : demandé localement par l'UI, c'est la source de
        # vérité pour le on/off (cf ui/tuner_panel.py). CC 11 ne reflète pas
        # fiablement l'activation du tuner — en pratique il semble plutôt lié
        # à la détection d'un signal (silence -> 0, corde jouée -> 1), donc
        # inutilisable pour piloter un simple interrupteur on/off.
        t = self._settings["tuner"]
        self.tuner_requested: bool = t["requested"]
        self.tuner_mode: int = 0   # toujours chromatique : les accordages sont gérés ici (cf midi/tunings.py)
        self.tuner_ref_hz: int = max(protocol.TUNER_REF_HZ_MIN, min(protocol.TUNER_REF_HZ_MAX, int(t.get("ref_hz", 440))))
        self.tuner_sound: bool = bool(t.get("sound", True))
        self.tuner_tuning: str = t.get("tuning", "Standard")
        zero = t.get("cent_zero")
        self.tuner_cent_zero: int = int(zero) if zero else _legacy_cent_zero()   # 0 / absent : jamais un vrai zéro
        self.tuner_cent_scale: float = float(t.get("cent_scale", 1.0))
        self.tuner_cent_zero_notes: dict[int, int] = {int(k): int(v) for k, v in t.get("cent_zero_notes", {}).items()}
        self.tuner_note_shift: int = int(t.get("note_shift", 0))   # demi-tons ajoutés au CC 12 (correction)
        self.tuner = TunerSession(self)   # lecture lissée, cordes accordées, son (cf state/tuner_session.py)
        self.tuner_enabled: bool = False  # miroir brut de CC 11, gardé pour diagnostic
        self.tuner_note: int = 0
        self.tuner_cent: int = 0
        self.tuner_string: int = 0   # CC 71 brut (diagnostic)

        # Batterie (direct en CC, pas de SysEx) — restaurée depuis app_settings.json
        d = self._settings["drum"]
        self.drum_enabled: bool = d["enabled"]
        self.drum_style: int = clamp_raw(d["style"])
        self.drum_favorites: list[int] = sorted({clamp_raw(i) for i in d.get("favorites", [])})
        # Plafonné : une valeur sauvegardée avant la mise à l'échelle du curseur (cf midi/protocol.py)
        # pourrait être bien trop forte, et elle est renvoyée à l'ampli au lancement.
        self.drum_level: int = min(d["level"], protocol.DRUM_LEVEL_CC_CAP)
        self.drum_bass: int = d["bass"]
        self.drum_middle: int = d["middle"]
        self.drum_treble: int = d["treble"]

    def _persist(self):
        # Seulement NOS sections : réécrire toute la copie chargée au lancement
        # écraserait les réglages sauvegardés depuis par les autres modules.
        update_settings({
            "current_preset": self.current_preset,
            "drum": {
                "enabled": self.drum_enabled,
                "style": self.drum_style,
                "level": self.drum_level,
                "bass": self.drum_bass,
                "middle": self.drum_middle,
                "treble": self.drum_treble,
                "favorites": self.drum_favorites,
            },
            "tuner": {
                "mode": self.tuner_mode,
                "requested": self.tuner_requested,
                "ref_hz": self.tuner_ref_hz,
                "sound": self.tuner_sound,
                "tuning": self.tuner_tuning,
                "cent_zero": self.tuner_cent_zero,
                "cent_scale": self.tuner_cent_scale,
                "note_shift": self.tuner_note_shift,
                "cent_zero_notes": {str(k): v for k, v in self.tuner_cent_zero_notes.items()},
            },
        })

    def set_setlist_enabled(self, enabled: bool):
        if enabled == self.setlist_enabled:
            return
        self.setlist_enabled = enabled
        update_settings({"setlist": {**load_settings()["setlist"], "enabled": enabled}})
        self.setlist_enabled_changed.emit(enabled)

    def set_connected(self, connected: bool):
        if connected == self.connected:
            return
        self.connected = connected
        self.connection_changed.emit(connected)

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

    def on_tuner_string(self, value: int):
        self.tuner_string = value
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

    def set_tuner_options(self, **changes):
        """ref_hz, sound, tuning, cent_zero, cent_scale (module Tuner)."""
        for name, value in changes.items():
            setattr(self, "tuner_" + name, value)
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

    def toggle_drum_favorite(self, raw: int):
        favs = set(self.drum_favorites)
        favs.symmetric_difference_update({clamp_raw(raw)})
        self.drum_favorites = sorted(favs)
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