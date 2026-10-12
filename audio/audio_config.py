"""
Choix des périphériques audio et de la taille du tampon pour la loop station.

Un seul AudioConfig est partagé par le moteur et les deux vues du looper (Dashboard / Classique) :
la page Réglages le pilote, les LoopPanel le lisent. Il possède la liste des entrées/sorties, la
sélection (mémorisée par nom dans la section "loop" de app_settings.json), la taille de tampon et
l'ouverture du flux (`start_engine`).
"""

import logging

import sounddevice as sd
from PySide6.QtCore import QObject, Signal

from audio import system_volume
from audio.loop_engine import BLOCK_SIZE, SAMPLE_RATE, LoopEngine
from settings import load_settings, update_settings

log = logging.getLogger("melos.audio")

BLOCKSIZES = (64, 128, 256, 512, 1024)

# Ordre de préférence des API audio de Windows : de la plus à la moins réactive
API_ORDER = ("WASAPI", "ASIO", "WDM-KS", "DirectSound", "MME")


def api_rank(name: str) -> int:
    for i, key in enumerate(API_ORDER):
        if key.lower() in name.lower():
            return i
    return len(API_ORDER)


def is_wasapi(name: str) -> bool:
    return "wasapi" in (name or "").lower()
AUTO = "auto"


def _hostapis() -> list[str]:
    try:
        return [h["name"] for h in sd.query_hostapis()]
    except Exception:
        return []


class AudioConfig(QObject):
    devices_changed = Signal()      # la liste des périphériques a été relue
    engine_restarted = Signal(bool)  # le flux a été (ré)ouvert : True si ça a marché

    def __init__(self, engine: LoopEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.input_devices: list[tuple[int, str]] = []    # ceux de l'API audio choisie : (index PortAudio, nom)
        self.output_devices: list[tuple[int, str]] = []
        self.api_names: list[str] = []                    # API audio proposant une entrée ET une sortie
        self.device_apis: dict[int, str] = {}             # index PortAudio -> API (pour le rapport de diagnostic)
        self._all: list[tuple[int, str, str, int, int]] = []   # (index, nom, API, entrées, sorties)
        self.error = ""
        self._load()
        self._query()
        self._filter()
        self._migrate_names()

    def _load(self):
        cfg = load_settings()["loop"]
        self._in_name = cfg.get("input_device_name")
        self._out_name = cfg.get("output_device_name")
        self._api_setting = cfg.get("host_api") or "auto"   # "auto" ou le nom exact d'une API
        self._api = ""                                       # API effectivement utilisée (cf _filter)
        self._exclusive = bool(cfg.get("wasapi_exclusive", False))
        bs = cfg.get("blocksize", BLOCK_SIZE)
        self._blocksize = bs if bs in BLOCKSIZES else BLOCK_SIZE

    def reload_from_settings(self):
        """Après un import / une réinitialisation : relit la sélection puis rouvre le flux."""
        self._load()
        self._query()
        self._filter()
        self._migrate_names()
        self.devices_changed.emit()
        self.start_engine()

    # --- Liste ---

    def _query(self):
        """Lit PortAudio : tous les périphériques avec leur API."""
        self.error = ""
        self._all = []
        try:
            try:
                apis = [a["name"] for a in sd.query_hostapis()]
            except Exception:
                apis = []
            for i, d in enumerate(sd.query_devices()):
                h = d.get("hostapi")
                api = apis[h] if isinstance(h, int) and 0 <= h < len(apis) else ""
                self._all.append((i, d["name"], api, d["max_input_channels"], d["max_output_channels"]))
        except Exception as exc:
            self.error = str(exc)
            log.warning("liste des périphériques audio impossible : %s", exc)

    def _filter(self):
        by_api: dict[str, tuple[list, list]] = {}
        for i, name, api, n_in, n_out in self._all:
            ins, outs = by_api.setdefault(api, ([], []))
            if n_in > 0:
                ins.append((i, name))
            if n_out > 0:
                outs.append((i, name))
        self.api_names = sorted((a for a, (ins, outs) in by_api.items() if ins and outs), key=api_rank)
        self.device_apis = {i: api for i, _, api, _, _ in self._all}
        if self._api_setting in self.api_names:
            self._api = self._api_setting
        else:
            self._api = self.api_names[0] if self.api_names else ""   # « auto » (ou API disparue) : la plus réactive
        self.input_devices, self.output_devices = by_api.get(self._api, ([], []))

    def refresh_devices(self):
        """Relit la liste de PortAudio (sans le réinitialiser : cf audio/portaudio_utils.refresh_portaudio)."""
        self._query()
        self._filter()
        self.devices_changed.emit()

    def _keyword(self) -> str:
        return (load_settings()["loop"].get("system_volume_keyword") or "").lower()

    def _names_for(self, api: str) -> tuple[str | None, str | None]:
        """Entrée / sortie à prendre en changeant d'API : celles de même nom, sinon (si on utilisait le Mighty)
        celles du Mighty, sinon les premières."""
        kw = self._keyword()
        def choose(names, old):
            if old in names:
                return old
            if kw and old and kw in old.lower():
                for n in names:
                    if kw in n.lower():
                        return n
            return names[0] if names else None
        ins = [n for _, n, a, n_in, _ in self._all if a == api and n_in > 0]
        outs = [n for _, n, a, _, n_out in self._all if a == api and n_out > 0]
        return choose(ins, self._in_name), choose(outs, self._out_name)

    def _migrate_names(self):
        """Au lancement (ou après un import) : si les périphériques mémorisés n'existent pas dans l'API utilisée
        (ex : ancien réglage en MME alors qu'on passe en WASAPI), prend les équivalents et les mémorise.
        Jamais appelé lors d'une simple actualisation : un appareil débranché doit rester mémorisé."""
        if not self.input_devices or not self.output_devices:
            return
        new_in, new_out = self._names_for(self._api)
        if (new_in, new_out) != (self._in_name, self._out_name):
            self._in_name, self._out_name = new_in, new_out
            cfg = load_settings()["loop"]
            cfg.update(input_device_name=new_in, output_device_name=new_out)
            update_settings({"loop": cfg})

    # --- Sélection ---

    @staticmethod
    def _pick(devices, remembered):
        """Index dans `devices` : le périphérique mémorisé s'il est là, sinon le premier."""
        for i, (_, name) in enumerate(devices):
            if name == remembered:
                return i
        return 0 if devices else -1

    @property
    def input_index(self) -> int:
        return self._pick(self.input_devices, self._in_name)

    @property
    def output_index(self) -> int:
        return self._pick(self.output_devices, self._out_name)

    @property
    def input_name(self) -> str:
        i = self.input_index
        return self.input_devices[i][1] if i >= 0 else ""

    @property
    def output_name(self) -> str:
        i = self.output_index
        return self.output_devices[i][1] if i >= 0 else ""

    @property
    def remembered_names(self) -> tuple[str | None, str | None]:
        return self._in_name, self._out_name

    @property
    def remembered_present(self) -> bool:
        """Les deux périphériques mémorisés sont dans la liste (sert à la restauration après débranchement)."""
        return (any(n == self._in_name for _, n in self.input_devices)
                and any(n == self._out_name for _, n in self.output_devices))

    @property
    def blocksize(self) -> int:
        return self._blocksize

    @property
    def effective_api(self) -> str:
        """API audio réellement utilisée (WASAPI, MME...)."""
        return self._api

    @property
    def api_setting(self) -> str:
        """Réglage : « auto » ou le nom d'une API."""
        return self._api_setting

    @property
    def is_wasapi(self) -> bool:
        return is_wasapi(self._api)

    @property
    def exclusive(self) -> bool:
        return self._exclusive

    def latency_ms(self, blocksize: int | None = None) -> float:
        return (blocksize or self._blocksize) * 1000.0 / SAMPLE_RATE

    def set_api(self, api: str):
        """`api` : « auto » ou le nom d'une API."""
        if api != self._api_setting and (api == "auto" or api in self.api_names):
            self._api_setting = api
            self._filter()
            self._in_name, self._out_name = self._names_for(self._api)
            self.devices_changed.emit()
            self._save_and_restart()

    def set_input(self, name: str):
        if name != self.input_name or name != self._in_name:
            self._in_name = name
            self._save_and_restart()

    def set_output(self, name: str):
        if name != self.output_name or name != self._out_name:
            self._out_name = name
            self._save_and_restart()

    def set_blocksize(self, blocksize: int):
        if blocksize in BLOCKSIZES and blocksize != self._blocksize:
            self._blocksize = blocksize
            self._save_and_restart()

    def set_exclusive(self, exclusive: bool):
        if exclusive != self._exclusive:
            self._exclusive = exclusive
            self._save_and_restart()

    def _save_and_restart(self):
        cfg = load_settings()["loop"]   # relu à l'instant : les LoopPanel écrivent aussi dans cette section
        cfg.update(input_device_name=self._in_name, output_device_name=self._out_name,
                   blocksize=self._blocksize, host_api=self._api_setting, wasapi_exclusive=self._exclusive)
        update_settings({"loop": cfg})
        self.start_engine()

    # --- Flux ---

    def start_engine(self) -> bool:
        if not self.input_devices or not self.output_devices:
            self.error = self.error or "aucune entrée et/ou sortie audio détectée"
            self.engine.stop_stream()
            self.engine.stream_error.emit(self.error)
            self.engine_restarted.emit(False)
            return False
        ok = self.engine.start(
            input_device=self.input_devices[self.input_index][0],
            output_device=self.output_devices[self.output_index][0],
            blocksize=self._blocksize,
            low_latency=True,
            wasapi=self.is_wasapi,
            exclusive=self._exclusive and self.is_wasapi,
        )
        if ok:
            lat = self.latency_info
            log.info("flux audio ouvert : API=%s, tampon=%d, latence annoncée entrée/sortie=%s ms",
                     self._api or "?", self._blocksize,
                     (round(lat["input_ms"], 1), round(lat["output_ms"], 1)) if lat else "?")
            self._apply_system_volume()
        self.engine_restarted.emit(ok)
        return ok

    def _apply_system_volume(self):
        """Le volume Windows de la sortie du Mighty s'ajoute au curseur de l'appli (cf
        audio/system_volume.py) : on le remet à 100 % pour que le curseur soit le seul réglage."""
        cfg = load_settings()["loop"]
        keyword = cfg.get("system_volume_keyword")
        if not cfg.get("force_system_volume", True) or not keyword:
            return
        if keyword.lower() not in self.output_name.lower():
            return  # sortie autre que le Mighty : on ne touche pas au volume Windows
        system_volume.apply_async(keyword)  # thread à part : les appels COM de Windows peuvent traîner

    # --- Latence annoncée ---

    @property
    def latency_info(self) -> dict:
        """{"input_ms", "output_ms", "total_ms", "api"} du flux ouvert ; vide si le flux est fermé ou muet."""
        info = self.engine.stream_info if self.engine.running else {}
        if "input_latency" not in info:
            return {}
        i, o = info["input_latency"] * 1000, info["output_latency"] * 1000
        return {"input_ms": i, "output_ms": o, "total_ms": i + o, "api": self.effective_api,
                "low_latency": info.get("low_latency", True)}