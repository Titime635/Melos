"""
Tempo, signature et options de quantification, partagés par toute l'appli.

Un seul objet pour les deux vues (Dashboard et Classique ont chacune leur
loop station) et pour la batterie : changer le tempo dans l'une met l'autre à
jour, et DeviceSync (cf midi/sync.py) l'envoie à la batterie du Mighty.
Sauvegardé dans la section "transport" de app_settings.json.
"""

from PySide6.QtCore import QObject, Signal

from midi import protocol
from settings import load_settings, update_settings

FIELDS = ("bpm", "beats", "unit", "bars", "quantize", "click", "sync_drums", "drum_latency_ms", "latency_comp_ms")
UNITS = (2, 4, 8, 16)  # dénominateurs de signature proposés


class TransportState(QObject):
    changed = Signal(str)  # nom du champ modifié

    def __init__(self, parent=None):
        super().__init__(parent)
        t = load_settings()["transport"]
        self.bpm: int = max(protocol.DRUM_TEMPO_MIN, min(protocol.DRUM_TEMPO_MAX, int(t["bpm"])))
        self.beats: int = max(1, min(16, int(t["beats"])))
        self.unit: int = int(t["unit"]) if int(t["unit"]) in UNITS else 4
        self.bars: int = max(0, int(t["bars"]))
        self.quantize: bool = bool(t["quantize"])
        self.click: bool = bool(t["click"])
        self.sync_drums: bool = bool(t["sync_drums"])
        self.drum_latency_ms: int = max(0, int(t["drum_latency_ms"]))
        self.latency_comp_ms: int = max(0, int(t["latency_comp_ms"]))

    def set(self, **changes):
        modified = []
        for name, value in changes.items():
            if name not in FIELDS:
                raise AttributeError(name)
            if getattr(self, name) != value:
                setattr(self, name, value)
                modified.append(name)
        if modified:
            update_settings({"transport": {name: getattr(self, name) for name in FIELDS}})
            for name in modified:
                self.changed.emit(name)
