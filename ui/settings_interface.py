"""
Page "Réglages" : ce qui n'est pas déjà dans les réglages d'un module.

  - Audio du looper : entrée, sortie (bouton d'actualisation) et taille du tampon ;
  - Port MIDI : automatique (le Mighty) ou choisi à la main ;
  - Thème : Windows / clair / sombre ;
  - Raccourcis : mode actuel + lien vers la page Raccourcis (rien n'y est dupliqué) ;
  - Données : dossier des réglages, export / import, réinitialisations ;
  - Diagnostic : rapport à copier, fichier de log.

La page ne touche pas aux autres modules : ce qui les concerne passe par des signaux que
MainWindow relie (cf `settings_replaced`, `dashboard_reset_requested`, `preset_names_reset`).
"""

import json
import logging
import threading
import time

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon, HeaderCardWidget, InfoBar, InfoBarPosition,
                            MessageBox, PushButton, SegmentedWidget, SwitchButton)

import diagnostics
import paths
import settings as settings_mod
from audio import portaudio_utils as pa
from audio.audio_config import BLOCKSIZES, AudioConfig
from midi import protocol
from settings import load_settings, update_settings
from shortcuts.manager import ShortcutManager
from ui import theme
from ui.preset_panel import NAMES_FILE
from ui.shortcuts_interface import MODE_LABELS
from ui.widgets import NoWheelComboBox
from setlist import model as setlist_model

log = logging.getLogger("melos.settings")

EXPORT_FORMAT = "melos-settings"
THEME_LABELS = {"auto": "Windows", "light": "Clair", "dark": "Sombre"}


class SettingsInterface(QScrollArea):
    settings_replaced = Signal()          # import / réinitialisation complète : les fichiers ont changé
    dashboard_reset_requested = Signal()
    preset_names_reset = Signal()
    open_shortcuts_requested = Signal()
    _hardware_refreshed = Signal(str)     # fin de la réinitialisation de PortAudio (thread de travail)

    def __init__(self, audio: AudioConfig, monitor, shortcuts: ShortcutManager, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsInterface")  # requis par FluentWindow pour la navigation
        self._audio, self._monitor, self._shortcuts = audio, monitor, shortcuts
        self._refreshing = False
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content.setMaximumWidth(860)
        col = QVBoxLayout(content)
        col.setContentsMargins(20, 20, 20, 20)
        col.setSpacing(16)
        outer = QWidget()
        outer.setStyleSheet("background: transparent;")
        row = QHBoxLayout(outer)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(content, 1)
        self.setWidget(outer)

        col.addWidget(self._build_audio())
        col.addWidget(self._build_midi())
        col.addWidget(self._build_theme())
        col.addWidget(self._build_shortcuts())
        col.addWidget(self._build_data())
        col.addWidget(self._build_diagnostics())
        col.addStretch()

        self._hardware_refreshed.connect(self._on_hardware_refreshed, Qt.QueuedConnection)
        audio.devices_changed.connect(self._fill_audio)
        audio.engine_restarted.connect(self._show_audio_status)
        shortcuts.mode_changed.connect(self._refresh_shortcuts_mode)
        self._fill_audio()
        self._fill_midi()
        self._show_audio_status(audio.engine.running)

    # ---------- helpers ----------

    @staticmethod
    def _card(title: str) -> tuple[HeaderCardWidget, QVBoxLayout]:
        card = HeaderCardWidget()
        card.setTitle(title)
        body = QVBoxLayout()
        body.setSpacing(10)
        card.viewLayout.addLayout(body)
        return card, body

    @staticmethod
    def _field(label: str, widget: QWidget, extra: QWidget | None = None) -> QHBoxLayout:
        row = QHBoxLayout()
        lab = BodyLabel(label)
        lab.setMinimumWidth(80)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        if extra is not None:
            row.addWidget(extra)
        return row

    @staticmethod
    def _note(text: str) -> CaptionLabel:
        lab = CaptionLabel(text)
        lab.setWordWrap(True)
        return lab

    def _toast(self, title: str, content: str = "", error: bool = False):
        fn = InfoBar.error if error else InfoBar.success
        fn(title=title, content=content, isClosable=True, duration=4000 if not error else 7000,
           position=InfoBarPosition.TOP, parent=self.window())

    # Surchargés par les tests (aucune boîte de dialogue en offscreen)
    def _confirm(self, title: str, text: str) -> bool:
        box = MessageBox(title, text, self.window())
        box.yesButton.setText("Continuer")
        box.cancelButton.setText("Annuler")
        return bool(box.exec())

    def _ask_save_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Exporter les réglages", "melos-reglages.json",
                                              "Réglages melos (*.json)")
        return path

    def _ask_open_path(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, "Importer des réglages", "", "Réglages melos (*.json)")
        return path

    def _open_path(self, path) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---------- Audio ----------

    def _build_audio(self):
        card, body = self._card("Audio du looper")
        self._api_combo = NoWheelComboBox()
        self._api_combo.currentIndexChanged.connect(self._on_api_chosen)
        body.addLayout(self._field("API audio", self._api_combo))
        self._in_combo = NoWheelComboBox()
        self._out_combo = NoWheelComboBox()
        self._in_combo.currentIndexChanged.connect(self._on_in_chosen)
        self._out_combo.currentIndexChanged.connect(self._on_out_chosen)
        self._refresh_btn = PushButton(FluentIcon.SYNC, "Actualiser")
        self._refresh_btn.setToolTip("Relit la liste des interfaces audio (utile après un branchement)")
        self._refresh_btn.clicked.connect(self._refresh_hardware)
        body.addLayout(self._field("Entrée", self._in_combo, self._refresh_btn))
        body.addLayout(self._field("Sortie", self._out_combo))
        self._block_combo = NoWheelComboBox()
        for n in BLOCKSIZES:
            self._block_combo.addItem(f"{n} échantillons  (≈ {self._audio.latency_ms(n):.1f} ms)", userData=n)
        self._block_combo.currentIndexChanged.connect(self._on_block_chosen)
        body.addLayout(self._field("Tampon", self._block_combo))
        self._exclusive_switch = SwitchButton()
        self._exclusive_switch.setOnText("Exclusif")
        self._exclusive_switch.setOffText("Partagé")
        self._exclusive_switch.setToolTip("WASAPI exclusif : latence minimale, mais les autres applis perdent la carte son")
        self._exclusive_switch.checkedChanged.connect(self._audio.set_exclusive)
        self._exclusive_row = self._field("Mode WASAPI", self._exclusive_switch)
        body.addLayout(self._exclusive_row)
        body.addWidget(self._note(
            "Plus le tampon est petit, plus la latence baisse, mais des craquements peuvent apparaître "
            "(256 par défaut). La compensation de latence des prises reste dans l'engrenage du looper."))
        self._audio_status = BodyLabel("")
        self._audio_status.setWordWrap(True)
        body.addWidget(self._audio_status)
        return card

    def _fill_combo(self, combo, names, current):
        combo.blockSignals(True)
        combo.clear()
        for n in names:
            combo.addItem(n, userData=n)
        combo.setCurrentIndex(names.index(current) if current in names else (0 if names else -1))
        combo.blockSignals(False)

    def _fill_audio(self):
        a = self._audio
        self._api_combo.blockSignals(True)
        self._api_combo.clear()
        self._api_combo.addItem(f"Auto ({a.effective_api or '—'})", userData="auto")
        for name in a.api_names:
            self._api_combo.addItem(name, userData=name)
        self._api_combo.setCurrentIndex(max(0, a.api_names.index(a.api_setting) + 1)
                                        if a.api_setting in a.api_names else 0)
        self._api_combo.blockSignals(False)
        self._exclusive_switch.blockSignals(True)
        self._exclusive_switch.setChecked(a.exclusive)
        self._exclusive_switch.blockSignals(False)
        self._exclusive_switch.setEnabled(a.is_wasapi)
        self._fill_combo(self._in_combo, [n for _, n in a.input_devices], a.input_name)
        self._fill_combo(self._out_combo, [n for _, n in a.output_devices], a.output_name)
        self._block_combo.blockSignals(True)
        self._block_combo.setCurrentIndex(BLOCKSIZES.index(a.blocksize))
        self._block_combo.blockSignals(False)

    def _show_audio_status(self, ok: bool):
        a = self._audio
        if ok:
            lat = a.latency_info
            text = f"Flux ouvert · {a.effective_api or 'API inconnue'} · tampon {a.blocksize}"
            if lat:
                text += (f"\nLatence annoncée : entrée {lat['input_ms']:.0f} ms + sortie {lat['output_ms']:.0f} ms"
                         f" = {lat['total_ms']:.0f} ms aller-retour")
                if lat["total_ms"] > 80:
                    text += "\nC'est beaucoup : essaie l'API WASAPI (ou ASIO si tu as un driver), voire le mode exclusif."
            self._audio_status.setText(text)
        else:
            self._audio_status.setText("⚠ Pas d'audio" + (f" : {a.error}" if a.error else ""))

    def _on_api_chosen(self, index: int):
        api = self._api_combo.itemData(index)
        if api:
            self._audio.set_api(api)

    def _on_in_chosen(self, index: int):
        name = self._in_combo.itemData(index)
        if name:
            self._audio.set_input(name)

    def _on_out_chosen(self, index: int):
        name = self._out_combo.itemData(index)
        if name:
            self._audio.set_output(name)

    def _on_block_chosen(self, index: int):
        n = self._block_combo.itemData(index)
        if n:
            self._audio.set_blocksize(n)

    def _refresh_hardware(self):
        """PortAudio ne relit sa liste qu'en se réinitialisant, et ça peut bloquer : thread à part."""
        if self._refreshing:
            return
        self._refreshing = True
        self._refresh_btn.setEnabled(False)
        self._audio.engine.stop_stream()   # PortAudio ne se réinitialise qu'avec zéro flux ouvert
        requested_at = time.monotonic()

        def work():
            self._hardware_refreshed.emit(pa.refresh_portaudio(requested_at))

        threading.Thread(target=work, name="portaudio-refresh", daemon=True).start()

    def _on_hardware_refreshed(self, status: str):
        self._refreshing = False
        self._refresh_btn.setEnabled(True)
        if status == "stuck":
            self._toast("Actualisation impossible", "Un flux audio est coincé : relance l'appli.", error=True)
        self._audio.refresh_devices()
        self._audio.start_engine()

    # ---------- MIDI ----------

    def _build_midi(self):
        card, body = self._card("Port MIDI")
        self._midi_mode = SegmentedWidget()
        self._midi_mode.addItem("auto", "Automatique", lambda: self._on_midi_mode("auto"))
        self._midi_mode.addItem("manual", "Manuel", lambda: self._on_midi_mode("manual"))
        body.addWidget(self._midi_mode)
        self._midi_in = NoWheelComboBox()
        self._midi_out = NoWheelComboBox()
        self._midi_in.currentIndexChanged.connect(self._on_midi_port)
        self._midi_out.currentIndexChanged.connect(self._on_midi_port)
        self._midi_refresh = PushButton(FluentIcon.SYNC, "Actualiser")
        self._midi_refresh.clicked.connect(self._fill_midi)
        body.addLayout(self._field("Entrée", self._midi_in, self._midi_refresh))
        body.addLayout(self._field("Sortie", self._midi_out))
        self._midi_note = self._note("")
        body.addWidget(self._midi_note)
        self._midi_status = BodyLabel("")
        self._midi_status.setWordWrap(True)
        body.addWidget(self._midi_status)
        return card

    def _fill_midi(self):
        cfg = load_settings()["midi"]
        manual = cfg["mode"] == "manual"
        inputs, outputs = self._monitor.list_ports() if self._monitor else ([], [])
        for combo, ports, saved in ((self._midi_in, inputs, cfg.get("input_name")),
                                    (self._midi_out, outputs, cfg.get("output_name"))):
            combo.blockSignals(True)
            combo.clear()
            names = list(ports)
            for n in names:
                combo.addItem(n, userData=n)
            if saved and saved not in names:
                combo.addItem(f"{saved} (absent)", userData=saved)
                names.append(saved)
            if saved in names:
                combo.setCurrentIndex(names.index(saved))
            else:
                guess = protocol.find_port(names)
                combo.setCurrentIndex(names.index(guess) if guess else (0 if names else -1))
            combo.blockSignals(False)
        self._midi_mode.setCurrentItem("manual" if manual else "auto")
        self._set_midi_enabled(manual)
        self.refresh_midi_status()

    def _set_midi_enabled(self, manual: bool):
        for w in (self._midi_in, self._midi_out, self._midi_refresh):
            w.setEnabled(manual)
        self._midi_note.setText(
            "Choisis les ports à utiliser (par exemple si plusieurs appareils portent le nom du Mighty)."
            if manual else f"Le Mighty est cherché tout seul (port dont le nom contient « {protocol.PORT_KEYWORD} »).")

    def _on_midi_mode(self, mode: str):
        if mode == "manual":
            # première bascule : part des ports actuellement proposés
            self._save_midi("manual")
        else:
            self._save_midi("auto")
        self._set_midi_enabled(mode == "manual")

    def _on_midi_port(self, _index: int):
        if load_settings()["midi"]["mode"] == "manual":
            self._save_midi("manual")

    def _save_midi(self, mode: str):
        update_settings({"midi": {
            "mode": mode,
            "input_name": self._midi_in.currentData(),
            "output_name": self._midi_out.currentData(),
        }})
        if self._monitor is not None:
            self._monitor.apply_preferences()
        self.refresh_midi_status()

    def refresh_midi_status(self):
        cur = self._monitor.current_ports if self._monitor else None
        self._midi_status.setText(
            f"Connecté · entrée « {cur[0]} » · sortie « {cur[1]} »" if cur else
            "Non connecté — la connexion est retentée toutes les secondes.")

    # ---------- Thème ----------

    def _build_theme(self):
        card, body = self._card("Thème")
        self._theme_switch = SegmentedWidget()
        for key, label in THEME_LABELS.items():
            self._theme_switch.addItem(key, label, lambda _=False, k=key: self._on_theme(k))
        current = load_settings()["ui"]["theme"]
        self._theme_switch.setCurrentItem(current if current in THEME_LABELS else "auto")
        body.addWidget(self._theme_switch)
        body.addWidget(self._note("« Windows » suit le thème clair / sombre du système."))
        return card

    def _on_theme(self, key: str):
        update_settings({"ui": {**load_settings()["ui"], "theme": key}})
        theme.apply_theme(key)

    # ---------- Raccourcis ----------

    def _build_shortcuts(self):
        card, body = self._card("Raccourcis clavier")
        row = QHBoxLayout()
        self._shortcuts_mode = BodyLabel("")
        row.addWidget(self._shortcuts_mode, 1)
        btn = PushButton(FluentIcon.RIGHT_ARROW, "Ouvrir la page Raccourcis")
        btn.clicked.connect(self.open_shortcuts_requested)
        row.addWidget(btn)
        body.addLayout(row)
        self._refresh_shortcuts_mode(self._shortcuts.mode)
        return card

    def _refresh_shortcuts_mode(self, mode: str):
        self._shortcuts_mode.setText(f"Mode actuel : {MODE_LABELS.get(mode, mode)}")

    # ---------- Données ----------

    def _build_data(self):
        card, body = self._card("Données")
        row = QHBoxLayout()
        for text, icon, fn in (("Ouvrir le dossier des réglages", FluentIcon.FOLDER, self._open_folder),
                               ("Exporter…", FluentIcon.SHARE, self.export_settings),
                               ("Importer…", FluentIcon.DOWNLOAD, self.import_settings)):
            b = PushButton(icon, text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch()
        body.addLayout(row)

        body.addWidget(BodyLabel("Réinitialiser"))
        rrow = QHBoxLayout()
        self._reset_buttons = {}
        for key, text in (("dashboard", "L'agencement du Dashboard"), ("names", "Les noms de presets"),
                          ("all", "Tout")):
            b = PushButton(text)
            b.clicked.connect(lambda _=False, k=key: self.reset(k))
            self._reset_buttons[key] = b
            rrow.addWidget(b)
        rrow.addStretch()
        body.addLayout(rrow)
        body.addWidget(self._note(
            "« Tout » remet tous les réglages à zéro (modules, raccourcis, périphériques…) et efface les noms "
            "de presets. Les séquences de setlist ne sont pas touchées."))
        return card

    def _data_files(self) -> dict[str, "object"]:
        return {"settings": settings_mod.SETTINGS_FILE, "preset_names": NAMES_FILE,
                "setlists": setlist_model.SETLISTS_FILE}

    def _open_folder(self):
        self._open_path(settings_mod.SETTINGS_FILE.parent)

    @staticmethod
    def _read_json(path):
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, ValueError):
            return None

    def export_settings(self, path: str | None = None) -> bool:
        path = path or self._ask_save_path()
        if not path:
            return False
        files = self._data_files()
        bundle = {"format": EXPORT_FORMAT, "version": 1,
                  "settings": load_settings(),
                  "preset_names": self._read_json(files["preset_names"]) or {},
                  "setlists": self._read_json(files["setlists"])}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(bundle, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            self._toast("Export impossible", str(exc), error=True)
            return False
        self._toast("Réglages exportés", str(path))
        return True

    def import_settings(self, path: str | None = None) -> bool:
        path = path or self._ask_open_path()
        if not path:
            return False
        try:
            with open(path, encoding="utf-8") as f:
                bundle = json.load(f)
            if bundle.get("format") != EXPORT_FORMAT or not isinstance(bundle.get("settings"), dict):
                raise ValueError("ce n'est pas un export de réglages melos")
        except (OSError, ValueError, AttributeError) as exc:
            self._toast("Import impossible", str(exc), error=True)
            return False
        if not self._confirm("Importer ces réglages ?",
                             "Tes réglages actuels (y compris noms de presets et setlists) seront remplacés."):
            return False
        files = self._data_files()
        # même fusion qu'au chargement : un export ancien reste valide, les clés manquantes reprennent leur défaut
        settings_mod.save_settings({**settings_mod.load_defaults(), **bundle["settings"]})
        files["preset_names"].write_text(json.dumps(bundle.get("preset_names") or {}, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
        if bundle.get("setlists") is not None:
            files["setlists"].write_text(json.dumps(bundle["setlists"], ensure_ascii=False, indent=2),
                                         encoding="utf-8")
        self._after_replace("Réglages importés")
        return True

    def reset(self, what: str) -> bool:
        texts = {
            "dashboard": ("Réinitialiser le Dashboard ?", "Les modules reprennent leur place et taille d'origine."),
            "names": ("Effacer les noms de presets ?", "Les presets reprennent leurs noms par défaut."),
            "all": ("Tout réinitialiser ?", "Tous les réglages et noms de presets seront remis à zéro. "
                                            "Les setlists sont conservées."),
        }
        if what not in texts or not self._confirm(*texts[what]):
            return False
        if what == "dashboard":
            self.dashboard_reset_requested.emit()
            self._toast("Dashboard réinitialisé")
        elif what == "names":
            NAMES_FILE.write_text("{}", encoding="utf-8")
            self.preset_names_reset.emit()
            self._toast("Noms de presets effacés")
        else:
            settings_mod.save_settings(settings_mod.load_defaults())
            NAMES_FILE.write_text("{}", encoding="utf-8")
            self._after_replace("Réglages réinitialisés")
        return True

    def _after_replace(self, title: str):
        """Les fichiers ont changé : on réapplique ce qui peut l'être à chaud, le reste au prochain lancement."""
        self.settings_replaced.emit()
        self._fill_audio()
        self._fill_midi()
        cur = load_settings()["ui"]["theme"]
        self._theme_switch.setCurrentItem(cur if cur in THEME_LABELS else "auto")
        self._toast(title, "Audio, port MIDI, thème, raccourcis, Dashboard et presets sont à jour. "
                           "Tempo, batterie et accordeur : au prochain lancement.")

    # ---------- Diagnostic ----------

    def _build_diagnostics(self):
        card, body = self._card("Diagnostic")
        row = QHBoxLayout()
        copy = PushButton(FluentIcon.COPY, "Copier le rapport")
        copy.clicked.connect(lambda _=False: self.copy_report())
        log_btn = PushButton(FluentIcon.DOCUMENT, "Ouvrir le fichier de log")
        log_btn.clicked.connect(lambda _=False: self.open_log())
        row.addWidget(copy)
        row.addWidget(log_btn)
        row.addStretch()
        body.addLayout(row)
        body.addWidget(self._note("Le rapport liste les versions, les ports MIDI et les périphériques audio : "
                                  "à coller dans un message en cas de problème."))
        return card

    def build_report(self) -> str:
        return diagnostics.build_report(self._audio, self._monitor, load_settings())

    def copy_report(self) -> str:
        text = self.build_report()
        QApplication.clipboard().setText(text)
        self._toast("Rapport copié", "Colle-le dans ton message.")
        return text

    def open_log(self) -> bool:
        if not paths.LOG_FILE.exists():
            self._toast("Pas encore de log", str(paths.LOG_FILE), error=True)
            return False
        return self._open_path(paths.LOG_FILE)