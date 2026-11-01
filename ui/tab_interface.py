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

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QFileDialog, QHBoxLayout, QLineEdit, QTextEdit,
                               QVBoxLayout, QWidget)
from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox, FluentIcon, LineEdit, PrimaryPushButton,
                            PushButton, SegmentedWidget, Slider, ToggleButton, ToolButton, qconfig, isDarkTheme)

from paths import APP_DIR
from settings import load_settings, update_settings
from ui.song_search import SearchEdit, SearchPopup, SearchWorker, looks_like_url
from ui.stem_dialog import StemDialog
from ui.track_list import TrackList
from tabs import server as tab_server
from tabs.alphatex import lyrics_for, markers_for, playable_tracks, to_alphatex
from tabs.client import TabError, load_song
from tabs.debug import dbg
from tabs.model import Score
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
    """Page de navigation. Aucune dépendance au reste de l'appli : un futur module « marqueurs » lira
    `current_bar` / `bar_changed` pour envoyer les presets au bon moment."""

    bar_changed = Signal(int)                 # index de mesure (0 = première) sous le curseur

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TabInterface")
        self._score: Score | None = None
        self._syncs: list[VideoSync] = []
        self._worker: _LoadWorker | None = None
        self._server: tab_server.TabServer | None = None
        self._view = None
        self._page_ready = False
        self._pending: tuple[str, str] | None = None
        self.current_bar = -1
        self._bar_starts: list[float] = []
        self._synth = False                 # mode « Synthèse » actif ?
        self._synth_loaded = False          # la page contient la partition COMPLÈTE en mode synthèse (changement de piste sans rechargement)
        self._synth_ready = False           # banque de sons chargée, lecture possible
        self._synth_playing = False
        self._synth_pos = (0, 0.0)          # (mesure, position dans la mesure 0-1) lues dans le synthétiseur
        self._synth_tex: str | None = None
        self._range = None                  # boucle / sélection de mesures [première, dernière] ou None
        self._autoplay = False              # relancer la lecture dès que le synthétiseur est prêt
        self._seek_after_load = None        # (secondes, lecture ?) à appliquer à mpv quand il est prêt (retour en mode Original)
        self._speed = 1.0
        self._volume = 1.0
        self._resume_synth = None           # (mesure, position 0-1) où démarrer la synthèse après une bascule

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        row = QHBoxLayout()
        self.url_edit = SearchEdit(self)
        self.url_edit.setPlaceholderText("Nom d'un morceau (ex. « the adults are talking »), ou lien Songsterr")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self._on_enter)
        # recherche par nom : liste de résultats sous le champ
        self._popup = SearchPopup()
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
        self.url_edit.dismiss.connect(self._close_popup)
        self.load_btn = PrimaryPushButton("Charger", self)
        self.load_btn.clicked.connect(self.load_from_edit)
        self.refresh_btn = PushButton("Re-télécharger", self)
        self.refresh_btn.setToolTip("Ignore le cache et redemande le morceau à Songsterr")
        self.refresh_btn.clicked.connect(lambda: self.load_from_edit(refresh=True))
        row.addWidget(self.url_edit, 1)
        row.addWidget(self.load_btn)
        row.addWidget(self.refresh_btn)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.mode_switch = SegmentedWidget(self)
        self.mode_switch.addItem("original", "Original", lambda: self._set_mode("original"))
        self.mode_switch.addItem("synth", "Synthèse", lambda: self._set_mode("synth"))
        self.mode_switch.setCurrentItem("original")
        self.mode_switch.setToolTip("Original : l'enregistrement YouTube. Synthèse : la partition jouée par le synthétiseur MIDI")
        row2.addWidget(self.mode_switch)
        row2.addSpacing(12)
        # mode « Original » : choix de la vidéo
        self._video_box = QWidget(self)
        vb = QHBoxLayout(self._video_box)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.addWidget(BodyLabel("Vidéo", self))
        self.video_combo = ComboBox(self)
        self.video_combo.setMinimumWidth(200)
        self.video_combo.currentIndexChanged.connect(self._on_video)
        vb.addWidget(self.video_combo)
        vb.addSpacing(12)
        self.open_btn = PushButton("Ouvrir sur YouTube", self)
        self.open_btn.clicked.connect(self._open_external)
        vb.addWidget(self.open_btn)
        row2.addWidget(self._video_box)
        # mode « Synthèse » : métronome, décompte, boucle, export
        self._synth_box = QWidget(self)
        sb = QHBoxLayout(self._synth_box)
        sb.setContentsMargins(0, 0, 0, 0)
        saved_synth = load_settings()["tabs"].get("synth", {})
        self.metro_btn = ToggleButton(FluentIcon.STOP_WATCH, "Métronome", self)
        self.metro_btn.setToolTip("Clic de métronome pendant la lecture")
        self.count_btn = ToggleButton("Décompte", self)
        self.count_btn.setToolTip("Une mesure de clics avant le départ")
        self.loop_btn = ToggleButton(FluentIcon.ROTATE, "Boucle", self)
        self.loop_btn.setToolTip("Rejouer en boucle la sélection (glisse sur la partition pour choisir des mesures) "
                                 "ou, sans sélection, tout le morceau")
        self.metro_btn.setChecked(bool(saved_synth.get("metronome", False)))
        self.count_btn.setChecked(bool(saved_synth.get("count_in", False)))
        self.loop_btn.setChecked(bool(saved_synth.get("loop", False)))
        self.metro_btn.toggled.connect(lambda on: self._synth_toggle("metronome", on))
        self.count_btn.toggled.connect(lambda on: self._synth_toggle("count_in", on))
        self.loop_btn.toggled.connect(lambda on: self._synth_toggle("loop", on))
        self.sound_combo = ComboBox(self)
        self.sound_combo.setToolTip("Banque de sons de la synthèse")
        self.sound_combo.setMinimumWidth(190)
        self._fill_soundfonts()
        self.sound_combo.currentIndexChanged.connect(self._on_soundfont)
        self.clear_range_btn = PushButton("Effacer la sélection", self)
        self.clear_range_btn.clicked.connect(lambda: self._js("melos.synth.clearRange()"))
        self.clear_range_btn.hide()
        self.export_btn = PushButton(FluentIcon.SAVE, "Exporter MIDI", self)
        self.export_btn.setToolTip("Enregistre la partition (toutes les pistes) en fichier .mid")
        self.export_btn.clicked.connect(self._export_midi)
        for w in (self.sound_combo, self.metro_btn, self.count_btn, self.loop_btn, self.clear_range_btn, self.export_btn):
            sb.addWidget(w)
        row2.addWidget(self._synth_box)
        self._synth_box.hide()
        row2.addStretch(1)
        self.status = CaptionLabel("", self)
        row2.addWidget(self.status)
        lay.addLayout(row2)

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
            # la page web reste « active » même cachée (autre onglet) : pas de rechargement ni de flash au retour
            page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            page.recommendedStateChanged.connect(
                lambda _s, p=page: p.setLifecycleState(QWebEnginePage.LifecycleState.Active))
            self._view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            # le synthétiseur (WebAudio) démarre sur ordre de Python, sans clic dans la page : sans ceci Chromium le laisse muet
            self._view.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
            self.track_list = TrackList(self)
            self.track_list.selected.connect(self._on_track)
            self.track_list.video_wanted.connect(self._switch_video)
            self.track_list.edit_mapping.connect(self._edit_mapping)
            self.track_list.synth_mix_changed.connect(self._on_mix_changed)
            body = QHBoxLayout()
            body.setSpacing(8)
            body.addWidget(self.track_list)
            body.addWidget(self._view, 1)
            lay.addLayout(body, 1)
            self._set_enabled(True)
            self._view.loadFinished.connect(self._on_page_loaded)

        # --- commandes de lecture ---
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.play_btn = ToolButton(FluentIcon.PLAY, self)
        self.play_btn.setToolTip("Lecture / pause (barre espace)")
        self.play_btn.clicked.connect(self._toggle_play)
        self.time_label = CaptionLabel("0:00 / 0:00", self)
        self.time_label.setMinimumWidth(80)
        self.seek_slider = Slider(Qt.Horizontal, self)
        self.seek_slider.setRange(0, 1)
        # Tout changement de valeur NON déclenché par nous (clic, glissement, flèches) = demande de saut de l'utilisateur ;
        # on ne s'appuie pas sur sliderPressed/Released, que ce Slider n'émet pas de façon fiable. Léger délai pour ne
        # sauter qu'une fois pendant un glissement.
        self._updating = False
        self._user_seek = QTimer(self)
        self._user_seek.setSingleShot(True)
        self._user_seek.setInterval(120)
        self._user_seek.timeout.connect(self._do_user_seek)
        self.seek_slider.valueChanged.connect(self._slider_moved)
        self.speed_combo = ComboBox(self)
        for r in (0.25, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5):
            self.speed_combo.addItem(f"{r:g}×", userData=r)
        self.speed_combo.setCurrentIndex(self.speed_combo.findData(1.0))
        self.speed_combo.currentIndexChanged.connect(self._on_speed)
        self.volume_slider = Slider(Qt.Horizontal, self)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.valueChanged.connect(self._on_volume)
        bar.addWidget(self.play_btn)
        bar.addWidget(self.time_label)
        bar.addWidget(self.seek_slider, 1)
        bar.addWidget(BodyLabel("Vitesse", self))
        bar.addWidget(self.speed_combo)
        bar.addWidget(BodyLabel("Volume", self))
        bar.addWidget(self.volume_slider)
        lay.addLayout(bar)

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
        QApplication.instance().focusChanged.connect(self._focus_changed)
        self._dragging = False
        self._duration = 0.0
        saved = load_settings()["tabs"]
        self.url_edit.setText(saved.get("url", ""))

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
        for name in ("url_edit", "load_btn", "refresh_btn", "video_combo", "play_btn", "open_btn", "mode_switch",
                     "seek_slider", "speed_combo", "volume_slider", "metro_btn", "count_btn", "loop_btn", "export_btn", "sound_combo"):
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

    def _on_loaded(self, score: Score, syncs: list[VideoSync]):
        self._score, self._syncs = score, syncs
        self._synth_tex, self._synth_loaded, self._synth_ready, self._range = None, False, False, None
        self.clear_range_btn.hide()
        saved = load_settings()["tabs"]
        url = self.url_edit.text().strip()
        update_settings({"tabs": {**saved, "url": url}})
        self.video_combo.blockSignals(True)
        self.video_combo.clear()
        self.video_combo.addItem("(sans audio)", userData="")
        for s in syncs:
            self.video_combo.addItem(f"{s.feature} · {(s.title or s.video_id)[:60]}", userData=s.video_id)
        want = saved.get("video", "") if saved.get("url") == url else ""
        self.video_combo.setCurrentIndex(next((i for i, s in enumerate(syncs, start=1) if s.video_id == want),
                                              1 if syncs else 0))
        self.video_combo.blockSignals(False)
        shown = [i for i, t in enumerate(score.tracks) if t.measures]
        idx = int(saved.get("track", -1)) if saved.get("url") == url else -1
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
        saved = load_settings()["tabs"]
        update_settings({"tabs": {**saved, "track": index}})
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
        dbg("melos.load", len(tex), "car.", opts.get("mode"))
        self._js(f"melos.load({json.dumps(tex)}, {json.dumps(isDarkTheme())}, {json.dumps(self._bar_starts)}, "
                 f"{json.dumps(lyrics_for(track))}, {json.dumps(markers_for(track))}, {json.dumps(opts)})")
        if opts.get("mode") == "synth":                      # mpv ne sert pas : la page web joue elle-même
            self._synth_loaded, self._synth_ready, self._synth_playing = True, False, False
            self.set_status("Synthèse : chargement de la banque de sons…")
            return
        self._set_video(video)
        self._video_state = None
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
        self._player.toggle()

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
        self.play_btn.setIcon(FluentIcon.PAUSE if playing else FluentIcon.PLAY)
        if self._dragging:
            return
        self._updating = True
        top = int(self._duration * 10) or 1
        if self.seek_slider.maximum() != top:
            self.seek_slider.setRange(0, top)
        self.seek_slider.setValue(int(sec * 10))
        self._updating = False
        self.time_label.setText(f"{self._fmt(sec)} / {self._fmt(self._duration)}")

    def _open_external(self):
        from PySide6.QtGui import QDesktopServices
        if self._video_id:
            QDesktopServices.openUrl(QUrl(f"https://www.youtube.com/watch?v={self._video_id}"))

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
            elif now < deadline:
                if now > retry_at and not retried:
                    self._player.seek(target)
                    self._seek_target = (target, deadline, retry_at, True)
                sec = target                                 # en attendant, on affiche la cible
            else:
                self._seek_target = None
                log.warning("mpv n'a pas sauté à %.1fs (position %.1fs)", target, sec)
                self.set_status(f"mpv n'a pas sauté à {self._fmt(target)} (il est à {self._fmt(sec)})")
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
        self._js(f"melos.sync({sec * 1000.0:.1f}, {str(bool(playing)).lower()}, {float(rate):.3f})")
        self._on_time(sec * 1000.0)

    def _on_page_loaded(self, ok: bool):
        self._page_ready = bool(ok)
        self._flush()

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
                dbg("page", data)
            elif kind == "error":
                self.set_status(f"alphaTab : {data}")
            elif self._synth and kind in ("pos", "state", "bar", "finished", "range", "player-ready"):
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
        if bar != self.current_bar:
            self.current_bar = bar
            self.bar_changed.emit(bar)

    # ---------- modes Original / Synthèse ----------
    def _synth_available(self, quiet: bool = False) -> bool:
        ok = tab_server.soundfont_installed()
        if not ok and not quiet:
            self.set_status("Synthèse impossible : aucune banque de sons (.sf2) dans tabs/vendor/alphatab/soundfont/")
        return ok

    def _apply_mode(self, synth: bool):
        self._synth = synth
        self.mode_switch.setCurrentItem("synth" if synth else "original")
        self._video_box.setVisible(not synth)
        self._synth_box.setVisible(synth)
        if hasattr(self, "track_list"):
            self.track_list.set_synth_mode(synth)
        self.play_btn.setIcon(FluentIcon.PLAY)

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

    def _alpha_map(self) -> dict[int, int]:
        """indice de piste de la partition -> indice de piste côté alphaTab (seules les pistes avec notes y sont)."""
        if self._score is None:
            return {}
        return {i: k for k, i in enumerate(i for i, t in enumerate(self._score.tracks) if t.measures)}

    def _synth_opts(self) -> dict:
        solo, mute, vol = self.track_list.synth_state() if hasattr(self, "track_list") else (set(), set(), {})
        a = self._alpha_map()
        opts = {"mode": "synth", "soundFont": tab_server.soundfont_url(self._soundfont_choice()), "speed": self._speed, "volume": self._volume,
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
            self._update_controls(data["ms"] / 1000.0, self._synth_playing, data["dur"] / 1000.0)
            self._set_bar(int(data["bar"]))
        elif kind == "state":
            self._synth_playing = bool(data)
            self.play_btn.setIcon(FluentIcon.PAUSE if data else FluentIcon.PLAY)
        elif kind == "bar":
            self._set_bar(int(data))
        elif kind == "finished":
            self._synth_playing = False
            self.play_btn.setIcon(FluentIcon.PLAY)
        elif kind == "range":
            self._range = data
            self.clear_range_btn.setVisible(bool(data))
        elif kind == "player-ready":
            self._synth_ready = True
            if self._score is not None:
                self.set_status(f"{self._score.artist} — {self._score.title}  ·  synthèse prête")
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

    def _on_volume(self, value: int):
        self._volume = value / 100.0
        self._player.set_volume(self._volume)
        if self._synth and self._synth_loaded:
            self._js(f"melos.synth.volume({self._volume})")

    def _fill_soundfonts(self):
        """Liste des banques de sons installées dans le menu (la sélection enregistrée, sinon « auto » = la meilleure)."""
        fonts = tab_server.soundfonts()
        wanted = load_settings()["tabs"].get("soundfont", "auto")
        self.sound_combo.blockSignals(True)
        self.sound_combo.clear()
        for name, label in fonts:
            self.sound_combo.addItem(label, userData=name)
        names = [n for n, _ in fonts]
        self.sound_combo.setCurrentIndex(names.index(wanted) if wanted in names else 0)
        self.sound_combo.setVisible(len(fonts) > 1)             # une seule banque : rien à choisir
        self.sound_combo.blockSignals(False)

    def _soundfont_choice(self) -> str:
        return self.sound_combo.currentData() or "auto"

    def _on_soundfont(self, _=None):
        """Autre banque de sons : on recharge la synthèse en reprenant à la même place, et en relançant si ça jouait."""
        saved = load_settings()["tabs"]
        update_settings({"tabs": {**saved, "soundfont": self._soundfont_choice()}})
        if not (self._synth and self._score is not None):
            return
        self._autoplay = self._synth_playing
        self._resume_synth = self._synth_pos
        self._js("melos.synth.pause()")
        self._synth_loaded = False
        self._push()

    def _synth_toggle(self, kind: str, on: bool):
        call = {"metronome": "metronome", "count_in": "countIn", "loop": "loop"}[kind]
        if self._synth_loaded:
            self._js(f"melos.synth.{call}({str(bool(on)).lower()})")
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
        self.status.setText(text)

    def _focus_changed(self, _old, new):
        # dans un champ texte, l'espace sert à écrire
        self._space.setEnabled(not isinstance(new, (QLineEdit, QTextEdit, QAbstractSpinBox)))

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