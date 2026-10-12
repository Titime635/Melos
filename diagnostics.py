"""
Rapport de diagnostic collable dans un message : versions, ports MIDI, périphériques audio, réglages
utiles. Sans dépendance à l'UI : la page Réglages ne fait que le copier dans le presse-papiers.
"""

import platform
import sys
from importlib import metadata


def _version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except Exception:
        return "absent"


def build_report(audio=None, monitor=None, settings: dict | None = None) -> str:
    """`audio` : AudioConfig (ou None), `monitor` : ConnectionMonitor (ou None)."""
    lines = ["=== Rapport de diagnostic melos ===", ""]

    lines.append("[Système]")
    lines.append(f"OS : {platform.platform()}")
    lines.append(f"Python : {sys.version.split()[0]} ({platform.architecture()[0]})")
    lines.append("")

    lines.append("[Versions]")
    for pkg in ("PySide6", "PySide6-Fluent-Widgets", "mido", "python-rtmidi", "sounddevice", "numpy", "keyboard"):
        lines.append(f"{pkg} : {_version(pkg)}")
    try:
        import sounddevice as sd
        lines.append(f"PortAudio : {sd.get_portaudio_version()[1]}")
    except Exception as exc:
        lines.append(f"PortAudio : indisponible ({exc})")
    lines.append("")

    lines.append("[MIDI]")
    try:
        import mido
        inputs, outputs = list(mido.get_input_names()), list(mido.get_output_names())
        lines.append("Entrées : " + (", ".join(repr(n) for n in inputs) or "aucune"))
        lines.append("Sorties : " + (", ".join(repr(n) for n in outputs) or "aucune"))
    except Exception as exc:
        lines.append(f"Énumération impossible : {exc}")
    if monitor is not None:
        lines.append(f"Mode du port : {monitor.mode}")
        cur = monitor.current_ports
        lines.append("Connecté : " + (f"oui (entrée={cur[0]!r}, sortie={cur[1]!r})" if cur else "non"))
    lines.append("")

    lines.append("[Audio]")
    if audio is not None:
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                api = audio.device_apis.get(i, "?")
                lines.append(f"#{i} [{api}] {d['name']} (entrées {d['max_input_channels']}, "
                             f"sorties {d['max_output_channels']}, défaut {d.get('default_low_input_latency', 0) * 1000:.0f}"
                             f"/{d.get('default_low_output_latency', 0) * 1000:.0f} ms bas, "
                             f"{d.get('default_high_input_latency', 0) * 1000:.0f}"
                             f"/{d.get('default_high_output_latency', 0) * 1000:.0f} ms haut)")
        except Exception as exc:
            lines.append(f"Énumération impossible : {exc}")
        lines.append(f"Looper : entrée={audio.input_name!r}, sortie={audio.output_name!r}")
        lines.append(f"Tampon : {audio.blocksize} échantillons (≈ {audio.latency_ms():.1f} ms par bloc)")
        lines.append(f"API utilisée : {audio.effective_api or 'inconnue'} (réglage : {audio.api_setting}, "
                     f"exclusif : {audio.exclusive})")
        lines.append(f"Flux ouvert : {'oui' if audio.engine.running else 'non'}")
        lat = audio.latency_info
        if lat:
            lines.append(f"Latence annoncée : entrée {lat['input_ms']:.1f} ms, sortie {lat['output_ms']:.1f} ms, "
                         f"total {lat['total_ms']:.1f} ms (mode faible latence : {lat['low_latency']})")
    lines.append("")

    if settings is not None:
        lines.append("[Réglages]")
        lines.append(f"Thème : {settings.get('ui', {}).get('theme')}")
        lines.append(f"Raccourcis : {settings.get('shortcuts', {}).get('mode')}")
        t = settings.get("transport", {})
        lines.append(f"Compensation de latence : {t.get('latency_comp_ms')} ms")
    return "\n".join(lines)