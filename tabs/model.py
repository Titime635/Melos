"""
Modèle de partition, indépendant de Songsterr et de l'affichage.

Convention des cordes : `string` = 0 pour la corde la PLUS AIGUË (comme Songsterr), `tuning` liste les notes MIDI
de la plus aiguë à la plus grave (ex guitare : [64, 59, 55, 50, 45, 40]).
Durées en fraction de ronde : (numérateur, dénominateur), ex (1, 8) = croche.
"""

from dataclasses import dataclass, field
from fractions import Fraction


@dataclass
class Note:
    string: int = 0
    fret: int = 0
    rest: bool = False
    tie: bool = False                 # liée à la note précédente
    dead: bool = False
    ghost: bool = False
    hammer: bool = False              # hammer-on / pull-off vers la note suivante
    palm_mute: bool = False
    accent: int = 0                   # 1 = accent, 2 = accent fort
    vibrato: bool = False
    let_ring: bool = False
    staccato: bool = False
    slide: str | None = None          # shift / legato / into_from_below / ...
    harmonic: str | None = None       # natural / artificial / pinch / tap / semi / feedback
    bend: list[tuple[int, int]] | None = None   # [(position 0-60, hauteur en 1/100 de ton)]


@dataclass
class Beat:
    notes: list[Note] = field(default_factory=list)
    rest: bool = False
    base: int = 4                     # 1, 2, 4, 8, 16, 32, 64
    dots: int = 0
    tuplet: int = 0                   # 0 = aucun, sinon 3, 5, 6, 7, 9, 10, 12
    let_ring: bool = False
    palm_mute: bool = False
    text: str | None = None
    chord: str | None = None
    velocity: str | None = None       # ppp ... fff
    grace: str | None = None          # beforeBeat / onBeat
    lyrics: str | None = None         # syllabe(s) chantée(s) sur ce temps

    @property
    def length(self) -> Fraction:
        """Durée réelle en fraction de ronde (points et n-olets compris)."""
        value = Fraction(1, self.base)
        add, half = value, value
        for _ in range(self.dots):
            half /= 2
            add += half
        if self.tuplet:
            num, den = tuplet_ratio(self.tuplet)
            add = add * den / num
        return add


# n-olet -> (notes jouées, notes de la mesure remplacées) : triolet 3 pour 2, quintolet 5 pour 4...
TUPLET_RATIO = {3: (3, 2), 4: (4, 3), 5: (5, 4), 6: (6, 4), 7: (7, 4), 8: (8, 6), 9: (9, 8), 10: (10, 8), 11: (11, 8),
                12: (12, 8), 13: (13, 8)}


def tuplet_ratio(n: int) -> tuple[int, int]:
    """(notes jouées, notes de la mesure remplacées) ; pour un n-olet inhabituel : la puissance de 2 juste en dessous."""
    if n in TUPLET_RATIO:
        return TUPLET_RATIO[n]
    den = 1
    while den * 2 < n:
        den *= 2
    return n, max(1, den)


@dataclass
class Measure:
    index: int
    signature: tuple[int, int] = (4, 4)
    marker: str | None = None         # nom de section : « Verse 1 », « Chorus »...
    voices: list[list[Beat]] = field(default_factory=list)
    repeat_start: bool = False
    repeat_end: int = 0               # nombre de passages (0 = pas de reprise)
    alt_ending: list[int] = field(default_factory=list)
    double_bar: bool = False

    @property
    def length(self) -> Fraction:
        return Fraction(self.signature[0], self.signature[1])


@dataclass
class Track:
    part_id: int
    name: str
    instrument: str = ""
    instrument_id: int = 0
    tuning: list[int] = field(default_factory=list)
    is_drums: bool = False
    is_bass: bool = False
    is_vocal: bool = False
    is_guitar: bool = False
    hash: str = ""                    # identifiant de piste Songsterr (lié aux pistes audio séparées)
    sounds: list[int] = field(default_factory=list)       # programmes General MIDI des « sons » de la piste (distorsion, clean, nappe...)
    sound_changes: list[tuple[int, float, int]] = field(default_factory=list)   # (mesure, position 0-1, indice dans `sounds`)
    lyrics: list[tuple[int, str]] = field(default_factory=list)   # [(mesure de départ à partir de 1, texte)]
    measures: list[Measure] = field(default_factory=list)


@dataclass
class TempoChange:
    measure: int
    position: float = 0.0             # position dans la mesure (0-1)
    bpm: float = 120.0
    unit: int = 4                     # valeur de note du tempo (4 = noire)


@dataclass
class Score:
    song_id: int
    revision_id: int
    title: str
    artist: str
    tempo: list[TempoChange] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    default_part: int = 0             # piste affichée par défaut sur songsterr.com

    @property
    def measure_count(self) -> int:
        return max((len(t.measures) for t in self.tracks), default=0)

    def sections(self) -> list[tuple[int, str]]:
        """[(index de mesure, nom de section)] — pris sur la première piste qui en a."""
        for t in self.tracks:
            found = [(m.index, m.marker) for m in t.measures if m.marker]
            if found:
                return found
        return []