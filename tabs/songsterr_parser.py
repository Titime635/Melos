"""
JSON de piste Songsterr -> modèle (tabs/model.py).

Format observé (sonde tools/songsterr_probe.py, février 2026 — endpoints non documentés, ils peuvent changer) :
  piste : name, instrument, instrumentId, tuning[], strings, measures[], automations.tempo[], ...
  mesure : voices[{beats[], rest}], signature [n, d] (seulement quand elle change), marker {text}, repeatStart,
           repeat, alternateEnding, doubleBarline
  temps  : notes[], rest, type (1..64), dots, tuplet, duration [n, d], letRing, palmMute, text, chord, velocity,
           graceNote
  note   : string (0 = corde la plus aiguë), fret, tie, dead, ghost, hp, accentuated, vibrato, staccato, slide,
           harmonic, bend {points[{position, tone}]}
"""

from fractions import Fraction

from .lyrics import attach_lyrics
from .model import Beat, Measure, Note, Score, TempoChange, Track

VALID_BASES = (1, 2, 4, 8, 16, 32, 64)


def _text(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("text")
    return str(value) if value else None


def _base_from_duration(duration) -> tuple[int, int]:
    """(base, points) retrouvés à partir d'une fraction [n, d] quand `type` manque."""
    try:
        frac = Fraction(int(duration[0]), int(duration[1]))
    except (TypeError, ValueError, ZeroDivisionError, IndexError):
        return 4, 0
    for base in VALID_BASES:
        unit = Fraction(1, base)
        total, half = unit, unit
        for dots in range(0, 4):
            if total == frac:
                return base, dots
            half /= 2
            total += half
    return 4, 0


def parse_note(raw: dict) -> Note:
    bend = None
    if isinstance(raw.get("bend"), dict):
        bend = [(int(p.get("position", 0)), int(p.get("tone", 0))) for p in raw["bend"].get("points") or []] or None
    return Note(
        string=int(raw.get("string", 0)), fret=int(raw.get("fret", 0)), rest=bool(raw.get("rest")),
        tie=bool(raw.get("tie")), dead=bool(raw.get("dead")), ghost=bool(raw.get("ghost")),
        hammer=bool(raw.get("hp")), palm_mute=bool(raw.get("palmMute")), accent=int(raw.get("accentuated") or 0),
        vibrato=bool(raw.get("vibrato") or raw.get("wideVibrato")), staccato=bool(raw.get("staccato")),
        slide=raw.get("slide") or None, harmonic=raw.get("harmonic") or None, bend=bend,
    )


def parse_beat(raw: dict) -> Beat:
    base = raw.get("type")
    dots = int(raw.get("dots") or 0)
    if base not in VALID_BASES:
        base, dots = _base_from_duration(raw.get("duration"))
    notes = [parse_note(n) for n in raw.get("notes") or []]
    rest = bool(raw.get("rest")) or (bool(notes) and all(n.rest for n in notes))
    return Beat(
        notes=[] if rest else [n for n in notes if not n.rest], rest=rest, base=int(base), dots=dots,
        tuplet=int(raw.get("tuplet") or 0), let_ring=bool(raw.get("letRing")), palm_mute=bool(raw.get("palmMute")),
        text=_text(raw.get("text")), chord=_text(raw.get("chord")), velocity=raw.get("velocity") or None,
        grace=raw.get("graceNote") or None,
    )


def _signature(raw, previous: tuple[int, int]) -> tuple[int, int]:
    try:
        n, d = int(raw[0]), int(raw[1])
        if n > 0 and d in VALID_BASES:
            return n, d
    except (TypeError, ValueError, IndexError):
        pass
    return previous


def parse_alt_ending(value) -> list[int]:
    if isinstance(value, list):
        return [int(v) for v in value]
    if isinstance(value, int) and value > 0:   # masque de bits : bit 0 = 1re fois, bit 1 = 2e...
        return [i + 1 for i in range(8) if value & (1 << i)]
    return []


def parse_track(raw: dict, meta: dict | None = None) -> Track:
    """`raw` : JSON de la piste ; `meta` : l'entrée correspondante de meta.current.tracks (nom, partId...)."""
    meta = meta or {}
    instrument_id = int(raw.get("instrumentId", meta.get("instrumentId", 0)) or 0)
    track = Track(
        part_id=int(raw.get("partId", meta.get("partId", 0)) or 0),
        name=str(raw.get("name") or meta.get("name") or "Piste"),
        instrument=str(raw.get("instrument") or meta.get("instrument") or ""),
        instrument_id=instrument_id,
        tuning=[int(x) for x in (raw.get("tuning") or meta.get("tuning") or [])],
        is_drums=bool(meta.get("isDrums")) or instrument_id == 1024,
        is_bass=bool(meta.get("isBassGuitar")),
        is_vocal=bool(meta.get("isVocalTrack")),
        is_guitar=bool(meta.get("isGuitar")),
        hash=str(meta.get("hash") or ""),
    )
    track.sounds = [int(x["instrumentId"]) for x in raw.get("sounds") or []
                    if isinstance(x, dict) and isinstance(x.get("instrumentId"), (int, float))]
    for a in (raw.get("trackAutomations") or {}).get("trackSoundAutomations") or []:    # changement de son en cours de morceau
        try:
            track.sound_changes.append((int(a.get("measure", 0)), float(a.get("position", 0) or 0), int(a["soundId"])))
        except (KeyError, TypeError, ValueError):
            continue
    track.sound_changes.sort()
    for entry in raw.get("newLyrics") or []:                # une seule ligne de paroles : la première qui a du texte
        if isinstance(entry, dict) and str(entry.get("text") or "").strip():
            track.lyrics = [(int(entry.get("offset") or 1), str(entry["text"]))]
            break
    if track.is_drums:                                      # débogage : forme des notes de batterie (numéro MIDI dans « fret » ?)
        from .debug import dbg
        sample = [n for rm in (raw.get("measures") or [])[:6] for rv in rm.get("voices") or []
                  for b in rv.get("beats") or [] for n in b.get("notes") or []][:6]
        dbg("batterie notes (extrait)", sample)
    signature = (4, 4)
    for i, rm in enumerate(raw.get("measures") or []):
        signature = _signature(rm.get("signature"), signature)
        voices = []
        for rv in rm.get("voices") or []:
            beats = [parse_beat(b) for b in rv.get("beats") or []]
            voices.append(beats)
        track.measures.append(Measure(
            index=i, signature=signature, marker=_text(rm.get("marker")), voices=voices,
            repeat_start=bool(rm.get("repeatStart")),
            repeat_end=int(rm.get("repeat") or rm.get("repeatCount") or 0),
            alt_ending=parse_alt_ending(rm.get("alternateEnding")),
            double_bar=bool(rm.get("doubleBarline")),
        ))
    return track


def parse_tempo(raw: dict) -> list[TempoChange]:
    out = []
    for a in (raw.get("automations") or {}).get("tempo") or []:
        try:
            out.append(TempoChange(int(a.get("measure", 0)), float(a.get("position", 0)), float(a["bpm"]),
                                   int(a.get("type", 4) or 4)))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out, key=lambda t: (t.measure, t.position))


def parse_score(meta_current: dict, track_jsons: dict[int, dict]) -> Score:
    """`meta_current` : meta.current de la page ; `track_jsons` : {partId: JSON de la piste}.
    Une piste de batterie (non téléchargée) devient une piste sans mesures : elle sert au mixage (mute/solo)."""
    score = Score(song_id=int(meta_current.get("songId", 0)), revision_id=int(meta_current.get("revisionId", 0)),
                  title=str(meta_current.get("title") or "Sans titre"),
                  artist=str(meta_current.get("artist") or ""),
                  default_part=int(meta_current.get("defaultTrack") or 0))
    for tm in meta_current.get("tracks") or []:
        if tm.get("isEmpty"):
            continue
        raw = track_jsons.get(tm.get("partId"))
        if raw is None:
            if not tm.get("isDrums"):
                continue
            raw = {"measures": []}
        track = parse_track(raw, tm)
        score.tracks.append(track)
        if not score.tempo and raw.get("automations"):
            score.tempo = parse_tempo(raw)
    attach_lyrics(score)
    return score