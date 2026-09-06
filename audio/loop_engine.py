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

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

SAMPLE_RATE = 44100
CHANNELS = 2
BLOCK_SIZE = 256

CLICK_FREQUENCY_HZ = 1000.0
CLICK_DURATION_S = 0.05
CLICK_DECAY = 30.0  # plus grand = clic plus court/sec


def _make_click(duration_s: float = CLICK_DURATION_S) -> np.ndarray:
    """Un clic de décompte synthétique (pas de fichier audio externe) :
    un court burst sinusoïdal avec décroissance exponentielle."""
    t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s), endpoint=False)
    envelope = np.exp(-CLICK_DECAY * t / duration_s)
    tone = (np.sin(2 * np.pi * CLICK_FREQUENCY_HZ * t) * envelope).astype("float32")
    return np.column_stack([tone, tone])


class LoopEngine(QObject):
    # "idle" | "counting_in" | "recording" | "playing" | "overdubbing" | "stopped"
    state_changed = Signal(str)
    loop_length_changed = Signal(float)  # secondes
    stream_error = Signal(str)
    tracks_changed = Signal()  # une piste a été ajoutée ou supprimée

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"

        self._tracks: list[np.ndarray] = []   # chaque piste : (n_samples, CHANNELS) float32
        self._loop_len: int = 0               # figé par la 1ère prise, 0 tant qu'aucune piste

        self._play_pos = 0
        self._record_chunks: list[np.ndarray] = []

        # Overdub : piste en cours de construction, séparée du mix existant
        self._overdub_buffer: np.ndarray | None = None
        self._overdub_passes_target: int | None = 1  # None = illimité (stop manuel)
        self._overdub_passes_done = 0

        # Décompte avant le tout premier enregistrement
        self._count_in_buffer: np.ndarray | None = None
        self._count_in_pos = 0

        self._repeats_target: int | None = None  # None = infini (lecture normale)
        self._repeats_done = 0

        self._volume = 1.0
        self._stream: sd.Stream | None = None

    # --- Cycle de vie du flux audio ---

    def start(self, input_device=None, output_device=None):
        self.stop_stream()
        try:
            self._stream = sd.Stream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                blocksize=BLOCK_SIZE,
                dtype="float32",
                device=(input_device, output_device),
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            self.stream_error.emit(str(exc))

    def stop_stream(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def track_count(self) -> int:
        return len(self._tracks)

    # --- Réglages ---

    def set_volume(self, volume: float):
        """0.0 à ~2.0 (100% = 1.0). N'affecte que la sortie audible."""
        self._volume = max(0.0, min(2.0, volume))

    def set_repeat_target(self, target: int):
        """0 (ou toute valeur <= 0) = boucle à l'infini."""
        self._repeats_target = target if target and target > 0 else None

    def set_overdub_passes_target(self, target: int):
        """Nombre de tours de boucle enregistrés d'affilée pendant un overdub
        avant arrêt automatique (0 ou moins = illimité, arrêt manuel)."""
        self._overdub_passes_target = target if target and target > 0 else None

    # --- Enregistrement de la première prise (avec décompte optionnel) ---

    def record(self):
        """Démarre l'enregistrement du premier tour, sans décompte."""
        self._record_chunks = []
        self._set_state("recording")

    def record_with_count_in(self, bpm: int, beats: int = 4):
        """Démarre un décompte audio (`beats` clics à `bpm`) avant de lancer
        l'enregistrement automatiquement. Uniquement pour la 1ère prise : les
        overdubs suivants ont déjà la boucle existante comme repère de tempo.
        """
        beat_samples = max(1, int(SAMPLE_RATE * 60.0 / max(1, bpm)))
        click = _make_click()
        buf = np.zeros((beat_samples * beats, CHANNELS), dtype="float32")
        for i in range(beats):
            start = i * beat_samples
            end = min(start + len(click), len(buf))
            buf[start:end] = click[: end - start]
        self._count_in_buffer = buf
        self._count_in_pos = 0
        self._set_state("counting_in")

    def stop_record(self):
        """Termine le premier tour : fige la longueur de la boucle (1ère
        piste) et passe en lecture."""
        if self._record_chunks:
            track = np.concatenate(self._record_chunks, axis=0)
            self._record_chunks = []
            self._tracks = [track]
            self._loop_len = len(track)
            self._play_pos = 0
            self._repeats_done = 0
            self.loop_length_changed.emit(self._loop_len / SAMPLE_RATE)
            self.tracks_changed.emit()
        self._set_state("playing" if self._tracks else "idle")

    def play(self):
        """Relance la lecture depuis le début (ex: après arrêt sur nombre de
        répétitions atteint)."""
        if self._tracks:
            self._play_pos = 0
            self._repeats_done = 0
            self._set_state("playing")

    # --- Overdub : construit une piste séparée, ajoutée à la fin ---

    def overdub(self):
        if not self._tracks:
            return
        self._overdub_buffer = np.zeros((self._loop_len, CHANNELS), dtype="float32")
        self._overdub_passes_done = 0
        self._set_state("overdubbing")

    def stop_overdub(self):
        """Arrêt manuel : on garde ce qui a été capturé jusqu'ici comme
        nouvelle piste, même si le nombre de passes cible n'est pas atteint."""
        self._finish_overdub()

    def _finish_overdub(self):
        if self._overdub_buffer is not None:
            self._tracks.append(self._overdub_buffer)
            self._overdub_buffer = None
            self.tracks_changed.emit()
        self._set_state("playing")

    def delete_track(self, index: int):
        """Supprime une piste individuellement. Si c'était la dernière,
        repasse tout à zéro (comme clear())."""
        if 0 <= index < len(self._tracks):
            del self._tracks[index]
            if not self._tracks:
                self.clear()
            else:
                self._play_pos = min(self._play_pos, self._loop_len - 1)
                self.tracks_changed.emit()

    def clear(self):
        self._tracks = []
        self._loop_len = 0
        self._play_pos = 0
        self._repeats_done = 0
        self._overdub_buffer = None
        self._set_state("idle")
        self.tracks_changed.emit()

    def _set_state(self, state: str):
        self._state = state
        self.state_changed.emit(state)

    # --- Callback audio (thread temps réel PortAudio) ---

    def _callback(self, indata, outdata, frames, time_info, status):
        if status:
            print(status)
        try:
            self._process(indata, outdata, frames)
        except Exception as exc:
            # Une exception ici arrêterait sinon le flux silencieusement.
            outdata[:] = 0
            self.stream_error.emit(f"erreur dans le traitement audio : {exc}")

    def _process(self, indata, outdata, frames):
        state = self._state  # capturé une fois : cohérent tout le long du bloc

        if state == "counting_in":
            self._process_count_in(outdata, frames)
            return

        if state == "recording":
            self._record_chunks.append(indata.copy())
            outdata[:] = 0
            return

        if state not in ("playing", "overdubbing") or not self._tracks:
            outdata[:] = 0
            return

        n = self._loop_len
        pos = self._play_pos
        end = pos + frames
        wrapped = end >= n  # >= : une boucle qui se termine pile compte comme un tour

        mix = self._read_mix(pos, end, n, frames, wrapped)
        outdata[:] = mix * self._volume

        if state == "overdubbing":
            self._write_overdub(indata, pos, end, n, wrapped)

        self._play_pos = end % n

        if wrapped:
            self._repeats_done += 1
            if state == "overdubbing":
                self._overdub_passes_done += 1
                if (
                    self._overdub_passes_target is not None
                    and self._overdub_passes_done >= self._overdub_passes_target
                ):
                    self._finish_overdub()
                    return  # état déjà changé, pas la peine de vérifier repeats en plus
            if self._repeats_target is not None and self._repeats_done >= self._repeats_target:
                self._set_state("stopped")

    def _process_count_in(self, outdata, frames):
        buf = self._count_in_buffer
        pos = self._count_in_pos
        end = pos + frames
        if end <= len(buf):
            outdata[:] = buf[pos:end]
            self._count_in_pos = end
        else:
            remaining = len(buf) - pos
            outdata[:remaining] = buf[pos:]
            outdata[remaining:] = 0
            self._count_in_pos = len(buf)

        if self._count_in_pos >= len(buf):
            self._count_in_buffer = None
            self._record_chunks = []
            self._set_state("recording")

    def _read_mix(self, pos, end, n, frames, wrapped) -> np.ndarray:
        mix = np.zeros((frames, CHANNELS), dtype="float32")
        if not wrapped:
            for track in self._tracks:
                mix += track[pos:end]
        else:
            wrap_idx = end - n
            for track in self._tracks:
                mix[: n - pos] += track[pos:n]
                mix[n - pos:] += track[0:wrap_idx]
        return mix

    def _write_overdub(self, indata, pos, end, n, wrapped):
        if not wrapped:
            self._overdub_buffer[pos:end] += indata
        else:
            wrap_idx = end - n
            self._overdub_buffer[pos:n] += indata[: n - pos]
            self._overdub_buffer[0:wrap_idx] += indata[n - pos:]