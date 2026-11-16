"""Modifications d'une partition (tabs/score_edits.py) : opérations, liste de changements, version, persistance."""
import os, sys, json, tempfile, pathlib
from fractions import Fraction
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tabs.model import Score, Track, Measure, Beat, Note, TempoChange
from tabs import score_edits as se
from tabs.alphatex import to_alphatex
from tabs.score_library import ScoreLibrary

tmp = pathlib.Path(tempfile.mkdtemp())


def make():
    G = [64, 59, 55, 50, 45, 40]
    t = Track(0, "Lead", "Guitar", tuning=G, is_guitar=True)
    for i in range(4):
        m = Measure(i, marker="Intro" if i == 0 else None)
        m.voices = [[Beat(notes=[Note(string=i % 6, fret=3 + i)], base=8) for _ in range(8)]]
        t.measures.append(m)
    return Score(1, 1, "T", "A", [TempoChange(0, 0.0, 120.0), TempoChange(2, 0.0, 90.0)], [t], 0)


orig = make()
m = se.measure_from_dict(se.measure_to_dict(orig.tracks[0].measures[1]), 1)
assert se.measure_to_dict(m) == se.measure_to_dict(orig.tracks[0].measures[1])                      # aller-retour
assert json.loads(json.dumps(se.measure_to_dict(m))) == se.measure_to_dict(m)                          # JSON sans perte
print("1. mesure : sérialisation aller-retour : OK")

# --- opérations
m = se.measure_from_dict(se.measure_to_dict(orig.tracks[0].measures[1]), 1)
se.set_fret(m, 0, 1, 9)                                                                              # change la case
assert se.find_note(m.voices[0][0], 1).fret == 9
se.set_fret(m, 1, 3, 5)                                                                              # ajoute une note (accord)
assert sorted(n.string for n in m.voices[0][1].notes) == [1, 3]
se.set_fret(m, 1, 1, None); se.set_fret(m, 1, 3, None)                                               # retire tout : silence
assert m.voices[0][1].rest and not m.voices[0][1].notes
se.set_fret(m, 1, 2, 7); assert not m.voices[0][1].rest and m.voices[0][1].notes[0].fret == 7       # un silence reprend une note
se.set_fret(m, 1, 2, 99); assert m.voices[0][1].notes[0].fret == se.MAX_FRET                          # plafonné
tot, want = se.fill(m); assert tot == want == Fraction(1, 1)
se.set_duration(m, 0, base=4); tot, want = se.fill(m); assert tot == Fraction(9, 8) and tot > want   # mesure trop longue : détectable
se.set_duration(m, 0, base=8, dots=1); assert se.beats(m)[0].dots == 1
j = se.remove_beat(m, 7); assert len(se.beats(m)) == 7 and j == 6
se.set_duration(m, 0, base=8, dots=0); se.set_duration(m, 0, base=8)
tot, want = se.fill(m); assert tot < want
assert se.complete_with_rests(m) >= 1 and se.fill(m)[0] == se.fill(m)[1]                            # complétée par des silences
j = se.insert_beat(m, 2, 16); assert se.beats(m)[3].rest and se.beats(m)[3].base == 16 and j == 3
se.make_rest(m, 0); assert se.beats(m)[0].rest
se.set_text(m, 0, "  riff  "); assert se.beats(m)[0].text == "riff"; se.set_text(m, 0, ""); assert se.beats(m)[0].text is None
se.set_marker(m, "Pont"); assert m.marker == "Pont"; se.set_marker(m, " "); assert m.marker is None
single = Measure(0, voices=[[Beat(notes=[Note(0, 1)], base=1)]])
assert se.remove_beat(single, 0) == 0 and single.voices[0][0].rest                                  # le dernier temps devient un silence
print("2. opérations : case / note / accord / silence / durée / temps / texte / section : OK")

# --- liste de changements
edits = []
m = se.measure_from_dict(se.measure_to_dict(orig.tracks[0].measures[1]), 1)
se.set_fret(m, 0, 1, 12)
edits = se.put_measure(edits, orig, 0, m)
assert len(edits) == 1 and edits[0]["bar"] == 1 and se.edited_bars(edits, 0) == [1] and se.edited_bars(edits, 5) == []
se.set_fret(m, 0, 1, orig.tracks[0].measures[1].voices[0][0].notes[0].fret)                         # remis comme à l'origine : plus de changement
assert se.put_measure(edits, orig, 0, m) == []
edits = se.put_measure(edits, orig, 0, se.measure_from_dict(se.measure_to_dict(orig.tracks[0].measures[1]), 1))
assert edits == []
m2 = se.measure_from_dict(se.measure_to_dict(orig.tracks[0].measures[3]), 3); se.set_fret(m2, 2, 0, 5)
m = se.measure_from_dict(se.measure_to_dict(orig.tracks[0].measures[1]), 1); se.set_fret(m, 0, 1, 12)
edits = se.put_measure(se.put_measure([], orig, 0, m), orig, 0, m2)
assert [e["bar"] for e in edits] == [1, 3]
edits = se.put_tempo(edits, orig, 3, 100)
assert any(e["op"] == "tempo" and e["bar"] == 3 for e in edits) and se.edited_bars(edits, 0) == [1, 3]
assert se.edited_bars(edits, 5) == [3]                                                               # le tempo concerne toutes les pistes
assert se.put_tempo(edits, orig, 3, se.tempo_at(orig, 3)) == [e for e in edits if e["op"] != "tempo"]     # tempo d'origine : plus de changement
print("3. liste de changements : une entrée par mesure, disparaît si identique à l'original : OK")

# --- application : l'original n'est pas touché, les autres mesures non plus
before = json.dumps(se.measure_to_dict(orig.tracks[0].measures[3]))
mine = se.apply_edits(orig, edits)
assert json.dumps(se.measure_to_dict(orig.tracks[0].measures[3])) == before                          # original intact
assert se.find_note(mine.tracks[0].measures[3].voices[0][2], 0).fret == 5
assert mine.tracks[0].measures[0] == orig.tracks[0].measures[0] and mine is not orig
assert se.tempo_at(mine, 3) == 100 and se.tempo_at(orig, 3) == 90 and se.tempo_at(mine, 2) == 90
tex_o, tex_m = to_alphatex(orig), to_alphatex(mine)
assert tex_o != tex_m and tex_m.count("|") == tex_o.count("|")                                       # même nombre de mesures : la synchro reste valable
assert len(mine.tracks[0].measures) == 4
print("4. application : copie modifiée, original intact, même nombre de mesures : OK")

# --- nettoyage / robustesse
bad = [{"op": "measure", "part": 0, "bar": 1, "data": {"voices": [[{"notes": [{"string": 1, "fret": 3}], "base": 8}]]}},
       {"op": "measure", "part": 0, "bar": -1, "data": {}}, {"op": "tempo", "bar": 2, "bpm": 9999}, {"op": "zzz"}, "x", {"bar": "a"},
       {"op": "tempo", "bar": 4, "bpm": 140}, {"op": "measure", "part": 0, "bar": 1, "data": {"voices": "bad"}}]
good = se.clean_edits(bad)
assert sorted((e["op"], e["bar"]) for e in good) == [("measure", 1), ("tempo", 4)]
assert se.apply_edits(orig, [{"op": "measure", "part": 7, "bar": 1, "data": {}}, {"op": "measure", "part": 0, "bar": 50, "data": {}}]).tracks[0].measures == orig.tracks[0].measures
print("5. liste abîmée / mesure ou piste inconnue : ignorés : OK")

# --- bibliothèque : version, persistance, protection contre l'élimination, restauration
lib = ScoreLibrary(tmp / "e.json", limit=1)
lib.touch(1, "u1", "T", "A")
assert lib.version(1) == "original" and lib.edits(1) == [] and not lib.set_version(9, "modified") and not lib.set_version(1, "x")
assert lib.set_edits(1, edits) and lib.set_version(1, "modified")
assert [e["bar"] for e in lib.edits(1)] == [e["bar"] for e in edits] and lib.version(1) == "modified"
for i in (2, 3, 4):
    lib.touch(i, f"u{i}", f"T{i}", "")
assert lib.get(1) is not None                                                                        # porteur de modifications : jamais éliminé
lib2 = ScoreLibrary(tmp / "e.json")
assert lib2.version(1) == "modified" and lib2.edits(1) == lib.edits(1)                               # persistance
assert lib.restore_marks(1, [], [], edits=[], version="original") and lib.edits(1) == [] and lib.version(1) == "original"
assert lib.restore_marks(1, [], [], edits=edits, version="modified") and len(lib.edits(1)) == len(edits)
assert lib.restore_marks(1, [], []) and len(lib.edits(1)) == len(edits)                              # sans `edits` : inchangé
(tmp / "e2.json").write_text(json.dumps({"entries": [{"song_id": 1, "url": "u", "version": "???", "edits": [{"op": "tempo", "bar": 1, "bpm": 100}, {"zz": 1}]}]}), encoding="utf-8")
l3 = ScoreLibrary(tmp / "e2.json")
assert l3.version(1) == "original" and len(l3.edits(1)) == 1                                         # fichier abîmé toléré
lib.set_edits(1, [])
print("6. bibliothèque : version, persistance, protection, restauration, fichier abîmé : OK")

# --- palette : outils (tabs/score_tools.py)
from tabs import score_tools as st
G = [64, 59, 55, 50, 45, 40]
def bar():
    return Measure(0, voices=[[Beat(notes=[Note(string=2, fret=5)], base=4) for _ in range(4)]])
ctx = st.Ctx(tuning=G)
ids = [t.id for t in st.TOOLS]
assert len(ids) == len(set(ids)) and all(t.tab in dict(st.TABS) for t in st.TOOLS)                   # table cohérente
assert all(t.id in st.VALUES or t.scope in ("op", "prompt") or t.id in ("alt", "key") for t in st.TOOLS)
m = bar()
# note : bouton = bascule, variantes exclusives, désactivé sans note
assert st.tool_state(st.BY_ID["vib"], m, 0, 2, ctx) == (True, False) and st.tool_state(st.BY_ID["vib"], m, 0, 4, ctx)[0] is False
st.apply_tool(st.BY_ID["vib"], m, 0, 2, ctx); assert m.voices[0][0].notes[0].vibrato
st.apply_tool(st.BY_ID["vibw"], m, 0, 2, ctx); n = m.voices[0][0].notes[0]; assert n.vibrato_wide and not n.vibrato
st.apply_tool(st.BY_ID["vibw"], m, 0, 2, ctx); assert not n.vibrato_wide
st.apply_tool(st.BY_ID["harm"], m, 0, 2, ctx, "pinch"); assert n.harmonic == "pinch" and st.tool_state(st.BY_ID["harm"], m, 0, 2, ctx)[1]
assert st.variant_on(st.BY_ID["harm"], m, 0, 2, ctx, "pinch") and not st.variant_on(st.BY_ID["harm"], m, 0, 2, ctx, "semi")
st.apply_tool(st.BY_ID["harm"], m, 0, 2, ctx); assert n.harmonic is None                              # bouton principal : éteint la variante posée
st.apply_tool(st.BY_ID["bend"], m, 0, 2, ctx, "br100"); assert n.bend == [(0, 0), (30, 100), (60, 0)]
st.apply_tool(st.BY_ID["trill"], m, 0, 2, ctx); assert n.trill == 7
st.apply_tool(st.BY_ID["acc"], m, 0, 2, ctx); st.apply_tool(st.BY_ID["hac"], m, 0, 2, ctx); assert n.accent == 2
st.apply_tool(st.BY_ID["ghost"], m, 0, 2, ctx); st.apply_tool(st.BY_ID["dead"], m, 0, 2, ctx); assert n.dead and not n.ghost
st.apply_tool(st.BY_ID["sl_ib"], m, 0, 2, ctx); assert n.slide == "into_from_below"
# temps
b = m.voices[0][1]
for tid, arg in (("fermata", "long"), ("dyn", "ff"), ("cre", None), ("pick_d", None), ("brush_u", "au"), ("rasg", "ii"), ("tremolo", "3"),
                 ("whammy", "dip"), ("wah_o", None), ("ped_d", None), ("golpe", "thumb"), ("tup", "5"), ("dot", None), ("grace_o", None), ("dead_slap", None)):
    st.apply_tool(st.BY_ID[tid], m, 1, 2, ctx, arg)
assert (b.fermata, b.velocity, b.crescendo, b.pick, b.brush, b.rasgueado, b.tremolo, b.wah, b.pedal, b.golpe, b.tuplet, b.dots, b.grace, b.dead_slap) == \
       ("long", "ff", "cre", "down", "au", "ii", 3, "open", "down", "thumb", 5, 1, "onBeat", True) and b.whammy == [(0, 0), (30, -100), (60, 0)]
st.apply_tool(st.BY_ID["dec"], m, 1, 2, ctx); assert b.crescendo == "dec"
st.apply_tool(st.BY_ID["pm"], m, 1, 2, ctx); assert b.palm_mute and b.notes[0].palm_mute and st.tool_state(st.BY_ID["pm"], m, 1, 2, ctx)[1]
st.apply_tool(st.BY_ID["pm"], m, 1, 2, ctx); assert not b.palm_mute and not b.notes[0].palm_mute
st.apply_tool(st.BY_ID["d16"], m, 1, 2, ctx); assert b.base == 16 and st.tool_state(st.BY_ID["d16"], m, 1, 2, ctx)[1]
st.apply_tool(st.BY_ID["d64"], m, 1, 2, ctx); assert b.base == 64
# mesure
for tid, arg in (("rep_s", None), ("rep_e", "4"), ("alt", "2"), ("alt", "1"), ("dbl", None), ("pickup", None), ("key", "-3")):
    st.apply_tool(st.BY_ID[tid], m, 0, 2, ctx, arg)
assert (m.repeat_start, m.repeat_end, m.alt_ending, m.double_bar, m.pickup, m.key) == (True, 4, [1, 2], True, True, -3)
st.apply_tool(st.BY_ID["alt"], m, 0, 2, ctx, "1"); assert m.alt_ending == [2]
assert se.set_signature(m, "3/4") and m.signature == (3, 4) and se.set_signature(m, "7 8") and m.signature == (7, 8)
assert not se.set_signature(m, "3/5") and not se.set_signature(m, "abc") and not se.set_signature(m, "0/4") and m.signature == (7, 8)
# exporter : tout ce qui est posé est écrit dans l'alphaTex
st.apply_tool(st.BY_ID["vibw"], m, 0, 2, ctx); st.apply_tool(st.BY_ID["harm"], m, 0, 2, ctx, "pinch"); st.apply_tool(st.BY_ID["tap"], m, 0, 2, ctx)
sc = Score(1, 1, "T", "A", [TempoChange(0, 0.0, 120.0)], [Track(0, "Lead", "Guitar", tuning=G, is_guitar=True, measures=[m, Measure(1, voices=[[Beat(base=1, rest=True)]])])], 0)
tex = to_alphatex(sc)
for frag in ("vw", "ph", "lht", "b (0 4 0)", "tr (7 16)", "hac", "sib", "fermata long", "dy ff", "dec", "sd", "au", "rasg ii", "tp 3", "tb (0 -4 0)", "waho",
             "spd", "glpt", "tu 5 4", "gr ob", "ds", "\\ro", "\\rc 4", "\\ae (2)", "\\db", "\\ac", "\\ks ebmajor", "\\ts (7 8)", "\\ks cmajor"):
    assert frag in tex, frag
# opérations
m = bar(); ctx = st.Ctx(tuning=G)
st.apply_tool(st.BY_ID["oct_p"], m, 0, 2, ctx); assert m.voices[0][0].notes[0].fret == 17
for _ in range(2):
    try: st.apply_tool(st.BY_ID["oct_p"], m, 0, 2, ctx)
    except st.ToolError: pass
assert m.voices[0][0].notes[0].fret <= se.MAX_FRET
m = bar(); r = st.apply_tool(st.BY_ID["mv_nd"], m, 0, 2, ctx); nn = m.voices[0][0].notes[0]           # corde 2 case 5 -> corde 3 : même hauteur
assert r.string == 3 and G[2] + 5 == G[3] + nn.fret and nn.string == 3
m = bar(); m.voices[0][0].notes.append(Note(string=3, fret=0))
try: st.apply_tool(st.BY_ID["mv_nd"], m, 0, 2, ctx); assert False
except st.ToolError: pass                                                                          # corde visée occupée
m = bar(); st.apply_tool(st.BY_ID["swap_r"], m, 0, 2, ctx)
c = st.Ctx(tuning=G); r = st.apply_tool(st.BY_ID["copy_b"], m, 1, 2, c); assert r.clip["kind"] == "beat" and r.beat == 1
c.clip = r.clip; m.voices[0][3].notes[0].fret = 9
st.apply_tool(st.BY_ID["paste"], m, 3, 2, c); assert m.voices[0][3].notes[0].fret == 5
r = st.apply_tool(st.BY_ID["cut_m"], m, 0, 2, c); assert all(x.rest for x in m.voices[0]) and r.clip["kind"] == "bar" and len(r.clip["data"]) == 4
c.clip = r.clip; st.apply_tool(st.BY_ID["paste"], m, 0, 2, c); assert [x.notes[0].fret for x in m.voices[0]] == [5, 5, 5, 5]
assert not st.tool_state(st.BY_ID["paste"], m, 0, 2, st.Ctx(tuning=G))[0]                           # presse-papiers vide : grisé
st.apply_tool(st.BY_ID["del_bar"], m, 0, 2, c); assert len(m.voices[0]) == 1 and m.voices[0][0].rest and m.voices[0][0].base == 1
# voix 2 : créée à la demande, sans toucher à la mesure d'origine quand on ne fait que la regarder
m = bar(); assert len(se.view(m, 1)) == 1 and len(m.voices) == 1
c2 = st.Ctx(tuning=G, voice=1); st.apply_tool(st.BY_ID["rest"], m, 0, 2, c2); assert len(m.voices) == 2
se.set_fret(m, 0, 1, 7, v=1); assert se.find_note(m.voices[1][0], 1).fret == 7 and m.voices[0][0].notes[0].fret == 5
assert "\\voice" in to_alphatex(Score(1, 1, "T", "A", [TempoChange(0, 0.0, 120.0)], [Track(0, "L", "G", tuning=G, measures=[m])], 0))
# recherche
assert {"vib", "vibw"} <= {t.id for t in st.search("vibrato")} and "harm" in {t.id for t in st.search("HARMONIQUE")} and not st.search("zzzz")
# sérialisation des nouveaux champs
m = bar(); st.apply_tool(st.BY_ID["whammy"], m, 0, 2, ctx, "dive"); st.apply_tool(st.BY_ID["bend"], m, 0, 2, ctx); st.apply_tool(st.BY_ID["key"], m, 0, 2, ctx, "2")
d = json.loads(json.dumps(se.measure_to_dict(m)))
assert se.measure_to_dict(se.measure_from_dict(d, 0)) == se.measure_to_dict(m)
print("7. palette : outils de note / temps / mesure / édition, exporteur alphaTex, voix, copier-coller, recherche : OK")
print("test_score_edits OK")