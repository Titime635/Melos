"""
Accordages de guitare 6 cordes et analyse d'une mesure du tuner de l'ampli.

L'ampli (en mode chromatique) donne la note la plus proche (CC 12, numéro MIDI) et l'écart en cents (CC 72).
Ici on compare ce qu'on entend à la note CIBLE de chaque corde de l'accordage choisi.
"""

from dataclasses import dataclass

PITCH = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
         "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Nom -> notes de la corde grave (6) à la corde aiguë (1)
TUNINGS: dict[str, str] = {
    "Standard": "E A D G B E",
    "Eb standard": "Eb Ab Db Gb Bb Eb",
    "D standard": "D G C F A D",
    "C standard": "C F Bb Eb G C",
    "B standard": "B E A D F# B",
    "Drop D": "D A D G B E",
    "Drop C#": "C# G# C# F# A# D#",
    "Drop C": "C G C F A D",
    "Drop B": "B F# B E G# C#",
    "Drop A": "A E A D F# B",
    "Open D": "D A D F# A D",
    "Open E": "E B E G# B E",
    "Open G": "D G D G B D",
    "Open A": "E A E A C# E",
    "Open C": "C G C G C E",
    "Open D mineur": "D A D F A D",
    "Open E mineur": "E B E G B E",
    "Open G mineur": "D G D G Bb D",
    "DADGAD": "D A D G A D",
    "DADDAD": "D A D D A D",
    "Double Drop D": "D A D G B D",
    "All Fourths": "E A D G C F",
    "New Standard Tuning": "C G D A E G",
}
QUICK = ("Standard", "Eb standard", "Drop D")   # boutons directs ; le reste est dans « … »
DEFAULT = "Standard"
IN_TUNE_CENTS = 3.0
FAR_SEMITONES = 1.5     # au-delà, aucune corde ne correspond : on affiche la note chromatique


@dataclass(frozen=True)
class GuitarString:
    number: int   # 6 (grave) ... 1 (aiguë)
    label: str    # "Eb", "F#"...
    midi: int     # note cible


def strings_of(tuning: str) -> list[GuitarString]:
    """Cordes de la plus grave à la plus aiguë, avec leur octave : la corde grave est la plus basse note
    >= 33 (La 1), puis chaque corde est la plus proche note >= la précédente."""
    labels = TUNINGS.get(tuning, TUNINGS[DEFAULT]).split()
    out: list[GuitarString] = []
    prev = 33
    for i, label in enumerate(labels):
        pc = PITCH[label]
        midi = prev + ((pc - prev) % 12)
        out.append(GuitarString(6 - i, label, midi))
        prev = midi
    return out


@dataclass(frozen=True)
class Reading:
    label: str                 # note à afficher en grand
    cents: float               # écart signé par rapport à la cible (ou à la note chromatique)
    string: int | None         # indice (0 = corde grave) de la corde visée, None si aucune
    fallback: bool             # True : note chromatique, aucune corde ne correspond

    @property
    def in_tune(self) -> bool:
        return abs(self.cents) <= IN_TUNE_CENTS


def _circular(semitones: float) -> float:
    return (semitones + 6.0) % 12.0 - 6.0


def analyze(pc: int, cents: float, tuning: str, selected: int | None,
            tuned: frozenset | set = frozenset(), prefer: int | None = None) -> Reading:
    """`pc` : classe de hauteur 0-11 (Do = 0) renvoyée par l'ampli, SANS octave ; `cents` : écart (déjà
    calibré) par rapport à cette note. Plusieurs cordes peuvent avoir la même note (Mi grave / Mi aigu) :
    on garde `prefer` (corde déjà visée sans coupure), sinon la première pas encore accordée."""
    strings = strings_of(tuning)
    pitch = pc + cents / 100.0
    if selected is not None and 0 <= selected < len(strings):
        target = strings[selected]
        dev = _circular(pitch - target.midi)
        return Reading(target.label, dev * 100.0, selected, False)
    best = min(range(len(strings)),
               key=lambda i: (round(abs(_circular(pitch - strings[i].midi)), 6), 0 if i == prefer else 1,
                              i in tuned, i))
    dev = _circular(pitch - strings[best].midi)
    if abs(dev) > FAR_SEMITONES:
        return Reading(SHARP_NAMES[pc % 12], cents, None, True)
    return Reading(strings[best].label, dev * 100.0, best, False)