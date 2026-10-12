"""Moteur de loop : grille, quantification, auto-length, clic, latence, départ batterie.
Le callback est piloté à la main avec une entrée "rampe" (la valeur d'un échantillon = son
numéro d'horloge) : on sait donc exactement d'où vient chaque échantillon d'une piste."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from PySide6.QtCore import QCoreApplication, Qt
app = QCoreApplication([])
from audio import loop_engine as le
from audio.loop_engine import LoopEngine, bar_samples, BLOCK_SIZE as B

def new_engine(bpm=120, beats=4, unit=4, **kw):
    e = LoopEngine()
    e._running = True
    e.set_grid(bpm, beats, unit)
    e.set_quantize(kw.get("quantize", False))
    e.set_auto_bars(kw.get("bars", 0))
    return e

def run(e, nsamples):
    """Fait tourner le callback ; renvoie la sortie. Entrée = rampe (numéro d'horloge)."""
    outs = []
    done = 0
    while done < nsamples:
        n = min(B, nsamples - done)
        t0 = e._clock
        ind = np.zeros((n, 2), dtype="float32")
        ind[:, 0] = np.arange(t0, t0 + n)
        out = np.zeros((n, 2), dtype="float32")
        e._callback(ind, out, n, None, None)
        outs.append(out.copy()); done += n
    return np.concatenate(outs)

# ---- 1. longueur de mesure ----
assert round(bar_samples(120, 4, 4)) == 88200
assert round(bar_samples(120, 6, 8)) == 66150       # 6 croches = 3 noires
assert round(bar_samples(90, 3, 4)) == 88200
print("1. longueur d'une mesure (4/4, 6/8, 3/4) : OK")

# ---- 2. auto-length sans quantification ----
e = new_engine(bars=2)
run(e, 1000)                              # horloge quelconque : démarrage immédiat
e.record(); run(e, 100)
assert e.state == "recording"
s0 = e._grid_origin
run(e, 176400 + 4000)
assert e.state == "playing" and e._loop_len == 176400, (e.state, e._loop_len)
assert e.loop_bars == 2
t = e._tracks[0][:, 0]
assert t[0] == s0 and t[-1] == s0 + 176399 and np.all(np.diff(t) == 1)
print("2. auto-length : arrêt pile à 2 mesures (176400 éch.), prise continue : OK")

# ---- 3. auto-length en 6/8 ----
e = new_engine(bpm=120, beats=6, unit=8, bars=2)
e.record(); run(e, 140000)
assert e._loop_len == 132300 and e.state == "playing"
print("3. auto-length en 6/8 : OK")

# ---- 4. début de prise calé sur la mesure (clic actif) ----
e = new_engine(quantize=True, bars=1)
e.set_click(True)                         # grille ancrée à 0
run(e, 5000)
e.record()
assert e.pending_action == "record" and e.state == "idle"
run(e, 88200 + 90000)
assert e.state == "playing" and e._loop_len == 88200, (e.state, e._loop_len)
assert e._tracks[0][0, 0] == 88200, e._tracks[0][0, 0]     # a démarré pile au début de la 2e mesure
print("4. Rec attend la mesure : démarre pile sur le temps 1 : OK")

# ---- 5. sans repère de phase : départ immédiat, grille ancrée ----
e = new_engine(quantize=True, bars=1)
run(e, 7000)
e.record(); run(e, 10)
assert e.state == "recording" and e._grid_origin == 7000
print("5. quantification sans repère : démarre tout de suite : OK")

# ---- 6. fin de prise manuelle calée sur la mesure ----
e = new_engine(quantize=True)
e.set_click(True)
run(e, 3000)
e.record()
run(e, (88200 - 3000) + 114660)            # 1,3 mesure après le départ (calé à 88200)
assert e.state == "recording"
e.stop_record()
assert e.pending_action == "stop_record"
run(e, 80000)
assert e.state == "playing", e.state
assert e._loop_len == 2 * 88200 and e.loop_bars == 2, (e._loop_len, e.loop_bars)
print("6. Stop de la 1re prise attend la fin de mesure (2 mesures pile) : OK")

# ---- 7. overdub calé : début sur une mesure de la boucle, longueur = 1 tour ----
e = new_engine(quantize=True, bars=2)
e.record(); run(e, 176400 + 100)           # immédiat (aucun repère) puis auto 2 mesures
L = e._loop_len; assert e.state == "playing"
run(e, 20000)
pos_before = e._play_pos
e.overdub(); assert e.pending_action == "overdub"
t_req = e._clock
run(e, 70000)
assert e.state == "overdubbing"
# a démarré sur une mesure de la boucle : la position à ce moment = multiple de 88200
od = e._overdub_buffer
n_written = int(np.count_nonzero(od[:, 0]))
run(e, L)                                  # un tour complet
assert e.state == "playing" and e.track_count == 2
tr = e._tracks[1][:, 0]
bar_pos = round(L / 2)
start_pos = int(np.argmin(np.where(tr > 0, tr, 1e12)))
assert start_pos in (0, bar_pos), start_pos                # a démarré sur une mesure de la boucle
assert np.count_nonzero(tr) >= L - 1                       # un tour entier couvert
print("7. Overdub attend la mesure, dure exactement un tour : OK")

# ---- 8. annulation de l'action en attente ----
e = new_engine(quantize=True, bars=1); e.set_click(True)
e.record(); assert e.pending_action == "record"
e.cancel_pending(); assert e.pending_action == ""
run(e, 100000); assert e.state == "idle"
print("8. annulation de l'action en attente : OK")

# ---- 9. décompte d'une mesure puis prise pile sur la mesure suivante ----
e = new_engine(bars=1)
run(e, 2000)
e.record_with_count_in()
assert e.state == "counting_in"
out = run(e, 88200 + 100)
assert e.state == "recording", e.state
assert e._grid_origin == 2000 + 88200
beat = round(88200 / 4)
env = np.abs(out[:, 0])
for k in range(4):
    assert env[k * beat: k * beat + 400].max() > 0.2, f"clic {k} absent"
assert env[beat + 3000: 2 * beat - 100].max() < 1e-6, "silence entre les clics"
print("9. décompte : 4 clics sur 1 mesure puis prise calée : OK")

# ---- 10. compensation de latence (prise) ----
e = new_engine(bars=1); e.set_latency_comp_ms(10)
lat = int(44100 * 10 / 1000)
e.record(); run(e, 20); s0 = e._grid_origin
run(e, 88200 + 3000)
assert e.state == "playing"
tr = e._tracks[0][:, 0]
assert tr[0] == s0 + lat and tr[88200 - lat - 1] == s0 + 88200 - 1
assert np.all(tr[88200 - lat:] == s0 + 88200 + np.arange(lat)), "queue de prise rattrapée"
print("10. latence : la prise est recalée, la queue arrive après le début de lecture : OK")

# ---- 11. compensation de latence (overdub) ----
e = new_engine(bars=1, quantize=False); e.set_latency_comp_ms(10)
e.record(); run(e, 88200 + 100)
L = e._loop_len; p0 = e._play_pos
e.overdub(); c0 = e._clock; pos0 = e._play_pos
run(e, L + lat + 3000)
assert e.state == "playing" and e.track_count == 2
tr = e._tracks[1][:, 0]
for k in (0, 1, 5000, L - 1):
    assert tr[(pos0 + k) % L] == c0 + lat + k, (k, tr[(pos0 + k) % L], c0 + lat + k)
print("11. latence en overdub : alignement et queue exacts : OK")

# ---- 12. démarrage de la batterie sur la mesure, avec avance ----
e = new_engine(quantize=True); e.set_click(True)
e.set_drum_lead_ms(10)
fired = []
e.drum_start_due.connect(lambda: fired.append(e._clock), Qt.DirectConnection)
run(e, 5000)
e.schedule_drum_start()
run(e, 100000)
assert len(fired) == 1
# émis dans le bloc qui contient (88200 - 441) ; l'horloge lue est celle du début du bloc
assert 88200 - 441 - B < fired[0] <= 88200 - 441, fired
print("12. départ de la batterie : calé sur la mesure moins l'avance MIDI : OK")

# ---- 13. départ de batterie sans repère : immédiat, ancre la grille ----
e = new_engine(quantize=True); e.set_drum_lead_ms(0)
fired.clear(); e.drum_start_due.connect(lambda: fired.append(e._clock), Qt.DirectConnection)
run(e, 3000); e.schedule_drum_start(); run(e, B * 2)
assert len(fired) == 1 and e._grid_origin == 3000
e.set_external_reference(True)
e.set_auto_bars(1)
run(e, 5000); e.record()
assert e.pending_action == "record", "batterie lancée par melos = repère de phase"
print("13. batterie sans repère : départ immédiat puis Rec calé dessus : OK")

# ---- 14. clic pendant la lecture : suit la grille de la boucle ----
e = new_engine(bars=2); e.set_click(True)
e.record(); run(e, 176400 + 10)
L = e._loop_len
run(e, L - 10)                             # jusqu'au bord de la boucle
e._tracks[0][:] = 0                       # piste coupée : on n'entend plus que le clic
assert e._play_pos == 0
out = run(e, L)
env = np.abs(out[:, 0]); hits = []
i = 0
while i < len(env):
    if env[i] > 0.05:
        hits.append(i); i += 3000
    else: i += 1
assert len(hits) == 8, len(hits)
step = L / 8
assert all(abs(h % round(step) ) < 40 or abs(h % round(step) - round(step)) < 40 for h in hits)
print("14. clic en lecture : 8 temps sur 2 mesures, calés sur la boucle : OK")

# ---- 15. stop / play calés sur la mesure ----
e = new_engine(quantize=True, bars=1); e.set_click(True)
e.record(); run(e, 95000)
assert e.state == "playing"
run(e, 10000); e.stop(); assert e.pending_action == "stop"
run(e, 90000); assert e.state == "stopped"
e.play(); assert e.pending_action == "play"
run(e, 100000); assert e.state == "playing"
print("15. Stop / Play attendent la mesure : OK")

# ---- 16. effacer annule tout ----
e.overdub(); e.clear(); assert e.pending_action == "" and e.state == "idle" and e.track_count == 0
print("16. clear remet tout à zéro : OK")

# ---- 17. clic : exactement un clic par temps, quelle que soit la taille des blocs ----
def run_odd(e, nsamples, sizes=(100, 256, 333, 77, 512, 1024, 191)):
    outs, done, k = [], 0, 0
    while done < nsamples:
        n = min(sizes[k % len(sizes)], nsamples - done); k += 1
        ind = np.zeros((n, 2), dtype="float32"); out = np.zeros((n, 2), dtype="float32")
        e._callback(ind, out, n, None, None); outs.append(out.copy()); done += n
    return np.concatenate(outs)

def onsets(sig):
    env = np.abs(sig[:, 0])
    win = env[: len(env) // 64 * 64].reshape(-1, 64).max(axis=1) > 0.05
    return [i * 64 for i in range(1, len(win)) if win[i] and not win[i - 1]] + ([0] if win[0] else [])

for bpm, beats, unit, bars in ((120, 4, 4, 4), (137, 6, 8, 3), (93, 3, 4, 4), (101, 12, 8, 2)):
    e = new_engine(bpm, beats, unit); e.set_click(True)
    sig = run_odd(e, round(bars * bar_samples(bpm, beats, unit)) - 400)
    n = len(onsets(sig))
    assert n == bars * beats, (bpm, beats, unit, n, bars * beats)
print("17. clic : un seul clic par temps (blocs de tailles quelconques, 4/4, 6/8, 3/4, 12/8) : OK")

# ---- 18. décompte calé sur la phase de la batterie ----
e = new_engine(120, 4, 4, quantize=True)
run(e, 5000)
e.schedule_drum_start(); run(e, 10)                 # sans repère : départ immédiat, grille ancrée ici
drum_origin = e._grid_origin
e.set_external_reference(True)                      # la batterie tourne
e.set_click(True)                                   # activer le clic ne doit pas déplacer la phase
e.set_grid(120, 4, 4)
assert e._grid_origin == drum_origin
e.set_click(False)                                  # seule la batterie donne le repère : le décompte est le seul son du clic
run(e, 30000)                                       # on est au milieu d'une mesure
t_press = e._clock
e.record_with_count_in()
assert e.state == "counting_in"
count_start = e._count_start
assert (count_start - drum_origin) % 88200 == 0 and 0 <= count_start - t_press < 88200   # début de la mesure suivante
snap = e.snapshot(); assert snap["beat"] == -1, "décompte pas encore commencé : aucune pastille allumée"
out = run(e, 3 * 88200)
assert e.state == "recording", e.state
start = e._grid_origin
assert (start - drum_origin) % 88200 == 0, (start - drum_origin) % 88200      # pile sur un temps 1 de la batterie
assert start == count_start + 88200, (start, count_start)                    # décompte = UNE mesure entière
assert 88200 < start - t_press <= 2 * 88200, start - t_press
# ticks : exactement 4, aucun avant le début du décompte (la mesure en cours reste silencieuse)
nz = np.abs(out[:, 0]) > 1e-6
first_tick_idx = np.argmax(nz)
assert abs(first_tick_idx - (count_start - t_press)) < B, (first_tick_idx, count_start - t_press)
ticks_at = [i for i in np.flatnonzero(nz & ~np.roll(nz, 1)) if i < start - t_press]
merged = [i for k, i in enumerate(ticks_at) if k == 0 or i - ticks_at[k - 1] > 5000]
assert len(merged) == 4, merged
print("18. décompte avec batterie : attend la mesure suivante, 4 ticks, enregistrement sur un temps 1 de la batterie : OK")

# sans batterie ni clic : le décompte repart de l'appui, une mesure pleine
e = new_engine(120, 4, 4, quantize=True); run(e, 7777)
e.record_with_count_in(); run(e, 88200 + 100)
assert e.state == "recording" and e._grid_origin == 7777 + 88200
print("18b. décompte sans repère : une mesure pleine depuis l'appui : OK")

# ---- 19. batterie lancée pendant le décompte ou la prise : calée sur la grille de la prise ----
for quant in (True, False):
    e = new_engine(120, 4, 4, quantize=quant); e.set_drum_lead_ms(20)       # 882 éch.
    due = []; e.drum_start_due.connect(lambda: due.append(e._clock), Qt.DirectConnection)
    run(e, 7777)
    e.record_with_count_in(); run(e, 30000)
    origin = e._grid_origin
    e.schedule_drum_start()
    assert e._grid_origin == origin, "la grille du décompte ne doit pas bouger (pas de retour en arrière)"
    assert e._drum_hook == origin + 88200 - 882, (e._drum_hook, origin)
    run(e, 2 * 88200)
    assert len(due) == 1 and abs(due[0] - (origin + 88200 - 882)) < B, due       # à un bloc près
    assert e.state == "recording" and e._grid_origin == origin + 88200
print("19. batterie lancée pendant le décompte : au temps 1 de l'enregistrement, grille intacte : OK")

e = new_engine(120, 4, 4); e.set_drum_lead_ms(20)
due = []; e.drum_start_due.connect(lambda: due.append(e._clock), Qt.DirectConnection)
run(e, 5000); e.record(); run(e, 40000)
origin = e._grid_origin
e.schedule_drum_start()
assert e._grid_origin == origin and e._drum_hook == origin + 88200 - 882
run(e, 60000)
assert len(due) == 1 and abs(due[0] - (origin + 88200 - 882)) < B
print("19b. batterie lancée pendant l'enregistrement : à la mesure suivante de la prise : OK")

# ---- 20. métronome lancé pendant le décompte / la prise : la grille ne bouge pas, le clic y est calé ----
e = new_engine(120, 4, 4, quantize=True)
run(e, 7777); e.record_with_count_in(); run(e, 30000)
origin = e._grid_origin
e.set_click(True)
assert e._grid_origin == origin, "le décompte ne repart pas"
run(e, 88200)
assert e.state == "recording" and e._grid_origin == origin + 88200
print("20. métronome activé pendant le décompte : le décompte continue, l'enregistrement part à l'heure : OK")

e = new_engine(120, 4, 4)
run(e, 5000); e.record(); run(e, 33333)
origin = e._grid_origin
e.set_click(True)
assert e._grid_origin == origin
start = e._clock
sig = run_odd(e, 88200)
ons = onsets(sig)
assert len(ons) == 4, ons
# les clics tombent sur les temps de la prise : origine + k * 22050
for o in ons:
    off = (start + o - origin) % 22050
    assert off < 64 or 22050 - off < 64, (o, off)
print("20b. métronome activé pendant la prise : clics sur les temps de la prise : OK")

print("\nMOTEUR OK")
import sounddevice as _sd
_sd._initialized = 0