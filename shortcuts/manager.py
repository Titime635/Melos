"""
Gestionnaire des raccourcis clavier.

  - associe une touche (ou combinaison) à chaque action de actions.py ;
  - 3 modes : "off" (rien n'est enregistré), "window" (les touches ne
    déclenchent l'action que si la fenêtre de l'appli est active) et "global"
    (même quand une autre fenêtre a le focus) ;
  - en mode off tout est désenregistré ;
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

Chaque action accepte jusqu'à MAX_KEYS touches (deux emplacements indépendants : on peut n'en lier
qu'une, et le 2e emplacement peut être rempli sans le 1er). Aucune touche par défaut : l'utilisateur les
choisit lui-même.

Pendant qu'on tape dans un champ de texte de l'appli (renommer un preset, valeur d'un SpinBox...), AUCUN
raccourci n'agit et aucune touche n'est avalée.
"""

import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

from settings import load_settings, update_settings

from .actions import BY_ID, Action
from .backend import KeyboardBackend
from .keyfilter import BoundKeyFilter, canonical_parts, qt_event_parts

CAPTURE_TIMEOUT_S = 15.0
MAX_KEYS = 2   # touches par action

MODE_OFF = "off"
MODE_WINDOW = "window"
MODE_GLOBAL = "global"
MODES = (MODE_OFF, MODE_WINDOW, MODE_GLOBAL)

# Modificateurs qui évitent qu'une touche se déclenche pendant qu'on tape du texte
_SAFE_MODIFIERS = {"ctrl", "alt", "alt gr", "windows", "left windows", "right windows", "cmd", "left ctrl",
                   "right ctrl", "left alt", "right alt"}
_TEXT_KEYS = {"space", "enter", "tab", "backspace", "delete", "esc"}


def is_text_input(widget) -> bool:
    """Champ où l'on tape : zone de texte, SpinBox (le focus reste sur le SpinBox lui-même, pas sur son
    QLineEdit interne), liste déroulante éditable."""
    if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
        return True
    return isinstance(widget, QComboBox) and widget.isEditable()


def typing_in_app() -> bool:
    """True si le focus est dans un champ de saisie de l'appli (renommer un preset, nom de séquence,
    valeur d'un SpinBox...) : aucun raccourci ne doit alors agir ni être avalé, sinon on ne pourrait
    plus taper un chiffre."""
    return is_text_input(QApplication.focusWidget())


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
    slot: int = 0
    removers: list = field(default_factory=list)
    armed: bool = True
    timer: threading.Timer | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class ShortcutManager(QObject):
    action_triggered = Signal(str)             # id de l'action déclenchée (thread Qt, mode respecté)
    bindings_changed = Signal()
    mode_changed = Signal(str)
    error = Signal(str)
    _raw_triggered = Signal(str)               # interne : émis depuis le thread clavier / un chrono
    capture_result = Signal(str, str, str)     # (action, touche, erreur) — touche "" si annulé/échec
    _captured = Signal(int, str, str)          # interne : (jeton, touche, erreur), émis depuis le thread de capture

    def __init__(self, backend=None, hold_seconds_override: float | None = None, parent=None):
        super().__init__(parent)
        self._backend = backend if backend is not None else KeyboardBackend()
        self._hold_override = hold_seconds_override  # pour les tests uniquement
        self._is_app_active = lambda: QGuiApplication.applicationState() == Qt.ApplicationActive
        self._regs: dict[tuple[str, int], _Registration] = {}
        self._capturing = False
        self._capture_action: str | None = None
        self._capture_slot = 0
        self._capture_token = 0
        self.last_error = ""

        cfg = load_settings()["shortcuts"]
        mode = cfg.get("mode")
        if mode not in MODES:  # anciens réglages : simple interrupteur on/off
            mode = MODE_GLOBAL if cfg.get("enabled", True) else MODE_OFF
        self._mode: str = mode
        # {action: [touche 1, touche 2]}, "" = emplacement libre. Ancien format : une simple chaîne.
        self._slots: dict[str, list[str]] = {}
        for aid, value in cfg["bindings"].items():
            if aid not in BY_ID:
                continue
            keys = [value] if isinstance(value, str) else list(value or [])
            keys = [normalize_key(k) if isinstance(k, str) and k.strip() else "" for k in keys][:MAX_KEYS]
            keys += [""] * (MAX_KEYS - len(keys))
            if any(keys):
                self._slots[aid] = keys
        self._bound_sets: set = set()
        self._migrate_setlist_keys()
        self._recompute_bound()
        self._captured.connect(self._on_captured, Qt.QueuedConnection)
        self._raw_triggered.connect(self._dispatch)  # direct dans le thread Qt, en file depuis un autre thread

        self._key_filter = BoundKeyFilter(self)
        app = QCoreApplication.instance()
        if app is not None:
            app.installEventFilter(self._key_filter)
        self._apply()

    # --- Lecture ---

    @property
    def available(self) -> bool:
        return self._backend.available

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def enabled(self) -> bool:
        return self._mode != MODE_OFF

    @property
    def capturing(self) -> bool:
        return self._capturing

    def bindings(self) -> dict[str, str]:
        """{action: première touche liée} (vue simplifiée ; cf all_bindings pour les deux emplacements)."""
        return {aid: next(k for k in ks if k) for aid, ks in self._slots.items() if any(ks)}

    def all_bindings(self) -> dict[str, list[str]]:
        return {aid: list(ks) for aid, ks in self._slots.items()}

    def keys_for(self, action_id: str) -> list[str]:
        """Les MAX_KEYS emplacements de l'action ("" = libre)."""
        return list(self._slots.get(action_id, [""] * MAX_KEYS))

    def binding_for(self, action_id: str) -> str | None:
        return next((k for k in self._slots.get(action_id, ()) if k), None)

    def _entries(self):
        for aid, ks in self._slots.items():
            for slot, key in enumerate(ks):
                if key:
                    yield aid, slot, key

    # --- Modification ---

    def set_mode(self, mode: str):
        if mode not in MODES or mode == self._mode:
            return
        self._mode = mode
        self._persist()
        self._apply()
        self.mode_changed.emit(mode)

    def cycle_mode(self):
        """Désactivés -> fenêtre active -> global -> désactivés (bouton de la barre latérale)."""
        self.set_mode(MODES[(MODES.index(self._mode) + 1) % len(MODES)])

    def assign(self, action_id: str, key: str | None, slot: int = 0) -> str | None:
        """Associe `key` à l'emplacement `slot` de l'action (ou le vide si `key` est vide).
        Renvoie un message d'erreur, ou None si c'est fait."""
        if action_id not in BY_ID:
            return "action inconnue"
        if not 0 <= slot < MAX_KEYS:
            return "emplacement inconnu"
        previous = self._slots.get(action_id)
        slots = list(previous) if previous else [""] * MAX_KEYS
        if not key or not key.strip():
            slots[slot] = ""
        else:
            new = normalize_key(key)
            for other, other_slot, other_key in self._entries():
                if other_key == new and not (other == action_id and other_slot == slot):
                    if other == action_id:
                        return "déjà utilisée par l'autre touche de cette action"
                    return f"déjà utilisée par « {BY_ID[other].label} »"
            slots[slot] = new
        self._store(action_id, slots)

        errors = self._apply()
        if action_id in errors:  # le backend refuse cette touche : on revient en arrière
            self._store(action_id, previous)
            self._apply()
            return errors[action_id]

        self._recompute_bound()
        self._persist()
        self.bindings_changed.emit()
        return None

    def restore(self, mode: str, bindings: dict[str, list[str]]):
        """Remet d'un coup un mode et un jeu de touches (annuler / rétablir). Les touches refusées par le
        backend sont simplement ignorées."""
        self._slots = {}
        for action_id, keys in bindings.items():
            if action_id in BY_ID:
                keys = (list(keys) + [""] * MAX_KEYS)[:MAX_KEYS]
                self._store(action_id, keys)
        if mode in MODES:
            self._mode = mode
        self._apply()
        self._recompute_bound()
        self._persist()
        self.bindings_changed.emit()
        self.mode_changed.emit(self._mode)

    def _store(self, action_id: str, slots: list[str] | None):
        if slots and any(slots):
            self._slots[action_id] = list(slots)
        else:
            self._slots.pop(action_id, None)

    # --- Capture d'une touche ---

    def start_capture(self, action_id: str, slot: int = 0):
        """Attend la prochaine combinaison pressée et l'associe à l'emplacement `slot` de `action_id`.
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
        self._capture_slot = slot
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
            err = self.assign(action_id, key, self._capture_slot)  # ré-applique les raccourcis
            if err:
                self._apply()
            self.capture_result.emit(action_id, "" if err else normalize_key(key), err or "")

    # --- Enregistrement auprès du backend ---

    def _apply(self) -> dict[str, str]:
        """(Ré)enregistre tout. Renvoie {action: erreur} pour les touches refusées."""
        self._unregister_all()
        errors: dict[str, str] = {}
        if self._mode == MODE_OFF or self._capturing or not self._slots:
            return errors
        if not self._backend.available:
            self._report("la librairie 'keyboard' n'est pas disponible sur ce système : raccourcis inactifs")
            return {aid: self.last_error for aid in self._slots}
        for action_id, slot, key in list(self._entries()):
            err = self._register(action_id, slot, key)
            if err:
                errors[action_id] = err
                self._report(err)
        return errors

    def _register(self, action_id: str, slot: int, key: str) -> str | None:
        reg = _Registration(BY_ID[action_id], slot)
        try:
            reg.removers.append(self._backend.add_hotkey(key, lambda: self._on_press(reg)))
            for part in key_parts(key):
                reg.removers.append(self._backend.on_release(part, lambda: self._on_release(reg)))
        except Exception as exc:
            for remove in reg.removers:
                self._safely(remove)
            return f"impossible d'assigner « {key} » : {exc}"
        self._regs[(action_id, slot)] = reg
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
            if not reg.armed or self._mode == MODE_OFF:
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
        if self._mode != MODE_OFF and self._regs.get((reg.action.id, reg.slot)) is reg:
            self._raw_triggered.emit(reg.action.id)

    def _dispatch(self, action_id: str):
        """Thread Qt : applique le mode avant de transmettre l'action."""
        if self._mode == MODE_OFF:
            return
        app_active = self._is_app_active()
        if self._mode == MODE_WINDOW and not app_active:
            return
        if app_active and typing_in_app():
            return  # on est en train de taper dans l'appli : le clavier appartient au champ de texte
        self.action_triggered.emit(action_id)

    # --- Touches avalées par l'appli (cf shortcuts/keyfilter.py) ---

    def _recompute_bound(self):
        self._bound_sets = {canonical_parts(key) for _aid, _slot, key in self._entries()}

    def swallows(self, event) -> bool:
        """True si cet évènement clavier correspond à une touche liée : l'appli ne doit pas
        le laisser agir sur le widget qui a le focus."""
        if self._mode == MODE_OFF or self._capturing or not self._bound_sets or typing_in_app():
            return False
        parts = qt_event_parts(event)
        return parts is not None and parts in self._bound_sets

    # --- Persistance ---

    def _persist(self):
        update_settings({"shortcuts": {"mode": self._mode, "bindings": self.all_bindings()}})

    def _migrate_setlist_keys(self):
        """Anciennes touches Suivant/Précédent de la setlist (settings["setlist"]) -> raccourcis."""
        setlist = load_settings()["setlist"]
        moved = False
        for old_field, action_id in (("next_key", "nav_next"), ("previous_key", "nav_previous")):
            key = setlist.get(old_field)
            if key:
                if action_id not in self._slots and normalize_key(key) not in (k for _a, _s, k in self._entries()):
                    self._slots[action_id] = [normalize_key(key)] + [""] * (MAX_KEYS - 1)
                moved = True
        if moved:
            update_settings({"setlist": {**setlist, "next_key": None, "previous_key": None}})
            self._persist()

    # --- Arrêt ---

    def shutdown(self):
        self._capture_token += 1
        self._capturing = False
        self._unregister_all()
        app = QCoreApplication.instance()
        if app is not None:
            app.removeEventFilter(self._key_filter)