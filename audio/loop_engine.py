"""
Moteur de la loop station PC.

Pipeline par callback sounddevice (pas de lecture/écriture bloquante), comme
l'ancien looper de l'utilisateur. Module 100% logiciel, indépendant du MIDI :
le Plug Pro n'a pas de looper hardware (cf docs/protocol_notes.md), toute la
boucle vit ici, côté PC. Le monitoring de la guitare et de la batterie
d'accompagnement se fait déjà nativement sur le hardware (confirmé par
l'utilisateur), donc ce moteur ne fait QUE jouer/enregistrer la boucle —
pas de passthrough du signal live en plus, ça créerait un écho.

Le pipeline utilise volontairement des devices d'entrée et de sortie
distincts (pas un seul device combiné) : sur Windows notamment, PortAudio
liste souvent une même interface physique comme deux entrées séparées
(une pour l'entrée, une pour la sortie), même quand elle gère les deux.
Exiger un seul device supportant les deux à la fois ne trouvait donc rien.

Architecture "pistes" : contrairement à un simple buffer unique où chaque
overdub était fusionné définitivement, chaque prise (la boucle de base +
chaque overdub) est gardée comme une piste séparée dans `_tracks`, toutes de
la même longueur (figée par la toute première prise). La lecture fait la
somme des pistes actives à chaque bloc. Ça permet de supprimer une piste
individuellement sans toucher aux autres (cf ui/loop_panel.py).

Le callback audio tourne dans le thread temps réel de PortAudio, pas dans le
thread Qt : il ne doit toucher aucun widget. Il ne fait que lire/écrire des
tableaux numpy et changer l'état interne. Les Signal Qt sont émis depuis ce
callback ET depuis les méthodes appelées côté UI ; la connexion doit être en
Qt.QueuedConnection côté UI pour rester thread-safe (cf ui/loop_panel.py).
"""

import math
import threading

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

from . import portaudio_utils as pa

SAMPLE_RATE = 44100
CHANNELS = 2
BLOCK_SIZE = 256

CLICK_DURATION_S = 0.05
CLICK_DECAY = 30.0  # plus grand = clic plus court/sec
CLICK_GAIN = 0.45


def bar_samples(bpm: float, beats: int, unit: int) -> float:
    """Longueur d'une mesure en échantillons (flottant : pas d'arrondi qui dérive).
    `bpm` = noires par minute ; `unit` = valeur de la note qui bat (4 = noire, 8 = croche...).
    Ex : 4/4 à 120 -> 2 s ; 6/8 à 120 -> 1,5 s (6 croches = 3 noires)."""
    return SAMPLE_RATE * 60.0 / max(1.0, bpm) * beats * 4.0 / max(1, unit)


def _make_click(freq: float = 1000.0, duration_s: float = CLICK_DURATION_S) -> np.ndarray:
    """Un clic synthétique (pas de fichier audio externe) : un court burst
    sinusoïdal avec décroissance exponentielle."""
    t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s), endpoint=False)
    envelope = np.exp(-CLICK_DECAY * t / duration_s)
    tone = (np.sin(2 * np.pi * freq * t) * envelope * CLICK_GAIN).astype("float32")
    return np.column_stack([tone, tone])


class LoopEngine(QObject):
    # "idle" | "counting_in" | "recording" | "playing" | "overdubbing" | "stopped"
    state_changed = Signal(str)
    loop_length_changed = Signal(float)  # secondes
    stream_error = Signal(str)
    tracks_changed = Signal()  # une piste a été ajoutée ou supprimée
    # Action en attente de la prochaine mesure ("record", "overdub", "stop_overdub", "stop",
    # "play", "stop_record") ou "" quand plus rien n'attend — pour l'affichage.
    pending_changed = Signal(str)
    # Le démarrage de la batterie programmé par schedule_drum_start() est dû (thread audio).
    drum_start_due = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"

        self._tracks: list[np.ndarray] = []   # chaque piste : (n_samples, CHANNELS) float32
        self._loop_len: int = 0               # figé par la 1ère prise, 0 tant qu'aucune piste
        self._loop_bars: int = 0              # nombre de mesures de la boucle (grille de la boucle)
        self._loop_bar_f: float = 0.0         # longueur d'une mesure DANS la boucle (loop_len / loop_bars)
        self._meta: dict[int, list] = {}      # id(piste) -> [gain, muet] (réglages de mixage par piste)

        self._play_pos = 0
        self._record_chunks: list[np.ndarray] = []
        self._rec_acc = 0                     # échantillons capturés depuis le début de la prise
        self._rec_target: int | None = None   # longueur visée de la prise (auto-length / fin calée)

        # Overdub : piste en cours de construction, séparée du mix existant
        self._overdub_buffer: np.ndarray | None = None
        self._overdub_passes_target: int | None = 1  # None = illimité (stop manuel)
        self._od_remaining: int | None = None  # échantillons restant à capturer (None = illimité)
        self._od_skip = 0                      # arrivées à ignorer (compensation de latence)

        # Fin de prise sous compensation de latence : les derniers échantillons de la piste arrivent
        # après le début de la lecture ; on les y glisse au fil de l'eau.
        self._tail: dict | None = None

        # Décompte avant le tout premier enregistrement
        self._repeats_target: int | None = None  # None = infini (lecture normale)
        self._repeats_done = 0

        # --- Grille rythmique / quantification ---
        self._bpm = 100.0
        self._beats = 4
        self._unit = 4
        self._bar_f = bar_samples(self._bpm, self._beats, self._unit)
        self._quantize = False
        self._click_on = False
        self._auto_bars = 0                    # 0 = fin manuelle
        self._external_ref = False             # batterie lancée par melos : donne une phase à suivre
        self._latency_comp = 0                 # échantillons
        self._drum_lead = 0                    # échantillons d'avance pour l'envoi MIDI à la batterie
        self._clock = 0                        # horloge en échantillons depuis le démarrage du flux
        self._count_start = 0                 # échantillon où le décompte devient audible (1er des ticks)
        self._grid_origin = 0                  # échantillon du temps 1 de la grille libre
        self._pending: tuple[str, int] | None = None
        self._pending_label = ""
        self._drum_hook: int | None = None
        self._lock = threading.Lock()
        self._click_up = _make_click(1000.0)
        self._click_down = _make_click(1500.0)
        self._click_cur: np.ndarray | None = None
        self._click_idx = 0

        self._volume = 1.0
        self._stream: sd.Stream | None = None
        self.stream_info: dict = {}   # latences annoncées par PortAudio pour le flux ouvert
        self._running = False  # False dès qu'on lâche le flux : le callback encore en vol rend du silence

    # --- Cycle de vie du flux audio ---

    def start(self, input_device=None, output_device=None, blocksize: int = BLOCK_SIZE,
              low_latency: bool = True, wasapi: bool = False, exclusive: bool = False) -> bool:
        """Ouvre le flux. Renvoie False si l'ouverture a échoué (l'erreur est aussi émise par stream_error).

        `low_latency` : demande la latence « low » du périphérique (sans ça PortAudio prend « high », souvent
        100 à 200 ms par sens sous Windows). `wasapi` : les périphériques sont en WASAPI (conversion de fréquence
        automatique : le flux est à 44,1 kHz, la carte peut tourner à 48 kHz). `exclusive` : mode exclusif WASAPI."""
        self.stop_stream(wait=1.0)  # laisse l'ancien flux se fermer, mais sans jamais bloquer longtemps
        self.stream_info = {}
        attempts = [(low_latency, wasapi)]
        if low_latency:
            attempts.append((False, wasapi))   # repli : certains pilotes refusent la latence « low »
        last_error = ""
        for low, use_wasapi in attempts:
            stream = None
            try:
                extra = None
                if use_wasapi:
                    extra = sd.WasapiSettings(exclusive=exclusive, auto_convert=not exclusive)
                kwargs = dict(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=blocksize, dtype="float32",
                              device=(input_device, output_device), callback=self._callback,
                              latency="low" if low else None)
                if extra is not None:
                    kwargs["extra_settings"] = extra
                stream = sd.Stream(**kwargs)
                self._running = True
                stream.start()
                self._stream = stream
                pa.stream_opened()
                self.stream_info = self._read_stream_info(stream, low)
                return True
            except Exception as exc:
                last_error = str(exc)
                self._running = False
                self._stream = None
                if stream is not None:
                    pa.close_stream_async(stream)
        self.stream_error.emit(last_error)
        return False

    @staticmethod
    def _read_stream_info(stream, low: bool) -> dict:
        """Latences réellement obtenues (secondes), telles que PortAudio les annonce."""
        info = {"low_latency": low}
        try:
            lat = stream.latency
            info["input_latency"], info["output_latency"] = float(lat[0]), float(lat[1])
        except Exception:
            pass
        try:
            info["samplerate"] = float(stream.samplerate)
        except Exception:
            pass
        return info

    def stop_stream(self, wait: float = 0.0):
        """Lâche le flux sans jamais bloquer le thread appelant : sous Windows,
        fermer un flux dont l'interface audio vient d'être débranchée peut rester
        coincé indéfiniment (cf audio/portaudio_utils.py). `wait` > 0 : attend au
        plus ce temps que la fermeture se termine."""
        stream, self._stream = self._stream, None
        self._running = False
        if stream is None:
            return
        pa.stream_released()
        closer = pa.close_stream_async(stream)
        if wait > 0:
            closer.join(wait)

    @property
    def running(self) -> bool:
        """Un flux audio est ouvert (le moteur est partagé par les deux vues : la 2e ne le relance pas)."""
        return self._running and self._stream is not None

    @property
    def state(self) -> str:
        return self._state

    @property
    def track_count(self) -> int:
        return len(self._tracks)

    def track_gain(self, index: int) -> float:
        return self._meta.get(id(self._tracks[index]), (1.0, False))[0] if 0 <= index < len(self._tracks) else 1.0

    def track_muted(self, index: int) -> bool:
        return self._meta.get(id(self._tracks[index]), (1.0, False))[1] if 0 <= index < len(self._tracks) else False

    def set_track_gain(self, index: int, gain: float):
        """Volume d'une piste (1.0 = inchangé). Sans effet sur le contenu enregistré."""
        if 0 <= index < len(self._tracks):
            key = id(self._tracks[index])
            self._meta[key] = [max(0.0, min(2.0, gain)), self._meta.get(key, [1.0, False])[1]]

    def set_track_muted(self, index: int, muted: bool):
        if 0 <= index < len(self._tracks):
            key = id(self._tracks[index])
            self._meta[key] = [self._meta.get(key, [1.0, False])[0], bool(muted)]

    @property
    def grid_locked(self) -> bool:
        """Tempo et mesure ne peuvent plus changer : une boucle existe (ou se crée)."""
        return bool(self._tracks) or self._state in ("recording", "counting_in")

    def snapshot(self) -> dict:
        """Photo en lecture seule pour l'affichage (appelée depuis le thread Qt, ~30 fois/s) :
        position dans la boucle ou dans la mesure, temps courant, action en attente."""
        state, beats = self._state, self._beats
        snap = {"state": state, "pending": self._pending_label, "beats": beats, "bars": 0,
                "frac": 0.0, "beat": -1, "bar": 0, "active": False, "beat_frac": 0.0}
        try:
            if self._tracks and self._loop_len and state in ("playing", "overdubbing", "stopped"):
                pos, bar_f = self._play_pos, self._loop_bar_f
                exact = pos / (bar_f / beats)
                idx = int(exact)
                snap.update(bars=self._loop_bars, frac=pos / self._loop_len, beat=idx % beats, bar=idx // beats,
                            active=state != "stopped", beat_frac=exact - idx)
            elif state == "recording":
                acc, bar_f, target = self._rec_acc, self._bar_f, self._rec_target
                exact = acc / (bar_f / beats)
                idx = int(exact)
                bars = round(target / bar_f) if target else 0
                frac = acc / target if target else (acc % bar_f) / bar_f
                snap.update(bars=bars or 1, frac=min(1.0, frac), beat=idx % beats, bar=idx // beats, active=True,
                            beat_frac=exact - idx)
            elif self._click_on or self._external_ref or state == "counting_in":
                bar_f = self._bar_f
                rel = (self._clock - self._grid_origin) % bar_f
                exact = rel / (bar_f / beats)
                snap.update(bars=1, frac=rel / bar_f, beat=int(exact) % beats, active=True, beat_frac=exact - int(exact))
                if state == "counting_in" and self._clock < self._count_start:
                    snap["beat"] = -1   # on attend le début de la mesure : le décompte n'a pas commencé
        except (ZeroDivisionError, ValueError):
            pass
        return snap

    @property
    def loop_bars(self) -> int:
        return self._loop_bars

    @property
    def pending_action(self) -> str:
        return self._pending_label

    # --- Réglages ---

    def set_volume(self, volume: float):
        """0.0 à ~2.0 (100% = 1.0). N'affecte que la sortie audible."""
        self._volume = max(0.0, min(2.0, volume))

    def set_repeat_target(self, target: int):
        """0 (ou toute valeur <= 0) = boucle à l'infini."""
        self._repeats_target = target if target and target > 0 else None

    def set_overdub_passes_target(self, target: int):
        """Nombre de tours de boucle enregistrés pendant un overdub avant arrêt
        automatique (0 ou moins = illimité, arrêt manuel)."""
        self._overdub_passes_target = target if target and target > 0 else None

    def set_grid(self, bpm: float, beats: int, unit: int):
        """Tempo et signature (ex : 120, 4, 4 ou 90, 6, 8). N'affecte pas une boucle déjà
        enregistrée (elle garde sa propre grille, cf _loop_bar_f)."""
        new = (float(bpm), max(1, int(beats)), max(1, int(unit)))
        if new == (self._bpm, self._beats, self._unit):
            return  # rien ne change : on garde la phase de la grille
        self._bpm, self._beats, self._unit = new
        self._bar_f = bar_samples(self._bpm, self._beats, self._unit)
        if self._may_reanchor():
            self._grid_origin = self._clock

    def _may_reanchor(self) -> bool:
        """La grille libre ne peut être recalée que si rien ne s'y réfère : ni batterie lancée par melos, ni
        décompte ou prise en cours (leur grille est LE repère : la déplacer décalerait le son du clic
        par rapport aux voyants et à la prise), ni boucle en lecture (elle a sa propre grille)."""
        return not self._external_ref and self._state in ("idle", "stopped")

    def set_quantize(self, on: bool):
        self._quantize = bool(on)

    def set_click(self, on: bool):
        if on and not self._click_on and self._may_reanchor():
            self._grid_origin = self._clock  # le clic part du temps 1 maintenant
        self._click_on = bool(on)

    def set_auto_bars(self, bars: int):
        """Auto-length : la 1ère prise s'arrête pile après `bars` mesures (0 = manuel)."""
        self._auto_bars = max(0, int(bars))

    def set_latency_comp_ms(self, ms: float):
        self._latency_comp = max(0, int(SAMPLE_RATE * ms / 1000.0))

    def set_drum_lead_ms(self, ms: float):
        self._drum_lead = max(0, int(SAMPLE_RATE * ms / 1000.0))

    def set_external_reference(self, active: bool):
        """True quand la batterie tourne (lancée par melos) : elle sert de repère de phase,
        donc la quantification attend la mesure même sans clic."""
        self._external_ref = bool(active)

    @property
    def bar_seconds(self) -> float:
        return self._bar_f / SAMPLE_RATE

    # --- Quantification : positions de mesure ---

    def _has_phase_reference(self) -> bool:
        return self._click_on or self._external_ref or (bool(self._tracks) and self._state in ("playing", "overdubbing"))

    def _boundary_after(self, sample: int) -> int:
        """Premier début de mesure >= `sample` (sample >= self._clock). Pendant la lecture d'une
        boucle, les mesures sont celles DE LA BOUCLE (elles retombent pile sur ses bords) ;
        sinon c'est la grille libre ancrée sur _grid_origin."""
        if self._tracks and self._loop_len and self._state in ("playing", "overdubbing"):
            ahead = sample - self._clock
            pos = self._play_pos + ahead
            loops, rel = divmod(pos, self._loop_len)
            j = math.ceil(rel / self._loop_bar_f - 1e-9)
            target = min(self._loop_len, round(j * self._loop_bar_f))
            return sample + (loops * self._loop_len + target - pos)
        j = math.ceil((sample - self._grid_origin) / self._bar_f - 1e-9)
        return max(sample, self._grid_origin + round(j * self._bar_f))

    def _schedule(self, action: str, sample: int):
        with self._lock:
            self._pending = (action, sample)
        self._set_pending_label(action)

    def _set_pending_label(self, label: str):
        if label != self._pending_label:
            self._pending_label = label
            self.pending_changed.emit(label)

    def cancel_pending(self):
        """Annule l'action en attente de la mesure (et une fin de prise calée, qui redevient manuelle)."""
        with self._lock:
            self._pending = None
            if self._state == "recording" and self._pending_label == "stop_record":
                self._rec_target = round(self._auto_bars * self._bar_f) if self._auto_bars else None
        self._set_pending_label("")

    # --- Enregistrement de la première prise (avec décompte optionnel) ---

    def record(self):
        """Démarre l'enregistrement du premier tour. Calé sur la prochaine mesure s'il y a un
        repère (clic ou batterie) et que la quantification est active, sinon immédiat."""
        if self._quantize and self._running and self._has_phase_reference():
            self._schedule("record", self._boundary_after(self._clock))
        else:
            self._begin_record(self._clock)

    def record_with_count_in(self, bpm: float | None = None, beats: int | None = None):
        """Décompte d'UNE mesure entière (un tick par temps : 4 en 4/4) puis l'enregistrement démarre tout seul,
        pile sur la mesure suivante. Uniquement pour la 1ère prise. `bpm` : ancien paramètre, s'il est donné
        il remplace le tempo.

        Avec un repère de phase (clic déjà lancé ou batterie lancée par melos), le décompte suit CETTE
        grille : si une mesure est en cours, il attend son début (silence) et ne commence qu'à la mesure
        suivante, donc toujours calé sur la batterie. Sans repère, la grille part de l'appui."""
        if bpm is not None and abs(bpm - self._bpm) > 1e-9:
            self.set_grid(bpm, self._beats, self._unit)
        if self._running and (self._click_on or self._external_ref):
            count_start = self._boundary_after(self._clock)               # début de la prochaine mesure
            start = self._boundary_after(count_start + round(self._bar_f * 0.5))   # + une mesure pile
        else:
            self._grid_origin = self._clock
            count_start = self._clock
            start = self._clock + round(self._bar_f)
        self._count_start = count_start
        self._set_state("counting_in")
        self._schedule("record", start)

    def _begin_record(self, at: int):
        with self._lock:
            self._pending = None
            self._record_chunks = []
            self._rec_acc = 0
            self._grid_origin = at
            self._rec_target = round(self._auto_bars * self._bar_f) if self._auto_bars else None
        self._set_pending_label("")
        self._set_state("recording")

    def stop_record(self):
        """Termine le premier tour : fige la longueur de la boucle (1ère piste) et passe en
        lecture. Quantifié : la prise continue jusqu'à la fin de la mesure en cours."""
        if self._quantize and self._running and self._state == "recording":
            k = max(1, math.ceil(self._rec_acc / self._bar_f - 1e-9))
            with self._lock:
                self._rec_target = max(self._rec_acc, round(k * self._bar_f))
            self._set_pending_label("stop_record")
            return
        self._finalize_record(None)

    def _finalize_record(self, length: int | None):
        chunks, self._record_chunks = self._record_chunks, []
        self._rec_target = None
        if chunks:
            raw = np.concatenate(chunks, axis=0)
            if length is not None:
                raw = raw[:length]
                if len(raw) < length:  # prise écourtée (flux interrompu) : complétée de silence
                    raw = np.concatenate([raw, np.zeros((length - len(raw), CHANNELS), dtype="float32")])
            n = len(raw)
            lat = min(self._latency_comp, max(0, n - 1))
            if lat:
                # Les `lat` premiers échantillons captés sont du jeu d'AVANT la prise (latence aller-retour) ;
                # les `lat` derniers de la boucle n'arriveront qu'après le début de la lecture.
                track = np.zeros_like(raw)
                track[: n - lat] = raw[lat:]
                self._tail = {"track": track, "dest": n - lat, "remaining": lat}
            else:
                track = raw
                self._tail = None
            self._tracks = [track]
            self._meta = {}
            self._loop_len = n
            self._loop_bars = max(1, round(n / self._bar_f))
            self._loop_bar_f = n / self._loop_bars
            self._play_pos = 0
            self._repeats_done = 0
            self.loop_length_changed.emit(self._loop_len / SAMPLE_RATE)
            self.tracks_changed.emit()
        self._set_pending_label("")
        self._set_state("playing" if self._tracks else "idle")

    def play(self):
        """Relance la lecture depuis le début (ex: après arrêt sur nombre de
        répétitions atteint). Quantifié : au début de la prochaine mesure."""
        if not self._tracks:
            return
        if self._quantize and self._running and self._has_phase_reference():
            self._schedule("play", self._boundary_after(self._clock))
        else:
            self._do_play()

    def _do_play(self):
        self._play_pos = 0
        self._repeats_done = 0
        self._set_state("playing")

    def stop(self):
        """Arrête la lecture (état "stopped") ; `play()` repart du début.
        Pendant un overdub, la prise en cours est gardée comme nouvelle piste."""
        if self._quantize and self._running and self._state in ("playing", "overdubbing"):
            action = "stop_overdub" if self._state == "overdubbing" else "stop"
            self._schedule(action, self._boundary_after(self._clock))
            return
        if self._state == "overdubbing":
            self._finish_overdub()
        if self._state == "playing":
            self._set_state("stopped")

    # --- Overdub : construit une piste séparée, ajoutée à la fin ---

    def overdub(self):
        if not self._tracks:
            return
        if self._quantize and self._running:
            self._schedule("overdub", self._boundary_after(self._clock))
        else:
            self._begin_overdub()

    def _begin_overdub(self):
        with self._lock:
            self._pending = None
            self._overdub_buffer = np.zeros((self._loop_len, CHANNELS), dtype="float32")
            passes = self._overdub_passes_target
            self._od_skip = min(self._latency_comp, self._loop_len - 1)
            # Durée exacte d'un nombre entier de tours (+ la latence à rattraper à la fin)
            self._od_remaining = None if passes is None else passes * self._loop_len + self._od_skip
        self._set_pending_label("")
        self._set_state("overdubbing")

    def stop_overdub(self):
        """Arrêt manuel : on garde ce qui a été capturé jusqu'ici comme
        nouvelle piste, même si le nombre de passes cible n'est pas atteint.
        Quantifié : à la fin de la mesure en cours."""
        if self._quantize and self._running and self._state == "overdubbing":
            self._schedule("stop_overdub", self._boundary_after(self._clock))
        else:
            self._finish_overdub()

    def _finish_overdub(self):
        buf, self._overdub_buffer = self._overdub_buffer, None
        self._od_remaining = None
        self._od_skip = 0
        if buf is not None:
            self._tracks.append(buf)
            self.tracks_changed.emit()
        self._set_pending_label("")
        self._set_state("playing")

    def delete_track(self, index: int):
        """Supprime une piste individuellement. Si c'était la dernière,
        repasse tout à zéro (comme clear())."""
        if 0 <= index < len(self._tracks):
            self._meta.pop(id(self._tracks[index]), None)
            del self._tracks[index]
            if not self._tracks:
                self.clear()
            else:
                self._play_pos = min(self._play_pos, self._loop_len - 1)
                self.tracks_changed.emit()

    def clear(self):
        with self._lock:
            self._pending = None
            self._tracks = []
            self._meta = {}
            self._loop_len = 0
            self._loop_bars = 0
            self._loop_bar_f = 0.0
            self._play_pos = 0
            self._repeats_done = 0
            self._overdub_buffer = None
            self._od_remaining = None
            self._rec_target = None
            self._tail = None
        self._set_pending_label("")
        self._set_state("idle")
        self.tracks_changed.emit()

    def abort_capture(self):
        """Annule une prise en cours quand le flux audio est perdu (interface
        débranchée) : la prise serait de toute façon incomplète. À appeler
        APRÈS stop_stream(), pour ne pas courir contre le callback audio. Les
        pistes déjà enregistrées sont conservées."""
        with self._lock:
            self._pending = None
            self._drum_hook = None
            self._rec_target = None
            self._tail = None
        self._set_pending_label("")
        if self._state in ("counting_in", "recording"):
            self._record_chunks = []
            self._set_state("idle")
        elif self._state == "overdubbing":
            self._overdub_buffer = None
            self._od_remaining = None
            self._set_state("playing")

    # --- Batterie : démarrage calé sur la mesure ---

    def schedule_drum_start(self):
        """Programme l'émission de `drum_start_due` au prochain début de mesure (avec l'avance
        réglée pour la latence MIDI de la batterie). Sans repère de phase, ou sans
        quantification : tout de suite, et la grille s'ancre sur ce départ.
        Pendant un décompte ou une prise, la grille de la prise EST le repère : la batterie attend sa
        prochaine mesure (même sans quantification) et la grille ne bouge pas."""
        lead = self._drum_lead
        if not self._running:
            self.drum_start_due.emit()
            return
        in_take = self._state in ("counting_in", "recording")
        if in_take or (self._quantize and self._has_phase_reference()):
            sample = self._boundary_after(self._clock + lead) - lead
        else:
            sample = self._clock
            if not self._tracks:
                self._grid_origin = self._clock + lead
        with self._lock:
            self._drum_hook = sample

    def cancel_drum_start(self):
        with self._lock:
            self._drum_hook = None

    def _set_state(self, state: str):
        self._state = state
        self.state_changed.emit(state)

    # --- Callback audio (thread temps réel PortAudio) ---

    def _callback(self, indata, outdata, frames, time_info, status):
        if not self._running:  # flux lâché mais callback encore en vol
            outdata[:] = 0
            return
        if status:
            print(status)
        try:
            self._process(indata, outdata, frames)
        except Exception as exc:
            # Une exception ici arrêterait sinon le flux silencieusement.
            outdata[:] = 0
            self.stream_error.emit(f"erreur dans le traitement audio : {exc}")

    def _process(self, indata, outdata, frames):
        """Le bloc est découpé en segments aux instants où quelque chose doit changer d'état
        (début de mesure demandé, fin de prise visée, bord de boucle) : les actions
        quantifiées tombent donc à l'échantillon près, pas au bloc près."""
        clock0 = self._clock
        off = 0
        guard = 0
        while off < frames:
            guard += 1
            if guard > 64:  # sécurité : ne jamais boucler indéfiniment dans le thread audio
                outdata[off:] = 0
                break
            at = clock0 + off
            self._fire_due(at)
            n = max(1, min(frames - off, self._samples_until_event(at)))
            self._segment(indata[off:off + n], outdata[off:off + n], n, at)
            off += n
        self._clock = clock0 + frames

    def _samples_until_event(self, at: int) -> int:
        limit = 1 << 30
        pending, hook = self._pending, self._drum_hook
        if pending is not None and pending[1] > at:
            limit = min(limit, pending[1] - at)
        if hook is not None and hook > at:
            limit = min(limit, hook - at)
        if self._state == "recording" and self._rec_target is not None:
            limit = min(limit, max(1, self._rec_target - self._rec_acc))
        if self._state == "overdubbing" and self._od_remaining is not None:
            limit = min(limit, max(1, self._od_remaining))
        if self._state in ("playing", "overdubbing") and self._tracks:
            limit = min(limit, max(1, self._loop_len - self._play_pos))
        return limit

    def _fire_due(self, at: int):
        if self._state == "recording" and self._rec_target is not None and self._rec_acc >= self._rec_target:
            self._finalize_record(self._rec_target)
        if self._state == "overdubbing" and self._od_remaining is not None and self._od_remaining <= 0:
            self._finish_overdub()
        with self._lock:
            pending = self._pending
            if pending is not None and pending[1] <= at:
                self._pending = None
            else:
                pending = None
            hook = self._drum_hook
            if hook is not None and hook <= at:
                self._drum_hook = None
            else:
                hook = None
        if pending is not None:
            self._execute(pending[0], at)
        if hook is not None:
            self.drum_start_due.emit()

    def _execute(self, action: str, at: int):
        if action == "record":
            if self._state in ("idle", "stopped", "counting_in"):
                self._begin_record(at)
        elif action == "overdub":
            if self._state == "playing" and self._tracks:
                self._begin_overdub()
        elif action == "stop_overdub":
            if self._state == "overdubbing":
                self._finish_overdub()
        elif action == "stop":
            if self._state == "playing":
                self._set_state("stopped")
        elif action == "play":
            if self._state == "stopped" and self._tracks:
                self._do_play()
        self._set_pending_label("")

    def _segment(self, indata, outdata, n, at):
        state = self._state  # capturé une fois : cohérent tout le long du segment
        start_pos = self._play_pos

        if state == "counting_in":
            outdata[:] = 0
        elif state == "recording":
            self._record_chunks.append(indata.copy())
            self._rec_acc += n
            outdata[:] = 0
        elif state in ("playing", "overdubbing") and self._tracks:
            pos = self._play_pos
            end = pos + n  # <= loop_len : un segment ne franchit jamais le bord de la boucle
            mix = np.zeros((n, CHANNELS), dtype="float32")
            for track in self._tracks:
                gain, muted = self._meta.get(id(track), (1.0, False))
                if muted:
                    continue
                mix += track[pos:end] if gain == 1.0 else track[pos:end] * gain
            outdata[:] = mix * self._volume

            if state == "overdubbing" and self._overdub_buffer is not None:
                self._write_overdub(indata, pos, n)
                if self._od_remaining is not None:
                    self._od_remaining -= n
            if self._tail is not None:
                self._feed_tail(indata, n)

            self._play_pos = end
            if end >= self._loop_len:
                self._play_pos = 0
                self._repeats_done += 1
                if self._repeats_target is not None and self._repeats_done >= self._repeats_target:
                    self._set_state("stopped")
        else:
            outdata[:] = 0

        self._mix_click(outdata, n, at, state, start_pos)

    def _write_overdub(self, indata, pos, n):
        """Écrit l'entrée dans la piste en construction, décalée de la latence aller-retour :
        ce qui arrive maintenant a été joué `latence` plus tôt."""
        skip = 0
        if self._od_skip and self._od_remaining is not None:
            done = (self._overdub_passes_target or 0) * self._loop_len + self._od_skip - self._od_remaining
            skip = max(0, min(n, self._od_skip - done))
        if skip >= n:
            return
        frames = indata[skip:]
        idx = (pos + skip - self._od_skip + np.arange(len(frames))) % self._loop_len
        self._overdub_buffer[idx] += frames

    def _feed_tail(self, indata, n):
        tail = self._tail
        track = tail["track"]
        if not any(track is t for t in self._tracks):
            self._tail = None
            return
        m = min(n, tail["remaining"])
        idx = (tail["dest"] + np.arange(m)) % len(track)
        track[idx] += indata[:m]
        tail["dest"] = (tail["dest"] + m) % len(track)
        tail["remaining"] -= m
        if tail["remaining"] <= 0:
            self._tail = None

    # --- Clic (métronome) ---

    def _click_active(self, state: str) -> bool:
        return self._click_on or state == "counting_in"

    def _mix_click(self, out, n, at, state, start_pos):
        if not self._click_active(state):
            self._click_cur = None
            return
        beats = self._beat_offsets(n, at, state, start_pos)
        if state == "counting_in" and not self._click_on:
            beats = [(off, down) for off, down in beats if at + off >= self._count_start]   # pas de tick avant le décompte
        cur, idx = self._click_cur, self._click_idx
        prev = 0
        for off, down in beats + [(n, None)]:
            if cur is not None and idx < len(cur) and off > prev:
                m = min(len(cur) - idx, off - prev)
                out[prev:prev + m] += cur[idx:idx + m]
                idx += m
            if down is not None:
                cur, idx = (self._click_down if down else self._click_up), 0
            prev = off
        self._click_cur, self._click_idx = cur, idx

    def _beat_offsets(self, n, at, state, start_pos) -> list[tuple[int, bool]]:
        """[(décalage dans le segment, temps fort ?)] des temps qui tombent dans [0, n)."""
        if state in ("playing", "overdubbing") and self._tracks:
            origin_pos, beat_f = start_pos, self._loop_bar_f / self._beats
        else:
            origin_pos, beat_f = at - self._grid_origin, self._bar_f / self._beats
        out = []
        # Position (entière) du temps j : toujours arrondie par excès, la même pour tous les segments,
        # donc un temps tombe dans UN segment et un seul (pas de temps perdu ni doublé).
        j = max(0, math.floor(origin_pos / beat_f) - 1) if origin_pos >= 0 else math.floor(origin_pos / beat_f) - 1
        while True:
            pos = math.ceil(j * beat_f - 1e-6)
            if pos >= origin_pos + n:
                break
            if pos >= origin_pos:
                out.append((pos - origin_pos, j % self._beats == 0))
            j += 1
        return out