"""Traces de débogage dans la console (préfixe [melos])  -  mets MELOS_DEBUG=0 pour les couper."""

import os
import sys
import threading
import time

ENABLED = os.environ.get("MELOS_DEBUG", "1") != "0"
_T0 = time.monotonic()


def dbg(*parts):
    if not ENABLED:
        return
    msg = " ".join(str(p) for p in parts)
    sys.stderr.write(f"[melos {time.monotonic() - _T0:8.2f}s {threading.current_thread().name}] {msg}\n")
    sys.stderr.flush()
