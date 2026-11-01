"""
Modèle (tabs/model.py) -> texte alphaTex (lu par alphaTab dans le panneau de partition).

Conventions alphaTex 1.8 : numéro de corde 1 = la plus AIGUË (= index Songsterr + 1), `fret.corde.durée`,
effets de note entre accolades après la note, effets de temps après la durée.
Les pistes de batterie sont écrites en percussion (`\\staff {score}` + `\\instrument percussion`) : la valeur de chaque
note est son numéro MIDI General MIDI (36 = grosse caisse, 38 = caisse claire, 42 = charley...).
"""

from fractions import Fraction

from .model import Beat, Measure, Note, Score, Track, tuplet_ratio

NOTE_NAMES = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"]
SLIDES = {"shift": "ss", "legato": "sl", "into_from_below": "sib", "into_from_above": "sia",
          "out_down": "sod", "out_up": "sou", "outdown": "sod", "outup": "sou"}
HARMONICS = {"natural": "nh", "artificial": "ah", "pinch": "ph", "tap": "th", "semi": "sh", "feedback": "fh"}


VOICE_PROGRAM = 54                      # « Voice Oohs » : la mélodie chantée (la piste de chant est écrite pour flûte, etc.)
DEFAULT_PROGRAM = {"guitar": 29, "bass": 33}


def midi_program(track: Track) -> int:
    """Numéro de programme General MIDI (0-127) qui sonne pour cette piste : celui de Songsterr (`instrumentId`) quand il
    est valide, sinon un son par défaut selon le type de piste ; la voix chantée prend toujours un son de voix."""
    if track.is_vocal:
        return VOICE_PROGRAM
    base = track.sounds[0] if track.sounds else track.instrument_id      # le premier « son » de la piste
    valid = 0 <= base <= 127
    if base and valid:
        return base
    if track.is_bass:
        return DEFAULT_PROGRAM["bass"]
    if track.is_guitar:
        return DEFAULT_PROGRAM["guitar"]
    return base if valid else 0                                 # 0 = piano à queue


def sound_swaps(track: Track) -> dict[int, list[tuple[float, int]]]:
    """{mesure: [(position 0-1, programme GM)]} : changements de son en cours de morceau (guitare saturée -> nappe...),
    tels que Songsterr les note (`trackSoundAutomations`). Vide pour le chant et la batterie."""
    out: dict[int, list[tuple[float, int]]] = {}
    if track.is_vocal or track.is_drums or len(track.sounds) < 2:
        return out
    current = midi_program(track)
    for measure, position, sound_id in sorted(track.sound_changes):
        if not 0 <= sound_id < len(track.sounds) or not 0 <= track.sounds[sound_id] <= 127:
            continue
        program = track.sounds[sound_id]
        if program != current or measure > 0 or position > 0:
            out.setdefault(measure, []).append((max(0.0, position), program))
            current = program
    return out


def playable_tracks(score: Score) -> list[Track]:
    """Pistes qui entrent dans le alphaTex complet (celles qui ont des mesures), dans l'ordre : la position dans cette liste
    est l'indice de la piste côté alphaTab (mute / solo / volume)."""
    return [t for t in score.tracks if t.measures]


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")


def midi_to_alphatex(pitch: int) -> str:
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def _note(n: Note, strings: int, let_ring: bool = False) -> str:
    s = n.string + 1                            # alphaTex : 1 = corde la plus aiguë (comme Songsterr, +1)
    s = max(1, min(strings, s))
    head = "x" if n.dead else str(n.fret)
    if n.tie:
        head = "-"
    fx = []
    if n.hammer:
        fx.append("h")
    if n.palm_mute:
        fx.append("pm")
    if let_ring:
        fx.append("lr")
    if n.accent == 1:
        fx.append("ac")
    elif n.accent >= 2:
        fx.append("hac")
    if n.ghost:
        fx.append("g")
    if n.vibrato:
        fx.append("v")
    if n.staccato:
        fx.append("st")
    if n.slide in SLIDES:
        fx.append(SLIDES[n.slide])
    if n.harmonic in HARMONICS:
        fx.append(HARMONICS[n.harmonic])
    if n.bend:
        pts = " ".join(str(round(t / 25)) for _, t in n.bend)   # alphaTex : valeurs seules, réparties à égale distance
        fx.append(f"b ({pts})")
    out = f"{head}.{s}"
    return out + (" {" + " ".join(fx) + "}" if fx else "")


def _duration_fx(b: Beat, program: int | None = None) -> str:
    fx = []
    if program is not None:
        fx.append(f"instrument {program}")                      # changement de son à partir de ce temps
    if b.dots == 1:
        fx.append("d")
    elif b.dots >= 2:
        fx.append("dd")
    if b.tuplet:
        fx.append("tu {} {}".format(*tuplet_ratio(b.tuplet)))     # forme à deux nombres : accepte aussi 4, 8, 11, 13...
    if b.grace:
        fx.append("gr")
    if b.chord or b.text:
        parts = []
        if b.text:
            parts.append(f'txt "{_esc(b.text)}"')
        if b.chord:
            parts.append(f'ch "{_esc(b.chord)}"')
        fx.append(" ".join(parts))
    if b.velocity in ("ppp", "pp", "p", "mp", "mf", "f", "ff", "fff"):
        fx.append(f"dy {b.velocity}")
    return "{" + " ".join(fx) + "}" if fx else ""


def _beat(b: Beat, strings: int, drums: bool = False, program: int | None = None) -> str:
    dur = f":{b.base} "
    fx = _duration_fx(b, program)
    if drums:                                   # percussion : numéros MIDI des éléments joués (les notes liées n'ont pas de sens)
        flags: dict[int, str] = {}
        for n in b.notes:
            if not n.tie and not n.rest and 27 <= n.fret <= 87:
                mark = "g" if n.ghost else ("hac" if n.accent >= 2 else ("ac" if n.accent == 1 else ""))
                flags[n.fret] = mark or flags.get(n.fret, "")
        hits = [f"{h} {{{flags[h]}}}" if flags[h] else str(h) for h in sorted(flags)]   # accent / note fantôme : le son suit
        if b.rest or not hits:
            return f"{dur}r {fx}".strip()
        body = hits[0] if len(hits) == 1 else "(" + " ".join(hits) + ")"
        return f"{dur}{body} {fx}".strip()
    if b.rest or not b.notes:
        return f"{dur}r {fx}".strip()
    notes = [_note(n, strings, b.let_ring) for n in b.notes]
    if b.palm_mute and not any("pm" in x for x in notes):
        notes = [x.replace("}", " pm}") if "{" in x else x + " {pm}" for x in notes]
    body = notes[0] if len(notes) == 1 else "(" + " ".join(notes) + ")"
    return f"{dur}{body} {fx}".strip()


def _rest_bar(m: Measure) -> str:
    """Mesure vide : silences dont la somme vaut la mesure (un seul « r » ne convient qu'au 4/4)."""
    left, out = m.length, []
    for base in (1, 2, 4, 8, 16, 32, 64):
        unit = Fraction(1, base)
        while left >= unit:
            out.append(f":{base} r")
            left -= unit
    return " ".join(out) or ":1 r"


def _measure(m: Measure, strings: int, voice: int, drums: bool = False, swaps: list[tuple[float, int]] | None = None) -> str:
    if voice >= len(m.voices) or not m.voices[voice]:
        return _rest_bar(m)
    if not swaps:
        return " ".join(_beat(b, strings, drums) for b in m.voices[voice])
    out, start, todo, length = [], Fraction(0), sorted(swaps), m.length
    for b in m.voices[voice]:
        program = None
        while todo and start >= Fraction(todo[0][0]).limit_denominator(1000) * length - Fraction(1, 1000):
            program = todo.pop(0)[1]                         # le changement tombe sur le premier temps qui commence à cette position
        out.append(_beat(b, strings, drums, program))
        start += b.length
    if todo:                                                 # position au-delà du dernier temps : on l'accroche au dernier
        out[-1] = out[-1].replace("{", "{instrument %d " % todo[-1][1], 1) if "{" in out[-1] else out[-1] + " {instrument %d}" % todo[-1][1]
    return " ".join(out)


def track_to_alphatex(track: Track, score: Score, with_header: bool = True) -> str:
    strings = len(track.tuning) or 6
    lines = []
    if with_header:
        lines.append(f'\\title "{_esc(score.title)}"')
        lines.append(f'\\artist "{_esc(score.artist)}"')
    first = track.measures[0].signature if track.measures else (4, 4)
    tempo = score.tempo[0].bpm if score.tempo else 120
    tuning = " ".join(midi_to_alphatex(p) for p in track.tuning)
    lines.append(f'\\track "{_esc(track.name[:40])}"')
    if track.is_drums:
        lines.append("\\staff {score}")
        lines.append("\\instrument percussion")
    else:
        lines.append("\\staff {tabs}")
        lines.append(f"\\tuning ({tuning})")
        lines.append(f"\\instrument {midi_program(track)}")           # son de la synthèse (mode « Synthèse »)
    lines.append(f"\\tempo {round(tempo)}")
    lines.append(f"\\ts ({first[0]} {first[1]})")
    changes = {(t.measure): t for t in score.tempo[1:]}
    swaps = sound_swaps(track)
    voices = max((len(m.voices) for m in track.measures), default=1)
    last_sig = first
    for v in range(max(1, voices)):
        if v > 0:
            lines.append("\\voice")
        bars = []
        last_sig = first
        for m in track.measures:
            pre = ""
            if v == 0:
                if m.signature != last_sig:
                    pre += f"\\ts ({m.signature[0]} {m.signature[1]}) "
                    last_sig = m.signature
                if m.repeat_start:
                    pre += "\\ro "
                if m.repeat_end:
                    pre += f"\\rc {max(2, m.repeat_end)} "
                if m.alt_ending:
                    pre += "\\ae (" + " ".join(str(i) for i in m.alt_ending) + ") "
                if m.index in changes and m.index > 0:
                    pre += f"\\tempo {round(changes[m.index].bpm)} "
            bars.append(pre + _measure(m, strings, v, track.is_drums, swaps.get(m.index) if v == 0 else None) + " |")
        lines.append("\n".join(bars))
    return "\n".join(lines) + "\n"


def to_alphatex(score: Score, part_ids: list[int] | None = None, sync: list[float] | None = None) -> str:
    """alphaTex complet des pistes demandées (toutes par défaut) + points de synchro vidéo.

    `sync` : temps de début de chaque mesure dans la vidéo (ms), cf tabs/sync.py."""
    tracks = [t for t in playable_tracks(score) if part_ids is None or t.part_id in part_ids]
    if not tracks:
        raise ValueError("aucune piste à convertir")
    text = "".join(track_to_alphatex(t, score, with_header=(i == 0)) for i, t in enumerate(tracks))
    if sync:
        from .sync import sync_lines
        text += "\n".join(sync_lines(sync)) + "\n"
    return text


def lyrics_for(track: Track) -> list[list]:
    """[[mesure, indice du temps, texte]] : syllabes à afficher SOUS la tablature (dessinées par la page web : alphaTab
    ne sait les mettre qu'au-dessus de la portée). Les indices sont ceux de la voix 1, comme dans l'alphaTex."""
    out = []
    if track.is_drums:                      # la portée de percussion n'a pas de place prévue pour les paroles
        return out
    for m in track.measures:
        if m.voices:
            for j, b in enumerate(m.voices[0]):
                if b.lyrics:
                    out.append([m.index, j, b.lyrics])
    return out


def markers_for(track: Track) -> list[list]:
    """[[mesure, texte]] : titres de section (« Chorus »...). Dessinés par la page web au-dessus de la ligne, car ceux
    d'alphaTab se superposent aux effets (« P.M. »...)."""
    return [[m.index, m.marker] for m in track.measures if m.marker]