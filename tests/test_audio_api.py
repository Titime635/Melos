"""API audio (WASAPI / MME), mode exclusif, latence annoncée, repli si la latence « low » est refusée."""
import os, sys, time, tempfile, pathlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import settings
settings.SETTINGS_FILE = pathlib.Path(tempfile.mkdtemp()) / "s.json"
# ancien réglage : périphériques MME, aucune API mémorisée
settings.save_settings({**settings.load_settings(), "loop": {**settings.load_settings()["loop"],
    "input_device_name": "Microphone (2- NUX NMP-03)", "output_device_name": "Haut-parleurs (2- NUX NMP-03)"}})

import sounddevice as sd
def dev(name, api, i, o): return {"name": name, "hostapi": api, "max_input_channels": i, "max_output_channels": o}
DEVICES = [dev("Microphone (2- NUX NMP-03)", 0, 2, 0), dev("Haut-parleurs (2- NUX NMP-03)", 0, 0, 2),   # MME
           dev("Micro PC", 0, 2, 0),
           dev("Microphone (2- NUX NMP-03)", 1, 2, 0), dev("Haut-parleurs (2- NUX NMP-03)", 1, 0, 2),  # WASAPI
           dev("Micro PC", 1, 2, 0), dev("Haut-parleurs PC", 1, 0, 2)]
sd.query_devices = lambda: list(DEVICES)
sd.query_hostapis = lambda: ({"name": "MME"}, {"name": "Windows WASAPI"})
OPENED = []; REFUSE_LOW = [False]
class FakeStream:
    def __init__(self, **kw):
        if REFUSE_LOW[0] and kw.get("latency") == "low": raise RuntimeError("latence refusée")
        self.kw = kw; self.active = False; self.samplerate = 44100.0
        self.latency = (0.012, 0.010) if kw.get("latency") == "low" else (0.12, 0.14)
        OPENED.append(self)
    def start(self): self.active = True
    def stop(self): self.active = False
    def close(self): self.active = False
sd.Stream = FakeStream
class FakeWasapi:
    def __init__(self, exclusive=False, auto_convert=False, **kw): self.exclusive, self.auto_convert = exclusive, auto_convert
sd.WasapiSettings = FakeWasapi
sd._terminate = lambda: None; sd._initialize = lambda: None

from PySide6.QtWidgets import QApplication
app = QApplication([])
from audio.audio_config import AudioConfig
from audio.loop_engine import LoopEngine
from settings import load_settings

eng = LoopEngine(); cfg = AudioConfig(eng)
assert cfg.api_names == ["Windows WASAPI", "MME"], cfg.api_names
assert cfg.effective_api == "Windows WASAPI" and cfg.is_wasapi
assert cfg.start_engine()
s = OPENED[-1]
assert s.kw["latency"] == "low" and s.kw["extra_settings"].auto_convert and not s.kw["extra_settings"].exclusive
assert s.kw["device"] == (3, 4), s.kw["device"]                     # les équivalents NUX en WASAPI, pas « Micro PC »
li = cfg.latency_info
assert round(li["input_ms"]) == 12 and round(li["output_ms"]) == 10 and round(li["total_ms"]) == 22
print("a. auto -> WASAPI, périphériques NUX retrouvés, faible latence, latence annoncée lue : OK")

cfg.set_exclusive(True)
assert OPENED[-1].kw["extra_settings"].exclusive and not OPENED[-1].kw["extra_settings"].auto_convert
cfg.set_exclusive(False)
cfg.set_api("MME")
assert not cfg.is_wasapi and "extra_settings" not in OPENED[-1].kw or OPENED[-1].kw.get("extra_settings") is None
assert OPENED[-1].kw["device"] == (0, 1) and load_settings()["loop"]["host_api"] == "MME"
cfg.set_api("auto"); assert cfg.effective_api == "Windows WASAPI" and OPENED[-1].kw["device"] == (3, 4)
print("b. exclusif, bascule MME <-> WASAPI : périphériques repris, réglage mémorisé : OK")

REFUSE_LOW[0] = True
assert cfg.start_engine() and OPENED[-1].kw["latency"] is None and cfg.latency_info["low_latency"] is False
REFUSE_LOW[0] = False
print("c. latence « low » refusée par le pilote : repli sur la latence par défaut : OK")
print("\nAPI AUDIO OK")
import sounddevice as _sd; _sd._initialized = 0
