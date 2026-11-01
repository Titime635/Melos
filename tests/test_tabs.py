"""Décodage Songsterr -> modèle -> alphaTex (données synthétiques, sans réseau)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tabs.alphatex import to_alphatex
from tabs.songsterr_parser import parse_score
from tabs.sync import build_bar_starts, sync_lines

def beat(fret, string, base=8, **kw):
    return {"notes": [{"fret": fret, "string": string, **kw.pop("note", {})}], "type": base, **kw}

track = {"name": "Gtr", "instrumentId": 30, "tuning": [64, 59, 55, 50, 45, 40], "partId": 0, "measures": [
    {"signature": [4, 4], "marker": {"text": "Intro"}, "voices": [{"beats": [beat(5, 0), beat(7, 1), beat(0, 5, 4, dots=1)]}]},
    {"voices": [{"beats": [{"rest": True, "type": 1, "notes": [{"rest": True}]}]}]},
    {"signature": [3, 4], "voices": [{"beats": [beat(3, 2, 4, note={"bend": {"points": [{"position": 0, "tone": 0}, {"position": 30, "tone": 50}]}})]}]},
], "automations": {"tempo": [{"measure": 0, "position": 0, "bpm": 120, "type": 4}]}}
meta = {"songId": 1, "revisionId": 2, "title": "T", "artist": "A",
        "tracks": [{"partId": 0, "name": "Gtr", "instrumentId": 30, "tuning": track["tuning"]}]}
score = parse_score(meta, {0: track})
assert score.measure_count == 3 and score.tracks[0].measures[2].signature == (3, 4)
tex = to_alphatex(score, [0], build_bar_starts([1.0, 3.0], 3))
assert "5.1" in tex and "0.6" in tex            # corde Songsterr 0 (aiguë) -> 1, 5 (grave) -> 6
assert '\\section' not in tex and "\\ts (3 4)" in tex and "b (0 2)" in tex
assert sync_lines([-5.0, 2000.0]) == ["\\sync (0 0 0)", "\\sync (1 0 2000)"]
assert build_bar_starts([1.0, 3.0], 3) == [1000.0, 3000.0, 5000.0]

# --- isoler / couper -> vidéo (tabs/mixer.py) ---
from tabs.mixer import Mix, MixModel
from tabs.model import Track
from tabs.sync import VideoSync
V = lambda vid, feat, h=None: VideoSync(vid, feat, [0.0], None, "", h)
videos = [V("full", "alternative"), V("solo_g", "solo", ["guitar_B", "guitar_C", "other_A"]),
          V("no_v", "backing", ["vocals_V"]), V("no_d", "backing", ["drums_X"]),
          V("no_g", "backing", ["guitar_B", "guitar_C", "other_A"])]
trk = [Track(0, "voix", is_vocal=True), Track(1, "g1", is_guitar=True), Track(2, "g2", is_guitar=True),
       Track(3, "basse", is_bass=True), Track(4, "synthé"), Track(5, "batt", is_drums=True)]
mm = MixModel(videos, trk)
st = mm.default
assert st.video.video_id == "full" and st.kind is None
s = mm.mute_click(st, 5)
assert s.kind == "mute" and s.video.video_id == "no_d" and s.tracks == {5}            # batterie coupée
s = mm.solo_click(st, 1)
assert s.video.video_id == "solo_g" and s.tracks == {1, 2, 3, 4}                      # pistes inséparables : ensemble
assert mm.solo_click(s, 1).kind is None and mm.solo_click(s, 1).video.video_id == "full"   # re-cliquer = annuler
s2 = mm.solo_click(s, 5)                                                              # + batterie : version compatible
assert s2.video.video_id == "no_v" and s2.tracks >= {1, 2, 3, 4, 5}
s3 = mm.mute_click(s, 1)                                                              # solo puis mute : l'isolement saute
assert s3.kind == "mute" and s3.video.video_id == "no_g"
assert mm.preview("solo", st, 3) == {1, 2, 3, 4}
assert MixModel([V("a", "alternative")], trk).solo_click(st, 1) is None               # aucune version séparée : grisé
# désélection : le nouveau mix est inclus dans l'actuel
vs = [V("full", "alternative"), V("s_a", "solo", ["guitar_B"]), V("s_ab", "solo", ["guitar_B", "bass_X"]),
      V("s_abc", "solo", ["guitar_B", "bass_X", "drums_X"])]
tr = [Track(0, "g", is_guitar=True, hash="guitar_B"), Track(1, "b", is_bass=True, hash="bass_X"),
      Track(2, "d", is_drums=True, hash="drums_X"), Track(3, "v", is_vocal=True, hash="vocals_V")]
m2 = MixModel(vs, tr)
cur = Mix("solo", vs[3], frozenset({0, 1, 2}))
off = m2.solo_click(cur, 2)
assert off.video.video_id == "s_ab" and off.tracks == {0, 1}                  # retire la batterie -> guitare + basse
off = m2.solo_click(cur, 0)
assert off.kind is None                                                       # aucune version ⊆ {basse, batterie} : tout est relâché
# choisir une autre vidéo à la main règle les boutons
sg = mm.state_for("solo_g"); assert sg.kind == "solo" and sg.tracks == {1, 2, 3, 4}
sv = mm.state_for("no_v"); assert sv.kind == "mute" and sv.tracks == {0}
assert mm.state_for("full").kind is None
# association manuelle piste -> piste audio : prioritaire, et non réutilisée par l'association automatique
mo = MixModel(videos, trk, {1: {"other_A"}, 4: set()})
assert mo.track_stems[1] == {"other_A"} and mo.track_stems[4] == set() and 4 not in mo.mixable
from tabs.alphatex import markers_for, to_alphatex
from tabs.lyrics import syllables
assert syllables("plug+in ba  - by x _ y") == ["plug in", "ba", None, "by", "x", None, "y"] and syllables("ry -   thing") == ["ry-", None, None, "thing"] and syllables("ba -by.") == ["ba-", "by."] and syllables("go   -ne.") == ["go", None, None, "ne."]
from tabs.sync import to_syncs as _to_syncs
assert _to_syncs(None, 10) == [] and _to_syncs({}, 10) == [] and _to_syncs([None, "x", {"status": "done"}], 10) == []
from fractions import Fraction
from tabs.model import tuplet_ratio, Beat as _Beat
assert tuplet_ratio(3) == (3, 2) and tuplet_ratio(4) == (4, 3) and tuplet_ratio(15) == (15, 8) and tuplet_ratio(2) == (2, 1)
assert _Beat(base=8, tuplet=4).length == Fraction(3, 32) and _Beat(base=8, tuplet=3).length == Fraction(1, 12)
from tabs.alphatex import _duration_fx
assert _duration_fx(_Beat(base=8, tuplet=4)) == "{tu 4 3}" and _duration_fx(_Beat(base=8, tuplet=3)) == "{tu 3 2}"
# recherche par nom : réponse de /api/songs (champs non documentés : lecture tolérante)
from tabs.client import parse_search, song_url, search_songs
import tabs.client as _client
sample = [{"id": 1234, "title": "The Adults Are Talking", "artist": {"id": 9, "name": "The Strokes"},
           "tracks": [{"instrument": "Distortion Guitar"}, {"name": "Bass"}, {"instrument": "Bass"}]},
          {"songId": "5", "title": " Été ", "artistName": "Céline"}, {"id": "x", "title": "cassé"}, {"id": 7}, "bruit"]
hits = parse_search(sample)
assert [h.song_id for h in hits] == [1234, 5] and hits[0].artist == "The Strokes" and hits[0].tracks == ["Distortion Guitar", "Bass"]
assert hits[0].url == "https://www.songsterr.com/a/wsa/the-strokes-the-adults-are-talking-tab-s1234" and hits[1].title == "Été"
assert song_url(5, "Été", "Céline").endswith("celine-ete-tab-s5")
assert parse_search({"songs": sample})[0].song_id == 1234 and parse_search(None) == [] and len(parse_search(sample, limit=1)) == 1
_seen = []
_client.fetch = lambda url, timeout=20.0: (_seen.append(url), __import__("json").dumps(sample).encode())[1]
assert [h.song_id for h in search_songs("the adults & talking")] == [1234, 5]
assert "pattern=the%20adults%20%26%20talking" in _seen[0] and search_songs(" a ") == []
# paroles : une note sautée consomme aussi une note liée (variante « saut-sur-liées »)
from fractions import Fraction
from tabs.model import Beat, Measure, Note, Track
from tabs.lyrics import _plan, _plan_absorb
def _vb(*kinds):                                   # n = note chantée, t = note liée, r = silence ; toutes des noires
    return [Beat(notes=[Note(0, 5, tie=(k == "t"))] if k != "r" else [], rest=(k == "r"), base=4) for k in kinds]
voc = Track(0, "v", is_vocal=True, lyrics=[(1, "a b   c d")],
            measures=[Measure(0, voices=[_vb("n", "n", "t", "t")]), Measure(1, voices=[_vb("n", "n", "r", "r")])])
pl, gap, _ = _plan(voc, False, "m1")                # a b ___ ___ c d : 4 chants non liés mais 6 jetons -> écart 2
assert gap == 2
pl2, gap2, _ = _plan_absorb(voc, "m1")              # les 2 sauts tombent sur les 2 notes liées : c et d tiennent
assert gap2 == 0 and pl2[(1, Fraction(0))] == "c" and pl2[(1, Fraction(1, 4))] == "d" and pl2[(0, Fraction(1, 2))] == "___"
# cas réel « ooh \n   Don't con - fuse. » : les 3 sauts tombent sur 2 notes liées + 1 note chantée, puis « Don't » suit
voc2 = Track(0, "v", is_vocal=True, lyrics=[(1, "ooh \n   Don't con - fuse. Ba - by")],
             measures=[Measure(0, voices=[_vb("n", "t", "t", "n")]), Measure(1, voices=[_vb("r", "r", "r", "r")]),
                       Measure(2, voices=[_vb("n", "n", "t", "n")]), Measure(3, voices=[_vb("t", "t", "t", "n")]),
                       Measure(4, voices=[_vb("n", "r", "r", "r")])])
pl3, gap3, _ = _plan_absorb(voc2, "m1")
q = Fraction(1, 4)
assert pl3[(0, 0)] == "ooh" and pl3[(0, q)] == pl3[(0, 2 * q)] == pl3[(0, 3 * q)] == "___"
assert pl3[(2, 0)] == "Don't" and pl3[(2, q)] == "con-" and pl3[(2, 2 * q)] == "___" and pl3[(2, 3 * q)] == "fuse."
assert pl3[(3, 0)] == pl3[(3, q)] == pl3[(3, 2 * q)] == "___" and pl3[(3, 3 * q)] == "Ba-" and pl3[(4, 0)] == "by"
# paroles : « truth   \n\nMa- » (espaces de fin de ligne + ligne vide) saute 3 notes ; « all \n\nI » en saute 1
assert syllables("the truth   \n\nMa-ma") == ["the", "truth", None, None, None, "Ma-", "ma"]
assert syllables("at all \n\nI see") == ["at", "all", None, "I", "see"]
# synthèse : programme General MIDI de chaque piste, pistes jouables, \instrument dans le alphaTex
from tabs.alphatex import midi_program, playable_tracks
assert midi_program(Track(0, "g", instrument_id=30, is_guitar=True)) == 30
assert midi_program(Track(0, "g", is_guitar=True)) == 29 and midi_program(Track(0, "b", is_bass=True)) == 33
assert midi_program(Track(0, "p", instrument_id=0)) == 0 and midi_program(Track(0, "s", instrument_id=48)) == 48
assert midi_program(Track(0, "v", instrument_id=73, is_vocal=True)) == 54 and midi_program(Track(0, "x", instrument_id=999)) == 0
_sc = parse_score({"songId": 1, "revisionId": 1, "title": "T", "artist": "A", "tracks": []}, {})
_sc.tracks = [Track(1, "vide"), Track(2, "g", instrument_id=30, tuning=[64, 59, 55, 50, 45, 40], is_guitar=True,
                                       measures=[Measure(0, voices=[_vb("n", "n", "n", "n")])])]
assert [t.part_id for t in playable_tracks(_sc)] == [2]
assert "\\instrument 30" in to_alphatex(_sc) and to_alphatex(_sc).count("\\track") == 1
# variantes d'instruments : le premier « son » donne le programme, trackSoundAutomations les changements en cours de morceau
from tabs.alphatex import sound_swaps
_g = Track(0, "g", instrument_id=29, is_guitar=True, sounds=[30, 90], sound_changes=[(2, 0.0, 1), (5, 0.5, 0)])
assert midi_program(_g) == 30 and sound_swaps(_g) == {2: [(0.0, 90)], 5: [(0.5, 30)]}
assert sound_swaps(Track(0, "d", is_drums=True, sounds=[1, 2], sound_changes=[(1, 0, 1)])) == {}
_sc.tracks[1].sounds, _sc.tracks[1].sound_changes = [30, 90], [(0, 0.0, 1)]
assert "{instrument 90" in to_alphatex(_sc)
from tabs import server as _srv
assert _srv.soundfont_url("n'existe-pas.sf2").startswith("/alphatab/soundfont/") and _srv.soundfont_installed()
print("test_tabs OK")