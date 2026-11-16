"""
Modifications de l'utilisateur sur une partition (page Partition, étape 10).

La partition de Songsterr n'est jamais touchée : « Ma version » = l'original + une liste de changements, rangée dans la
bibliothèque des morceaux. Les changements sont à la MESURE (une entrée = le contenu complet d'une mesure d'une piste) ou au
tempo : une insertion ou une suppression de temps ne décale donc rien d'autre, et défaire un changement = retirer son entrée.
Le nombre de mesures ne change jamais : les points de synchro de la vidéo restent valables.

    {"op": "measure", "part": id de piste, "bar": index de mesure, "data": {... contenu de la mesure ...}}
    {"op": "tempo", "bar": index de mesure, "bpm": tempo}

Aucune dépendance à Qt : testable seul.
"""

import copy
from dataclasses import asdict, fields
from fractions import Fraction

from .model import Beat, Measure, Note, Score, TempoChange

BASES = (1, 2, 4, 8, 16, 32, 64)
MAX_FRET = 30
BPM_RANGE = (20, 400)


# ---------------------------------------------------------------------------------------------------------
# (dé)sérialisation d'une mesure

def measure_to_dict(m: Measure) -> dict:
    d = asdict(m)
    d.pop("index", None)
    d["signature"] = list(m.signature)
    return d


def _fields_of(cls, raw: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in raw.items() if k in names}


def _note_from(d) -> Note:
    kw = _fields_of(Note, d)
    if kw.get("bend"):
        kw["bend"] = [tuple(p) for p in kw["bend"]]
    return Note(**kw)


def _beat_from(d) -> Beat:
    kw = _fields_of(Beat, d)
    kw["notes"] = [_note_from(n) for n in d.get("notes", [])]
    if kw.get("whammy"):
        kw["whammy"] = [tuple(p) for p in kw["whammy"]]
    return Beat(**kw)


def measure_from_dict(d: dict, index: int) -> Measure:
    kw = _fields_of(Measure, d)
    kw["index"] = index
    kw["signature"] = tuple(d.get("signature", (4, 4)))
    kw["voices"] = [[_beat_from(b) for b in v] for v in d.get("voices", [])]
    kw["alt_ending"] = list(d.get("alt_ending", []))
    return Measure(**kw)


# ---------------------------------------------------------------------------------------------------------
# liste de changements

def clean_edits(raw) -> list[dict]:
    """Ne garde que les changements valides (un seul abîmé ne fait pas perdre les autres). Un changement par (piste, mesure)."""
    out: dict[tuple, dict] = {}
    for e in raw if isinstance(raw, list) else []:
        try:
            bar = int(e["bar"])
            if bar < 0:
                continue
            if e["op"] == "measure" and isinstance(e["data"], dict):
                measure_from_dict(e["data"], bar)                      # doit pouvoir se relire
                out[("m", int(e["part"]), bar)] = {"op": "measure", "part": int(e["part"]), "bar": bar, "data": e["data"]}
            elif e["op"] == "tempo" and BPM_RANGE[0] <= float(e["bpm"]) <= BPM_RANGE[1]:
                out[("t", bar)] = {"op": "tempo", "bar": bar, "bpm": round(float(e["bpm"]), 2)}
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return [out[k] for k in sorted(out, key=lambda k: (k[0], k[1:]))]


def edited_bars(edits: list[dict], part: int | None = None) -> list[int]:
    """Mesures modifiées (pour la piste `part` ; les changements de tempo comptent pour toutes les pistes)."""
    bars = {e["bar"] for e in edits if e["op"] == "tempo" or part is None or e["part"] == part}
    return sorted(bars)


def apply_edits(score: Score, edits: list[dict]) -> Score:
    """Copie de `score` avec les changements appliqués (l'original n'est pas modifié)."""
    out = copy.deepcopy(score)
    tracks = {t.part_id: t for t in out.tracks}
    for e in edits:
        if e["op"] == "measure":
            t = tracks.get(e["part"])
            if t is not None and e["bar"] < len(t.measures):
                t.measures[e["bar"]] = measure_from_dict(e["data"], e["bar"])
        elif e["op"] == "tempo":
            set_tempo(out, e["bar"], e["bpm"])
    return out


def set_tempo(score: Score, bar: int, bpm: float):
    for t in score.tempo:
        if t.measure == bar and t.position == 0.0:
            t.bpm = float(bpm)
            return
    score.tempo.append(TempoChange(bar, 0.0, float(bpm)))
    score.tempo.sort(key=lambda t: (t.measure, t.position))


def tempo_at(score: Score, bar: int) -> float:
    """Tempo en vigueur au début de la mesure `bar`."""
    bpm = score.tempo[0].bpm if score.tempo else 120.0
    for t in score.tempo:
        if t.measure <= bar:
            bpm = t.bpm
    return bpm


def put_measure(edits: list[dict], original: Score, part: int, new: Measure) -> list[dict]:
    """Liste de changements avec la mesure `new` : l'entrée disparaît si elle est redevenue identique à l'originale."""
    track = next((t for t in original.tracks if t.part_id == part), None)
    rest = [e for e in edits if not (e["op"] == "measure" and e["part"] == part and e["bar"] == new.index)]
    if track is None or new.index >= len(track.measures):
        return rest
    data = measure_to_dict(new)
    if data == measure_to_dict(track.measures[new.index]):
        return rest
    return rest + [{"op": "measure", "part": part, "bar": new.index, "data": data}]


def put_tempo(edits: list[dict], original: Score, bar: int, bpm: float) -> list[dict]:
    """Tempo `bpm` à partir de la mesure `bar` ; l'entrée disparaît si c'est le tempo d'origine."""
    rest = [e for e in edits if not (e["op"] == "tempo" and e["bar"] == bar)]
    if abs(tempo_at(original, bar) - bpm) < 0.01:
        return rest
    return rest + [{"op": "tempo", "bar": bar, "bpm": round(float(bpm), 2)}]


def drop_bar(edits: list[dict], part: int | None, bar: int) -> list[dict]:
    """Retire les changements de la mesure `bar` (« revenir à l'original » pour cette mesure)."""
    return [e for e in edits if not (e["bar"] == bar and (e["op"] == "tempo" or part is None or e["part"] == part))]


# ---------------------------------------------------------------------------------------------------------
# opérations sur UNE mesure (la copie de travail) ; `v` = indice de la voix (0 = voix 1)

def rest_beats(length: Fraction) -> list[Beat]:
    """Silences dont la somme vaut `length`."""
    out, left = [], Fraction(length)
    for base in BASES:
        unit = Fraction(1, base)
        while left >= unit:
            out.append(Beat(rest=True, base=base))
            left -= unit
    return out


def beats(m: Measure, v: int = 0) -> list[Beat]:
    """Temps de la voix `v` (créée, remplie de silences, si elle n'existe pas encore)."""
    if not m.voices:
        m.voices = [[]]
    while len(m.voices) <= v:
        m.voices.append(rest_beats(m.length))
    return m.voices[v]


def view(m: Measure, v: int = 0) -> list[Beat]:
    """Comme `beats`, mais sans toucher à la mesure : une voix absente est montrée comme des silences (liste temporaire)."""
    if v < len(m.voices):
        return m.voices[v]
    return rest_beats(m.length)


def fill(m: Measure, v: int = 0) -> tuple[Fraction, Fraction]:
    """(durée des temps de la voix `v`, durée de la mesure) : égales quand la mesure est juste."""
    return sum((b.length for b in view(m, v)), Fraction(0)), m.length


def find_note(b: Beat, string: int) -> Note | None:
    return next((n for n in b.notes if n.string == string and not n.rest), None)


def set_fret(m: Measure, j: int, string: int, fret: int | None, v: int = 0) -> int:
    """Pose la note `fret` sur la corde `string` du temps `j` (la crée si besoin, le temps n'est plus un silence) ; `fret` = None :
    retire la note (le temps devient un silence s'il n'en reste aucune). Renvoie l'indice du temps."""
    b = beats(m, v)[j]
    n = find_note(b, string)
    if fret is None:
        if n is not None:
            b.notes.remove(n)
        if not b.notes:
            b.rest = True
        return j
    fret = max(0, min(MAX_FRET, int(fret)))
    if n is None:
        b.notes = [x for x in b.notes if not x.rest] + [Note(string=string, fret=fret)]
        b.notes.sort(key=lambda x: x.string)
    else:
        n.fret, n.dead, n.tie = fret, False, False
    b.rest = False
    return j


def set_duration(m: Measure, j: int, base: int | None = None, dots: int | None = None, tuplet: int | None = None, v: int = 0):
    b = beats(m, v)[j]
    if base is not None and base in BASES:
        b.base = base
    if dots is not None:
        b.dots = max(0, min(2, dots))
    if tuplet is not None:
        b.tuplet = tuplet


def make_rest(m: Measure, j: int, v: int = 0):
    b = beats(m, v)[j]
    b.notes, b.rest = [], True
    b.palm_mute = b.let_ring = False


def insert_beat(m: Measure, j: int, base: int = 8, v: int = 0) -> int:
    """Un silence de durée `base` après le temps `j` (j = -1 : au début). Renvoie son indice."""
    beats(m, v).insert(j + 1, Beat(rest=True, base=base))
    return j + 1


def remove_beat(m: Measure, j: int, v: int = 0) -> int:
    """Retire le temps `j` (la mesure devient plus courte : à compléter). Renvoie l'indice du temps à sélectionner ensuite."""
    bs = beats(m, v)
    if len(bs) <= 1:
        make_rest(m, 0, v)
        return 0
    del bs[j]
    return min(j, len(bs) - 1)


def complete_with_rests(m: Measure, v: int = 0) -> int:
    """Ajoute à la fin les silences qui manquent pour que la mesure soit juste (rien si elle est déjà pleine ou trop longue).
    Renvoie le nombre de silences ajoutés."""
    total, want = fill(m, v)
    extra = rest_beats(want - total) if want > total else []
    beats(m, v).extend(extra)
    return len(extra)


def set_text(m: Measure, j: int, text: str, v: int = 0):
    beats(m, v)[j].text = (text or "").strip()[:60] or None


def set_chord(m: Measure, j: int, text: str, v: int = 0):
    beats(m, v)[j].chord = (text or "").strip()[:20] or None


def set_marker(m: Measure, text: str):
    m.marker = (text or "").strip()[:40] or None


def set_signature(m: Measure, text: str) -> bool:
    """« 3/4 », « 7 8 »... : change la signature de la mesure. Faux si le texte n'est pas une signature valide."""
    import re
    got = re.fullmatch(r"\s*(\d{1,2})\s*[/ ]\s*(\d{1,2})\s*", text or "")
    if not got:
        return False
    num, den = int(got.group(1)), int(got.group(2))
    if not 1 <= num <= 32 or den not in BASES[:6]:
        return False
    m.signature = (num, den)
    return True


def clear_measure(m: Measure):
    """Vide la mesure : un seul voix de silences (les repères — reprise, section, armure — restent)."""
    m.voices = [rest_beats(m.length)]