"""
Garde-fous autour de PortAudio (sounddevice).

Sous Windows, Pa_StopStream / Pa_CloseStream (et donc Pa_Terminate) peuvent
BLOQUER indéfiniment quand l'interface audio est débranchée pendant qu'un flux
tourne. Appelés depuis le thread Qt, ils gèlent toute l'appli (arrêt forcé).
Tout ce qui touche au cycle de vie de PortAudio passe donc ici :

  - close_stream_async : stop()+close() dans un thread jetable, jamais attendu
    par l'UI (si l'appel reste coincé, seul ce thread est perdu) ;
  - refresh_portaudio  : réinitialisation de PortAudio (pour qu'il revoie les
    interfaces branchées après coup), à lancer depuis un thread de travail ;
    refusée s'il reste un flux ouvert ou une fermeture coincée.
"""

import threading
import time

import sounddevice as sd

_state_lock = threading.Lock()
_closers: list[threading.Thread] = []
_active_streams = 0

_refresh_lock = threading.Lock()
_last_refresh_done = 0.0


def stream_opened():
    global _active_streams
    with _state_lock:
        _active_streams += 1


def stream_released():
    global _active_streams
    with _state_lock:
        _active_streams = max(0, _active_streams - 1)


def active_stream_count() -> int:
    with _state_lock:
        return _active_streams


def close_stream_async(stream) -> threading.Thread:
    """Ferme `stream` dans un thread à part et rend la main immédiatement."""
    def work():
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    thread = threading.Thread(target=work, name="portaudio-close", daemon=True)
    with _state_lock:
        _closers.append(thread)
    thread.start()
    return thread


def closing_in_progress() -> bool:
    """True si une fermeture de flux n'est pas encore terminée (peut-être coincée)."""
    with _state_lock:
        _closers[:] = [t for t in _closers if t.is_alive()]
        return bool(_closers)


def wait_for_closes(timeout: float) -> bool:
    """Attend (au plus `timeout` s) la fin des fermetures. True si tout est fermé."""
    deadline = time.monotonic() + timeout
    while closing_in_progress():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def refresh_portaudio(requested_at: float, timeout: float = 3.0) -> str:
    """Réinitialise PortAudio. Renvoie "ok", "busy" (un flux est encore ouvert :
    la réinitialisation le tuerait) ou "stuck" (une fermeture est coincée).

    `requested_at` (time.monotonic() au moment de la demande) évite de
    réinitialiser deux fois quand plusieurs panneaux le demandent ensemble : la
    seconde réinitialisation tuerait le flux que le premier vient de relancer.
    À appeler depuis un thread de travail, jamais depuis le thread Qt.
    """
    global _last_refresh_done
    if not _refresh_lock.acquire(timeout=timeout):
        return "stuck"
    try:
        if _last_refresh_done >= requested_at:
            return "ok"
        if not wait_for_closes(timeout):
            return "stuck"
        if active_stream_count() > 0:
            return "busy"
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        _last_refresh_done = time.monotonic()
        return "ok"
    finally:
        _refresh_lock.release()
