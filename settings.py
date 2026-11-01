"""
Persistance simple d'un fichier JSON unique (app_settings.json, à côté de ce
module) pour les réglages qui doivent survivre au redémarrage : preset
courant, réglages batterie/EQ, mode du tuner, entrées/sortie + volume/
répétitions/passes d'overdub/décompte de la loop station, séquence active
+ raccourcis clavier.

Neutre par rapport aux autres modules : pas de dépendance à AmpState ni à
LoopEngine ici, chaque module lit/écrit juste sa propre section pour
préserver leur indépendance (la loop station reste 100% logicielle et ne
connaît rien du MIDI, cf audio/loop_engine.py).
"""

import json
import os
from typing import Any

from paths import SETTINGS_FILE

_DEFAULTS: dict[str, Any] = {
    "current_preset": 0,
    "drum": {
        "enabled": False,
        "style": 0,
        "level": 0,
        "bass": 0,
        "middle": 0,
        "treble": 0,
        "favorites": [],   # styles favoris (CC brut), cf ui/drum_panel.py
    },
    "tuner": {
        "mode": 0,           # 0=chromatique, 1=guitare compensée, 2=guitare standard, 3=basse
        "requested": False,  # état demandé par l'utilisateur, pas une confirmation matérielle
        "ref_hz": 440,       # référence du La (module Tuner, engrenage)
        "sound": True,       # petit son quand une corde est accordée
        "tuning": "Standard",
        "cent_zero": None,   # valeur brute du CC 72 pour « 0 cent » (None : ancien fichier de calibration, sinon 52)
        "cent_scale": 1.0,   # cents réels par unité du CC 72
        "cent_zero_notes": {},   # zéro propre à chaque note (classe de hauteur 0-11 -> valeur brute du CC 72)
        "note_shift": 0,     # correction de la note du CC 12, en demi-tons
    },
    "loop": {
        "input_device_name": None,
        "output_device_name": None,
        "volume": 1.0,
        "repeat_target": 0,       # 0 = infini
        "overdub_passes_target": 1,  # 0 = illimité (arrêt manuel)
        "count_in_enabled": False,
        "count_in_bpm": 100,
        # Le volume Windows de la sortie du Mighty s'ajoute au curseur de l'appli : on le remet à
        # 100 % au démarrage du flux (cf audio/system_volume.py). Mettre False pour ne pas y toucher.
        "force_system_volume": True,
        "system_volume_keyword": "NUX NMP-03",
        "blocksize": 256,         # taille du tampon audio en échantillons (page Réglages)
        "host_api": "auto",       # API audio Windows : "auto" (WASAPI de préférence), ou le nom exact (MME, ASIO...)
        "wasapi_exclusive": False,  # WASAPI exclusif : latence minimale, mais la carte n'est plus partagée
    },
    # Port MIDI : "auto" cherche le Mighty tout seul ; "manual" impose les ports choisis (page Réglages)
    "midi": {
        "mode": "auto",
        "input_name": None,
        "output_name": None,
    },
    "ui": {
        "theme": "auto",      # "auto" (celui de Windows) | "light" | "dark"
    },
    # Page Partition (tablature Songsterr + vidéo YouTube)
    "tabs": {
        "url": "",            # dernier lien Songsterr chargé
        "track": 0,           # numéro de piste affichée (position dans la liste, batterie exclue)
        "video": "",          # identifiant YouTube choisi pour la synchro ("" = première disponible)
        "scale": 1.0,         # zoom de la partition
        "country": "FR",      # code pays : ne propose que les vidéos disponibles là
        "stem_map": {},       # association piste de la partition -> piste audio, par morceau : {songId: {partId: [pistes]}}
        "mode": "original",   # "original" (enregistrement YouTube) | "synth" (synthèse MIDI de la partition)
        "synth": {"metronome": False, "count_in": False, "loop": False},
        "soundfont": "auto",  # banque de sons de la synthèse : « auto » (la meilleure installée) ou un nom de fichier .sf2
        "synth_mix": {},      # solo / mute / volumes des pistes en synthèse, par morceau : {songId: {"solo": [partId], "mute": [...], "vol": {partId: 0-1.5}}}
    },
    # Tempo et quantification (partagés entre le looper et la batterie, cf state/transport_state.py)
    "transport": {
        "bpm": 100,           # noires par minute
        "beats": 4,           # signature : beats / unit (4/4, 6/8, 3/4...)
        "unit": 4,
        "bars": 0,            # auto-length : nombre de mesures de la 1re prise (0 = fin manuelle)
        "quantize": True,     # Rec / Overdub / Stop attendent la prochaine mesure
        "click": False,       # métronome audible
        "sync_drums": True,   # le démarrage de la batterie est calé sur la mesure + tempo envoyé à l'ampli
        "drum_latency_ms": 0,    # avance à donner à l'ordre MIDI de démarrage de la batterie
        "latency_comp_ms": 0,    # latence aller-retour audio à compenser sur les prises
    },
    "setlist": {
        "active_sequence_name": None,
        "enabled": True,      # si False, naviguer les étapes ne pilote plus le device
        "next_key": None,      # obsolète : migré vers "shortcuts" au lancement (cf shortcuts/manager.py)
        "previous_key": None,  # idem
    },
    # Agencement du Dashboard (cf ui/dashboard_interface.py) : état des docks (QMainWindow.saveState, base64)
    # et modules supprimés
    "dashboard": {
        "state": None,
        "hidden": [],
    },
    "shortcuts": {
        "mode": None,      # "off" | "window" | "global" ; None = ancien réglage, voir "enabled"
        "enabled": True,   # obsolète (avant les 3 modes) : True -> global, False -> off
        "bindings": {},    # {id d'action: touche}, ex {"loop_cycle": "f5"} — aucune par défaut
    },
}


def load_defaults() -> dict:
    """Copie profonde des réglages par défaut."""
    return json.loads(json.dumps(_DEFAULTS))


def load_settings() -> dict:
    data: dict = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            data = {}

    merged = json.loads(json.dumps(_DEFAULTS))  # copie profonde des défauts
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def save_settings(settings: dict):
    # Écriture atomique : un crash en plein milieu ne doit pas laisser un JSON tronqué
    # (qui ferait repartir l'appli sur les réglages par défaut).
    tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def update_settings(changes: dict):
    """Réécrit UNIQUEMENT les sections données, sur la version du fichier relue à l'instant.

    Plusieurs modules (AmpState, LoopPanel, SetlistPanel, ShortcutManager...) gardent
    leur propre copie des réglages. Réécrire une copie complète (save_settings) depuis
    l'un d'eux écrasait les changements des autres faits entre-temps (ex: changer de
    preset remettait le volume du looper à son ancienne valeur).
    """
    data = load_settings()
    data.update(changes)
    save_settings(data)