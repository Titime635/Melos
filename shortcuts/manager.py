"""
Gestionnaire des raccourcis clavier globaux.

  - associe une touche (ou combinaison) à chaque action de actions.py ;
  - les enregistre auprès du backend clavier tant que l'interrupteur global
    est actif ; les désenregistre tous quand il est coupé ;
  - persiste le tout dans la section "shortcuts" de app_settings.json ;
  - émet `action_triggered(id)` quand une touche est actionnée.

Les callbacks du backend arrivent dans un thread qui n'est pas celui de Qt :
le manager ne touche jamais à l'UI, il émet seulement des Signal (reçus en
QueuedConnection côté UI/routeur, cf shortcuts/router.py).

Anti-répétition : maintenir une touche enfoncée fait répéter l'appui par
Windows. Chaque raccourci n'est donc "armé" qu'une fois relâché (on écoute
le relâchement de chacune des touches de la combinaison), et se désarme dès
qu'il a déclenché.

Actions "à maintenir" (Action.hold_seconds > 0, ex: effacer la boucle) :
l'appui lance un chrono, le relâchement l'annule ; l'action n'est émise que
si la touche reste enfoncée assez longtemps.

Aucune touche par défaut : l'utilisateur les choisit lui-même.
"""

import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Qt, Signal

from settings import load_settings, update_settings

from .actions import BY_ID, Action
from .backend import KeyboardBackend

CAPTURE_TIMEOUT_S = 15.0

# Modificateurs qui évitent qu'une touche se déclenche pendant qu'on tape du texte
_SAFE_MODIFIERS = {"ctrl", "alt", "alt gr", "windows", "left windows", "right windows", "cmd", "left ctrl",
                   "right ctrl", "left alt", "right alt"}
_TEXT_KEYS = {"space", "enter", "tab", "backspace", "delete", "esc"}


def normalize_key(key: str) -> str:
    """Forme canonique pour comparer deux touches : minuscules, sans espaces autour des '+'."""
    return "+".join(" ".join(part.lower().split()) for part in key.strip().split("+"))


def key_parts(key: str) -> list[str]:
    return [p for p in (part.strip() for part in key.split("+")) if p]


def risk_note(key: str) -> str | None:
    """Avertissement si la touche se déclenchera aussi pendant qu'on tape ailleurs."""
    parts = key_parts(normalize_key(key))
    if any(p in _SAFE_MODIFIERS for p in parts[:-1]):
        return None
    last = parts[-1] if parts else ""
    if len(last) == 1 or last in _TEXT_KEYS:
        return ("touche de saisie : elle se déclenchera aussi quand tu tapes dans une autre application "
                "(coupe l'interrupteur pour taper, ou préfère une touche F / une combinaison avec Ctrl/Alt)")
    return None


@dataclass
class _Registration:
    action: Action
    removers: list = field(default_factory=list)
    armed: bool = True
    timer: threading.Timer | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class ShortcutManager(QObject):
    action_triggered = Signal(str)             # id de l'action déclenchée
    bindings_changed = Signal()
    enabled_changed = Signal(bool)
    error = Signal(str)
    capture_result = Signal(str, str, str)     # (action, touche, erreur) — touche "" si annulé/échec
    _captured = Signal(int, str, str)          # interne : (jeton, touche, erreur), émis depuis le thread de capture

    def __init__(self, backend=None, hold_seconds_override: float | None = None, parent=None):
        super().__init__(parent)
        self._backend = backend if backend is not None else KeyboardBackend()
        self._hold_override = hold_seconds_override  # pour les tests uniquement
        self._regs: dict[str, _Registration] = {}
        self._capturing = False
        self._capture_action: str | None = None
        self._capture_token = 0
        self.last_error = ""

        cfg = load_settings()["shortcuts"]
        self._enabled: bool = bool(cfg["enabled"])
        self._bindings: dict[str, str] = {
            aid: normalize_key(key) for aid, key in cfg["bindings"].items() if aid in BY_ID and key
        }
        self._migrate_setlist_keys()
        self._captured.connect(self._on_captured, Qt.QueuedConnection)
        self._apply()

    # --- Lecture ---

    @property
    def available(self) -> bool:
        return self._backend.available

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def capturing(self) -> bool:
        return self._capturing

    def bindings(self) -> dict[str, str]:
        return dict(self._bindings)

    def binding_for(self, action_id: str) -> str | None:
        return self._bindings.get(action_id)

    # --- Modification ---

    def set_enabled(self, enabled: bool):
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self._persist()
        self._apply()
        self.enabled_changed.emit(enabled)

    def assign(self, action_id: str, key: str | None) -> str | None:
        """Associe `key` à l'action (ou retire l'association si `key` est vide).
        Renvoie un message d'erreur, ou None si c'est fait."""
        if action_id not in BY_ID:
            return "action inconnue"
        previous = self._bindings.get(action_id)
        if not key or not key.strip():
            self._bindings.pop(action_id, None)
        else:
            new = normalize_key(key)
            for other, other_key in self._bindings.items():
                if other != action_id and other_key == new:
                    return f"déjà utilisée par « {BY_ID[other].label} »"
            self._bindings[action_id] = new

        errors = self._apply()
        if action_id in errors:  # le backend refuse cette touche : on revient en arrière
            if previous is None:
                self._bindings.pop(action_id, None)
            else:
                self._bindings[action_id] = previous
            self._apply()
            return errors[action_id]

        self._persist()
        self.bindings_changed.emit()
        return None

    # --- Capture d'une touche ---

    def start_capture(self, action_id: str):
        """Attend la prochaine combinaison pressée et l'associe à `action_id`.
        Les raccourcis sont suspendus pendant la capture (sinon appuyer sur une
        touche déjà utilisée déclencherait son action). Résultat : capture_result."""
        if action_id not in BY_ID:
            return
        if not self._backend.available:
            self.capture_result.emit(action_id, "", "la librairie 'keyboard' n'est pas disponible")
            return
        self._capture_token += 1
        token = self._capture_token
        self._capturing = True
        self._capture_action = action_id
        self._apply()  # suspend

        def wait():
            try:
                key, err = self._backend.read_hotkey(), ""
            except Exception as exc:
                key, err = "", f"capture de touche impossible : {exc}"
            self._captured.emit(token, key or "", err)

        threading.Thread(target=wait, daemon=True).start()
        QTimer.singleShot(int(CAPTURE_TIMEOUT_S * 1000), lambda: self._capture_timeout(token))

    def cancel_capture(self, reason: str = ""):
        if not self._capturing:
            return
        action_id = self._capture_action
        self._capture_token += 1  # le résultat éventuel du thread en attente sera ignoré
        self._capturing = False
        self._capture_action = None
        self._apply()
        self.capture_result.emit(action_id, "", reason)

    def _capture_timeout(self, token: int):
        if self._capturing and token == self._capture_token:
            self.cancel_capture("délai dépassé, rien n'a été pressé")

    def _on_captured(self, token: int, key: str, error: str):
        if token != self._capture_token or not self._capturing:
            return  # capture annulée entre-temps
        action_id = self._capture_action
        self._capturing = False
        self._capture_action = None
        if error:
            self._apply()
            self.capture_result.emit(action_id, "", error)
        elif normalize_key(key) == "esc":
            self._apply()
            self.capture_result.emit(action_id, "", "")
        else:
            err = self.assign(action_id, key)  # ré-applique les raccourcis
            if err:
                self._apply()
            self.capture_result.emit(action_id, "" if err else normalize_key(key), err or "")

    # --- Enregistrement auprès du backend ---

    def _apply(self) -> dict[str, str]:
        """(Ré)enregistre tout. Renvoie {action: erreur} pour les touches refusées."""
        self._unregister_all()
        errors: dict[str, str] = {}
        if not self._enabled or self._capturing or not self._bindings:
            return errors
        if not self._backend.available:
            self._report("la librairie 'keyboard' n'est pas disponible sur ce système : raccourcis inactifs")
            return {aid: self.last_error for aid in self._bindings}
        for action_id, key in self._bindings.items():
            err = self._register(action_id, key)
            if err:
                errors[action_id] = err
                self._report(err)
        return errors

    def _register(self, action_id: str, key: str) -> str | None:
        reg = _Registration(BY_ID[action_id])
        try:
            reg.removers.append(self._backend.add_hotkey(key, lambda: self._on_press(reg)))
            for part in key_parts(key):
                reg.removers.append(self._backend.on_release(part, lambda: self._on_release(reg)))
        except Exception as exc:
            for remove in reg.removers:
                self._safely(remove)
            return f"impossible d'assigner « {key} » : {exc}"
        self._regs[action_id] = reg
        return None

    def _unregister_all(self):
        regs, self._regs = self._regs, {}
        for reg in regs.values():
            with reg.lock:
                if reg.timer is not None:
                    reg.timer.cancel()
                    reg.timer = None
            for remove in reg.removers:
                self._safely(remove)

    @staticmethod
    def _safely(fn):
        try:
            fn()
        except Exception:
            pass  # déjà retiré / backend en train de s'arrêter

    def _report(self, message: str):
        self.last_error = message
        self.error.emit(message)

    # --- Callbacks du backend (thread clavier, PAS le thread Qt) ---

    def _hold_for(self, action: Action) -> float:
        if action.hold_seconds > 0 and self._hold_override is not None:
            return self._hold_override
        return action.hold_seconds

    def _on_press(self, reg: _Registration):
        with reg.lock:
            if not reg.armed or not self._enabled:
                return  # répétition automatique d'une touche maintenue
            reg.armed = False
            hold = self._hold_for(reg.action)
            if hold > 0:
                reg.timer = threading.Timer(hold, self._fire, args=(reg,))
                reg.timer.daemon = True
                reg.timer.start()
                return
        self._fire(reg)

    def _on_release(self, reg: _Registration):
        with reg.lock:
            reg.armed = True
            if reg.timer is not None:
                reg.timer.cancel()
                reg.timer = None

    def _fire(self, reg: _Registration):
        with reg.lock:
            reg.timer = None
        if self._enabled and self._regs.get(reg.action.id) is reg:
            self.action_triggered.emit(reg.action.id)

    # --- Persistance ---

    def _persist(self):
        update_settings({"shortcuts": {"enabled": self._enabled, "bindings": dict(self._bindings)}})

    def _migrate_setlist_keys(self):
        """Anciennes touches Suivant/Précédent de la setlist (settings["setlist"]) -> raccourcis."""
        setlist = load_settings()["setlist"]
        moved = False
        for old_field, action_id in (("next_key", "nav_next"), ("previous_key", "nav_previous")):
            key = setlist.get(old_field)
            if key:
                if action_id not in self._bindings and normalize_key(key) not in self._bindings.values():
                    self._bindings[action_id] = normalize_key(key)
                moved = True
        if moved:
            update_settings({"setlist": {**setlist, "next_key": None, "previous_key": None}})
            self._persist()

    # --- Arrêt ---

    def shutdown(self):
        self._capture_token += 1
        self._capturing = False
        self._unregister_all()
