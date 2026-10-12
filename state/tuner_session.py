"""
Session d'accordage, partagée par toutes les vues (Dashboard et Classique affichent la même chose et un seul
son est joué) :

- lit les messages du tuner de l'ampli (AmpState.tuner_note / tuner_cent), applique la calibration
  (zéro + échelle du CC 72), lisse l'écart et le compare à la corde visée (midi/tunings.py) ;
- corde choisie à la main (`selected`) ou, si aucune, détection automatique ;
- retient les cordes accordées (écart <= 3 cents tenu ~0,4 s) et joue un petit tintement une fois par corde.
"""

import math
import tempfile
import time
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from midi import protocol, tunings

SMOOTHING = 0.45          # poids de la nouvelle mesure dans la moyenne glissante
SIGNAL_TIMEOUT_S = 1.2    # sans message de l'ampli : plus de signal
HOLD_S = 0.6              # on garde la dernière note affichée un instant après la fin du signal
TUNED_HOLD_S = 0.4        # temps à rester dans la tolérance avant de valider la corde
UNTUNE_CENTS = 12.0       # une corde validée qui s'écarte de plus que ça est à refaire


def make_chime_wav(path: Path):
    """Petit tintement montant (deux notes), 16 bits mono."""
    rate = 44100
    frames = bytearray()
    total = int(rate * 0.5)
    samples = [0.0] * total
    for freq, start, length in ((987.8, 0.0, 0.25), (1318.5, 0.10, 0.40)):
        for i in range(int(length * rate)):
            t = i / rate
            env = min(1.0, t / 0.004) * math.exp(-t * 9.0)
            idx = int(start * rate) + i
            if idx < total:
                samples[idx] += 0.32 * env * (math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t))
    for s in samples:
        frames += int(max(-1.0, min(1.0, s)) * 32000).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(bytes(frames))


class TunerSession(QObject):
    updated = Signal()       # lecture, signal, sélection ou cordes accordées ont changé
    string_tuned = Signal(int)

    def __init__(self, state, clock=time.monotonic, parent=None):
        super().__init__(parent or state)
        self._state = state
        self._clock = clock
        self.selected: int | None = None        # corde choisie à la main (None = automatique)
        self.tuned: set[int] = set()
        self.reading: tunings.Reading | None = None
        self.signal = False
        self.play_chime = self._default_chime   # remplaçable (tests)
        self._effect = None
        self._cents = 0.0
        self._note = None
        self._pc = None
        self._last_msg = -1e9
        self._last_signal = -1e9
        self._in_tune_since: float | None = None
        self._was_requested = state.tuner_requested

        state.tuner_updated.connect(self._on_state)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.tick)
        self._timer.start()

    # --- Commandes de l'UI ---

    def select(self, index: int | None):
        """Cliquer une corde la vise ; recliquer la même revient en automatique."""
        self.selected = None if index == self.selected else index
        self._in_tune_since = None
        self._recompute()
        self.updated.emit()

    def reset(self):
        self.tuned.clear()
        self._in_tune_since = None
        self.reading = None
        self.signal = False
        self.updated.emit()

    @property
    def tuning(self) -> str:
        return self._state.tuner_tuning

    def set_tuning(self, name: str):
        if name not in tunings.TUNINGS or name == self._state.tuner_tuning:
            return
        self._state.set_tuner_options(tuning=name)
        self.selected = None
        self.reset()

    # --- Mesures de l'ampli ---

    def calibrated_cents(self) -> float:
        s = self._state
        pc = protocol.tuner_pitch_class(s.tuner_note, s.tuner_note_shift)
        zero = s.tuner_cent_zero_notes.get(pc, s.tuner_cent_zero)   # zéro propre à la note s'il a été calibré
        return (s.tuner_cent - zero) * s.tuner_cent_scale

    def _on_state(self):
        s = self._state
        if s.tuner_requested != self._was_requested:
            self._was_requested = s.tuner_requested
            self.reset()
            return
        if not s.tuner_requested:
            return
        now = self._clock()
        cents = self.calibrated_cents()
        if s.tuner_note != self._note:
            self._note = s.tuner_note
            self._cents = cents            # autre note : on repart de la mesure
        else:
            self._cents += SMOOTHING * (cents - self._cents)
        self._last_msg = self._last_signal = now
        self._recompute()
        self.updated.emit()

    def _recompute(self):
        if self._note is None or not self._state.tuner_requested:
            return
        pc = protocol.tuner_pitch_class(self._note, self._state.tuner_note_shift)
        continuing = self.reading is not None and self._pc == pc and self.signal
        self._pc = pc
        prefer = self.reading.string if continuing else None
        self.reading = tunings.analyze(pc, self._cents, self._state.tuner_tuning, self.selected,
                                       self.tuned, prefer)

    # --- Chronomètre : fin de signal, validation des cordes ---

    def tick(self):
        if not self._state.tuner_requested:
            return
        now = self._clock()
        had_signal = self.signal
        self.signal = (now - self._last_msg) < SIGNAL_TIMEOUT_S
        changed = had_signal != self.signal
        r = self.reading
        if self.signal and r is not None and r.string is not None and not r.fallback:
            idx = r.string
            if idx in self.tuned and abs(r.cents) > UNTUNE_CENTS:
                self.tuned.discard(idx); changed = True
            if r.in_tune and idx not in self.tuned:
                if self._in_tune_since is None:
                    self._in_tune_since = now
                elif now - self._in_tune_since >= TUNED_HOLD_S:
                    self.tuned.add(idx)
                    self._in_tune_since = None
                    changed = True
                    self.string_tuned.emit(idx)
                    if self._state.tuner_sound:
                        self.play_chime()
            elif not r.in_tune:
                self._in_tune_since = None
        else:
            self._in_tune_since = None
        if not self.signal and r is not None and now - self._last_signal > HOLD_S + SIGNAL_TIMEOUT_S:
            self.reading = None; changed = True
        if changed:
            self.updated.emit()

    # --- Son ---

    def _default_chime(self):
        try:
            if self._effect is None:
                from PySide6.QtMultimedia import QSoundEffect
                path = Path(tempfile.gettempdir()) / "melos_tuner_chime.wav"
                if not path.exists():
                    make_chime_wav(path)
                self._effect = QSoundEffect(self)
                self._effect.setSource(QUrl.fromLocalFile(str(path)))
                self._effect.setVolume(0.6)
            self._effect.play()
        except Exception:
            pass   # pas de sortie audio / module absent : l'accordage marche sans le son