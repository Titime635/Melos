"""
Volume Windows de l'interface audio du Mighty.

Le Mighty sert de carte son USB à la loop station : ce que joue le looper passe
donc par le volume Windows de cette sortie, EN PLUS du curseur de l'appli. La
batterie, elle, vit dans l'ampli et ne dépend que de son curseur : il fallait
monter le volume de Windows pour entendre la boucle. On remet donc ce volume à
100 % (et on retire le mute) pour que le curseur de l'appli soit le seul réglage ;
le niveau final se règle alors sur le bouton volume de l'ampli.

Windows uniquement, via la librairie optionnelle `pycaw` (pip install pycaw).
Sans elle, ou hors Windows, rien n'est modifié. Ne lève jamais d'exception.

`apply_async` lance le réglage dans un thread à part : les appels COM de Windows peuvent
traîner (ou se bloquer) quand une interface audio vient d'être branchée, et ils ne doivent
jamais geler l'UI. COM est initialisé dans ce thread-là, pas dans le thread Qt.
"""

import logging
import sys
import threading

log = logging.getLogger("melos.audio")


def set_output_volume_max(keyword: str) -> str:
    """Remet à 100 % (sans mute) les sorties dont le nom contient `keyword`. Renvoie un message d'état."""
    if sys.platform != "win32":
        return "ignoré (hors Windows)"
    try:
        from ctypes import POINTER, cast

        import comtypes
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except Exception:
        return "pycaw non installé (pip install pycaw) : volume Windows inchangé"

    try:
        comtypes.CoInitialize()
    except Exception:
        pass  # déjà initialisé dans ce thread
    try:
        done, errors = 0, []
        for device in AudioUtilities.GetAllDevices():
            name = getattr(device, "FriendlyName", "") or ""
            device_id = getattr(device, "id", "") or ""
            if keyword.lower() not in name.lower():
                continue
            if not device_id.startswith("{0.0.0"):  # sorties uniquement (les entrées : {0.0.1)
                continue
            try:
                volume = getattr(device, "EndpointVolume", None)
                if volume is None:  # anciennes versions de pycaw
                    interface = device._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMute(0, None)
                volume.SetMasterVolumeLevelScalar(1.0, None)
                done += 1
            except Exception as exc:  # p.ex. un périphérique désactivé qui porte le même nom
                errors.append(str(exc))
        if done:
            return f"volume Windows mis à 100 % sur {done} sortie(s)"
        return f"aucune sortie réglée ({'; '.join(errors)})" if errors else "aucune sortie correspondante"
    except Exception as exc:
        log.warning("réglage du volume Windows impossible : %s", exc)
        return f"réglage impossible : {exc}"
    finally:
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass


def apply_async(keyword: str) -> threading.Thread:
    """Comme set_output_volume_max, dans un thread jetable ; le résultat est écrit dans le journal."""
    def work():
        log.info("volume Windows : %s", set_output_volume_max(keyword))

    thread = threading.Thread(target=work, name="system-volume", daemon=True)
    thread.start()
    return thread
