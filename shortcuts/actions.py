"""
Catalogue des actions pilotables par raccourci.

Une action = un identifiant stable + un libellé. Elle ne sait pas COMMENT
elle s'exécute (c'est shortcuts/router.py) ni QUELLE touche la déclenche
(c'est shortcuts/manager.py) : la source (clavier aujourd'hui, pédalier
Arduino en V4, Jarvis en V5) est interchangeable, il suffit d'émettre
l'identifiant d'une action.
"""

from dataclasses import dataclass

PRESET_COUNT = 7

GROUP_PRESETS = "Presets"
GROUP_LOOP = "Loop station"
GROUPS = [GROUP_PRESETS, GROUP_LOOP]


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    group: str
    hold_seconds: float = 0.0  # > 0 : n'a lieu que si la touche reste enfoncée ce temps-là


ACTIONS: list[Action] = [
    *[Action(f"preset_{i}", f"Preset {i}", GROUP_PRESETS) for i in range(1, PRESET_COUNT + 1)],
    Action("nav_next", "Suivant (setlist si active, sinon preset)", GROUP_PRESETS),
    Action("nav_previous", "Précédent (setlist si active, sinon preset)", GROUP_PRESETS),
    Action("loop_cycle", "Touche cyclique : rec → play → overdub", GROUP_LOOP),
    Action("loop_record", "Enregistrer / arrêter l'enregistrement", GROUP_LOOP),
    Action("loop_overdub", "Overdub / arrêter l'overdub", GROUP_LOOP),
    Action("loop_play", "Play / Stop", GROUP_LOOP),
    Action("loop_clear", "Effacer la boucle (maintenir 1 s)", GROUP_LOOP, hold_seconds=1.0),
]

BY_ID: dict[str, Action] = {a.id: a for a in ACTIONS}
