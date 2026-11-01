"""
Paroles Songsterr -> syllabes posées sur les temps de TOUTES les pistes.

Les paroles sont rattachées à la piste de chant (`newLyrics` : lignes {line, offset, text}, « offset » = mesure de départ
à partir de 1, texte au format Guitar Pro : mots séparés par des espaces, syllabes par des tirets). Chaque syllabe va sur
la note chantée suivante de CETTE piste ; on retient sa place dans la mesure (mesure + position) et on la dépose sur le
temps correspondant des autres pistes, pour qu'elle s'affiche sous chaque tablature, alignée sur le chant.
"""

import re
from fractions import Fraction

from .debug import dbg
from .model import Score, Track


def _skips(spaces: int, newlines: int) -> int:
    """Notes sautées par un bloc d'espaces / retours à la ligne entre deux mots (règle vérifiée sur Plug In Baby et sur
    Bohemian Rhapsody) : une espace (ou un retour à la ligne) sert de séparateur ; chaque espace en plus saute une note ;
    chaque ligne vide en plus (« \\n\\n ») en saute une."""
    return max(0, spaces - 1) + max(0, newlines - 1) if newlines else max(0, spaces - 1)


def syllables(text: str) -> list[str | None]:
    """Unités du texte dans l'ordre ; None = note sautée (« ___ »).

    Format de Songsterr : les mots et syllabes sont séparés par UNE espace ; chaque espace en plus saute une note
    (« ba  - by », « neath's  no », « go   -ne » = 2 notes sautées) ; le tiret n'est qu'un séparateur d'affichage
    (« ex - posed », « ba -by ») ; « _ » saute une note ; « + » relie deux mots chantés sur une seule note. Un retour à la
    ligne est un séparateur comme une espace (« \\n » et « \\n » + espace = un seul séparateur) ; les espaces autour
    comptent comme des espaces en plus, sauf une qui sert de séparateur ; une ligne vide saute une note (« truth   \\n\\nMa- »
    = 3 notes sautées)."""
    out: list[str | None] = []
    for m in re.finditer(r"[^ \n]+|[ \n]+", text.strip()):
        part = m.group()
        if part[0] in " \n":
            out.extend([None] * _skips(part.count(" "), part.count("\n")))
        elif part == "_":
            out.append(None)
        else:
            if part.startswith("-") and out and out[-1] and not out[-1].endswith("-"):
                out[-1] += "-"                                   # « ba -by » : le tiret relie ba à by
            if part == "-":
                continue
            body = part.lstrip("-")
            out.extend(c.replace("+", " ") for c in re.findall(r"[^-]+-?", body))
    return out


def _links(beat) -> bool:
    """La note de ce temps est-elle liée à la SUIVANTE en legato (hammer-on / pull-off / glissé legato) ?"""
    return any(n.hammer or n.slide == "legato" for n in beat.notes)


def _starts(track: Track, measure_index: int, count_ties: bool = False) -> list[tuple[Fraction, bool]]:
    """(début du temps dans la mesure, chantable ?) pour la voix 1 de la mesure.

    Comme sur Songsterr, une note liée (tie) ne reçoit PAS de syllabe : la syllabe précédente se prolonge (« ___ »).
    `count_ties=True` : on compte toutes les notes (pour placer les « ___»)."""
    m = track.measures[measure_index]
    if not m.voices:
        return []
    linked = False
    if measure_index > 0 and track.measures[measure_index - 1].voices and track.measures[measure_index - 1].voices[0]:
        linked = _links(track.measures[measure_index - 1].voices[0][-1])
    pos, out = Fraction(0), []
    for b in m.voices[0]:
        has_note = bool(b.notes) and not b.rest
        continuation = has_note and all(n.tie for n in b.notes)
        out.append((pos, has_note and (count_ties or not continuation)))
        linked = _links(b) if has_note else False
        pos += b.length
    return out


def _plan(src: Track, count_ties: bool, mode: str):
    """Place les lignes de texte sur les notes chantées ; renvoie (placement, écart total, détails).

    On ne connaît pas avec certitude la convention de Songsterr (« offset » = mesure à partir de 0 ou de 1 ? ou rang de la
    note ? les notes liées portent-elles une syllabe ?) : on essaie chaque variante et on garde celle où le nombre de
    syllabes de chaque ligne colle le mieux au nombre de notes chantées jusqu'à la ligne suivante."""
    sung = [(mi, pos) for mi in range(len(src.measures)) for pos, ok in _starts(src, mi, count_ties) if ok]
    first_of = {}
    for g, (mi, _) in enumerate(sung):
        first_of.setdefault(mi, g)

    def start(offset: int) -> int:
        if mode == "rank":
            return max(0, offset)
        mi = max(0, offset - (1 if mode == "m1" else 0))
        return next((first_of[m] for m in sorted(first_of) if m >= mi), len(sung))

    lines = sorted(src.lyrics)
    placed: dict[tuple[int, Fraction], str] = {}
    gap, details = 0, []
    for k, (offset, text) in enumerate(lines):
        chunks = syllables(text)
        g = start(offset)
        end = start(lines[k + 1][0]) if k + 1 < len(lines) else len(sung)
        room = end - g
        details.append((offset, len(chunks), room))
        gap += abs(len(chunks) - room)
        for j, chunk in enumerate(chunks[:max(0, room)]):
            key = sung[g + j]
            chunk = chunk or "___"                           # note sautée : la syllabe précédente se prolonge
            placed[key] = (placed[key] + " " + chunk) if key in placed else chunk
    if not count_ties and placed:                            # note liée : la syllabe se prolonge (Songsterr affiche « ___ »)
        sung_set = set(sung)
        first = min(placed)
        for mi in range(len(src.measures)):
            for pos, ok in _starts(src, mi, True):
                key = (mi, pos)
                if ok and key not in sung_set and key not in placed and key > first:
                    placed[key] = "___"
    return placed, gap, details


def _plan_absorb(src: Track, mode: str = "m1"):
    """Variante : une note « sautée » (espace en plus, « _ ») consomme la note suivante QU'ELLE SOIT LIÉE OU NON ; seules
    les vraies syllabes évitent les notes liées. Revient au même si aucune note liée ne suit une note sautée.
    Écart = syllabes qui ne tiennent pas + notes chantées restées sans syllabe."""
    notes = []                                               # (mesure, position, liée ?) de toutes les notes du chant
    for mi in range(len(src.measures)):
        free = {pos for pos, ok in _starts(src, mi, False) if ok}
        notes += [(mi, pos, pos not in free) for pos, ok in _starts(src, mi, True) if ok]
    first_of = {}
    for g, (mi, _, _) in enumerate(notes):
        first_of.setdefault(mi, g)

    def start(offset: int) -> int:
        mi = max(0, offset - (1 if mode == "m1" else 0))
        return next((first_of[m] for m in sorted(first_of) if m >= mi), len(notes))

    lines = sorted(src.lyrics)
    placed: dict[tuple[int, Fraction], str] = {}
    gap, details = 0, []
    for k, (offset, text) in enumerate(lines):
        chunks = syllables(text)
        p = start(offset)
        end = start(lines[k + 1][0]) if k + 1 < len(lines) else len(notes)
        room = sum(1 for n in notes[p:end] if not n[2])
        details.append((offset, len(chunks), room))
        left = 0
        for chunk in chunks:
            if chunk is not None:
                while p < end and notes[p][2]:               # une syllabe ne se pose jamais sur une note liée
                    p += 1
            if p >= end:
                left += 1
                continue
            key = notes[p][:2]
            chunk = chunk or "___"
            placed[key] = (placed[key] + " " + chunk) if key in placed else chunk
            p += 1
        gap += left + sum(1 for n in notes[p:end] if not n[2])
    if placed:
        first = min(placed)
        for mi, pos, tied in notes:
            if (mi, pos) not in placed and (mi, pos) > first and tied:
                placed[(mi, pos)] = "___"
    return placed, gap, details


def _dump(src: Track, placed: dict, title: str) -> None:
    """Écrit `melos_lyrics.txt` : pour chaque mesure du chant, chaque temps (n = note chantée, t = note liée, r = silence)
    avec la syllabe qui lui a été donnée. Sert à vérifier le placement face à Songsterr, mesure par mesure."""
    try:
        from paths import APP_DIR
        lines = [f"# {title}", "# mesure : temps[type]=syllabe ; n = note chantée, t = note liée (tie), r = silence", ""]
        for mi, m in enumerate(src.measures):
            if not m.voices:
                continue
            pos, items = Fraction(0), []
            for b in m.voices[0]:
                kind = "r" if b.rest or not b.notes else ("t" if all(n.tie for n in b.notes) else "n")
                items.append(f"{pos}[{kind}]={placed.get((mi, pos), '')}" if kind != "r" else f"{pos}[r]")
                pos += b.length
            lines.append(f"m{mi + 1}: " + "  ".join(items))
        lines += ["", "# jetons (dans l'ordre) :"]
        toks = []
        for _, text in sorted(src.lyrics):
            toks += syllables(text)
        lines.append(" | ".join("___" if t is None else t for t in toks))
        lines += ["", "# texte brut Songsterr (offset de la ligne, texte exact avec espaces et retours à la ligne) :"]
        lines += [f"{off} {text!r}" for off, text in sorted(src.lyrics)]
        (APP_DIR / "melos_lyrics.txt").write_text("\n".join(lines), encoding="utf-8")
        dbg("paroles", "détail écrit dans melos_lyrics.txt")
    except Exception as exc:                                   # le débogage ne doit jamais gêner l'affichage
        dbg("paroles", "écriture du détail impossible :", exc)


def attach_lyrics(score: Score) -> None:
    """Remplit `Beat.lyrics` de toutes les pistes à partir de la piste de chant (ou de la première qui a des paroles)."""
    sources = [t for t in score.tracks if t.lyrics]
    if not sources:
        return
    src = next((t for t in sources if t.is_vocal), sources[0])
    for off, text in sorted(src.lyrics)[:6]:
        dbg("paroles brut", off, repr(text[:90]))
    for off, text in sorted(src.lyrics):
        dbg("paroles TEXTE COMPLET", off, repr(text))
    best = None
    # La première est la convention de Songsterr (vérifiée sur ses affichages, cf. « ooh \n   Don't » : les espaces en plus
    # tombent aussi sur les notes liées) ; les autres ne servent qu'en secours si l'écart de celle-ci est énorme.
    variants = [(False, "m1", True), (False, "m1", False), (False, "m0", False), (False, "rank", False),
                (True, "m1", False), (True, "m0", False), (True, "rank", False)]
    for count_ties, mode, absorb in variants:
        plan = _plan_absorb(src, mode) if absorb else _plan(src, count_ties, mode)
        dbg("paroles essai", f"liées={count_ties} départ={mode} saut-sur-liées={absorb} écart={plan[1]}")
        if best is None or plan[1] < best[1][1] - 15:          # convention de Songsterr gardée sauf écart énorme
            best = ((count_ties, mode, absorb), plan)
    (count_ties, mode, absorb), (placed, gap, details) = best
    dbg("paroles choix", f"liées={count_ties} départ={mode} saut-sur-liées={absorb} écart={gap}", details[:12])
    toks = []
    for off, text in sorted(src.lyrics):
        toks += syllables(text)
    dbg("paroles jetons 90-125", toks[90:125])
    _dump(src, placed, f"liées={count_ties} départ={mode} saut-sur-liées={absorb} écart={gap}")
    for track in score.tracks:
        for mi, m in enumerate(track.measures):
            if not m.voices:
                continue
            starts = _starts(track, mi, True)
            if not starts:
                continue
            wanted = sorted((pos, w) for (i, pos), w in placed.items() if i == mi)
            for pos, word in wanted:
                idx = max((j for j, (p, _) in enumerate(starts) if p <= pos), default=0)
                beat = m.voices[0][idx]
                beat.lyrics = (beat.lyrics + " " + word) if beat.lyrics else word