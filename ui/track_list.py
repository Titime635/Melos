"""
Liste des pistes d'une partition, comme sur Songsterr : une ligne par instrument (icône colorée, nom, musicien) et deux
boutons — casque = isoler (solo), haut-parleur barré = couper (mute). Cliquer sur la ligne affiche sa tablature.

Mode « Original » : les boutons sont « intelligents » (cf. tabs/mixer.py) : grisés quand aucune version audio de Songsterr
ne permet le réglage, verts au survol pour montrer TOUTES les pistes concernées, bleu (solo) / rouge (mute) une fois actifs.
Mode « Synthèse » : tout est libre (plusieurs solos, plusieurs mutes) et chaque ligne a un curseur de volume.
Aucune barre de défilement horizontale : les textes sont rognés plutôt que de repousser les boutons.
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QScrollArea, QToolButton, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, FluentIcon, PushButton, Slider, isDarkTheme

from tabs.debug import dbg
from tabs.mixer import Mix, MixModel, family

FAMILY_STYLE = {      # icône, couleur
    "vocals": (FluentIcon.MICROPHONE, "#ff6b9d"),
    "guitar": (FluentIcon.MUSIC, "#ff9f43"),
    "bass": (FluentIcon.MUSIC, "#c084fc"),
    "drums": (FluentIcon.ALBUM, "#f7d154"),
    "other": (FluentIcon.SPEAKERS, "#7dd3fc"),
}
SOLO_COLOR, MUTE_COLOR, PREVIEW_COLOR = "#4da3ff", "#ff5252", "#2ecc71"


class _Elided(QWidget):
    """Texte rogné avec « … » plutôt que d'élargir la ligne."""

    def __init__(self, label_cls, text: str, parent=None):
        super().__init__(parent)
        self._label = label_cls("", self)
        self._text = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def sizeHint(self):
        return QSize(10, self._label.sizeHint().height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._label.setGeometry(0, 0, self.width(), self.height())
        self._label.setText(self._label.fontMetrics().elidedText(self._text, Qt.ElideRight, self.width()))


class StateButton(QToolButton):
    """Bouton rond à états : off / on (couleur du mode) / aperçu (vert) / désactivé (grisé)."""
    hovered = Signal(bool)

    def __init__(self, icon, active_color: str, tip: str, parent=None):
        super().__init__(parent)
        self._icon, self._active = icon, QColor(active_color)
        self.on = False
        self.preview = False
        self.allowed = True
        self._tip = tip
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setAttribute(Qt.WA_Hover, True)

    def set_state(self, on: bool, allowed: bool):
        self.on, self.allowed = on, allowed
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

    def paintEvent(self, ev):
        dark = isDarkTheme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.preview:
            bg, fg = QColor(PREVIEW_COLOR), QColor("white")
        elif self.on:
            bg, fg = QColor(self._active), QColor("white")
        else:
            bg = QColor(255, 255, 255, 22) if dark else QColor(0, 0, 0, 16)
            fg = QColor("white") if dark else QColor("#222")
        if not self.allowed and not self.on:
            bg.setAlpha(bg.alpha() // 2)
            fg.setAlpha(70)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)
        self._icon.icon(color=fg).paint(p, self.rect().adjusted(8, 8, -8, -8))


VOLUME_MAX = 150                         # curseur de volume : 0 à 150 % (100 % au milieu du tiers droit)


class _VolumeSlider(Slider):
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
        fam = family(track)
        icon, self.color = FAMILY_STYLE[fam]
        self.setObjectName("trackRow")
        self.setCursor(Qt.PointingHandCursor if self.displayable else Qt.ArrowCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(8)
        self.badge = QToolButton(self)                  # pastille colorée de la famille
        self.badge.setEnabled(False)
        self.badge.setFixedSize(34, 34)
        self.badge.setIcon(icon.icon(color=QColor("white")))
        self.badge.setStyleSheet(f"QToolButton{{background:{self.color};border-radius:17px;border:none}}")
        lay.addWidget(self.badge)
        sub = track.name.split(" | ")
        self.title = _Elided(BodyLabel, track.instrument or "Piste", self)
        self.subtitle = _Elided(CaptionLabel, " | ".join(sub[:3]), self)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        self.volume = _VolumeSlider(Qt.Horizontal, self)         # visible seulement en mode « Synthèse », à la place du musicien
        self.volume.setRange(0, VOLUME_MAX)
        self.volume.setValue(100)
        self.volume.setFixedHeight(18)
        self.volume.setToolTip("Volume de cette piste (double-clic : 100 %)")
        self.volume.valueChanged.connect(self._on_volume)
        self.volume.hide()
        texts.addWidget(self.volume)
        lay.addLayout(texts, 1)
        self.solo = StateButton(FluentIcon.HEADPHONE, SOLO_COLOR, "Isoler cet instrument", self)
        self.mute = StateButton(FluentIcon.MUTE, MUTE_COLOR, "Couper cet instrument", self)
        lay.addWidget(self.solo)
        lay.addWidget(self.mute)
        self.set_selected(False)

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
        c = QColor(self.color)
        if on:
            veil = f"rgba({c.red()},{c.green()},{c.blue()},0.20)"
            self.setStyleSheet(f"#trackRow{{background:{veil};border-left:4px solid {self.color};border-radius:8px}}")
        else:
            hover = "rgba(255,255,255,0.06)" if isDarkTheme() else "rgba(0,0,0,0.05)"
            self.setStyleSheet("#trackRow{background:transparent;border-left:4px solid transparent;border-radius:8px}"
                               f"#trackRow:hover{{background:{hover}}}")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.displayable:
            self.clicked.emit(self.index)
        super().mousePressEvent(ev)


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
        self.setFixedWidth(340)
        self.setStyleSheet("QScrollArea{background:transparent}")
        self._body = QWidget()
        self._body.setStyleSheet("background:transparent")
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(4)
        self._map_btn = PushButton(FluentIcon.SETTING, "Associer les pistes audio", self._body)
        self._map_btn.setToolTip("Choisir à la main quelle piste audio correspond à chaque instrument")
        self._map_btn.clicked.connect(self.edit_mapping.emit)
        self.setWidget(self._body)
        self._rows: list[_Row] = []
        self._current = -1
        self._model: MixModel | None = None
        self._state = Mix(None, None, frozenset())
        self._synth = False                                   # mode « Synthèse » (réglages libres, sans vidéo)
        self._solo: set[int] = set()
        self._mute: set[int] = set()
        self._vol: dict[int, float] = {}

    # ---------- construction ----------
    def set_tracks(self, tracks, current: int, syncs=None, overrides=None, synth_mix=None):
        """`synth_mix` : (solo, mute, volumes) mémorisés pour ce morceau (mode « Synthèse »), par indice de piste."""
        if synth_mix is not None:
            self._solo, self._mute, self._vol = set(synth_mix[0]), set(synth_mix[1]), dict(synth_mix[2])
        self._lay.removeWidget(self._map_btn)
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
        self._lay.addWidget(self._map_btn)
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