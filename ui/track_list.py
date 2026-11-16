"""
Liste des pistes d'une partition, comme sur Songsterr : une ligne par instrument (icône colorée, nom, musicien) et deux
boutons — casque = isoler (solo), haut-parleur barré = couper (mute). Cliquer sur la ligne affiche sa tablature.

Mode « Original » : les boutons sont « intelligents » (cf. tabs/mixer.py) : grisés quand aucune version audio de Songsterr
ne permet le réglage, verts au survol pour montrer TOUTES les pistes concernées, bleu (solo) / rouge (mute) une fois actifs.
Mode « Synthèse » : tout est libre (plusieurs solos, plusieurs mutes) et chaque ligne a un curseur de volume.
L'engrenage de l'en-tête ouvre les réglages audio du mode Original : version audio (vidéo) et association des pistes.
Aucune barre de défilement horizontale : les textes sont rognés plutôt que de repousser les boutons.
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import qconfig

from tabs.debug import dbg
from tabs.mixer import Mix, MixModel, family
from ui import tab_icons
from ui.tab_widgets import ChoiceModel, PopupCard, TabButton, TabSlider
from ui.theme import INSTRUMENT_COLORS, card_style, mix, pal, rgba, scrollbar_qss


class _Elided(QWidget):
    """Texte rogné avec « … » plutôt que d'élargir la ligne. `label_cls` : seul son nom compte (« Caption » = petit, grisé)."""

    def __init__(self, label_cls, text: str, parent=None, fit: bool = False):
        super().__init__(parent)
        self._small = "Caption" in getattr(label_cls, "__name__", "")
        self._strong = "Strong" in getattr(label_cls, "__name__", "")
        self._text = text
        self._fit = fit                                  # fit : prend la largeur de son texte (sinon : celle qu'on lui laisse)
        self.setSizePolicy(QSizePolicy.Preferred if fit else QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)

    def _font(self) -> QFont:
        f = self.font()
        f.setPointSizeF(8.5 if self._small else 10)
        if self._strong:
            f.setWeight(QFont.Weight.DemiBold)
        return f

    def setText(self, text: str):
        self._text = text
        if self._fit:
            self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(QFontMetrics(self._font()).horizontalAdvance(self._text) + 2 if self._fit else 10,
                     QFontMetrics(self._font()).height() + 2)

    def paintEvent(self, ev):
        p = QPainter(self)
        f = self._font()
        p.setFont(f)
        p.setPen(QColor(pal()["muted" if self._small else "text"]))
        p.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(self._text, Qt.ElideRight, self.width()))


class StateButton(TabButton):
    """Bouton à états d'une ligne : repos / survol / actif (couleur du mode) / aperçu (vert, pistes concernées) / désactivé."""
    hovered = Signal(bool)

    def __init__(self, icon_name: str, active_color: str, tip: str, parent=None):
        super().__init__("", icon_name, "ghost", parent, color=active_color, height=30)
        self.on = False
        self.preview = False
        self.allowed = True
        self._tip = tip
        self.setToolTip(tip)
        self.setFixedSize(30, 30)

    def set_state(self, on: bool, allowed: bool):
        self.on, self.allowed = on, allowed
        self.setCheckable(True)
        self.setChecked(on)
        self.setEnabled(allowed or on)
        self.setCursor(Qt.PointingHandCursor if allowed else Qt.ForbiddenCursor)
        self.update()

    def set_preview(self, preview: bool):
        if preview != self.preview:
            self.preview = preview
            self.update()

    def enterEvent(self, ev):
        super().enterEvent(ev)
        self.hovered.emit(True)

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        self.hovered.emit(False)

    def _colors(self):
        if self.preview and not self.on:                       # aperçu : ce que ce clic mettrait en solo / muet
            p = pal()
            g = QColor(p["preview"])
            bg = QColor(g); bg.setAlphaF(0.2)
            bd = QColor(g); bd.setAlphaF(0.55)
            return bg, mix(g, QColor(p["text"]), 0.2), bd
        bg, fg, bd = super()._colors()
        if not self.isEnabled() and not self.on:               # « pas possible » : à peine visible
            fg = QColor(pal()["faint"]); fg.setAlphaF(0.55)
        return bg, fg, bd


VOLUME_MAX = 150                         # curseur de volume : 0 à 150 % (100 % au milieu du tiers droit)


class _VolumeSlider(TabSlider):
    """Curseur de volume d'une piste ; double-clic = retour à 100 %."""

    def mouseDoubleClickEvent(self, ev):
        self.setValue(100)
        ev.accept()


class _Row(QFrame):
    clicked = Signal(int)
    volume_changed = Signal(int, float)    # indice de piste, volume (1.0 = 100 %)

    def __init__(self, index: int, track, parent=None):
        super().__init__(parent)
        self.index = index
        self.displayable = bool(track.measures)         # la batterie n'a pas de tablature affichée
        self.kind = tab_icons.instrument_kind(track.instrument, family(track))
        self.color = INSTRUMENT_COLORS[self.kind]
        self.setObjectName("trackRow")
        self.setCursor(Qt.PointingHandCursor if self.displayable else Qt.ArrowCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(10)
        self.badge = QFrame(self)                       # pastille de l'instrument : teinte douce + icône de sa couleur
        self.badge.setFixedSize(34, 34)
        self.badge.setStyleSheet(f"QFrame{{background:{rgba(self.color, 0.16)};border-radius:10px}}")
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._badge_icon = QWidget(self.badge)
        self._badge_icon.setGeometry(0, 0, 34, 34)
        self._badge_icon.paintEvent = self._paint_badge
        lay.addWidget(self.badge)
        sub = track.name.split(" | ")
        self.title = _Elided(type("BodyLabel", (), {}), track.instrument or "Piste", self)
        self.subtitle = _Elided(type("CaptionLabel", (), {}), " | ".join(sub[:3]), self)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        self.volume = _VolumeSlider(Qt.Horizontal, self, fill=self.color, groove=3)    # visible seulement en mode « Synthèse »
        self.volume.setRange(0, VOLUME_MAX)
        self.volume.setValue(100)
        self.volume.setFixedHeight(18)
        self.volume.setToolTip("Volume de cette piste (double-clic : 100 %)")
        self.volume.valueChanged.connect(self._on_volume)
        self.volume.hide()
        texts.addWidget(self.volume)
        lay.addLayout(texts, 1)
        self.solo = StateButton("headphones", "solo", "Isoler cet instrument", self)
        self.mute = StateButton("mute", "mute", "Couper cet instrument", self)
        lay.addWidget(self.solo)
        lay.addWidget(self.mute)
        self.set_selected(False)

    def _paint_badge(self, ev):
        p = QPainter(self._badge_icon)
        p.drawPixmap(8, 8, tab_icons.pixmap(tab_icons.instrument_icon_name(self.kind), self.color, 18))

    def _on_volume(self, value: int):
        self.volume.setToolTip(f"Volume de cette piste : {value} % (double-clic : 100 %)")
        self.volume_changed.emit(self.index, value / 100.0)

    def set_synth(self, on: bool, volume: float = 1.0):
        self.subtitle.setVisible(not on)
        self.volume.setVisible(on)
        if on:
            self.volume.blockSignals(True)
            self.volume.setValue(round(volume * 100))
            self.volume.blockSignals(False)
            self.volume.setEnabled(self.displayable)

    def set_selected(self, on: bool):
        """Sélectionnée : fine bordure de la couleur de l'instrument + fond à peine teinté. Sinon : survol discret."""
        if on:
            self.setStyleSheet(f"#trackRow{{background:{rgba(self.color, 0.09)};border:1px solid {rgba(self.color, 0.6)};"
                               f"border-radius:11px}}")
        else:
            self.setStyleSheet("#trackRow{background:transparent;border:1px solid transparent;border-radius:11px}"
                               f"#trackRow:hover{{background:{rgba('hover', 0.55)}}}")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.displayable:
            self.clicked.emit(self.index)
        super().mousePressEvent(ev)


class AudioSettingsPopup(PopupCard):
    """Réglages audio du mode Original (engrenage de l'en-tête) : version audio à utiliser + association des pistes."""
    mapping_wanted = Signal()

    def __init__(self, choice: ChoiceModel, parent=None):
        super().__init__(parent)
        self.choice = choice
        self.setFixedWidth(360)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 12, 12, 12)
        self._lay.setSpacing(4)

    def _clear(self):
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def rebuild(self):
        self._clear()
        head = _Elided(type("CaptionLabel", (), {}), "VERSION AUDIO", self)
        self._lay.addWidget(head)
        n = self.choice.count()
        for i in range(n):
            b = TabButton(self.choice.itemText(i), "check" if i == self.choice.currentIndex() else None, "ghost", self,
                          height=32, align="left")
            b.setCheckable(True)
            b.setChecked(i == self.choice.currentIndex())
            b.setToolTip(self.choice.itemText(i))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, i=i: self._pick(i))
            self._lay.addWidget(b)
        if n == 0:
            self._lay.addWidget(_Elided(type("BodyLabel", (), {}), "Aucune version audio pour ce morceau", self))
        sep = QFrame(self)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{pal()['border']}")
        self._lay.addSpacing(6)
        self._lay.addWidget(sep)
        self._lay.addSpacing(6)
        m = TabButton("Associer les pistes audio…", "sliders", "soft", self, height=34)
        m.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        m.setToolTip("Choisir à la main quelle piste audio correspond à chaque instrument")
        m.clicked.connect(lambda: (self.close(), self.mapping_wanted.emit()))
        self._lay.addWidget(m)
        self.adjustSize()

    def _pick(self, i: int):
        self.close()
        self.choice.setCurrentIndex(i)

    def popup_for(self, widget: QWidget):
        self.rebuild()
        self.place_near(widget, align_right=False)
        self.show()


class TrackList(QScrollArea):
    selected = Signal(int)                  # indice de la piste à afficher
    video_wanted = Signal(str)              # identifiant de la vidéo qui correspond au mix choisi
    mix_status = Signal(str)
    edit_mapping = Signal()                 # demande d'ouverture de la fenêtre d'association des pistes
    synth_mix_changed = Signal()            # mode « Synthèse » : solo / mute / volumes modifiés (cf. synth_state)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # jamais de défilement horizontal
        self.setFixedWidth(312)
        self._apply_frame()
        qconfig.themeChanged.connect(lambda *_: self._apply_frame())
        self._body = QWidget()
        self._body.setStyleSheet("background:transparent")
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(8, 8, 8, 8)
        self._lay.setSpacing(3)
        # en-tête : « Pistes » + nombre d'instruments, et l'engrenage des réglages audio (mode Original)
        self._head = QWidget(self._body)
        hl = QHBoxLayout(self._head)
        hl.setContentsMargins(8, 0, 0, 2)
        hl.setSpacing(8)
        hl.addWidget(_Elided(type("StrongBodyLabel", (), {}), "Pistes", self._head, fit=True))
        self._count = _Elided(type("CaptionLabel", (), {}), "", self._head, fit=True)
        hl.addWidget(self._count)
        hl.addStretch(1)
        self._map_btn = TabButton("", "sliders", "ghost", self._head, height=30)
        self._map_btn.setToolTip("Réglages audio : version audio (vidéo) à utiliser, association des pistes")
        self._map_btn.clicked.connect(self._open_audio_settings)
        hl.addWidget(self._map_btn)
        self._map_btn.hide()
        self.choice: ChoiceModel | None = None                # versions audio (alimenté par la page Partition)
        self._audio_popup: AudioSettingsPopup | None = None
        self._empty = _Elided(type("CaptionLabel", (), {}), "Charge un morceau pour voir ses instruments.", self._body)
        self._lay.addWidget(self._head)
        self._lay.addWidget(self._empty)
        self._lay.addStretch(1)
        self.setWidget(self._body)
        self._rows: list[_Row] = []
        self._current = -1
        self._model: MixModel | None = None
        self._state = Mix(None, None, frozenset())
        self._synth = False                                   # mode « Synthèse » (réglages libres, sans vidéo)
        self._solo: set[int] = set()
        self._mute: set[int] = set()
        self._vol: dict[int, float] = {}

    def _apply_frame(self):
        self.setStyleSheet(card_style("TrackList") + scrollbar_qss())
        self.viewport().setStyleSheet("background:transparent")
        for r in getattr(self, "_rows", []):
            r.set_selected(r.index == self._current)

    def set_choice(self, choice: ChoiceModel):
        """Modèle des versions audio, montré dans la fenêtre de l'engrenage."""
        self.choice = choice

    def _open_audio_settings(self):
        if self.choice is None:
            self.edit_mapping.emit()
            return
        if self._audio_popup is None:
            self._audio_popup = AudioSettingsPopup(self.choice, self)
            self._audio_popup.mapping_wanted.connect(self.edit_mapping.emit)
        self._audio_popup.popup_for(self._map_btn)

    # ---------- construction ----------
    def set_tracks(self, tracks, current: int, syncs=None, overrides=None, synth_mix=None):
        """`synth_mix` : (solo, mute, volumes) mémorisés pour ce morceau (mode « Synthèse »), par indice de piste."""
        if synth_mix is not None:
            self._solo, self._mute, self._vol = set(synth_mix[0]), set(synth_mix[1]), dict(synth_mix[2])
        self._lay.removeWidget(self._head)
        for r in self._rows:
            r.setParent(None)
            r.deleteLater()
        self._rows = []
        while self._lay.count():
            self._lay.takeAt(0)
        self._model = MixModel(list(syncs or []), list(tracks), overrides) if syncs else None
        self._state = self._model.default if self._model else Mix(None, None, frozenset())
        if self._model:
            for line in self._model.describe(list(tracks)):
                dbg("mix", line)
        self._lay.addWidget(self._head)
        self._empty.setVisible(not tracks)
        self._count.setText(f"{len(tracks)}" if tracks else "")
        if not tracks:
            self._lay.addWidget(self._empty)
        for i, t in enumerate(tracks):
            row = _Row(i, t, self._body)
            row.clicked.connect(self._on_clicked)
            row.volume_changed.connect(self._on_volume)
            row.solo.clicked.connect(lambda _=False, i=i: self._click("solo", i))
            row.mute.clicked.connect(lambda _=False, i=i: self._click("mute", i))
            row.solo.hovered.connect(lambda on, i=i: self._hover("solo", i, on))
            row.mute.hovered.connect(lambda on, i=i: self._hover("mute", i, on))
            self._lay.addWidget(row)
            self._rows.append(row)
        self._lay.addStretch(1)
        self._map_btn.setVisible(self._model is not None and not self._synth)
        self.select(current, emit=False)
        self._apply_synth()
        self._refresh()

    def set_current_video(self, video_id: str):
        """La vidéo a été changée à la main : les boutons ne correspondent plus à rien."""
        if self._model and (self._state.video is None or self._state.video.video_id != video_id):
            self._state = self._model.state_for(video_id)
            self._refresh()

    # ---------- sélection de la tablature ----------
    def select(self, index: int, emit: bool = True):
        self._current = index
        for r in self._rows:
            r.set_selected(r.index == index)
        if emit:
            self.selected.emit(index)

    def _on_clicked(self, index: int):
        if index != self._current:
            self.select(index)

    # ---------- mode « Synthèse » ----------
    def set_synth_mode(self, on: bool):
        self._synth = on
        self._map_btn.setVisible(self._model is not None and not on)
        self._apply_synth()
        self._refresh()

    def synth_state(self) -> tuple[set[int], set[int], dict[int, float]]:
        """(pistes en solo, pistes coupées, volumes {piste: 1.0 = 100 %}) — indices de la liste de pistes."""
        return set(self._solo), set(self._mute), {i: v for i, v in self._vol.items() if abs(v - 1.0) > 1e-6}

    def _apply_synth(self):
        for r in self._rows:
            r.set_synth(self._synth, self._vol.get(r.index, 1.0))

    def _on_volume(self, index: int, volume: float):
        self._vol[index] = volume
        self.synth_mix_changed.emit()

    def _synth_click(self, kind: str, index: int):
        group = self._solo if kind == "solo" else self._mute
        if not self._rows[index].displayable:
            return
        group.symmetric_difference_update({index})
        dbg("synthèse", kind, index, "->", sorted(group))
        self._refresh()
        self.synth_mix_changed.emit()

    # ---------- mixage ----------
    def _refresh(self):
        m, st = self._model, self._state
        if self._synth:
            for r in self._rows:
                for btn, group, tip in ((r.solo, self._solo, "Isoler cet instrument"), (r.mute, self._mute, "Couper cet instrument")):
                    btn.set_state(r.index in group, r.displayable)
                    btn.set_preview(False)
                    btn.setToolTip(tip if r.displayable else "Piste sans notes : rien à jouer")
            return
        for r in self._rows:
            for btn, kind in ((r.solo, "solo"), (r.mute, "mute")):
                on = st.kind == kind and r.index in st.tracks
                ok = on or (m is not None and m.clickable(kind, st, r.index))
                btn.set_state(on, ok)
                btn.set_preview(False)
                btn.setToolTip(btn._tip if ok else "Aucune version audio de Songsterr ne permet ce réglage")

    def _click(self, kind: str, index: int):
        if self._synth:
            self._synth_click(kind, index)
            return
        if self._model is None:
            return
        new = (self._model.solo_click if kind == "solo" else self._model.mute_click)(self._state, index)
        dbg("clic", kind, index, "->", None if new is None else (new.kind, new.video.video_id, sorted(new.tracks)))
        if new is None:
            return
        self._state = new
        self._refresh()
        self._hover(kind, index, True)                              # l'aperçu reflète le nouvel état sous le curseur
        if new.video is not None:
            self.video_wanted.emit(new.video.video_id)

    def _hover(self, kind: str, index: int, on: bool):
        if self._synth:
            return
        for r in self._rows:
            r.solo.set_preview(False)
            r.mute.set_preview(False)
        if not on or self._model is None:
            return
        group = self._model.preview(kind, self._state, index)
        for i in group:
            (self._rows[i].solo if kind == "solo" else self._rows[i].mute).set_preview(True)