"""
Page « Partition » : tablature Songsterr (alphaTab dans QtWebEngine) synchronisée avec l'audio d'une vidéo YouTube.

  - Python télécharge/décode le morceau (tabs/client.py), le convertit en alphaTex avec les points de synchro de
    la vidéo choisie (tabs/alphatex.py + tabs/sync.py) et l'envoie à la page web (tabs/web/tab_view.html) ;
  - mode « Original » : le son vient de mpv en audio seul (tabs/player.py) : tous les codecs, pas de pub, pas de page
    YouTube. Python lit la position de mpv toutes les ~50 ms et la transmet au curseur alphaTab ; inversement,
    lecture/pause/saut demandés dans la partition sont appliqués à mpv ;
  - mode « Synthèse » : le synthétiseur MIDI d'alphaTab joue TOUTES les pistes de la partition (banque de sons General MIDI) ;
    mute / solo / volume sont libres piste par piste, avec métronome, décompte, boucle de mesures et export MIDI. mpv se
    tait ; la position vient d'alphaTab.
"""

import json
import logging
import time

from PySide6.QtCore import QPoint, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QTextEdit, QVBoxLayout,
                               QWidget)
from qfluentwidgets import BodyLabel, CaptionLabel, qconfig, isDarkTheme

from settings import load_settings, update_settings
from state.undo import UndoStack
from tabs.score_library import ScoreLibrary
from ui.bookmark_popup import BookmarkPopup
from ui.preset_marks_popup import PresetMarksPopup, resolve as resolve_preset, slot_color
from ui.tab_widgets import (ChoiceModel, ChoicePopup, DragGhost, ScoreMenu, SegmentedPill, TabButton, TabSlider, TitleField)
from ui.theme import card_style, pal, score_bg
from ui.score_library_popup import ScorePicker, StarButton
from ui.song_search import SearchPopup, SearchWorker, looks_like_url
from ui.stem_dialog import StemDialog
from ui.tab_editing import EditController
from ui.track_list import TrackList
from tabs import server as tab_server
from tabs.alphatex import lyrics_for, markers_for, to_alphatex
from tabs.client import TabError, load_song
from tabs.debug import dbg
from tabs.model import Score
from tabs.score_edits import apply_edits, edited_bars
from tabs.player import AudioPlayer, PlayerError
from tabs.sync import VideoSync

log = logging.getLogger("melos.tabs")

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_ERROR = None
except Exception as exc:                      # PySide6 sans QtWebEngine
    QWebEngineView = None
    WEBENGINE_ERROR = f"{type(exc).__name__}: {exc}"


if QWebEngineView is not None:
    class _LoggingPage(QWebEnginePage):
        """Page web dont les messages de la console JavaScript sont recopiés dans la console de l'appli."""

        def javaScriptConsoleMessage(self, level, message, line, source):
            dbg("js", message[:300])
            super().javaScriptConsoleMessage(level, message, line, source)



def volume_gain(percent: int) -> float:
    """Curseur 0-100 -> gain 0-1, courbe quadratique : l'oreille entend en dB, une courbe linéaire laisse tout le
    réglage utile dans le bas du curseur."""
    return (max(0, min(100, percent)) / 100.0) ** 2


class _LoadWorker(QThread):
    done = Signal(object, object)             # Score, list[VideoSync]
    failed = Signal(str)

    def __init__(self, url: str, refresh: bool, country: str = "FR", parent=None):
        super().__init__(parent)
        self._url, self._refresh, self._country = url, refresh, country

    def run(self):
        try:
            score, syncs = load_song(self._url, self._refresh, self._country)
            self.done.emit(score, syncs)
        except TabError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            log.exception("chargement partition")
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class TabInterface(QWidget):
    """Page de navigation. Presque aucune dépendance au reste de l'appli : `set_amp(state, sender, names)` la relie à
    l'ampli pour que les changements de preset posés sur la partition s'envoient à la bonne mesure (cf. `_apply_preset`)."""

    bar_changed = Signal(int)                 # index de mesure (0 = première) sous le curseur

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TabInterface")
        self._score: Score | None = None         # partition AFFICHÉE : l'originale, ou « Ma version » (original + modifications)
        self._orig_score: Score | None = None    # partition de Songsterr, jamais modifiée
        self._edit_sig = None                    # (version, modifications) affichées
        self._syncs: list[VideoSync] = []
        self._worker: _LoadWorker | None = None
        self._server: tab_server.TabServer | None = None
        self._view = None
        self._page_ready = False
        self._pending: tuple[str, str] | None = None
        self.current_bar = -1
        self.current_frac = 0.0                              # position dans la mesure (0-1) : changements de preset au temps près
        self._state = self._sender = self._names = None     # reliés à l'ampli par set_amp()
        self._auto_key = None                               # (mesure, emplacement) du dernier changement traité pendant cette lecture
        self._drag = None                                   # glisser-déposer en cours : {"kind", "payload", "ghost", "t"}
        self._counting = False                              # décompte en cours (mode Original)
        self._loop_last = None                              # (position, lecture) précédentes : détecte le passage de la fin de boucle
        self._was_playing = False
        self._preset_auto = bool(load_settings()["tabs"].get("preset_auto", True))
        self._bar_starts: list[float] = []
        self._synth = False                 # mode « Synthèse » actif ?
        self._synth_loaded = False          # la page contient la partition COMPLÈTE en mode synthèse (changement de piste sans rechargement)
        self._synth_ready = False           # banque de sons chargée, lecture possible
        self._synth_playing = False
        self._synth_pos = (0, 0.0)          # (mesure, position dans la mesure 0-1) lues dans le synthétiseur
        self._synth_tex: str | None = None
        self._undo = UndoStack(self._apply_undo, parent=self)            # Ctrl+Z / Ctrl+Y de la page : marqueurs et zone de boucle
        self._marks_last = None                                         # (morceau, marque-pages, presets) avant le dernier changement
        self._range_last = None                                         # mesures [a, b] de la zone de boucle avant le dernier changement
        self._range = None                  # zone de boucle {"bars": [première, dernière], "t0", "t1" (s)} ou None
        self._autoplay = False              # relancer la lecture dès que le synthétiseur est prêt
        self._seek_after_load = None        # (secondes, lecture ?) à appliquer à mpv quand il est prêt (retour en mode Original)
        self._speed = 1.0
        self._volume = 1.0
        self._resume_synth = None           # (mesure, position 0-1) où démarrer la synthèse après une bascule

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        tabs_cfg = load_settings()["tabs"]
        self._committed_url = ""                           # lien du morceau affiché (le champ y revient quand on quitte la saisie)
        self._zoom = float(tabs_cfg.get("scale", 1.0))

        # --- en-tête : [panneau] [morceaux] [titre / recherche] [favori] [re-télécharger]   [Original|Synthèse] [outils du mode] ---
        head = QHBoxLayout()
        head.setSpacing(8)
        self.panel_btn = TabButton("", "panel-left", "soft", self, height=36)
        self.panel_btn.setCheckable(True)
        self.panel_btn.setChecked(bool(tabs_cfg.get("panel_open", True)))
        self.panel_btn.setToolTip("Afficher / masquer la liste des pistes")
        self.panel_btn.toggled.connect(self._toggle_panel)
        head.addWidget(self.panel_btn)
        # morceaux : historique + favoris des partitions
        self.library = ScoreLibrary()
        self._picker = ScorePicker(self.library, self)
        self._picker.chosen.connect(self._choose_entry)
        self.lib_btn = TabButton("Morceaux", "music", "soft", self, height=36)
        self.lib_btn.setToolTip("Mes morceaux : récents et favoris")
        self.lib_btn.clicked.connect(lambda: self._picker.popup_at(self.lib_btn))
        head.addWidget(self.lib_btn)
        # titre du morceau ; un clic le transforme en champ de recherche / lien
        self.title_field = TitleField(self, height=44)
        self.url_edit = self.title_field.edit
        self.url_edit.returnPressed.connect(self._on_enter)
        self._popup = SearchPopup()                         # recherche par nom : liste de résultats sous le champ
        self._popup.chosen.connect(self._choose_hit)
        self._search_token = 0
        self._search_workers: list[SearchWorker] = []
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._run_search)
        self.url_edit.textEdited.connect(self._on_text_edited)
        self.url_edit.move.connect(self._popup.move_selection)
        self.url_edit.accept.connect(lambda: self._choose_hit(self._popup.current_hit()))
        self.url_edit.dismiss.connect(self._end_edit)
        self.title_field.editing_changed.connect(lambda on: self.load_btn.setVisible(on))
        self.status = self.title_field                      # set_full() : état / erreurs, affichés sous le titre
        head.addWidget(self.title_field, 1)
        self.load_btn = TabButton("Charger", None, "accent", self, height=36)
        self.load_btn.clicked.connect(self.load_from_edit)
        self.load_btn.hide()
        head.addWidget(self.load_btn)
        self.star_btn = StarButton(False, self)
        self.star_btn.clicked.connect(self._toggle_favorite)
        self.library.listeners.append(self._update_star)
        head.addWidget(self.star_btn)
        self.refresh_btn = TabButton("", "refresh", "soft", self, height=36)
        self.refresh_btn.setToolTip("Re-télécharger : ignore le cache et redemande le morceau à Songsterr")
        self.refresh_btn.clicked.connect(lambda: self.load_from_edit(refresh=True))
        head.addWidget(self.refresh_btn)
        head.addSpacing(6)
        self.mode_switch = SegmentedPill(self, height=36)
        self.mode_switch.addItem("original", "Original", lambda: self._set_mode("original"))
        self.mode_switch.addItem("synth", "Synthèse", lambda: self._set_mode("synth"))
        self.mode_switch.setCurrentItem("original")
        self.mode_switch.setToolTip("Original : l'enregistrement YouTube. Synthèse : la partition jouée par le synthétiseur MIDI")
        head.addWidget(self.mode_switch)
        # versions audio (vidéos) : même API qu'un QComboBox, affichées dans l'engrenage des pistes
        self.video_combo = ChoiceModel(self)
        self.video_combo.currentIndexChanged.connect(self._on_video)
        # outils de lecture, IDENTIQUES dans les deux modes (rien ne bouge quand on change de mode) : métronome, décompte,
        # boucle, export MIDI
        saved_synth = tabs_cfg.get("synth", {})
        self.metro_btn = TabButton("", "metronome", "soft", self, height=36)
        self.metro_btn.setToolTip("Métronome : clic pendant la lecture")
        self.count_btn = TabButton("", "count", "soft", self, height=36)
        self.count_btn.setToolTip("Décompte : une mesure de clics avant le départ")
        self.loop_btn = TabButton("", "loop", "soft", self, height=36)
        self.loop_btn.setToolTip("Boucle : rejoue la zone choisie sur la partition (glisse sur des mesures, ou clic droit), "
                                 "ou tout le morceau s'il n'y en a pas")
        for b_ in (self.metro_btn, self.count_btn, self.loop_btn):
            b_.setCheckable(True)
        self.metro_btn.setChecked(bool(saved_synth.get("metronome", False)))
        self.count_btn.setChecked(bool(saved_synth.get("count_in", False)))
        self.loop_btn.setChecked(bool(saved_synth.get("loop", False)))
        self.metro_btn.toggled.connect(lambda on: self._synth_toggle("metronome", on))
        self.count_btn.toggled.connect(lambda on: self._synth_toggle("count_in", on))
        self.loop_btn.toggled.connect(lambda on: self._synth_toggle("loop", on))
        self.loop_btn.toggled.connect(lambda on: self._js(f"melos.setLoopMode({str(bool(on)).lower()})"))
        self.export_btn = TabButton("", "save", "soft", self, height=36)
        self.export_btn.setToolTip("Exporter en MIDI : enregistre la partition (toutes les pistes) en fichier .mid")
        self.export_btn.clicked.connect(self._export_midi)
        self.edit_btn = TabButton("", "edit", "soft", self, height=36)
        self.edit_btn.setCheckable(True)
        self.edit_btn.setToolTip("Modifier la partition : change des notes, des durées, le tempo… sans toucher à l'original de Songsterr "
                                 "(« Ma version »)")
        for w in (self.metro_btn, self.count_btn, self.loop_btn, self.export_btn, self.edit_btn):
            head.addWidget(w)
        lay.addLayout(head)
        self._update_star()

        if QWebEngineView is None:
            lay.addWidget(BodyLabel("QtWebEngine est indisponible (" + str(WEBENGINE_ERROR) + "). "
                                    "Réinstalle PySide6 : pip install -r requirements.txt", self), 1)
            self._set_enabled(False)
        elif not tab_server.alphatab_installed():
            lay.addWidget(BodyLabel("alphaTab n'est pas installé. Lance une fois :  "
                                    ".venv\\Scripts\\python.exe tools\\fetch_alphatab.py  puis relance l'appli.", self), 1)
            self._set_enabled(False)
        else:
            self._view = QWebEngineView(self)
            self._view.setPage(_LoggingPage(self._view))
            page = self._view.page()
            self._apply_view_background()      # fond uni de la couleur du thème : plus de blanc pendant l'initialisation / les redimensionnements
            qconfig.themeChanged.connect(lambda *_: self._apply_view_background())
            # la page web reste « active » même cachée (autre onglet) : pas de rechargement ni de flash au retour
            page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            page.recommendedStateChanged.connect(
                lambda _s, p=page: p.setLifecycleState(QWebEnginePage.LifecycleState.Active))
            self._view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            # le synthétiseur (WebAudio) démarre sur ordre de Python, sans clic dans la page : sans ceci Chromium le laisse muet
            self._view.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
            self.track_list = TrackList(self)
            self.track_list.set_choice(self.video_combo)
            self.track_list.setVisible(self.panel_btn.isChecked())
            self.track_list.selected.connect(self._on_track)
            self.track_list.video_wanted.connect(self._switch_video)
            self.track_list.edit_mapping.connect(self._edit_mapping)
            self.track_list.synth_mix_changed.connect(self._on_mix_changed)
            body = QHBoxLayout()
            body.setSpacing(10)
            body.addWidget(self.track_list)
            self._score_card = QFrame(self)                # la partition dans une « carte » comme le panneau des pistes
            self._score_card.setObjectName("scoreCard")
            sc = QVBoxLayout(self._score_card)
            sc.setContentsMargins(1, 1, 1, 1)
            sc.addWidget(self._view)
            body.addWidget(self._score_card, 1)
            lay.addLayout(body, 1)
            self._set_enabled(True)
            self._view.loadFinished.connect(self._on_page_loaded)

        # --- commandes de lecture : [lecture] temps ───curseur─── [marque-pages] [vitesse] [zoom − 100 % +] [volume] ---
        self._transport = QFrame(self)
        self._transport.setObjectName("transport")
        bar = QHBoxLayout(self._transport)
        bar.setContentsMargins(8, 6, 14, 6)
        bar.setSpacing(8)
        self.play_btn = TabButton("", "play", "accent", self, height=38, icon_size=18, radius=19)
        self.play_btn.setFixedSize(38, 38)
        self.play_btn.setToolTip("Lecture / pause (barre espace)")
        self.play_btn.clicked.connect(self._toggle_play)
        self.time_label = CaptionLabel("0:00 / 0:00", self)
        self.time_label.setMinimumWidth(78)
        self.seek_slider = TabSlider(Qt.Horizontal, self)
        self.seek_slider.setRange(0, 1)
        # Tout changement de valeur NON déclenché par nous (clic, glissement, flèches) = demande de saut de l'utilisateur ;
        # léger délai pour ne sauter qu'une fois pendant un glissement.
        self._updating = False
        self._user_seek = QTimer(self)
        self._user_seek.setSingleShot(True)
        self._user_seek.setInterval(120)
        self._user_seek.timeout.connect(self._do_user_seek)
        self.seek_slider.valueChanged.connect(self._slider_moved)
        self.speed_combo = ChoiceModel(self)                # vitesses : même API qu'un QComboBox, affichées par le bouton ci-dessous
        for r in (0.25, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5):
            self.speed_combo.addItem(f"{r:g}×", userData=r)
        self.speed_combo.setCurrentIndex(self.speed_combo.findData(1.0))
        self.speed_combo.currentIndexChanged.connect(self._on_speed)
        self.speed_btn = TabButton("1×", "gauge", "soft", self, height=34)
        self.speed_btn.setToolTip("Vitesse de lecture")
        self.speed_btn.clicked.connect(self._open_speeds)
        self.speed_combo.changed.connect(lambda: self.speed_btn.setText(self.speed_combo.currentText()))
        self._speed_popup = ChoicePopup([self.speed_combo.itemText(i) for i in range(self.speed_combo.count())], 4, self)
        self._speed_popup.chosen.connect(self.speed_combo.setCurrentIndex)
        # zoom de la partition
        self.zoom_out_btn = TabButton("", "minus", "ghost", self, height=30)
        self.zoom_out_btn.setFixedSize(30, 30)
        self.zoom_out_btn.setToolTip("Zoom arrière (Ctrl + −)")
        self.zoom_out_btn.clicked.connect(lambda: self._step_zoom(-1))
        self.zoom_btn = TabButton(f"{round(self._zoom * 100)} %", None, "ghost", self, height=30)
        self.zoom_btn.setFixedWidth(58)
        self.zoom_btn.setToolTip("Zoom de la partition : clic pour revenir à 100 % (Ctrl + 0)")
        self.zoom_btn.clicked.connect(lambda: self._set_zoom(1.0))
        self.zoom_in_btn = TabButton("", "plus", "ghost", self, height=30)
        self.zoom_in_btn.setFixedSize(30, 30)
        self.zoom_in_btn.setToolTip("Zoom avant (Ctrl + +)")
        self.zoom_in_btn.clicked.connect(lambda: self._step_zoom(1))
        self.mute_btn = TabButton("", "volume", "ghost", self, height=30)      # clic : couper / rétablir le son
        self.mute_btn.setFixedSize(30, 30)
        self.mute_btn.setToolTip("Couper / rétablir le son")
        self.mute_btn.clicked.connect(self._toggle_mute)
        self.volume_slider = TabSlider(Qt.Horizontal, self)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setPageStep(10)
        self.volume_slider.setSingleStep(5)                                 # molette : 5 % par cran
        self.volume_slider.setFixedWidth(92)
        _v = load_settings()["tabs"]
        self._muted = bool(_v.get("muted", False))
        self.volume_slider.setValue(int(_v.get("volume", 100)))
        self.volume_slider.valueChanged.connect(self._on_volume)
        bar.addWidget(self.play_btn)
        bar.addWidget(self.time_label)
        bar.addWidget(self.seek_slider, 1)
        self.bkm_btn = TabButton("", "bookmark", "soft", self, height=34)
        self.bkm_btn.setToolTip("Marque-pages du morceau : ajouter à la mesure courante, y revenir (Ctrl+B pour ajouter / retirer, "
                                "Ctrl+←/→ pour le précédent / suivant)")
        self.bkm_btn.clicked.connect(self._open_bookmarks)
        self._bkm_popup = BookmarkPopup(self.library, name_hint=self._bookmark_hint, parent=self)
        self._bkm_popup.jump.connect(self._goto_bar)
        self._bkm_popup.drag_started.connect(lambda label, color: self._drag_begin("bookmark", None, label, color))
        self._bkm_popup.drag_moved.connect(self._drag_move)
        self._bkm_popup.drag_dropped.connect(self._drag_drop)
        self._bkm_sent = None                 # dernière liste envoyée à la page (évite les renvois inutiles)
        self.library.listeners.append(self._on_bookmarks_changed)
        self.library.listeners.append(self._record_marks)
        bar.addWidget(self.bkm_btn)
        self.pre_btn = TabButton("", "pedal", "soft", self, height=34)
        self.pre_btn.setToolTip("Presets : changements de preset placés sur la partition, envoyés à l'ampli quand la lecture atteint la mesure")
        self._reload_timer = QTimer(self)                  # regroupe les modifications rapprochées en UN seul redessin
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(90)
        self._reload_timer.timeout.connect(self._reload_now)
        self.edit = EditController(self)
        lay.addWidget(self.edit.palette)
        lay.addWidget(self.edit.bar)
        self.edit_btn.toggled.connect(self.edit.toggle)
        self.library.listeners.append(self._on_edits_changed)
        self.pre_btn.clicked.connect(self._open_presets)
        self._pre_popup = PresetMarksPopup(self.library, name_hint=self._bookmark_hint, auto=self._preset_auto, parent=self)
        self._pre_popup.jump.connect(self._goto_bar)
        self._pre_popup.auto_changed.connect(self._on_preset_auto)
        self._pre_popup.add_requested.connect(self._place_preset)
        self._pre_popup.drag_started.connect(lambda t, label, color: self._drag_begin("preset", t, label, color))
        self._pre_popup.drag_moved.connect(self._drag_move)
        self._pre_popup.drag_dropped.connect(self._drag_drop)
        self._pre_sent = None                 # dernière liste envoyée à la page
        self.library.listeners.append(self._on_presets_changed)
        self.bar_changed.connect(lambda b: self._apply_preset(b, self.current_frac))
        bar.addWidget(self.pre_btn)
        bar.addWidget(self.speed_btn)
        bar.addSpacing(4)
        bar.addWidget(self.zoom_out_btn)
        bar.addWidget(self.zoom_btn)
        bar.addWidget(self.zoom_in_btn)
        bar.addSpacing(4)
        bar.addWidget(self.mute_btn)
        bar.addWidget(self.volume_slider)
        lay.addWidget(self._transport)
        self._apply_cards()
        qconfig.themeChanged.connect(lambda *_: self._apply_cards())

        self._set_enabled(self._view is not None)
        self._poll = QTimer(self)
        self._poll.setInterval(50)
        self._poll.timeout.connect(self._tick)
        self._player = AudioPlayer()
        self._track_idx = 0
        self._video_id = ""
        self._video_state = None      # (secondes, en lecture, vitesse) lu dans mpv
        self._seek_lock = 0.0
        self._seek_target = None
        self._tick_busy, self._tick_sent, self._tick_warned = False, 0.0, 0.0
        self._resume = None           # (mesure, décalage dans la mesure en s, lecture en cours) pendant un changement d'audio
        self._audio_timer = QTimer(self)                 # regroupe les clics rapides en UN seul chargement mpv
        self._audio_timer.setSingleShot(True)
        self._audio_timer.setInterval(300)
        self._audio_timer.timeout.connect(self._start_audio)
        # Barre espace = lecture / pause (raccourci Qt ; PAS de filtre d'évènements global : il fait planter PySide6).
        self._space = QShortcut(QKeySequence(Qt.Key_Space), self)
        self._space.setContext(Qt.WidgetWithChildrenShortcut)
        self._space.activated.connect(self._space_pressed)
        # marque-pages : Ctrl+B pose / retire à la mesure courante, Ctrl+←/→ saute au précédent / suivant
        self._bkm_keys = []
        for seq, fn in (("Ctrl+B", self._toggle_bookmark_here), ("Ctrl+Left", lambda: self._step_bookmark(-1)),
                        ("Ctrl+Right", lambda: self._step_bookmark(1))):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self._bkm_keys.append(sc)
        for seq, fn in ((("Ctrl++", "Ctrl+="), lambda: self._step_zoom(1)), (("Ctrl+-",), lambda: self._step_zoom(-1)),
                        (("Ctrl+0",), lambda: self._set_zoom(1.0))):
            for sq in seq:
                sc = QShortcut(QKeySequence(sq), self)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(fn)
                self._bkm_keys.append(sc)
        self._update_bookmark_btn()
        self._update_preset_btn()
        QApplication.instance().focusChanged.connect(self._focus_changed)
        self._dragging = False
        self._duration = 0.0
        saved = load_settings()["tabs"]
        self.url_edit.setText(saved.get("url", ""))
        self._committed_url = saved.get("url", "").strip()
        self._apply_volume()                                       # volume / muet de la dernière fois
        if saved.get("url") and saved.get("preload", True):        # dernière partition rechargée au lancement
            QTimer.singleShot(1200, self._preload_last)

    def _apply_view_background(self):
        """Couleur de fond de la vue web (identique à celle de la page : --bg de tab_view.html)."""
        if self._view is None:
            return
        col = QColor(score_bg())
        self.setStyleSheet(f"TabInterface{{background:{pal()['bg']}}}")
        self._view.page().setBackgroundColor(col)
        self._view.setStyleSheet(f"background:{col.name()};border-radius:9px")
        self._sync_page_theme()

    def _apply_cards(self):
        """Style des « cartes » (partition, barre de lecture), selon le thème."""
        card = getattr(self, "_score_card", None)
        if card is not None:
            card.setStyleSheet(card_style("#scoreCard", radius=12))
        self._transport.setStyleSheet(card_style("#transport", radius=14))
        self.url_edit.apply_theme()

    # ---------- en-tête : saisie, panneau, zoom, vitesse ----------
    def _end_edit(self):
        """Fin de la saisie (clic ailleurs, Échap) : retour à l'affichage du titre, le champ reprend le lien du morceau affiché."""
        self._close_popup()
        self._search_timer.stop()
        self.title_field.finish_edit()
        self._release_text_focus()
        if self._worker is None and self.url_edit.text().strip() != self._committed_url:
            self.url_edit.setText(self._committed_url)

    def _toggle_panel(self, on: bool):
        if getattr(self, "track_list", None) is not None:
            self.track_list.setVisible(on)
        update_settings({"tabs": {**load_settings()["tabs"], "panel_open": bool(on)}})

    ZOOMS = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0)

    def _step_zoom(self, direction: int):
        z = self._zoom
        nxt = [v for v in self.ZOOMS if v > z + 1e-6] if direction > 0 else [v for v in self.ZOOMS if v < z - 1e-6][::-1]
        if nxt:
            self._set_zoom(nxt[0])

    def _set_zoom(self, z: float):
        z = max(self.ZOOMS[0], min(self.ZOOMS[-1], float(z)))
        if abs(z - self._zoom) < 1e-6:
            return
        self._zoom = z
        self.zoom_btn.setText(f"{round(z * 100)} %")
        self.zoom_out_btn.setEnabled(z > self.ZOOMS[0] + 1e-6)
        self.zoom_in_btn.setEnabled(z < self.ZOOMS[-1] - 1e-6)
        update_settings({"tabs": {**load_settings()["tabs"], "scale": z}})
        if self._page_ready and self._score is not None:
            self._js(f"melos.setScale({z})")

    def _open_speeds(self):
        self._speed_popup.popup_for(self.speed_btn, self.speed_combo.currentIndex())

    def _preload_last(self):
        """Recharge la dernière partition ouverte (sans rien lancer). Annulé si l'utilisateur a déjà chargé ou modifié le lien."""
        saved = load_settings()["tabs"]
        if self._view is None or self._score is not None or self._worker is not None:
            return
        if self.url_edit.text().strip() != saved.get("url", "").strip():
            return
        self.load_from_edit()

    # ---------- recherche par nom ----------
    def _on_text_edited(self, text: str):
        self._search_token += 1                          # une saisie rend caduque la recherche en cours
        if looks_like_url(text) or len(text.strip()) < 2:
            self._search_timer.stop()
            self._close_popup()
            return
        self._search_timer.start()                       # on attend la fin de la frappe

    def _on_enter(self):
        text = self.url_edit.text().strip()
        if not text or looks_like_url(text):
            self.load_from_edit()
        elif self._search_timer.isActive():
            self._search_timer.stop()
            self._run_search()

    def _run_search(self):
        query = self.url_edit.text().strip()
        if len(query) < 2 or looks_like_url(query):
            return
        self._search_token += 1
        token = self._search_token
        dbg("recherche", repr(query))
        self.set_status("Recherche…")
        w = SearchWorker(token, query, self)
        w.done.connect(self._on_hits)
        w.failed.connect(self._on_search_failed)
        w.finished.connect(lambda w=w: self._search_done(w))
        self._search_workers.append(w)
        w.start()

    def _search_done(self, w):
        w.wait()
        if w in self._search_workers:
            self._search_workers.remove(w)
        w.deleteLater()

    def _on_hits(self, token: int, hits):
        if token != self._search_token or not self.url_edit.hasFocus():
            return                                       # réponse périmée, ou champ quitté entre-temps
        dbg("recherche :", len(hits), "résultats")
        self.set_status("" if hits else "Aucun résultat")
        self._popup.set_hits(hits)
        self.url_edit.popup_open = True
        self._popup.show_under(self.url_edit)

    def _on_search_failed(self, token: int, message: str):
        if token == self._search_token:
            self.set_status(message)

    def _close_popup(self):
        self.url_edit.popup_open = False
        self._popup.hide()

    def _choose_hit(self, hit):
        if hit is None:
            return
        self._close_popup()
        self._search_timer.stop()
        dbg("recherche : choisi", hit.song_id, hit.title, "-", hit.artist)
        self.url_edit.setText(hit.url)
        self.load_from_edit()

    # ---------- morceaux (historique / favoris) ----------
    def _choose_entry(self, entry):
        dbg("bibliothèque : choisi", entry.song_id, entry.label)
        self._close_popup()
        self._search_timer.stop()
        self.url_edit.setText(entry.url)
        self.load_from_edit()

    def _toggle_favorite(self):
        if self._score is not None:
            self.library.toggle_favorite(self._score.song_id)

    def _update_star(self):
        on = self._score is not None and self.library.is_favorite(self._score.song_id)
        self.star_btn.set_on(on)
        self.star_btn.setEnabled(self._score is not None)
        if self._score is None:
            self.star_btn.setToolTip("Charge un morceau pour pouvoir le mettre en favori")

    # ---------- marque-pages ----------
    def _bookmark_pairs(self) -> list:
        if self._score is None:
            return []
        return [[b["bar"], b["name"]] for b in self.library.bookmarks(self._score.song_id)]

    def _bookmark_hint(self, bar: int) -> str:
        """Nom proposé pour un marque-page : titre de section de la mesure (« Chorus »), sinon « Chorus (mes. 20) » si on est
        dedans, sinon vide (le modèle met « Mesure N »)."""
        if self._score is None or not self._score.tracks:
            return ""
        marks = [(b, str(t)) for b, t in markers_for(self._score.tracks[self._track_idx]) if b <= bar]
        if not marks:
            return ""
        b, text = marks[-1]
        return text if b == bar else f"{text} (mes. {bar + 1})"

    def _update_bookmark_btn(self):
        n = len(self._bookmark_pairs())
        self.bkm_btn.setText(str(n) if n else "")                       # icône seule (+ le nombre de marque-pages)
        self.bkm_btn.setEnabled(self._score is not None)

    def _on_bookmarks_changed(self):
        self._update_bookmark_btn()
        self._update_preset_btn()
        pairs = self._bookmark_pairs()
        if pairs != self._bkm_sent and self._page_ready and self._score is not None:
            self._bkm_sent = pairs
            self._js(f"melos.setBookmarks({json.dumps(pairs)})")

    def _open_bookmarks(self):
        if self._score is not None:
            self._bkm_popup.popup_at(self.bkm_btn, self._score.song_id, self.current_bar)

    # ---------- changements de preset ----------
    def set_amp(self, state, sender, names=None):
        """Relie la page à l'ampli (AmpState + MidiSender) et à la bibliothèque de presets (SlotNames)."""
        self._state, self._sender, self._names = state, sender, names
        self._pre_popup.names = names
        if names is not None:
            names.changed.connect(self._on_presets_changed)

    def _preset_quads(self) -> list:
        """[[mesure, numéro d'emplacement ou "", couleur, nom, avertissement, état, temps]] : ce que la page dessine."""
        if self._score is None:
            return []
        out = []
        for m in self.library.preset_marks(self._score.song_id):
            r = resolve_preset(self._names, m)
            warn = r["note"] if r["status"] in ("ahead", "changed", "missing", "deleted") else ""
            out.append([m["bar"], str(r["slot"] + 1) if r["slot"] is not None else "", slot_color(r["slot"]), r["name"], warn, r["status"], m.get("beat", 0)])
        return out

    def _update_preset_btn(self):
        n = len(self.library.preset_marks(self._score.song_id)) if self._score is not None else 0
        self.pre_btn.setText(str(n) if n else "")                # icône + nombre : la barre du bas manque de place pour un libellé
        self.pre_btn.setEnabled(self._score is not None)

    def _on_presets_changed(self):
        self._update_preset_btn()
        quads = self._preset_quads()
        if quads != self._pre_sent and self._page_ready and self._score is not None:
            self._pre_sent = quads
            self._js(f"melos.setPresets({json.dumps(quads)})")
        if self._was_playing:                       # on a posé / retiré un changement (ou chargé un preset) pendant la lecture
            self._apply_preset(self.current_bar)

    def _open_presets(self, anchor=None, bar: int | None = None, page: str | None = None, beat: int = 0):
        if self._score is not None:
            self._pre_popup.popup_at(anchor or self.pre_btn, self._score.song_id, self.current_bar if bar is None else bar, page, beat)

    def _on_preset_auto(self, on: bool):
        self._preset_auto = bool(on)
        update_settings({"tabs": {**load_settings()["tabs"], "preset_auto": self._preset_auto}})
        self._auto_key = None
        if on and self._was_playing:
            self._apply_preset(self.current_bar)

    def _place_preset(self, target: dict, bar: int, beat: int = 0):
        """Pose un changement vers `target` ({"entry": id, "name"} de la bibliothèque, ou {"slot": n}) à la mesure `bar`,
        au temps `beat` (0 = début de mesure)."""
        if self._score is None or bar < 0:
            return
        sid = self._score.song_id
        if target.get("entry"):
            self.library.set_preset_entry(sid, bar, target["entry"], target.get("name", ""), beat)
        else:
            self.library.set_preset_mark(sid, bar, int(target.get("slot", 0)), beat)
        res = resolve_preset(self._names, target)
        self.set_status(f"Mesure {bar + 1}{f', temps {beat + 1}' if beat else ''} : {res['name']}" + (f" — {res['note']}" if res["note"] else ""))

    def _beat_in_bar(self, bar: int, frac: float) -> int:
        """Temps (0 = premier) où l'on est dans la mesure `bar` à la fraction `frac` (0-1) ; avance de ~0,1 temps pour que
        l'ordre parte un peu avant le temps visé (le MIDI et l'ampli ont un petit délai)."""
        tracks = self._score.tracks if self._score is not None else []
        meas = tracks[self._track_idx].measures if tracks and self._track_idx < len(tracks) else []
        n = meas[bar].signature[0] if 0 <= bar < len(meas) else 4
        return max(0, min(n - 1, int(frac * n + 0.1)))

    def _apply_preset(self, bar: int, frac: float = 0.0):
        """Pendant la lecture : envoie à l'ampli le preset en vigueur à la mesure `bar` (et au temps correspondant à `frac`)
        s'il n'est pas déjà celui qu'on a traité.
        Le changement vise un preset de la bibliothèque : on l'envoie à l'emplacement où il est chargé ; s'il n'est dans aucun
        emplacement, rien n'est envoyé (il faudrait écraser un emplacement) et on le dit."""
        if not (self._preset_auto and self._was_playing and self._score is not None and self._sender is not None):
            return
        sid = self._score.song_id
        if not self.library.preset_marks(sid):
            return
        m = self.library.active_preset(sid, max(bar, 0), self._beat_in_bar(max(bar, 0), frac) if bar >= 0 else 0)
        if m is None:
            return
        res = resolve_preset(self._names, m)
        key = (m["bar"], m.get("beat", 0), res["slot"], res["status"])
        if key == self._auto_key:
            return
        self._auto_key = key
        slot = res["slot"]
        if slot is None:
            self.set_status(f"« {res['name']} » : {res['note']} ({self._where(m)})")
            return
        if not self._sender.is_open:
            self.set_status(f"Ampli non connecté : preset {slot + 1} non envoyé ({self._where(m)})")
            return
        self._sender.set_preset(slot)
        if self._state is not None:
            self._state.on_preset_changed(slot)         # mise à jour optimiste, comme la setlist
        self.set_status(f"Preset {slot + 1} — {res['name']} ({self._where(m)})")
        dbg("preset auto", slot, "mesure", m["bar"], "temps", m.get("beat", 0))

    @staticmethod
    def _where(m: dict) -> str:
        return f"mesure {m['bar'] + 1}" + (f", temps {m['beat'] + 1}" if m.get("beat") else "")

    # ---------- clic droit : menu « ici » ----------
    def _on_context(self, d: dict):
        if self._score is None or self._view is None:
            return
        bar, beat = int(d.get("bar", -1)), max(0, int(d.get("beat") or 0))
        if bar < 0:
            return
        sid = self._score.song_id
        pos = self._view.mapToGlobal(QPoint(int(d.get("x", 0)), int(d.get("y", 0))))
        menu = ScoreMenu(self)
        menu.set_title(f"Mesure {bar + 1}" + (f" · {self._bookmark_hint(bar).split(' (')[0]}" if self._bookmark_hint(bar) else ""))
        has_bm = self.library.bookmark_at(sid, bar) is not None
        has_pre = self.library.preset_at(sid, bar, beat) is not None
        at = f" (temps {beat + 1})" if beat else ""
        if has_bm:
            menu.add_item("bookmark", "Retirer le marque-page", lambda: self.library.remove_bookmark(sid, bar), color=pal()["amber"])
        else:
            menu.add_item("bookmark", "Ajouter un marque-page ici",
                          lambda: self.library.add_bookmark(sid, bar, self._bookmark_hint(bar)), color=pal()["amber"])
        menu.add_item("pedal", ("Changer le preset ici" if has_pre else "Changement de preset ici") + at + "…",
                      lambda: self._open_presets(pos, bar, "add", beat), color=pal()["accent"])
        if has_pre:
            menu.add_item("close", "Retirer le changement de preset" + at, lambda: self.library.remove_preset_mark(sid, bar, beat))
        menu.add_separator()
        menu.add_item("play", "Lire à partir d'ici", lambda: self._goto_bar(bar))
        menu.add_separator()
        r = self._range["bars"] if self._range else None
        menu.add_item("loop", "Début de boucle ici", lambda: self._loop_from(bar), hint="" if not r else f"mes. {r[0] + 1} → {r[1] + 1}")
        menu.add_item("loop", "Fin de boucle ici", lambda: self._loop_to(bar))
        menu.add_item("loop", "Boucler cette mesure", lambda: self._set_range(bar, bar))
        if r:
            menu.add_item("close", "Effacer la boucle", self._clear_range)
        if self.edit.on and bar in self._edited_bars():
            menu.add_separator()
            menu.add_item("refresh", "Revenir à l'original (cette mesure)", lambda: self.edit.revert_bar(bar), color=pal()["amber"])
        elif not self.edit.on and self.library.edits(sid):
            menu.add_separator()
            mine = self.library.version(sid) == "modified"
            menu.add_item("music", "Afficher la partition de Songsterr" if mine else "Afficher Ma version",
                          lambda: self.library.set_version(sid, "original" if mine else "modified"))
        menu.popup_at(pos)
        self._ctx_menu = menu                                # garde une référence (la fenêtre se ferme toute seule)

    def _on_move_mark(self, d: dict):
        """Un marqueur (marque-page / changement de preset) glissé sur la partition d'une mesure à une autre."""
        if self._score is None:
            return
        sid, a, b = self._score.song_id, int(d["from"]), int(d["to"])
        if d.get("kind") == "preset":
            self.library.move_preset_mark(sid, a, b, int(d.get("fromBeat") or 0), int(d.get("toBeat") or 0))
        else:
            self.library.move_bookmark(sid, a, b)

    # ---------- glisser-déposer depuis les fenêtres du bas vers la partition ----------
    def _drag_begin(self, kind: str, payload, label: str, color: str):
        self._drag_end()
        ghost = DragGhost(label, color)
        ghost.show()
        self._drag = {"kind": kind, "payload": payload, "ghost": ghost, "t": 0.0}

    def _view_point(self, gpos: QPoint):
        """Position dans la page web (coordonnées client) si le point est au-dessus de la partition, sinon None."""
        if self._view is None:
            return None
        p = self._view.mapFromGlobal(gpos)
        return p if self._view.rect().contains(p) else None

    def _drag_move(self, gpos: QPoint):
        d = self._drag
        if d is None:
            return
        d["ghost"].follow(gpos)
        now = time.monotonic()
        if now - d["t"] < 0.03:
            return
        d["t"] = now
        p = self._view_point(gpos)
        fine = "true" if d["kind"] == "preset" else "false"                  # un preset se pose au temps près, un marque-page à la mesure
        self._js(f"melos.dragHover({p.x()}, {p.y()}, {fine})" if p is not None else "melos.dragCancel()")

    def _drag_drop(self, gpos: QPoint):
        d = self._drag
        if d is None:
            return
        p = self._view_point(gpos)
        kind, payload = d["kind"], d["payload"]
        self._drag_end()
        if p is None:
            self._js("melos.dragCancel()")
            return
        self._js(f"melos.dragEnd({p.x()}, {p.y()})", lambda bar: self._dropped_on(kind, payload, bar))

    def _drag_end(self):
        if self._drag is not None:
            self._drag["ghost"].close()
            self._drag = None

    def _dropped_on(self, kind: str, payload, bar):
        """`bar` : ce que renvoie la page au dépôt — {"bar": mesure, "beat": temps} (ou juste le numéro de mesure)."""
        beat = 0
        if isinstance(bar, dict):
            beat, bar = bar.get("beat") or 0, bar.get("bar")
        if not isinstance(bar, (int, float)) or isinstance(bar, bool) or bar < 0 or self._score is None:
            return
        bar, beat = int(bar), max(0, int(beat))
        if kind == "preset":
            self._place_preset(payload, bar, beat)
        else:
            self.library.add_bookmark(self._score.song_id, bar, self._bookmark_hint(bar))
            self.set_status(f"Marque-page posé à la mesure {bar + 1}")

    # ---------- « Ma version » : l'original + les modifications de l'utilisateur ----------
    def _edits_sig(self, sid: int):
        return (self.library.version(sid), self.library.edits(sid))

    def _display_score(self, orig: Score) -> Score:
        """La partition à afficher : « Ma version » si elle est choisie et contient des modifications, sinon l'original."""
        ver, edits = self._edits_sig(orig.song_id)
        return apply_edits(orig, edits) if ver == "modified" and edits else orig

    def _edited_bars(self) -> list[int]:
        if self._score is None or self._orig_score is None or self.library.version(self._score.song_id) != "modified":
            return []
        part = self._score.tracks[self._track_idx].part_id if self._score.tracks else None
        return edited_bars(self.library.edits(self._score.song_id), part)

    def _update_title(self):
        s = self._orig_score
        if s is None:
            return
        mine = self.library.version(s.song_id) == "modified" and bool(self.library.edits(s.song_id))
        self.title_field.set_track(s.title, f"{s.artist} · Ma version" if mine else s.artist)

    def _on_edits_changed(self):
        """La bibliothèque a changé : si les modifications ou la version affichée ne sont plus celles de la page, on la redessine."""
        if self._orig_score is None:
            return
        sig = self._edits_sig(self._orig_score.song_id)
        if sig == self._edit_sig:
            return
        self._edit_sig = sig
        self._score = self._display_score(self._orig_score)
        self._synth_tex = None
        self._update_title()
        self._reload_timer.start()
        if self.edit.on:
            self.edit.refresh()

    def _reload_now(self):
        """Redessine la partition avec le nouveau contenu (même page : la banque de sons et la lecture ne sont pas rechargées)."""
        if self._score is None or not self._page_ready or self._view is None or not self._score.tracks:
            return
        track = self._score.tracks[self._track_idx]
        if not track.measures:
            return
        if self._synth:
            if not self._synth_loaded:
                self._push()
                return
            self._synth_tex = to_alphatex(self._score)
            tex, idx = self._synth_tex, self._alpha_map().get(self._track_idx, 0)
        else:
            sync = self._current_sync()
            tex, idx = to_alphatex(self._score, part_ids=[track.part_id], sync=sync.bar_starts_ms if sync else None), 0
        self._js(f"melos.reload({json.dumps(tex)}, {json.dumps(lyrics_for(track))}, {json.dumps(markers_for(track))}, "
                 f"{json.dumps({'track': idx, 'edited': self._edited_bars()})})")

    # ---------- annuler / rétablir (Ctrl+Z, Ctrl+Y) ----------
    def _marks_snapshot(self):
        if self._score is None:
            return None
        sid = self._score.song_id
        return {"sid": sid, "bm": self.library.bookmarks(sid), "pre": self.library.preset_marks(sid), "ed": self.library.edits(sid)}

    @staticmethod
    def _marks_label(a: dict, b: dict) -> str:
        if a.get("ed") != b.get("ed"):
            return "modification de la partition"
        for key, noun in (("bm", "marque-page"), ("pre", "changement de preset")):
            x, y = a[key], b[key]
            if x == y:
                continue
            if len(y) > len(x):
                return f"{noun} posé" if key == "pre" else f"{noun} ajouté"
            if len(y) < len(x):
                return f"{noun} retiré"
            return f"{noun} déplacé" if [(m["bar"], m.get("beat", 0)) for m in x] != [(m["bar"], m.get("beat", 0)) for m in y] else f"{noun} modifié"
        return "modification"

    def _record_marks(self):
        """Appelé à chaque changement de la bibliothèque : compare les marqueurs du morceau affiché à l'état précédent."""
        now, last = self._marks_snapshot(), self._marks_last
        self._marks_last = now
        if now is None or last is None or last["sid"] != now["sid"] or last == now:
            return
        self._undo.record("marks", object(), last, now, self._marks_label(last, now))

    def _apply_undo(self, kind: str, values: dict) -> bool:
        if self._score is None or values.get("sid") != self._score.song_id:
            return False
        sid = self._score.song_id
        if kind == "marks":
            ed = values.get("ed")
            ok = self.library.restore_marks(sid, values["bm"], values["pre"], edits=ed,
                                            version="modified" if ed is not None and ed != self.library.edits(sid) else None)
            self._marks_last = self._marks_snapshot()
            return ok
        bars = values.get("bars")
        self._range_last = list(bars) if bars else None          # l'évènement de retour de la page ne doit pas être ré-enregistré
        if bars:
            self._set_range(bars[0], bars[1])
        else:
            self._clear_range()
        return True

    def undo_redo(self, redo: bool = False) -> str:
        """Annule / rétablit la dernière action de la page Partition (marqueurs, zone de boucle). Renvoie le texte à afficher."""
        sid = self._score.song_id if self._score is not None else None
        accept = lambda e: e.after.get("sid") == sid
        entry = (self._undo.redo if redo else self._undo.undo)(accept)
        if entry is None:
            return "Rien à rétablir" if redo else "Rien à annuler"
        return f"{'Rétabli' if redo else 'Annulé'} : {entry.label}"

    # ---------- zone de boucle ----------
    def _set_range(self, a: int, b: int):
        """Zone de boucle = mesures a..b (incluses) ; on active la boucle puisqu'on vient d'en choisir une."""
        if self._score is None:
            return
        self._js(f"melos.setRange({int(a)}, {int(b)})")
        if not self.loop_btn.isChecked():
            self.loop_btn.setChecked(True)

    def _loop_from(self, bar: int):
        end = self._range["bars"][1] if self._range and self._range["bars"][1] >= bar else 10 ** 6   # jusqu'à la fin du morceau
        self._set_range(bar, end)

    def _loop_to(self, bar: int):
        start = self._range["bars"][0] if self._range and self._range["bars"][0] <= bar else max(0, min(self.current_bar, bar))
        self._set_range(start, bar)

    def _clear_range(self):
        self._js("melos.clearRange()")

    def _on_range(self, data):
        if data:
            lo, hi = data["bars"]
            self._range = {"bars": [int(lo), int(hi)], "t0": float(data["t0"]) / 1000.0, "t1": float(data["t1"]) / 1000.0}
            if not self.loop_btn.isChecked():                    # choisir une zone = vouloir la boucler
                self.loop_btn.setChecked(True)
        else:
            self._range = None
        new = list(self._range["bars"]) if self._range else None
        old, self._range_last = self._range_last, new
        if self._score is not None:
            sid = self._score.song_id
            self._undo.record("range", object(), {"sid": sid, "bars": old}, {"sid": sid, "bars": new},
                              "zone de boucle" if new else "zone de boucle effacée")
        self._update_range_ui()

    def _update_range_ui(self):
        r = self._range
        if r:
            self.seek_slider.setBand(int(r["t0"] * 10), int(r["t1"] * 10))
            self.loop_btn.setToolTip(f"Boucle sur les mesures {r['bars'][0] + 1} à {r['bars'][1] + 1} (clic droit sur la partition pour la changer ou l'effacer)")
        else:
            self.seek_slider.setBand(None)
            self.loop_btn.setToolTip("Boucle : rejoue la zone choisie (glisse sur des mesures, ou clic droit), ou tout le morceau s'il n'y en a pas")

    def _original_loop(self, sec: float, playing: bool):
        """Boucle en mode Original : mpv ne boucle pas tout seul. À la fin de la zone (ou du morceau), on revient au début."""
        last, self._loop_last = self._loop_last, (sec, playing)
        if last is None or not self.loop_btn.isChecked() or self._seek_target is not None or self._counting:
            return
        r = self._range
        t0, t1 = (r["t0"], r["t1"]) if r else (0.0, self._duration)
        if t1 <= t0:
            return
        if playing and last[0] < t1 <= sec + 0.02 and sec - t1 < 0.8:
            self._request_seek(t0)
        elif r is None and last[1] and not playing and self._duration and sec >= self._duration - 0.5:     # fin du morceau
            self._request_seek(0.0)
            self._player.set_paused(False)

    # ---------- métronome et décompte du mode Original (clics produits par la page) ----------
    def _click_volume(self) -> float:
        return 0.15 + 0.6 * min(1.0, max(0.0, self._volume))

    def _original_start(self):
        """Lecture en mode Original, avec décompte (une mesure de clics au tempo de la mesure courante) si demandé."""
        st = self._video_state
        if self._counting:                                    # un second appui annule le décompte
            self._counting = False
            self._js("melos.stopClicks()")
            return
        if st is not None and not st[1] and self.count_btn.isChecked() and self._bar_starts:
            self._counting = True
            self.set_status("Décompte…")
            bar = max(0, self.current_bar)
            self._js(f"melos.countInBar({bar}, {float(st[2]) or 1.0:.3f})", self._count_started)
            return
        self._player.toggle()

    def _count_started(self, total_ms):
        if not self._counting:
            return
        QTimer.singleShot(int(total_ms or 0), self._count_done)

    def _count_done(self):
        if self._counting:
            self._counting = False
            self._player.set_paused(False)

    def _goto_bar(self, bar: int):
        """Saute au début de la mesure `bar` (0 = première), en Original comme en Synthèse, et la montre à l'écran."""
        if self._score is None or bar < 0:
            return
        if self._synth:
            if not self._synth_ready:
                self.set_status("Synthèse pas encore prête")
                return
            self._js(f"melos.synth.seekBar({int(bar)}, 0)")
        elif 0 <= bar < len(self._bar_starts):
            self._request_seek(self._bar_starts[bar] / 1000.0)
        else:                                               # pas de synchro audio : au moins le curseur de la partition
            self._js(f"melos.seekBar({int(bar)})")
        self._js(f"melos.revealBar({int(bar)})")

    def _toggle_bookmark_here(self):
        if self._score is None or self.current_bar < 0:
            self.set_status("Marque-pages : place d'abord le curseur sur la partition")
            return
        sid, bar = self._score.song_id, self.current_bar
        if self.library.bookmark_at(sid, bar):
            self.library.remove_bookmark(sid, bar)
            self.set_status(f"Marque-page retiré (mesure {bar + 1})")
        else:
            b = self.library.add_bookmark(sid, bar, self._bookmark_hint(bar))
            self.set_status(f"Marque-page posé : {b['name']}" if b else "Marque-page impossible")

    def _step_bookmark(self, direction: int):
        if self._score is None:
            return
        b = self.library.neighbour_bookmark(self._score.song_id, self.current_bar, direction)
        if b is None:
            self.set_status("Pas d'autre marque-page " + ("plus loin" if direction > 0 else "avant"))
            return
        self._goto_bar(b["bar"])
        self.set_status(f"Marque-page : {b['name']} (mesure {b['bar'] + 1})")

    def hideEvent(self, ev):
        self._close_popup()
        super().hideEvent(ev)

    # ---------- chargement ----------
    def _ensure_page(self):
        if self._view is None or self._server is not None:
            return
        self._server = tab_server.TabServer().start()
        self._view.load(QUrl(self._server.url))
        self._poll.start()

    def _set_enabled(self, on: bool):
        for name in ("url_edit", "lib_btn", "load_btn", "refresh_btn", "play_btn", "mode_switch", "panel_btn",
                     "seek_slider", "speed_btn", "pre_btn", "volume_slider", "mute_btn", "zoom_in_btn", "zoom_out_btn", "zoom_btn", "metro_btn", "count_btn", "loop_btn", "export_btn"):
            w = getattr(self, name, None)
            if w is not None:
                w.setEnabled(on)

    def load_from_edit(self, refresh: bool = False):
        url = self.url_edit.text().strip()
        if not url or self._worker is not None:
            return
        self.set_status("Téléchargement et vérification des vidéos…")
        self.load_btn.setEnabled(False)
        self._ensure_page()
        self._worker = _LoadWorker(url, bool(refresh), load_settings()["tabs"].get("country", "FR"), self)
        self._worker.done.connect(self._on_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _worker_finished(self):
        # Ne jamais lâcher un QThread encore en cours de fin (plantage 0xC0000005) : on attend sa sortie puis on le détruit
        # proprement.
        dbg("worker terminé")
        w, self._worker = self._worker, None
        if w is not None:
            w.wait()
            w.deleteLater()
        self.load_btn.setEnabled(self._view is not None)

    def _on_failed(self, message: str):
        self.set_status(message)
        if not self.title_field.editing:                     # le lien qui a échoué ne doit pas rester dans le champ
            self.url_edit.setText(self._committed_url)

    def _on_loaded(self, score: Score, syncs: list[VideoSync]):
        self._orig_score, self._syncs = score, syncs
        self.edit.stop()
        self._score = self._display_score(score)
        self._edit_sig = self._edits_sig(score.song_id)
        self._synth_tex, self._synth_loaded, self._synth_ready = None, False, False
        self._range, self._range_last = None, None
        self._update_range_ui()
        saved = load_settings()["tabs"]
        url = self.url_edit.text().strip()
        self._committed_url = url
        self._update_title()
        self.title_field.finish_edit()
        mem = self.library.get(score.song_id)                # piste / vidéo laissées la dernière fois sur CE morceau
        self.library.touch(score.song_id, url, score.title, score.artist)
        if self.library.seed_bookmarks(score.song_id, score.sections()):      # marque-pages par défaut : les sections de Songsterr
            self._marks_last = self._marks_snapshot()                          # (pas une action à annuler)
        update_settings({"tabs": {**saved, "url": url}})
        self.video_combo.blockSignals(True)
        self.video_combo.clear()
        self.video_combo.addItem("(sans audio)", userData="")
        for s in syncs:
            self.video_combo.addItem(f"{s.feature} · {(s.title or s.video_id)[:60]}", userData=s.video_id)
        want = (mem.video if mem and mem.video is not None else
                saved.get("video", "") if saved.get("url") == url else "")
        no_audio = bool(mem and mem.video == "")             # « sans audio » choisi explicitement la dernière fois
        self.video_combo.setCurrentIndex(0 if no_audio else
                                         next((i for i, s in enumerate(syncs, start=1) if s.video_id == want),
                                              1 if syncs else 0))
        self.video_combo.blockSignals(False)
        shown = [i for i, t in enumerate(score.tracks) if t.measures]
        idx = (mem.track if mem and mem.track >= 0 else
               int(saved.get("track", -1)) if saved.get("url") == url else -1)
        if idx not in shown:
            idx = next((i for i in shown if score.tracks[i].part_id == score.default_part), shown[0] if shown else 0)
        self._track_idx = idx
        # mode : celui de la dernière fois ; sans vidéo (ou sans banque de sons) il n'y a pas le choix
        want_synth = (saved.get("mode") == "synth" or not syncs) and self._synth_available(quiet=bool(syncs))
        self._apply_mode(want_synth)
        if want_synth:                                       # on ne garde pas l'audio du morceau précédent
            self._player.stop()
            self._video_id, self._video_state, self._seek_target = "", None, None
        self.track_list.set_tracks(score.tracks, idx, syncs, self._stem_overrides(), synth_mix=self._load_mix())
        self.track_list.set_current_video(self.video_combo.currentData() or "")
        self._marks_last = self._marks_snapshot()
        self._update_star()
        self._update_bookmark_btn()
        self._update_preset_btn()
        self._push()

    # ---------- association piste de la partition -> piste audio (choix manuel, mémorisé par morceau) ----------
    def _stem_overrides(self) -> dict[int, set]:
        if self._score is None:
            return {}
        saved = load_settings()["tabs"].get("stem_map", {}).get(str(self._score.song_id), {})
        by_part = {str(t.part_id): i for i, t in enumerate(self._score.tracks)}
        return {by_part[k]: set(v) for k, v in saved.items() if k in by_part}

    def _edit_mapping(self):
        from tabs.mixer import MixModel, universe
        if self._score is None or not self._syncs:
            return
        tracks = self._score.tracks
        stems = sorted(universe(self._syncs))
        titles = {s.track_hashes[0]: (s.title or s.video_id) for s in self._syncs
                  if s.feature == "solo" and len(s.track_hashes or []) == 1}
        auto = MixModel(self._syncs, tracks).track_stems
        dlg = StemDialog(tracks, stems, titles, auto, self._stem_overrides(), self.window())
        if dlg.exec() != StemDialog.Accepted:
            return
        chosen = dlg.result_map()
        settings = load_settings()["tabs"]
        book = dict(settings.get("stem_map", {}))
        book[str(self._score.song_id)] = {str(tracks[i].part_id): sorted(v) for i, v in chosen.items()}
        update_settings({"tabs": {**settings, "stem_map": book}})
        dbg("association pistes enregistrée", book[str(self._score.song_id)])
        self.track_list.set_tracks(tracks, self._track_idx, self._syncs, chosen)
        self.track_list.set_current_video(self.video_combo.currentData() or "")

    def _on_track(self, index: int):
        dbg("piste", index)
        self._track_idx = index
        if self._score is not None and self.edit.on:
            self.edit.track_changed()
        saved = load_settings()["tabs"]
        update_settings({"tabs": {**saved, "track": index}})
        if self._score is not None:
            self.library.remember(self._score.song_id, track=index)
        if self._synth and self._synth_loaded and self._score is not None:     # même partition : pas de rechargement
            track = self._score.tracks[index]
            a = self._alpha_map().get(index)
            if a is not None:
                self._js(f"melos.setTrack({a}, {json.dumps(lyrics_for(track))}, {json.dumps(markers_for(track))})")
                return
        self._push()

    def _on_video(self, _):
        self._switch_video(self.video_combo.currentData() or "")

    def _switch_video(self, video_id: str):
        """Change l'audio SANS recharger la partition : nouveaux points de synchro, reprise à la même mesure."""
        if video_id == self._video_id:
            return
        sync = next((s for s in self._syncs if s.video_id == video_id), None)
        if hasattr(self, "track_list"):
            self.track_list.set_current_video(video_id)
        saved = load_settings()["tabs"]
        update_settings({"tabs": {**saved, "video": video_id}})
        if self._score is not None:
            self.library.remember(self._score.song_id, video=video_id)
        idx = self.video_combo.findData(video_id)
        if idx >= 0 and idx != self.video_combo.currentIndex():
            self.video_combo.blockSignals(True)
            self.video_combo.setCurrentIndex(idx)
            self.video_combo.blockSignals(False)
        if sync is None:                                     # « sans audio »
            self._video_id, self._video_state, self._bar_starts = "", None, []
            self._resume = None
            self._audio_timer.stop()
            self._player.stop()
            return
        state, bar, old = self._video_state, self.current_bar, self._bar_starts
        new = list(sync.bar_starts_ms)
        if state is not None:                                # on mémorise l'endroit de la partition (mesure + décalage)
            off = state[0] - old[bar] / 1000.0 if 0 <= bar < len(old) else None
            self._resume = (bar, off, state[0], bool(state[1]))
        resume = self._resume or (-1, None, 0.0, False)
        rbar, off, absolute, playing = resume
        pos = new[rbar] / 1000.0 + off if off is not None and 0 <= rbar < len(new) else absolute
        self._bar_starts = new
        self._js(f"melos.setSync({json.dumps(new)})")
        self._video_id, self._video_state, self._seek_target = video_id, None, None
        self._start_at = (max(0.0, pos), playing)
        self.set_status("Audio : " + (sync.title or sync.feature))
        dbg("switch_video", video_id, f"reprise={pos:.2f}s lecture={playing}")
        self._audio_timer.start()                            # relancé à chaque clic : seul le dernier choix charge

    def _start_audio(self):
        if not self._video_id:
            return
        pos, playing = self._start_at
        try:
            self._player.load(self._video_id, start=pos, paused=not playing)
        except PlayerError as exc:
            self.set_status(str(exc))

    def _current_sync(self) -> VideoSync | None:
        vid = self.video_combo.currentData()
        return next((s for s in self._syncs if s.video_id == vid), None)

    def _push(self):
        """(Re)génère l'alphaTex de la piste affichée + les points de synchro de la vidéo choisie."""
        if self._score is None or not self._score.tracks:
            return
        track = self._score.tracks[self._track_idx]
        if not track.measures:
            return
        if self._synth:
            if self._synth_tex is None:                      # toutes les pistes : le synthétiseur joue toute la partition
                self._synth_tex = to_alphatex(self._score)
            opts = self._synth_opts()
            opts["track"] = self._alpha_map().get(self._track_idx, 0)
            self._bar_starts = []
            self.current_bar = -1
            self._pending = (self._synth_tex, "", opts)
            self._flush()
            return
        sync = self._current_sync()
        tex = to_alphatex(self._score, part_ids=[track.part_id], sync=sync.bar_starts_ms if sync else None)
        self._bar_starts = list(sync.bar_starts_ms) if sync else []
        self.current_bar = -1
        self._pending = (tex, sync.video_id if sync else "", {"mode": "original"})
        self._synth_loaded = False
        self._flush()

    def _flush(self):
        if not self._pending or not self._page_ready:
            return
        tex, video, opts = self._pending
        self._pending = None
        track = self._score.tracks[self._track_idx]
        opts = {**opts, "bookmarks": self._bookmark_pairs(), "presets": self._preset_quads(), "scale": self._zoom,
                "range": self._range["bars"] if self._range else None,
                "edited": self._edited_bars(), "edit": self.edit.on, "voice": self.edit.voice, "loopMode": self.loop_btn.isChecked()}
        self._bkm_sent, self._pre_sent = opts["bookmarks"], opts["presets"]
        dbg("melos.load", len(tex), "car.", opts.get("mode"))
        self._js(f"melos.load({json.dumps(tex)}, {json.dumps(isDarkTheme())}, {json.dumps(self._bar_starts)}, "
                 f"{json.dumps(lyrics_for(track))}, {json.dumps(markers_for(track))}, {json.dumps(opts)})")
        if opts.get("mode") == "synth":                      # mpv ne sert pas : la page web joue elle-même
            self._synth_loaded, self._synth_ready, self._synth_playing = True, False, False
            self.set_status("Synthèse : chargement de la banque de sons…")
            return
        self._set_video(video)
        self._video_state = None
        self._js(f"melos.click({str(self.metro_btn.isChecked()).lower()}, {self._click_volume():.2f})")
        self.set_status(f"{self._score.artist} — {self._score.title}")

    # ---------- audio (mpv) ----------
    def _set_video(self, video_id: str):
        if video_id == self._video_id:
            return
        self._video_id = video_id
        self._video_state = None
        self._resume = None
        dbg("set_video", video_id)
        if not video_id:
            self._player.stop()
            return
        try:
            self._player.load(video_id)
            self.set_status("Préparation de l'audio…")
        except PlayerError as exc:
            self.set_status(str(exc))

    def _toggle_play(self):
        if self._synth:
            if self._synth_ready:
                self._js("melos.synth.toggle()")
            return
        self._original_start()

    @staticmethod
    def _fmt(sec: float) -> str:
        sec = max(0, int(sec))
        return f"{sec // 60}:{sec % 60:02d}"

    def _slider_moved(self, value: int):
        if self._updating:
            return
        self._dragging = True
        self.time_label.setText(f"{self._fmt(value / 10)} / {self._fmt(self._duration)}")
        self._user_seek.start()

    def _do_user_seek(self):
        sec = self.seek_slider.value() / 10.0
        self._request_seek(sec)
        self._dragging = self.seek_slider.isSliderDown()
        if self._dragging:
            self._user_seek.start()

    def _update_controls(self, sec: float, playing: bool, dur: float):
        self._duration = dur or self._duration
        self.play_btn.setIconName("pause" if playing else "play")
        if playing != self._was_playing:                     # début / fin de lecture : on (ré)envoie le preset en vigueur à la reprise
            self._was_playing = playing
            self._auto_key = None
            if playing:
                self._apply_preset(self.current_bar)
        if self._dragging:
            return
        self._updating = True
        top = int(self._duration * 10) or 1
        if self.seek_slider.maximum() != top:
            self.seek_slider.setRange(0, top)
        self.seek_slider.setValue(int(sec * 10))
        self._updating = False
        self.time_label.setText(f"{self._fmt(sec)} / {self._fmt(self._duration)}")

    def _poll_video(self):
        self._player.pump()
        err = self._player.take_error()
        if err:
            self.set_status(f"Audio : {err[:160]}")
        if self._synth or not self._video_id:
            return
        st = self._player.state()
        if st is None:
            return
        sec, playing, rate, dur = st
        if self._seek_target is not None:
            target, deadline, retry_at, retried = self._seek_target
            now = time.monotonic()
            if abs(sec - target) < 1.5:
                self._seek_target = None                     # mpv est arrivé
                self._seek_floor = (target, now + 1.5)
            elif now < deadline:
                if now > retry_at and not retried:
                    self._player.seek(target)
                    self._seek_target = (target, deadline, retry_at, True)
                sec = target                                 # en attendant, on affiche la cible
            else:
                self._seek_target = None
                log.warning("mpv n'a pas sauté à %.1fs (position %.1fs)", target, sec)
                self.set_status(f"mpv n'a pas sauté à {self._fmt(target)} (il est à {self._fmt(sec)})")
        fl = getattr(self, "_seek_floor", None)
        if fl is not None and self._seek_target is None:
            # mpv se pose parfois quelques dizaines de ms AVANT la cible : cliquer sur une mesure affichait alors la précédente
            if time.monotonic() > fl[1]:
                self._seek_floor = None
            elif 0.0 < fl[0] - sec < 0.5:
                sec = fl[0]
        if self._video_state is None:
            self._resume = None
            self._js(f"melos.setDuration({dur * 1000.0})")
            self.set_status(f"{self._score.artist} — {self._score.title}" if self._score else "")
            if self._seek_after_load is not None:             # retour de la synthèse : on reprend là où elle en était
                target, play = self._seek_after_load
                self._seek_after_load = None
                self._player.set_speed(self._speed)
                self._request_seek(target)
                self._player.set_paused(not play)
        self._video_state = (sec, playing, rate)
        self._update_controls(sec, playing, dur)
        self._original_loop(sec, playing)
        self._js(f"melos.sync({sec * 1000.0:.1f}, {str(bool(playing)).lower()}, {float(rate):.3f})")
        self._on_time(sec * 1000.0)

    def _on_page_loaded(self, ok: bool):
        self._page_ready = bool(ok)
        self._sync_page_theme()
        self._flush()

    def _sync_page_theme(self):
        """Thème de la page d'accueil de la partition (avant tout chargement, sinon elle reste blanche en thème sombre)."""
        if self._page_ready and self._view is not None:
            self._view.page().runJavaScript(f"document.body.classList.toggle('dark', {'true' if isDarkTheme() else 'false'})")

    # ---------- page web ----------
    def _js(self, code: str, callback=None):
        if self._view is None:
            return
        page = self._view.page()
        page.runJavaScript(code, callback) if callback else page.runJavaScript(code)

    def _tick(self):
        if self._view is None or not self._page_ready:
            return
        self._view.page().runJavaScript("typeof melos !== 'undefined' ? melos.drain() : '[]'", self._on_events)

    def _on_events(self, raw):
        self._tick_busy = False
        try:
            events = json.loads(raw or "[]")
        except ValueError:
            return
        for ev in events:
            kind, data = ev.get("type"), ev.get("data")
            if kind == "log":
                if str(data).startswith("SONDE"):      # sonde de diagnostic de la page : dans melos_debug.log
                    logging.getLogger("melos.probe").warning("%s", data)
                dbg("page", data)
            elif kind == "error":
                self.set_status(f"alphaTab : {data}")
            elif kind == "range":                              # mêmes évènements dans les deux modes
                self._on_range(data)
            elif kind == "context":
                self._on_context(data)
            elif kind == "moveMark":
                self._on_move_mark(data)
            elif kind == "editsel":                            # un temps / une corde choisis dans la page (mode édition)
                self.edit.on_select(data)
            elif kind == "editkey":                            # touche tapée dans la page (mode édition)
                self.edit.on_key(data)
            elif kind == "zoom":                               # Ctrl + molette dans la page : même zoom que les boutons
                self._set_zoom(1.0) if not data else self._step_zoom(1 if data > 0 else -1)
            elif kind == "undo":                               # Ctrl+Z / Ctrl+Y pris par la page (focus dedans)
                win = self.window()
                if hasattr(win, "undo_redo"):
                    win.undo_redo(bool(data))
            elif self._synth and kind in ("pos", "state", "bar", "finished", "player-ready"):
                self._on_synth_event(kind, data)
            elif self._synth:                                  # évènements de l'ancien mode encore en file
                continue
            elif kind == "play":
                self._player.set_paused(False)
            elif kind == "pause":
                self._player.set_paused(True)
            elif kind == "seek":
                self._request_seek(float(data) / 1000.0)
            elif kind == "rate":
                self._player.set_speed(float(data))
        self._poll_video()           # après les évènements : un clic sur la partition ne doit pas être écrasé

    def _request_seek(self, sec: float):
        """Saut demandé (clic sur la partition ou barre de progression). mpv met un instant à répondre : tant qu'il n'est
        pas arrivé on affiche la CIBLE (sinon le curseur reviendrait en arrière), puis on contrôle le résultat."""
        sec = max(0.0, sec)
        if self._synth:
            self._js(f"melos.synth.seekMs({sec * 1000.0:.1f})")
            return
        self._player.seek(sec)
        now = time.monotonic()
        self._seek_target = (sec, now + 4.0, now + 1.0, False)   # cible, délai max, relance éventuelle, relancé ?
        log.info("saut demandé à %.2fs", sec)
        self.set_status(f"Saut à {self._fmt(sec)}")

    def _on_time(self, ms: float):
        starts = self._bar_starts
        if not starts:
            return
        bar = -1
        for i, t in enumerate(starts):
            if ms >= t:
                bar = i
            else:
                break
        self.current_frac = 0.0
        if bar >= 0:
            end = starts[bar + 1] if bar + 1 < len(starts) else starts[bar] + (starts[bar] - starts[bar - 1] if bar > 0 else 2000.0)
            self.current_frac = max(0.0, min(0.999, (ms - starts[bar]) / max(1.0, end - starts[bar])))
        if bar != self.current_bar:
            self.current_bar = bar
            self.bar_changed.emit(bar)
        elif self._was_playing:
            self._apply_preset(bar, self.current_frac)                  # même mesure : un changement posé sur un autre temps peut arriver

    # ---------- modes Original / Synthèse ----------
    def _synth_available(self, quiet: bool = False) -> bool:
        ok = tab_server.soundfont_installed()
        if not ok and not quiet:
            self.set_status("Synthèse impossible : aucune banque de sons (.sf2) dans tabs/vendor/alphatab/soundfont/")
        return ok

    def _apply_mode(self, synth: bool):
        self._synth = synth
        self.mode_switch.setCurrentItem("synth" if synth else "original")
        if hasattr(self, "track_list"):
            self.track_list.set_synth_mode(synth)
        self.play_btn.setIconName("play")

    def _original_position(self):
        """(mesure, position dans la mesure 0-1, lecture en cours ?) de l'audio original, ou None."""
        st, starts = self._video_state, self._bar_starts
        if st is None or not starts:
            return None
        ms = st[0] * 1000.0
        bar = max(0, min(len(starts) - 1, self.current_bar if self.current_bar >= 0 else 0))
        a = starts[bar]
        b = starts[bar + 1] if bar + 1 < len(starts) else a + (a - starts[bar - 1] if bar > 0 else 2000.0)
        return bar, max(0.0, min(0.999, (ms - a) / max(1.0, b - a))), bool(st[1])

    def _set_mode(self, mode: str):
        synth = mode == "synth"
        if synth == self._synth:
            return
        if synth and not self._synth_available():
            self.mode_switch.setCurrentItem("original")
            return
        if not synth and self._score is not None and not self._syncs:
            self.set_status("Pas de vidéo synchronisée pour ce morceau : seule la synthèse est possible")
            self.mode_switch.setCurrentItem("synth")
            return
        saved = load_settings()["tabs"]
        update_settings({"tabs": {**saved, "mode": mode}})
        if synth:
            pos = self._original_position()
            self._autoplay = bool(pos and pos[2])
            self._resume_synth = (pos[0], pos[1]) if pos else None
            self._player.set_paused(True)                         # l'enregistrement se tait ; mpv reste chargé
            self._audio_timer.stop()
            self._apply_mode(True)
        else:
            bar, frac = self._synth_pos
            playing = self._synth_playing
            self._js("melos.synth.pause()")
            self._apply_mode(False)
            self._synth_loaded = False
            starts = list(self._current_sync().bar_starts_ms) if self._current_sync() else []
            if starts:
                bar = max(0, min(len(starts) - 1, bar))
                nxt = starts[bar + 1] if bar + 1 < len(starts) else starts[bar] + (starts[bar] - starts[bar - 1] if bar else 2000.0)
                self._seek_after_load = ((starts[bar] + (nxt - starts[bar]) * frac) / 1000.0, playing)
            self._video_state = None
        if self._score is not None:
            self._push()
        for ms in (50, 500, 2500):                            # diagnostic : la fenêtre déborde-t-elle de l'écran ?
            QTimer.singleShot(ms, lambda ms=ms: self._log_window(ms))

    def _log_window(self, after_ms: int):
        try:
            w = self.window()
            scr = w.screen()
            av, sg = scr.availableGeometry(), scr.geometry()
            r = lambda q: f"{q.x()},{q.y()} {q.width()}x{q.height()}"
            logging.getLogger("melos.window").warning(
                "+%d ms après changement de mode : fenêtre=%s maximisée=%s plein écran=%s | zone utile=%s écran=%s | "
                "min fenêtre=%dx%d min page=%dx%d | vue=%s", after_ms, r(w.geometry()), w.isMaximized(), w.isFullScreen(),
                r(av), r(sg), w.minimumSizeHint().width(), w.minimumSizeHint().height(),
                self.minimumSizeHint().width(), self.minimumSizeHint().height(),
                f"{self._view.width()}x{self._view.height()}" if self._view is not None else "-")
        except Exception:
            pass

    def _alpha_map(self) -> dict[int, int]:
        """indice de piste de la partition -> indice de piste côté alphaTab (seules les pistes avec notes y sont)."""
        if self._score is None:
            return {}
        return {i: k for k, i in enumerate(i for i, t in enumerate(self._score.tracks) if t.measures)}

    def _synth_opts(self) -> dict:
        solo, mute, vol = self.track_list.synth_state() if hasattr(self, "track_list") else (set(), set(), {})
        a = self._alpha_map()
        opts = {"mode": "synth", "soundFont": tab_server.soundfont_url("auto"), "speed": self._speed, "volume": self._volume,
                "metronome": self.metro_btn.isChecked(), "countIn": self.count_btn.isChecked(), "loop": self.loop_btn.isChecked(),
                "solo": [a[i] for i in sorted(solo) if i in a], "mute": [a[i] for i in sorted(mute) if i in a],
                "vol": {str(a[i]): v for i, v in vol.items() if i in a}}
        if self._resume_synth is not None:
            opts["bar"], opts["frac"] = self._resume_synth
            self._resume_synth = None
        return opts

    def _on_synth_event(self, kind: str, data):
        if kind == "pos":
            self._synth_pos = (int(data["bar"]), float(data["frac"]))
            self.current_frac = max(0.0, min(0.999, float(data["frac"])))
            self._update_controls(data["ms"] / 1000.0, self._synth_playing, data["dur"] / 1000.0)
            if int(data["bar"]) == self.current_bar:
                self._apply_preset(self.current_bar, self.current_frac)
            self._set_bar(int(data["bar"]))
        elif kind == "state":
            self._synth_playing = bool(data)
            self.play_btn.setIconName("pause" if data else "play")
        elif kind == "bar":
            self.current_frac = 0.0
            self._set_bar(int(data))
        elif kind == "finished":
            self._synth_playing = False
            self.play_btn.setIconName("play")
        elif kind == "player-ready":
            self._synth_ready = True
            if self._score is not None:
                self.set_status("Synthèse prête")
            if self._autoplay:
                self._autoplay = False
                self._js("melos.synth.toggle()")

    def _set_bar(self, bar: int):
        if bar != self.current_bar:
            self.current_bar = bar
            self.bar_changed.emit(bar)

    def _on_speed(self, _=None):
        self._speed = float(self.speed_combo.currentData())
        if self._synth:
            self._js(f"melos.synth.speed({self._speed})")
        else:
            self._player.set_speed(self._speed)

    def _on_volume(self, value: int, save: bool = True):
        if self._muted and value > 0 and self.sender() is self.volume_slider:
            self._muted = False                                # toucher au curseur rétablit le son
        self._apply_volume()
        if save:
            saved = load_settings()["tabs"]
            update_settings({"tabs": {**saved, "volume": int(value), "muted": self._muted}})

    def _toggle_mute(self):
        self._muted = not self._muted
        if not self._muted and self.volume_slider.value() == 0:
            self.volume_slider.setValue(50)
        self._apply_volume()
        saved = load_settings()["tabs"]
        update_settings({"tabs": {**saved, "muted": self._muted}})

    def _apply_volume(self):
        value = self.volume_slider.value()
        self._volume = 0.0 if self._muted else volume_gain(value)
        self._player.set_volume(self._volume)
        if self._synth and self._synth_loaded:
            self._js(f"melos.synth.volume({self._volume})")
        elif not self._synth and self._page_ready:
            self._js(f"melos.click({str(self.metro_btn.isChecked()).lower()}, {self._click_volume():.2f})")
        off = self._muted or value == 0
        self.mute_btn.setIconName("volume-x" if off else "volume-low" if value < 40 else "volume")
        self.mute_btn.setToolTip("Rétablir le son" if off else "Couper le son")
        self.volume_slider.setToolTip("Son coupé" if off else f"Volume : {value} %")

    def _synth_toggle(self, kind: str, on: bool):
        call = {"metronome": "metronome", "count_in": "countIn", "loop": "loop"}[kind]
        if self._synth:
            if self._synth_loaded:
                self._js(f"melos.synth.{call}({str(bool(on)).lower()})")
        elif kind == "metronome" and self._page_ready:             # mode Original : clics produits par la page
            self._js(f"melos.click({str(bool(on)).lower()}, {self._click_volume():.2f})")
        saved = load_settings()["tabs"]
        update_settings({"tabs": {**saved, "synth": {**saved.get("synth", {}), kind: bool(on)}}})

    # mute / solo / volumes par piste (propres à chaque morceau)
    def _on_mix_changed(self):
        solo, mute, vol = self.track_list.synth_state()
        a = self._alpha_map()
        if self._synth_loaded:
            self._js(f"melos.synth.mix({json.dumps([a[i] for i in sorted(solo) if i in a])}, "
                     f"{json.dumps([a[i] for i in sorted(mute) if i in a])}, "
                     f"{json.dumps({str(a[i]): v for i, v in vol.items() if i in a})})")
        if self._score is None:
            return
        parts = [t.part_id for t in self._score.tracks]
        saved = load_settings()["tabs"]
        book = dict(saved.get("synth_mix", {}))
        entry = {"solo": [parts[i] for i in sorted(solo)], "mute": [parts[i] for i in sorted(mute)],
                 "vol": {str(parts[i]): round(v, 2) for i, v in vol.items()}}
        if entry["solo"] or entry["mute"] or entry["vol"]:
            book[str(self._score.song_id)] = entry
        else:
            book.pop(str(self._score.song_id), None)
        update_settings({"tabs": {**saved, "synth_mix": book}})

    def _load_mix(self):
        if self._score is None:
            return set(), set(), {}
        entry = load_settings()["tabs"].get("synth_mix", {}).get(str(self._score.song_id), {})
        by_part = {t.part_id: i for i, t in enumerate(self._score.tracks)}
        pick = lambda key: {by_part[p] for p in entry.get(key, []) if p in by_part}
        vol = {by_part[int(p)]: float(v) for p, v in entry.get("vol", {}).items() if int(p) in by_part}
        return pick("solo"), pick("mute"), vol

    def _export_midi(self):
        if not self._synth_loaded or self._score is None:
            return
        self._js("melos.synth.exportMidi()", self._save_midi)

    def _save_midi(self, b64):
        import base64
        import re
        from pathlib import Path
        if not b64 or self._score is None:
            self.set_status("Export MIDI impossible")
            return
        name = re.sub(r'[\\/:*?"<>|]', "", f"{self._score.artist} - {self._score.title}").strip() or "partition"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en MIDI", str(Path.home() / f"{name}.mid"), "Fichier MIDI (*.mid)")
        if not path:
            return
        try:
            Path(path).write_bytes(base64.b64decode(b64))
            self.set_status(f"MIDI enregistré : {path}")
        except OSError as exc:
            self.set_status(f"Export MIDI impossible : {exc}")

    def set_status(self, text: str):
        self.status.set_full(text)

    def _focus_changed(self, _old, new):
        # dans un champ texte, l'espace sert à écrire
        typing = isinstance(new, (QLineEdit, QTextEdit, QAbstractSpinBox))
        self._space.setEnabled(not typing)
        for sc in getattr(self, "_bkm_keys", []):          # dans un champ texte, Ctrl+←/→ déplacent le curseur de texte
            sc.setEnabled(not typing)

    def _release_text_focus(self):
        """Un morceau vient de se charger : si le champ de recherche a encore le focus, la barre espace y écrivait un espace au lieu de
        lancer la lecture (il fallait cliquer ailleurs). Le focus passe à la page."""
        w = QApplication.focusWidget()
        if w is not None and isinstance(w, (QLineEdit, QTextEdit, QAbstractSpinBox)) and (w is self or self.isAncestorOf(w)):
            w.clearFocus()
            if self._view is not None:
                self._view.setFocus()
        self._space.setEnabled(True)
        for sc in getattr(self, "_bkm_keys", []):
            sc.setEnabled(True)

    def _space_pressed(self):
        if self._synth:
            self._toggle_play()
        elif self._video_id and self._player.state() is not None:
            dbg("espace -> lecture/pause")
            self._toggle_play()

    def stop(self):
        self._search_timer.stop()
        self._popup.close()
        for w in list(self._search_workers):
            w.wait(3000)
        self._audio_timer.stop()
        self._poll.stop()
        self._player.shutdown()
        if self._server is not None:
            self._server.stop()
            self._server = None