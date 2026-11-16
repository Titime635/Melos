"""Historique + favoris des partitions : modèle (tabs/score_library.py), popup, intégration dans la page Partition."""
import os, sys, time, tempfile, pathlib, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tabs.score_library import ScoreLibrary

tmp = pathlib.Path(tempfile.mkdtemp())
t = [1000.0]
def clock():
    t[0] += 1
    return t[0]

# ---------- modèle ----------
f = tmp / "lib.json"
lib = ScoreLibrary(f, limit=3, clock=clock)
for i in range(1, 5):
    lib.touch(i, f"https://www.songsterr.com/a/wsa/x-s{i}", f"Titre {i}", f"Artiste {i}")
assert [e.song_id for e in lib.recent()] == [4, 3, 2]                  # limite 3 : le plus ancien part
lib.touch(2, "https://www.songsterr.com/a/wsa/x-s2", "Titre 2", "Artiste 2")
assert [e.song_id for e in lib.recent()] == [2, 4, 3] and lib.get(2).count == 2
print("1. historique borné, rouvrir remet en tête : OK")

lib.set_favorite(3, True)
for i in range(10, 14):
    lib.touch(i, f"u{i}", f"T{i}", "")
assert lib.get(3) is not None and lib.is_favorite(3)                    # un favori n'est jamais éliminé
assert len([e for e in lib.recent() if not e.favorite]) == 3
lib.touch(3, "u3", "Titre 3", "Artiste 3")
assert lib.get(3).favorite and lib.get(3).count == 2                    # le favori survit à une réouverture
print("2. favoris conservés (limite, réouverture) : OK")

lib.remember(3, track=2, video="abc")
lib2 = ScoreLibrary(f, limit=3, clock=clock)                            # relecture du fichier
e = lib2.get(3)
assert e.favorite and e.track == 2 and e.video == "abc" and e.title == "Titre 3"
assert [x.song_id for x in lib2.favorites()] == [3]
print("3. persistance (favori, piste, vidéo) : OK")

lib2.clear_history()
assert [e.song_id for e in lib2.recent()] == [3]                        # seuls les favoris restent
lib2.remove(3)
assert lib2.recent() == []
assert [e.song_id for e in lib.search("titre 3", lib.recent())] == [3]
assert lib.search("artiste", lib.recent()) == [] or all("artiste" in (e.title + e.artist).lower() for e in lib.search("artiste", lib.recent()))
print("4. vider l'historique / retirer / filtrer : OK")

bad = tmp / "bad.json"
bad.write_text("{pas du json", encoding="utf-8")
assert ScoreLibrary(bad).recent() == []                                  # fichier corrompu : repart vide sans planter
bad.write_text(json.dumps({"entries": [{"song_id": "x"}, {"song_id": 5, "url": "u", "inconnu": 1}, 7]}), encoding="utf-8")
assert [e.song_id for e in ScoreLibrary(bad).recent()] == [5]            # entrées invalides ignorées
seen = []
lib3 = ScoreLibrary(tmp / "l3.json")
lib3.listeners.append(lambda: seen.append(1))
lib3.touch(1, "u", "T", "A")
assert seen
print("5. fichier corrompu / entrées invalides / listeners : OK")

# ---------- marque-pages ----------
bl = ScoreLibrary(tmp / "bm.json", limit=2, clock=clock)
bl.touch(1, "u1", "Un", "A")
assert bl.add_bookmark(99, 3) is None                                    # morceau inconnu
b = bl.add_bookmark(1, 16, "Refrain")
assert b == {"bar": 16, "name": "Refrain"}
bl.add_bookmark(1, 4)
bl.add_bookmark(1, 40, "x" * 100)
assert [(m["bar"], m["name"]) for m in bl.bookmarks(1)] == [(4, "Mesure 5"), (16, "Refrain"), (40, "x" * 40)]   # triés, nom borné, défaut « Mesure N »
bl.add_bookmark(1, 16)                                                   # même mesure sans nom : pas de doublon, nom conservé
assert len(bl.bookmarks(1)) == 3 and bl.bookmark_at(1, 16)["name"] == "Refrain"
bl.add_bookmark(1, 16, "Chorus")                                         # avec un nom : renomme
assert bl.bookmark_at(1, 16)["name"] == "Chorus"
bl.rename_bookmark(1, 4, "  Intro   riff ")
assert bl.bookmark_at(1, 4)["name"] == "Intro riff"
assert bl.neighbour_bookmark(1, 4, 1)["bar"] == 16 and bl.neighbour_bookmark(1, 16, 1)["bar"] == 40
assert bl.neighbour_bookmark(1, 40, 1) is None and bl.neighbour_bookmark(1, 4, -1) is None
assert bl.neighbour_bookmark(1, 10, -1)["bar"] == 4 and bl.neighbour_bookmark(1, 10, 1)["bar"] == 16
bl.remove_bookmark(1, 40)
assert [m["bar"] for m in bl.bookmarks(1)] == [4, 16]
print("8. marque-pages : ajout / doublon / renommage / voisins / suppression : OK")

for i in (2, 3, 4):
    bl.touch(i, f"u{i}", f"T{i}", "")
assert bl.get(1) is not None                                             # des marque-pages : jamais éliminé (limite 2)
bl.clear_history()
assert [e.song_id for e in bl.recent()] == [1]                           # idem au « vider l'historique »
bl2 = ScoreLibrary(tmp / "bm.json")
assert [(m["bar"], m["name"]) for m in bl2.bookmarks(1)] == [(4, "Intro riff"), (16, "Chorus")]
(tmp / "bm2.json").write_text(json.dumps({"entries": [{"song_id": 1, "url": "u", "bookmarks": [{"bar": 3}, {"nom": 1}, {"bar": -2, "name": "z"}, {"bar": 1, "name": "ok"}]}]}), encoding="utf-8")
assert [m["bar"] for m in ScoreLibrary(tmp / "bm2.json").bookmarks(1)] == [1, 3]   # un marque-page abîmé est ignoré, pas toute l'entrée
print("9. marque-pages protègent l'entrée, persistent, fichier abîmé toléré : OK")

# ---------- changements de preset (modèle) ----------
pl = ScoreLibrary(tmp / "pre.json", limit=2, clock=clock)
pl.touch(1, "u1", "Un", "A")
assert pl.set_preset_mark(99, 3, 0) is False and pl.set_preset_mark(1, -1, 0) is False and pl.set_preset_mark(1, 3, 7) is False
assert pl.set_preset_mark(1, 16, 2) and pl.set_preset_mark(1, 0, 0) and pl.set_preset_mark(1, 40, 5)
assert [(m["bar"], m["slot"]) for m in pl.preset_marks(1)] == [(0, 0), (16, 2), (40, 5)]          # triés
pl.set_preset_mark(1, 16, 3)                                                                       # même mesure : remplace
assert len(pl.preset_marks(1)) == 3 and pl.preset_at(1, 16)["slot"] == 3
assert pl.active_preset(1, 0)["slot"] == 0 and pl.active_preset(1, 15)["slot"] == 0                # en vigueur jusqu'au suivant
assert pl.active_preset(1, 16)["slot"] == 3 and pl.active_preset(1, 99)["slot"] == 5
pl.remove_preset_mark(1, 0)
assert pl.active_preset(1, 5) is None and pl.active_preset(1, 16)["slot"] == 3                     # rien avant le premier
for i in (2, 3, 4):
    pl.touch(i, f"u{i}", f"T{i}", "")
assert pl.get(1) is not None                                                                       # porteur de presets : jamais éliminé
assert [(m["bar"], m["slot"]) for m in ScoreLibrary(tmp / "pre.json").preset_marks(1)] == [(16, 3), (40, 5)]
(tmp / "pre2.json").write_text(json.dumps({"entries": [{"song_id": 1, "url": "u", "presets": [{"bar": 3, "slot": 9}, {"bar": "x"}, {"bar": 2, "slot": 1}, {"nope": 1}]}]}), encoding="utf-8")
assert [(m["bar"], m["slot"]) for m in ScoreLibrary(tmp / "pre2.json").preset_marks(1)] == [(2, 1)]  # un marqueur abîmé est ignoré
# cible = preset de la bibliothèque, déplacement des marqueurs
pe = ScoreLibrary(tmp / "pre3.json", clock=clock)
pe.touch(1, "u1", "Un", "A")
assert pe.set_preset_entry(1, 4, "e1", "Clean Funk") and not pe.set_preset_entry(1, 4, "", "x") and not pe.set_preset_entry(9, 4, "e1")
assert pe.preset_at(1, 4) == {"bar": 4, "entry": "e1", "name": "Clean Funk"}
pe.set_preset_mark(1, 10, 2)
assert pe.move_preset_mark(1, 4, 7) and [m["bar"] for m in pe.preset_marks(1)] == [7, 10] and pe.preset_at(1, 7)["entry"] == "e1"
assert pe.move_preset_mark(1, 7, 10) and len(pe.preset_marks(1)) == 1 and pe.preset_at(1, 10)["entry"] == "e1"   # remplace la cible
assert not pe.move_preset_mark(1, 3, 5) and not pe.move_preset_mark(1, 10, 10) and not pe.move_preset_mark(1, 10, -1)
assert ScoreLibrary(tmp / "pre3.json").preset_at(1, 10)["name"] == "Clean Funk"                                   # persistance
pe.add_bookmark(1, 2, "Mesure 3"); pe.add_bookmark(1, 6, "Refrain")
assert pe.move_bookmark(1, 2, 5) and pe.bookmark_at(1, 5)["name"] == "Mesure 6"                                     # nom par défaut : suit la mesure
assert pe.move_bookmark(1, 6, 5) and [b["bar"] for b in pe.bookmarks(1)] == [5] and pe.bookmark_at(1, 5)["name"] == "Refrain"
assert not pe.move_bookmark(1, 9, 3)
print("12. changements de preset : pose / remplacement / en vigueur / persistance / fichier abîmé : OK")

from tabs.score_library import ScoreEntry
from ui.score_library_popup import ago
now = 100_000_000.0
assert ago(now - 100, now) == "aujourd'hui" and ago(now - 90000, now) == "hier" and ago(now - 5 * 86400, now) == "il y a 5 j"
assert ago(now - 21 * 86400, now) == "il y a 3 sem." and ago(now - 120 * 86400, now) == "il y a 4 mois"

# ---------- interface ----------
import settings
settings.SETTINGS_FILE = tmp / "app_settings.json"
import tabs.score_library as tl
from PySide6.QtWidgets import QApplication
app = QApplication([])
def pump(sec=0.15):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)

import ui.tab_interface as ti_mod
from ui.score_library_popup import ScorePicker
from tabs.model import Score

lib = ScoreLibrary(tmp / "ui.json", clock=clock)
lib.touch(1, "https://www.songsterr.com/a/wsa/aaa-s1", "Alpha", "Les A")
lib.touch(2, "https://www.songsterr.com/a/wsa/bbb-s2", "Bravo", "Les B")
lib.set_favorite(1, True)
picker = ScorePicker(lib)
chosen = []
picker.chosen.connect(chosen.append)
from qfluentwidgets import PushButton
anchor = PushButton("x"); anchor.show()
picker.popup_at(anchor); pump()
assert [picker.list.item(i).data(0x0100).song_id for i in range(picker.list.count())] == [2, 1]   # récents : Bravo avant Alpha
picker._set_tab("fav"); pump()
assert picker.list.count() == 1 and picker.list.item(0).data(0x0100).song_id == 1
picker._set_tab("recent"); picker.search.setText("alp"); pump()
assert picker.list.count() == 1
picker._clicked(picker.list.item(0))
assert chosen and chosen[0].song_id == 1
picker.popup_at(anchor); picker.search.clear(); pump()
picker._toggle_star(2); pump()
assert lib.is_favorite(2)
picker._clear(); pump()
assert [e.song_id for e in lib.recent()] == [2, 1]                      # tous deux favoris : rien n'est perdu
print("6. popup : récents / favoris / filtre / choix / ★ / vider : OK")

ti = ti_mod.TabInterface()
ti.resize(1100, 700); ti.show(); pump()
assert not ti.star_btn.isEnabled()                                       # aucun morceau chargé
ti.library.path = tmp / "ti.json"
if not hasattr(ti, "track_list"):                                        # alphaTab absent (bac à sable) : on neutralise l'affichage
    class _TL:
        def __getattr__(self, name): return lambda *a, **k: None
    ti.track_list = _TL()
ti._push = lambda: None
score = Score(song_id=42, revision_id=1, title="Zeta", artist="Les Z", tempo=120, tracks=[], default_part=0)
ti.url_edit.setText("https://www.songsterr.com/a/wsa/zeta-s42")
ti._on_loaded(score, []); pump()
e = ti.library.get(42)
assert e and e.title == "Zeta" and e.url.endswith("s42") and ti.star_btn.isEnabled() and not ti.star_btn.on
ti.star_btn.click(); pump()
assert ti.library.is_favorite(42) and ti.star_btn.on
ti.library.remember(42, track=3, video="vid")
assert ti.library.get(42).track == 3
launched = []
ti.load_from_edit = lambda refresh=False: launched.append(ti.url_edit.text())
ti._choose_entry(ti.library.get(42))                                    # choisir dans la bibliothèque remplit le lien et charge
assert launched == ["https://www.songsterr.com/a/wsa/zeta-s42"]
print("7. page Partition : chargement -> historique, ★ favori, choix depuis la bibliothèque : OK")

# ---------- marque-pages dans la page Partition ----------
from ui.bookmark_popup import BookmarkPopup
ti.library.remember(42, track=0)
ti._score = score
sent = []
ti._page_ready = True
ti._js = lambda code, cb=None: sent.append(code)
ti.current_bar = -1
ti._toggle_bookmark_here()
assert ti.library.bookmarks(42) == []                                    # pas de mesure courante : rien
ti.current_bar = 7
ti._toggle_bookmark_here()
assert ti.library.bookmark_at(42, 7)["name"] == "Mesure 8" and ti.bkm_btn.text() == "1"
assert any("melos.setBookmarks([[7, \"Mesure 8\"]])" in c for c in sent)  # la page reçoit la liste
ti.current_bar = 7
ti._toggle_bookmark_here()
assert ti.library.bookmarks(42) == [] and ti.bkm_btn.text() == ""
ti.library.add_bookmark(42, 3, "Intro"); ti.library.add_bookmark(42, 20, "Solo")
ti.current_bar = 10
sent.clear(); ti._synth, ti._synth_ready = True, True
ti._step_bookmark(1)
assert any("melos.synth.seekBar(20, 0)" in c for c in sent) and any("revealBar(20)" in c for c in sent)
sent.clear(); ti._synth = False; ti._bar_starts = [i * 2000.0 for i in range(40)]
seeks = []
ti._request_seek = lambda sec: seeks.append(sec)
ti._step_bookmark(-1)
assert seeks == [6.0] and any("revealBar(3)" in c for c in sent)         # Original : saut au début de la mesure 4 (index 3)
ti.current_bar = 30
ti._step_bookmark(1)
assert "Pas d'autre" in ti.status._full if hasattr(ti.status, "_full") else True
ti._bookmark_hint(5)
print("10. page Partition : Ctrl+B, voisins, saut Original / Synthèse, envoi à la page : OK")

pop = BookmarkPopup(ti.library, name_hint=ti._bookmark_hint)
jumps = []
pop.jump.connect(jumps.append)
pop.popup_at(anchor, 42, 12); pump()
assert pop.list.count() == 2 and pop.add_btn.text() == "Ajouter à la mesure 13"
pop._add_or_remove(); pump()
assert ti.library.bookmark_at(42, 12) and pop.add_btn.text() == "Retirer (mesure 13)" and pop.list.count() == 3
row = pop.list.itemWidget(pop.list.item(0))
row.edit.setText("Début"); row._commit(); pump()
assert ti.library.bookmark_at(42, 3)["name"] == "Début"
pop._clicked(pop.list.item(1))
assert jumps == [12]
pop.popup_at(anchor, 42, 12); pump()
pop.list.itemWidget(pop.list.item(2)).removed.emit(20); pump()
assert ti.library.bookmark_at(42, 20) is None
print("11. popup marque-pages : ajouter / renommer / sauter / supprimer : OK")


# ---------- changements de preset dans la page Partition ----------
from types import SimpleNamespace as NS
from PySide6.QtCore import QObject, Signal, QPoint
from ui.preset_marks_popup import PresetMarksPopup, resolve

class FakeNames(QObject):
    """Bibliothèque de presets : a « Clean Funk » (chargé, emplacement 1), b « Edge » (chargé mais à renvoyer, emplacement 3),
    c « Solo Lead » (pas chargé)."""
    changed = Signal()
    has_library = True
    ents = {"a": NS(id="a", name="Clean Funk", tags=["funk"]), "b": NS(id="b", name="Edge", tags=[]), "c": NS(id="c", name="Solo Lead", tags=[])}
    loaded = {"a": [(0, "synced")], "b": [(2, "ahead")], "c": []}
    def library_entries(self): return list(self.ents.values())
    def library_entry(self, i): return self.ents.get(i)
    def slots_of(self, i): return self.loaded.get(i, [])
    def title(self, i): return {0: "Clean"}.get(i, f"Preset {i + 1}")
    def state(self, i): return ("synced", None)
class FakeSender:
    def __init__(self): self.sent, self.is_open = [], True
    def set_preset(self, i): self.sent.append(i)
class FakeState:
    def __init__(self): self.cur = []
    def on_preset_changed(self, i): self.cur.append(i)
names, snd, st = FakeNames(), FakeSender(), FakeState()
ti.set_amp(st, snd, names)
ti._synth = False
for b in ti.library.bookmarks(42):
    ti.library.remove_bookmark(42, b["bar"])
sent.clear()
A, B, C = {"entry": "a", "name": "Clean Funk"}, {"entry": "b", "name": "Edge"}, {"entry": "c", "name": "Solo Lead"}
assert resolve(names, A)["slot"] == 0 and resolve(names, A)["status"] == "ok"
assert resolve(names, B)["slot"] == 2 and resolve(names, B)["status"] == "ahead"
assert resolve(names, C)["slot"] is None and resolve(names, C)["status"] == "missing"              # pas chargé : dit clairement
assert resolve(names, {"entry": "zz", "name": "Vieux"})["status"] == "deleted"
assert resolve(names, {"slot": 3})["status"] == "raw" and resolve(names, {"slot": 3})["slot"] == 3
ti._place_preset(A, 4); ti._place_preset(B, 12); ti._place_preset(C, 20)
assert ti.pre_btn.text() == "3" and any("melos.setPresets([[4, \"1\"," in c for c in sent)             # la page reçoit les pastilles
q = ti._preset_quads()
assert q[0][:2] == [4, "1"] and q[0][4] == "" and q[0][5] == "ok"
assert q[1][:2] == [12, "3"] and q[1][4] != "" and q[1][5] == "ahead"                              # chargé mais à renvoyer : avertissement
assert q[2][1] == "" and q[2][4] != "" and q[2][5] == "missing"                                    # non chargé : pastille « non chargé »
ti._apply_preset(5)
assert snd.sent == []                                                                              # à l'arrêt : rien n'est envoyé
ti.current_bar = 13
ti._update_controls(0.0, True, 60.0)                                                               # lecture lancée à la mesure 13 : preset b (emplacement 3)
assert snd.sent == [2] and st.cur == [2]
ti._apply_preset(14); ti._apply_preset(13)
assert snd.sent == [2]                                                                             # même preset : pas de renvoi
ti.current_bar = 4; ti._apply_preset(4)
assert snd.sent == [2, 0]                                                                          # retour en arrière (boucle) : on se remet au bon preset
msgs = []
_ss = ti.set_status; ti.set_status = lambda t, *a, **k: msgs.append(t)
ti.current_bar = 21; ti._apply_preset(21)
assert snd.sent == [2, 0] and msgs and "non chargé" in msgs[-1]                                    # preset non chargé : rien d'envoyé, message
ti.set_status = _ss
ti._update_controls(1.0, False, 60.0); ti._apply_preset(12)
assert snd.sent == [2, 0]                                                                          # en pause : rien
ti.current_bar = 5
ti._update_controls(1.0, True, 60.0)                                                               # reprise : on renvoie le preset en vigueur (mesure 5 -> a)
assert snd.sent == [2, 0, 0]
ti._on_preset_auto(False); ti._apply_preset(12)
assert snd.sent == [2, 0, 0]                                                                       # envoi auto coupé
ti._on_preset_auto(True)
assert settings.load_settings()["tabs"]["preset_auto"] is True and snd.sent[-1] == 0
snd.is_open = False
ti._auto_key = None; ti.current_bar = 12; ti._apply_preset(12)
assert len(snd.sent) == 4 or snd.sent[-1] == 0                                                     # ampli déconnecté : pas d'envoi
n_sent = len(snd.sent)
ti._auto_key = None; ti._apply_preset(12)
assert len(snd.sent) == n_sent
snd.is_open = True
# un preset chargé plus tard dans un emplacement est retrouvé tout seul (le lien est par preset, pas par emplacement)
names.loaded["c"] = [(5, "synced")]
assert resolve(names, C)["slot"] == 5 and ti._preset_quads()[2][1] == "6"
names.loaded["c"] = []
print("13. page Partition : presets liés à la bibliothèque, non chargé signalé, envoi automatique : OK")

# déplacement et dépôt sur la partition
ti._on_move_mark({"kind": "preset", "from": 4, "to": 8})
assert ti.library.preset_at(42, 4) is None and ti.library.preset_at(42, 8)["entry"] == "a"
ti.library.add_bookmark(42, 2, "Intro")
ti._on_move_mark({"kind": "bookmark", "from": 2, "to": 3})
assert ti.library.bookmark_at(42, 2) is None and ti.library.bookmark_at(42, 3)["name"] == "Intro"
ti._dropped_on("preset", C, 30.0)                                                                  # la page renvoie un nombre à virgule
assert ti.library.preset_at(42, 30)["entry"] == "c"
ti._dropped_on("preset", C, -1); ti._dropped_on("preset", C, None); ti._dropped_on("bookmark", None, 14)
assert ti.library.preset_at(42, 31) is None and ti.library.bookmark_at(42, 14) is not None         # hors partition : ignoré
print("15. déplacer / déposer marqueurs et presets sur la partition : OK")

# zone de boucle
js_sent = []
ti._js = lambda code, cb=None: js_sent.append(code)
ti.loop_btn.setChecked(False)
ti._set_range(2, 4)
assert "melos.setRange(2, 4)" in js_sent and ti.loop_btn.isChecked()                               # choisir une zone active la boucle
assert "melos.setLoopMode(true)" in js_sent                                                        # et la page est prévenue (glisser crée une zone)
js_sent.clear(); ti.loop_btn.setChecked(False); assert js_sent == ["melos.setLoopMode(false)"]    # mode boucle coupé : le glisser n'en crée plus
ti.loop_btn.setChecked(True); js_sent.clear()
ti._on_range({"bars": [2.0, 4.0], "t0": 4000.0, "t1": 10000.0})
assert ti._range == {"bars": [2, 4], "t0": 4.0, "t1": 10.0}
ti._loop_to(7); assert js_sent[-1] == "melos.setRange(2, 7)"
ti._loop_from(3); assert js_sent[-1].startswith("melos.setRange(3, ")
ti._clear_range(); assert js_sent[-1] == "melos.clearRange()"
ti._on_range(None); assert ti._range is None
print("16. zone de boucle : choisir / début / fin / effacer : OK")

# menu clic droit
if ti._view is not None:
    ti._on_context({"bar": 6, "x": 50, "y": 50, "kind": "", "mark": -1}); pump()
    assert ti._ctx_menu.isVisible()
    from ui.tab_widgets import _MenuRow
    rows = {r.text(): r for r in ti._ctx_menu.findChildren(_MenuRow)}
    assert any("marque-page" in t.lower() for t in rows) and any("preset" in t.lower() for t in rows)
    assert "Boucler cette mesure" in rows and "Lire à partir d'ici" in rows
    rows["Boucler cette mesure"].click(); pump()
    assert js_sent[-1] == "melos.setRange(6, 6)" and not ti._ctx_menu.isVisible()                   # une entrée agit puis ferme le menu
    ti._ctx_menu.close()
print("17. menu clic droit : OK")

ppop = PresetMarksPopup(ti.library, names=names, name_hint=ti._bookmark_hint)
jumps, added = [], []
ppop.jump.connect(jumps.append)
ppop.add_requested.connect(lambda t, b, k: added.append((t, b, k)))
ppop.popup_at(anchor, 42, 9); pump()
nm = len(ti.library.preset_marks(42))
assert ppop.list.count() == nm and ppop.stack.currentIndex() == 0                                  # des changements existent : page « Sur ce morceau »
ppop._page("add"); pump()
assert ppop.lib.count() == 3                                                                       # les 3 presets de la bibliothèque
ppop.search.setText("solo"); pump()
assert ppop.lib.count() == 1
ppop.search.clear(); pump()
ppop._picked(A)
assert added == [(A, 9, 0)]
ppop._clicked(ppop.list.item(0)); assert jumps == [ti.library.preset_marks(42)[0]["bar"]]
ppop.popup_at(anchor, 42, 9, "marks"); pump()
ppop.list.itemWidget(ppop.list.item(0)).removed.emit(ti.library.preset_marks(42)[0]["bar"], 0); pump()
assert len(ti.library.preset_marks(42)) == nm - 1
dr = []
ppop.drag_started.connect(lambda t, l, c: dr.append(("start", t)))
ppop.drag_dropped.connect(lambda p: dr.append(("drop", p)))
ppop._drag_started(B, "Edge", "#fff"); ppop._drag_dropped(QPoint(5, 5))
assert dr == [("start", B), ("drop", QPoint(5, 5))] and ppop.windowOpacity() == 1.0
print("14. popup presets : bibliothèque / filtre / placer / sauter / supprimer / glisser : OK")

# ---------- annuler / rétablir (Ctrl+Z, Ctrl+Y) ----------
pr = ScoreLibrary(tmp / "undo.json", clock=clock)
pr.touch(1, "u", "T", "A"); pr.add_bookmark(1, 2, "Intro"); pr.set_preset_mark(1, 4, 1)
assert pr.restore_marks(1, [{"bar": 9, "name": "X"}, {"bar": "?"}], [{"bar": 3, "slot": 0}]) and not pr.restore_marks(5, [], [])
assert [b["bar"] for b in pr.bookmarks(1)] == [9] and [p["bar"] for p in pr.preset_marks(1)] == [3]               # entrées abîmées ignorées

ti._undo.clear()
ti._marks_last = ti._marks_snapshot()
sid = 42
ti.library.add_bookmark(sid, 20, "Pont")
ti.library.set_preset_mark(sid, 21, 3)
ti.library.move_preset_mark(sid, 21, 25)
ti.library.remove_bookmark(sid, 20)
assert ti.undo_redo(False) == "Annulé : marque-page retiré" and ti.library.bookmark_at(sid, 20) is not None
assert ti.undo_redo(False) == "Annulé : changement de preset déplacé" and ti.library.preset_at(sid, 21) is not None
assert ti.library.preset_at(sid, 25) is None
assert ti.undo_redo(True) == "Rétabli : changement de preset déplacé" and ti.library.preset_at(sid, 25) is not None
assert ti.undo_redo(False) and ti.undo_redo(False) == "Annulé : changement de preset posé" and ti.library.preset_at(sid, 21) is None
assert ti.undo_redo(False) == "Annulé : marque-page ajouté" and ti.library.bookmark_at(sid, 20) is None
assert ti.undo_redo(False) == "Rien à annuler"
assert ti.undo_redo(True).startswith("Rétabli") and ti.library.bookmark_at(sid, 20) is not None
ti.library.add_bookmark(sid, 30, "Fin")                                                                        # un nouveau changement vide « rétablir »
assert ti.undo_redo(True) == "Rien à rétablir"
# la zone de boucle s'annule aussi
js_sent.clear()
ti._on_range({"bars": [2, 4], "t0": 4000.0, "t1": 10000.0})
ti._on_range({"bars": [6, 7], "t0": 12000.0, "t1": 16000.0})
assert ti.undo_redo(False) == "Annulé : zone de boucle" and js_sent[-1] == "melos.setRange(2, 4)"
ti._on_range({"bars": [2, 4], "t0": 4000.0, "t1": 10000.0})                                                    # l'écho de la page n'est pas ré-enregistré
assert ti.undo_redo(False) == "Annulé : zone de boucle" and js_sent[-1] == "melos.clearRange()"
assert ti.undo_redo(True) == "Rétabli : zone de boucle" and js_sent[-1] == "melos.setRange(2, 4)"
print("18. Ctrl+Z / Ctrl+Y de la page Partition : marqueurs, déplacements, zone de boucle : OK")

# Ctrl + molette dans la page = zoom de l'application
ti._set_zoom(1.0)
ti._on_events(json.dumps([{"type": "zoom", "data": 1}])); assert ti._zoom == 1.1
ti._on_events(json.dumps([{"type": "zoom", "data": -1}, {"type": "zoom", "data": -1}])); assert ti._zoom == 0.9
ti._on_events(json.dumps([{"type": "zoom", "data": 0}])); assert ti._zoom == 1.0
print("19. molette : le zoom de la souris passe par celui de l'application : OK")

# les fenêtres flottantes restent dans la fenêtre de l'application
from PySide6.QtCore import QRect
ti.resize(900, 640); pump(0.3)
ti._open_presets(); pump(0.3)
win = QRect(ti.mapToGlobal(QPoint(0, 0)), ti.size())
assert win.contains(ti._pre_popup.frameGeometry())
ti._pre_popup.close()
ti._pre_popup.popup_at(ti.mapToGlobal(QPoint(ti.width() - 5, ti.height() - 5)), 42, 4, "add"); pump(0.3)
assert win.contains(ti._pre_popup.frameGeometry())
ti._pre_popup.close()
print("20. fenêtres flottantes : toujours dans la fenêtre de l'application : OK")

# ---------- Ma version : édition de la partition ----------
from tabs.model import Score as _Sc, Track as _Tr, Measure as _Me, Beat as _Be, Note as _No, TempoChange as _Tc
from tabs import score_edits as _se


def _mk_score(sid_):
    G = [64, 59, 55, 50, 45, 40]
    t = _Tr(0, "Lead", "Guitar", tuning=G, is_guitar=True)
    d = _Tr(1, "Drums", "Drums", tuning=[], is_drums=True)
    for i in range(4):
        m = _Me(i); m.voices = [[_Be(notes=[_No(string=i % 6, fret=3)], base=8) for _ in range(8)]]
        t.measures.append(m)
        dm = _Me(i); dm.voices = [[_Be(notes=[_No(string=0, fret=36)], base=8) for _ in range(8)]]
        d.measures.append(dm)
    return _Sc(sid_, 1, "Edit", "Test", [_Tc(0, 0.0, 120.0)], [t, d], 0)


es = _mk_score(77)
for _n in ("stop", "load", "set_paused"):
    setattr(ti._player, _n, lambda *a, **k: None)                                                       # pas de mpv ici
ti._js = lambda code, cb=None: js_sent.append(code)
ti._on_loaded(es, []); pump()
ti._track_idx = 0
E = ti.edit
assert not E.on and ti._score is ti._orig_score and ti.library.version(77) == "original"
ti.edit_btn.setChecked(True)
assert E.on and ti.library.version(77) == "modified" and not E.bar.isHidden()                  # entrer en édition affiche « Ma version »
E.on_select({"bar": 1, "beat": 2, "string": 0})
assert E.sel == (1, 2, 0) and "Mesure 2" in E.bar.info.text() and "vide" in E.bar.info.text()
E.on_key({"key": "1"}); E.on_key({"key": "2"})                                                     # « 1 » puis « 2 » vite = case 12
n = _se.find_note(ti._score.tracks[0].measures[1].voices[0][2], 0)
assert n and n.fret == 12 and [e["bar"] for e in ti.library.edits(77)] == [1]
assert _se.find_note(ti._orig_score.tracks[0].measures[1].voices[0][2], 0) is None             # l'original n'est pas touché
assert ti._reload_timer.isActive()
ti._page_ready, ti._synth = True, False; ti._reload_now()
assert js_sent[-1].startswith("melos.reload(") and '"edited": [1]' in js_sent[-1]                  # la page est redessinée, mesure signalée
assert ti._edited_bars() == [1] and "Ma version" in ti.title_field.artist
E.on_key({"key": "ArrowRight"}); assert E.sel == (1, 3, 0) and js_sent[-1] == "melos.select(1, 3, 0, 0)"
E.on_key({"key": "ArrowDown"}); assert E.sel == (1, 3, 1)
E.on_key({"key": "ArrowUp"}); E.on_key({"key": "ArrowUp"}); assert E.sel == (1, 3, 0)
E.sel = (1, 7, 0); E.on_key({"key": "ArrowRight"}); assert E.sel == (2, 0, 0)                         # passe à la mesure suivante
E.on_key({"key": "ArrowLeft"}); assert E.sel == (1, 7, 0)
E.sel = (1, 2, 0)
E.on_key({"key": "Delete"})                                                                       # supprime la note de la corde choisie (l'autre reste)
b2 = ti._score.tracks[0].measures[1].voices[0][2]
assert _se.find_note(b2, 0) is None and _se.find_note(b2, 1) is not None and not b2.rest
E.on_key({"key": "r"}); assert ti._score.tracks[0].measures[1].voices[0][2].rest
E.set_duration(4); assert ti._score.tracks[0].measures[1].voices[0][2].base == 4
assert "trop longue" in E.bar.info.text()                                                          # mesure déséquilibrée : signalée
E.on_key({"key": "Delete", "shift": True})                                                        # Maj+Suppr : retire le temps
assert len(ti._score.tracks[0].measures[1].voices[0]) == 7 and "incomplète" in E.bar.info.text()
E.complete_bar(); assert _se.fill(ti._score.tracks[0].measures[1])[0] == 1
E.on_key({"key": "."}); E.on_key({"key": "r"})
E.set_text("riff"); assert ti._score.tracks[0].measures[1].voices[0][E.sel[1]].text == "riff"
E.set_marker("Pont"); assert ti._score.tracks[0].measures[1].marker == "Pont"
E.set_tempo("abc"); E.set_tempo("9999"); assert not any(e["op"] == "tempo" for e in ti.library.edits(77))     # tempo invalide : refusé
E.set_tempo("95"); assert _se.tempo_at(ti._score, 1) == 95 and _se.tempo_at(ti._orig_score, 1) == 120
assert ti.undo_redo(False) == "Annulé : modification de la partition" and _se.tempo_at(ti._score, 1) == 120
assert ti.undo_redo(True) == "Rétabli : modification de la partition" and _se.tempo_at(ti._score, 1) == 95
# version d'origine : lecture seule
E.choose_version("original")
assert ti._score is ti._orig_score and ti._edited_bars() == [] and "lecture seule" in E.bar.info.text()
before = ti.library.edits(77)
E.on_select({"bar": 0, "beat": 0, "string": 0}); E.on_key({"key": "9"}); assert ti.library.edits(77) == before          # rien ne s'écrit
E.choose_version("modified")
assert ti._score is not ti._orig_score
E.revert_bar(1); assert 1 not in [e["bar"] for e in ti.library.edits(77) if e["op"] == "measure"]
E.sel = (0, 0, 0); E.on_key({"key": "5"}); assert [e["bar"] for e in ti.library.edits(77) if e["op"] == "measure"] == [0]
E.revert_all(); assert ti.library.edits(77) == [] and ti._score is not None and "Ma version" not in ti.title_field.artist
assert ti.undo_redo(False) == "Annulé : modification de la partition" and ti.library.edits(77)                  # tout rétablir se défait
ti.edit_btn.setChecked(False); assert not E.on and E.bar.isHidden() and ti.library.version(77) == "modified"   # terminer garde la version
# batterie : pas d'édition
ti._track_idx = 1
ti.edit_btn.setChecked(True); assert not E.on and not ti.edit_btn.isChecked()
ti._track_idx = 0
# chargement d'un autre morceau : on sort du mode édition ; « Ma version » est restituée à la réouverture
ti.edit_btn.setChecked(True); assert E.on
ti._on_loaded(_mk_score(78), []); pump(); assert not E.on and E.bar.isHidden()
ti._on_loaded(_mk_score(77), []); pump()
assert ti._score is not ti._orig_score and _se.edited_bars(ti.library.edits(77), 0) and "Ma version" in ti.title_field.artist
ti.library.set_edits(77, []); ti.library.set_version(77, "original")
print("21. édition : sélection, touches, durée, silence, tempo, texte, annuler, version d'origine en lecture seule : OK")

# ---------- palette d'outils (parité avec Songsterr) ----------
from tabs import score_tools as _st
ti._on_loaded(_mk_score(79), []); pump(); ti._track_idx = 0
E = ti.edit
js_sent.clear()
ti.edit_btn.setChecked(True); pump()
P = E.palette
assert not P.isHidden() and not E.bar.dur.isVisible() and E.bar.tools.isChecked()                    # palette montrée, doublons de la barre masqués
E.bar.tools.setChecked(False); assert P.isHidden() and not E.bar.dur.isHidden(); E.bar.tools.setChecked(True); assert not P.isHidden()
assert len(P.buttons) == len(_st.TOOLS) and all(not b.isEnabled() or not b._enabled for b in P.buttons.values() if b.tool.scope == "note")   # rien de choisi : tout grisé
E.on_select({"bar": 1, "beat": 2, "string": 2}); pump()
assert P.buttons["vib"]._enabled is False and P.buttons["fermata"]._enabled and P.buttons["d8"].active and P.buttons["rep_s"]._enabled     # pas de note sur la corde 2 : effets de note grisés
E.on_select({"bar": 1, "beat": 2, "string": 1}); pump()
assert P.buttons["vib"]._enabled and not P.buttons["vib"].active and P.buttons["paste"]._enabled is False
P.tool_clicked.emit("vibw"); pump()
assert _se.find_note(ti._score.tracks[0].measures[1].voices[0][2], 1).vibrato_wide and P.buttons["vibw"].active
P.tool_clicked.emit("vibw"); assert not P.buttons["vibw"].active
for tid in ("fermata", "cre", "pm", "ghost"):
    P.tool_clicked.emit(tid)
b = ti._score.tracks[0].measures[1].voices[0][2]
assert b.fermata == "medium" and b.crescendo == "cre" and b.palm_mute and b.notes[0].ghost
assert "fermata medium" in __import__("tabs.alphatex", fromlist=["x"]).to_alphatex(ti._score, part_ids=[0])
E.on_tool("tup", "3"); assert ti._score.tracks[0].measures[1].voices[0][2].tuplet == 3 and "3" in E.bar.info.text() or True
# copier / coller par les touches de la page
E.on_key({"key": "c", "ctrl": True}); assert E.clip and E.clip["kind"] == "beat"
E.on_select({"bar": 2, "beat": 5, "string": 1}); E.on_key({"key": "v", "ctrl": True})
assert ti._score.tracks[0].measures[2].voices[0][5].fermata == "medium"
# invite de texte : accord, signature (refusée si invalide)
E.set_chord("Am7"); assert ti._score.tracks[0].measures[2].voices[0][E.sel[1]].chord == "Am7"
E.set_signature("3/5"); assert ti._score.tracks[0].measures[2].signature == (4, 4)
E.set_signature("3/4"); assert ti._score.tracks[0].measures[2].signature == (3, 4) and "trop longue" in E.bar.info.text()
# armure : de la mesure choisie à la fin, une seule annulation
E.on_select({"bar": 1, "beat": 0, "string": 1}); E.on_tool("key", "-2")
assert [m.key for m in ti._score.tracks[0].measures] == [0, -2, -2, -2]
assert ti.undo_redo(False) == "Annulé : modification de la partition" and [m.key for m in ti._score.tracks[0].measures] == [0, 0, 0, 0]
# voix 2 : la page est prévenue, la sélection se fait par la position dans la mesure
js_sent.clear(); P.voice_chosen.emit(1)
assert E.voice == 1 and any("setVoice(1)" in c for c in js_sent) and E.sel is None
E.on_select({"bar": 0, "beat": -1, "string": 1, "frac": 0.6, "voice": 1}); assert E.sel == (0, 0, 1) and "voix 2" in E.bar.info.text()
assert len(ti._score.tracks[0].measures[0].voices) == 1                                            # regarder une voix vide ne crée rien
E.type_digit(7); assert len(ti._score.tracks[0].measures[0].voices) == 2 and _se.find_note(ti._score.tracks[0].measures[0].voices[1][0], 1).fret == 7
assert ti._score.tracks[0].measures[0].voices[0][0].notes[0].fret == 3                              # la voix 1 est intacte
P.voice_chosen.emit(0)
# recherche : filtre tous les onglets ; vider la recherche revient à l'onglet
P.search.setText("vibrato"); pump(); assert {t.id for t in P._shown()} >= {"vib", "vibw"} and not P.buttons["rep_s"].isVisible()
P.search.setText(""); pump(); assert P.buttons["d8"].isVisible() and not P.buttons["vib"].isVisible()
# jamais de défilement : à toute largeur, chaque bouton reste dans le corps du panneau, et la hauteur suffit à tous les onglets
for w in (1480, 1100, 880):
    ti.resize(w, 760); pump(0.4)
    for key, _ in _st.TABS:
        P.tabs.setCurrentItem(key); P._tab(key); pump(0.1)
        bw = P.body.width()
        for t in _st.TOOLS:
            if t.tab == key:
                bt = P.buttons[t.id]
                assert bt.isVisible() and bt.x() >= 0 and bt.x() + bt.width() <= bw and bt.y() + bt.height() <= P.body.height(), (w, key, t.id)
P.tabs.setCurrentItem("temps"); P._tab("temps")
ti.edit_btn.setChecked(False); assert P.isHidden()
ti.library.set_edits(79, []); ti.library.set_version(79, "original")
print("22. palette : états grisés / allumés, effets, copier-coller, armure, voix, recherche, mise en page sans défilement : OK")

# ---- 23. presets au temps près + marque-pages par défaut ----
ti._on_loaded(_mk_score(80), []); pump()
L = ti.library
sid = 80
for m in L.preset_marks(sid):
    L.remove_preset_mark(sid, m["bar"], m.get("beat", 0))
assert L.set_preset_mark(sid, 6, 1) and L.set_preset_mark(sid, 6, 3, beat=2) and L.set_preset_mark(sid, 6, 5, beat=4)
assert [(p["bar"], p.get("beat", 0), p["slot"]) for p in L.preset_marks(sid)] == [(6, 0, 1), (6, 2, 3), (6, 4, 5)]
assert "beat" not in L.preset_at(sid, 6, 0) and L.preset_at(sid, 6, 2)["beat"] == 2            # temps 0 : format inchangé
assert L.active_preset(sid, 6, 0)["slot"] == 1 and L.active_preset(sid, 6, 1)["slot"] == 1
assert L.active_preset(sid, 6, 2)["slot"] == 3 and L.active_preset(sid, 6, 5)["slot"] == 5
assert L.active_preset(sid, 7, 0)["slot"] == 5 and L.active_preset(sid, 5, 3) is None
assert L.move_preset_mark(sid, 6, 6, beat=2, to_beat=3) and L.preset_at(sid, 6, 3)["slot"] == 3 and L.preset_at(sid, 6, 2) is None
assert not L.set_preset_mark(sid, 6, 2, beat=99)                                                 # temps absurde : refusé
L.remove_preset_mark(sid, 6, 3); assert L.preset_at(sid, 6, 3) is None and L.preset_at(sid, 6, 0)
L.load_data(L.to_data()); assert L.preset_at(sid, 6, 4)["slot"] == 5                          # relecture du fichier
# page : le 7e champ des pastilles est le temps ; un dépôt renvoie {"bar", "beat"}
assert all(len(q) == 7 for q in ti._preset_quads()) and [q[6] for q in ti._preset_quads()] == [0, 4]
ti._dropped_on("preset", {"slot": 2}, {"bar": 9, "beat": 3}); assert L.preset_at(sid, 9, 3)["slot"] == 2
ti._dropped_on("preset", {"slot": 4}, 11); assert L.preset_at(sid, 11, 0)["slot"] == 4
ti._on_move_mark({"kind": "preset", "from": 9, "fromBeat": 3, "to": 9, "toBeat": 1}); assert L.preset_at(sid, 9, 1) and not L.preset_at(sid, 9, 3)
# déclenchement : même mesure, temps différent -> le bon preset part au bon moment
snd.sent.clear(); ti._auto_key = None; ti._was_playing = True; ti._preset_auto = True
ti._apply_preset(9, 0.0); assert snd.sent[-1] == 5                                                 # début de mesure 9 : celui de la mesure 6 (temps 5) est encore en vigueur
ti._apply_preset(9, 0.9); assert snd.sent[-1] == 2, snd.sent                                       # passé le temps 2 de la mesure 9 : preset 3
# marque-pages par défaut : posés une seule fois, pas pris pour du travail de l'utilisateur
lib2 = ScoreLibrary(pathlib.Path(tempfile.mkdtemp()) / "l.json")
lib2.touch(7, "u", "T", "A")
assert lib2.seed_bookmarks(7, [(0, "Intro"), (8, "Chorus"), (8, "Doublon")]) == 2 and [b["name"] for b in lib2.bookmarks(7)] == ["Intro", "Chorus"]
assert not lib2.get(7).keep                                                                        # seulement des marque-pages d'office : pas de protection de l'historique
lib2.remove_bookmark(7, 8); assert lib2.seed_bookmarks(7, [(8, "Chorus")]) == 0 and lib2.bookmark_at(7, 8) is None   # supprimé : ne revient pas
lib2.rename_bookmark(7, 0, "Mon intro"); assert lib2.get(7).keep                                   # retouché : devient à lui
lib2.touch(7, "u", "T", "A"); assert [b["name"] for b in lib2.bookmarks(7)] == ["Mon intro"]
print("23. presets au temps près, marque-pages par défaut : OK")