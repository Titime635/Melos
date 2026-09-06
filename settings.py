"""
Persistance simple d'un fichier JSON unique (app_settings.json, à côté de ce
module) pour les réglages qui doivent survivre au redémarrage : preset
courant, réglages batterie/EQ, mode du tuner, entrées/sortie + volume/
répétitions/passes d'overdub/décompte de la loop station, séquence active
+ touches globales de la setlist.

Neutre par rapport aux autres modules : pas de dépendance à AmpState ni à
LoopEngine ici, chaque module lit/écrit juste sa propre section pour
préserver leur indépendance (la loop station reste 100% logicielle et ne
connaît rien du MIDI, cf audio/loop_engine.py).
"""

import json
from pathlib import Path
from typing import Any

SETTINGS_FILE = Path(__file__).resolve().parent / "app_settings.json"

_DEFAULTS: dict[str, Any] = {
    "current_preset": 0,
    "drum": {
        "enabled": False,
        "style": 0,
        "level": 0,
        "bass": 0,
        "middle": 0,
        "treble": 0,
    },
    "tuner": {
        "mode": 0,           # 0=chromatique, 1=guitare compensée, 2=guitare standard, 3=basse
        "requested": False,  # état demandé par l'utilisateur, pas une confirmation matérielle
    },
    "loop": {
        "input_device_name": None,
        "output_device_name": None,
        "volume": 1.0,
        "repeat_target": 0,       # 0 = infini
        "overdub_passes_target": 1,  # 0 = illimité (arrêt manuel)
        "count_in_enabled": False,
        "count_in_bpm": 100,
    },
    "setlist": {
        "active_sequence_name": None,
        "enabled": True,      # si False, naviguer les étapes ne pilote plus le device
        "next_key": None,
        "previous_key": None,
    },
}


def load_settings() -> dict:
    data: dict = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            data = {}

    merged = json.loads(json.dumps(_DEFAULTS))  # copie profonde des défauts
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def save_settings(settings: dict):
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")