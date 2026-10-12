"""
Ports MIDI "abandonnés" : on ne les ferme JAMAIS.

Sous Windows, fermer un port MIDI dont le device vient d'être débranché reste
coincé dans le pilote (midiInClose / midiOutClose), et python-rtmidi ne libère
pas le GIL pendant cet appel : TOUT le process se fige (fenêtre incluse), peu
importe le thread qui ferme. Le même appel part tout seul quand l'objet port est
ramassé par le ramasse-miettes (mido.Port.__del__ appelle close()) : c'est ce que
montrait melos_crash.log (listener.py / connection_monitor.py -> __del__ -> close).

On garde donc une référence au port mort pour toujours : il n'est jamais
détruit, donc jamais fermé. Windows rend les handles à la fin du process ; au
quit, main.py sort avec os._exit si des ports ont été abandonnés (sinon
l'interpréteur les détruirait à l'arrêt, avec le même blocage).
"""

import threading

_lock = threading.Lock()
_dead: list = []


def abandon(port) -> None:
    if port is None:
        return
    with _lock:
        _dead.append(port)


def has_abandoned() -> bool:
    return bool(_dead)
