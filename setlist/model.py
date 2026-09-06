"""
Modèle de données des setlists.

Une séquence nommée (un morceau) est une liste ordonnée d'étapes, chaque
étape correspondant à un preset (0-6) avec un label optionnel ("Couplet",
"Refrain", "Solo"...). Persisté dans setlists.json à la racine du projet,
séparé de app_settings.json (settings.py) : ce n'est pas un simple réglage
d'appli mais du contenu créé par l'utilisateur (ses morceaux).
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

SETLISTS_FILE = Path(__file__).resolve().parent.parent / "setlists.json"


@dataclass
class Step:
    preset: int       # 0-6, index du preset à envoyer pour cette étape
    label: str = ""   # ex: "Couplet", "Refrain" — facultatif


@dataclass
class Sequence:
    name: str
    steps: list[Step] = field(default_factory=list)


def load_sequences() -> list[Sequence]:
    if not SETLISTS_FILE.exists():
        return []
    try:
        raw = json.loads(SETLISTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []

    sequences = []
    for seq in raw.get("sequences", []):
        steps = [Step(preset=s["preset"], label=s.get("label", "")) for s in seq.get("steps", [])]
        sequences.append(Sequence(name=seq["name"], steps=steps))
    return sequences


def save_sequences(sequences: list[Sequence]):
    data = {
        "sequences": [
            {"name": seq.name, "steps": [asdict(s) for s in seq.steps]}
            for seq in sequences
        ]
    }
    SETLISTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
