"""
Édition de la partition (page Partition, étape 10) : barre d'outils, saisie de texte, et le contrôleur qui relie la
sélection faite dans la page, le modèle (tabs/score_edits.py) et la bibliothèque (« Ma version » = original + changements).

La page web ne fait que montrer et choisir (un clic = un temps + une corde, les touches sont renvoyées telles quelles) ;
tout le modèle est ici. Chaque action modifie une COPIE de la mesure affichée, puis l'enregistre dans la bibliothèque (une
entrée par mesure modifiée) ; la page est redessinée à partir de là (cf. TabInterface._on_edits_changed).
"""

import copy
import time
from fractions import Fraction

from PySide6.QtCore import QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from tabs import score_edits as se
from tabs import score_tools as st
from ui.tab_palette import PalettePanel
from ui.tab_widgets import PopupCard, ScoreMenu, SearchField, SegmentedPill, TabButton
from ui.theme import card_style, pal

DURATIONS = (1, 2, 4, 8, 16, 32, 64)
DURATION_NAMES = {1: "ronde", 2: "blanche", 4: "noire", 8: "croche", 16: "double-croche", 32: "triple-croche", 64: "quadruple-croche"}


def _frac(f: Fraction) -> str:
    return f"{f.numerator}/{f.denominator}"


class _Info(QWidget):
    """Texte d'une ligne, rogné avec « … » (jamais de défilement), de la couleur voulue."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text, self._color = "", "#888888"
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)

    def set(self, text: str, color: str):
        self._text, self._color = text, color
        self.setToolTip(text)
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self):
        return QSize(10, QFontMetrics(self.font()).height() + 4)

    def paintEvent(self, ev):
        p = QPainter(self)
        f = self.font()
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.setPen(QColor(self._color))
        p.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(self._text, Qt.ElideRight, self.width()))


class PromptPopup(PopupCard):
    """Petite fenêtre « un titre, un champ, valider » (annotation, nom de section, tempo)."""
    done = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self.title = QLabel(self)
        self.hint = QLabel(self)
        self.box = QFrame(self)
        self.box.setFixedHeight(34)
        bl = QHBoxLayout(self.box)
        bl.setContentsMargins(10, 0, 4, 0)
        self.field = SearchField(self.box)
        bl.addWidget(self.field)
        self.ok = TabButton("Valider", "check", "accent", self, height=34)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.box, 1)
        row.addWidget(self.ok)
        lay.addWidget(self.title)
        lay.addLayout(row)
        lay.addWidget(self.hint)
        self.setFixedWidth(360)
        self.ok.clicked.connect(self._validate)
        self.field.returnPressed.connect(self._validate)

    def ask(self, anchor_pos, title: str, text: str = "", hint: str = ""):
        c = pal()
        self.title.setText(title)
        self.title.setStyleSheet(f"color:{c['text']};font-size:13px;font-weight:600;background:transparent")
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        self.hint.setStyleSheet(f"color:{c['muted']};font-size:11px;background:transparent")
        self.box.setStyleSheet(f"QFrame{{background:{c['soft']};border-radius:8px}}")
        self.field.apply_theme()
        self.field.setText(text)
        self.adjustSize()
        self.place_at(anchor_pos)
        self.show()
        self.field.setFocus()
        self.field.selectAll()

    def _validate(self):
        self.done.emit(self.field.text())
        self.close()


class EditBar(QFrame):
    """Barre d'édition (sous la partition) : version affichée, sélection, outils d'un temps."""
    version_chosen = Signal(str)
    fret_step = Signal(int)
    duration_chosen = Signal(int)
    dot_toggled = Signal()
    rest_clicked = Signal()
    more_clicked = Signal()
    tools_toggled = Signal(bool)
    done_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editBar")
        self.setFixedHeight(46)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)
        self.version = SegmentedPill(self, height=30)
        self.version.addItem("original", "Songsterr", lambda: self.version_chosen.emit("original"))
        self.version.addItem("modified", "Ma version", lambda: self.version_chosen.emit("modified"))
        self.version.setCurrentItem("modified")
        self.version.setToolTip("Songsterr : la partition d'origine, jamais modifiée. Ma version : l'origine + tes modifications")
        lay.addWidget(self.version)
        self.info = _Info(self)
        lay.addWidget(self.info, 1)
        self.minus = TabButton("", "minus", "soft", self, height=30)
        self.plus = TabButton("", "plus", "soft", self, height=30)
        self.minus.setToolTip("Case −1 (ou tape le numéro de la case)")
        self.plus.setToolTip("Case +1 (ou tape le numéro de la case)")
        self.minus.clicked.connect(lambda: self.fret_step.emit(-1))
        self.plus.clicked.connect(lambda: self.fret_step.emit(1))
        self.dur = SegmentedPill(self, height=30)
        for d in DURATIONS:
            self.dur.addItem(str(d), str(d), lambda d=d: self.duration_chosen.emit(d))
        self.dur.setToolTip("Durée du temps : 1 = ronde, 2 = blanche, 4 = noire, 8 = croche, 16 = double-croche, 32 = triple-croche, 64")
        self.dot = TabButton("•", None, "soft", self, height=30)
        self.dot.setCheckable(True)
        self.dot.setToolTip("Point : allonge la note de la moitié de sa durée (touche .)")
        self.dot.clicked.connect(lambda: self.dot_toggled.emit())
        self.rest = TabButton("Silence", None, "soft", self, height=30)
        self.rest.setToolTip("Transforme le temps en silence (touche R)")
        self.rest.clicked.connect(lambda: self.rest_clicked.emit())
        self.more = TabButton("", "sliders", "soft", self, height=30)
        self.more.setToolTip("Plus d'outils : insérer / supprimer un temps, compléter la mesure, annotation, section, tempo, revenir à l'original")
        self.more.clicked.connect(lambda: self.more_clicked.emit())
        self.tools = TabButton("Outils", "sliders", "soft", self, height=30)
        self.tools.setCheckable(True)
        self.tools.setChecked(True)
        self.tools.setToolTip("Palette d'outils : effets, techniques, mesures, copier-coller… (comme sur Songsterr)")
        self.tools.toggled.connect(self.tools_toggled)
        self.finish = TabButton("", "check", "accent", self, height=30)
        self.finish.setToolTip("Terminer l'édition (la version affichée est conservée)")
        self.finish.clicked.connect(lambda: self.done_clicked.emit())
        for w in (self.minus, self.plus, self.dur, self.dot, self.rest, self.tools, self.more, self.finish):
            lay.addWidget(w)
        self.apply_theme()

    def apply_theme(self):
        self.setStyleSheet(card_style("#editBar", radius=12))
        self.info.update()

    def set_state(self, *, version: str, info: str, warn: bool, enabled: bool, base: int | None, dots: int):
        self.version.setCurrentItem(version)
        c = pal()
        self.info.set(info, c["amber"] if warn else c["muted"])
        for w in (self.minus, self.plus, self.dur, self.dot, self.rest):
            w.setEnabled(enabled)
        self.more.setEnabled(version == "modified")
        if base in DURATIONS:
            self.dur.setCurrentItem(str(base))
        self.dot.setChecked(dots > 0)


class EditController(QObject):
    """Sélection, touches et actions d'édition. `ti` = la page Partition (TabInterface)."""

    def __init__(self, ti):
        super().__init__(ti)
        self.ti = ti
        self.on = False
        self.voice = 0                                          # voix éditée (0 = voix 1)
        self.clip: dict | None = None                           # presse-papiers : un temps ou les temps d'une voix de mesure
        self.sel: tuple[int, int, int] | None = None          # (mesure, temps (-1 = aucun), corde du modèle 0 = la plus aiguë)
        self._digit = (0, 0.0)                                  # dernier chiffre tapé et son heure : « 1 » puis « 2 » = 12
        self.bar = EditBar(ti)
        self.bar.hide()
        self.palette = PalettePanel(ti)
        self.palette.hide()
        self.prompt = PromptPopup(ti)
        self.bar.version_chosen.connect(self.choose_version)
        self.bar.fret_step.connect(self.bump_fret)
        self.bar.duration_chosen.connect(self.set_duration)
        self.bar.dot_toggled.connect(self.toggle_dot)
        self.bar.rest_clicked.connect(self.make_rest)
        self.bar.more_clicked.connect(self.open_menu)
        self.bar.tools_toggled.connect(lambda on: self._show_palette())
        self.bar.done_clicked.connect(lambda: ti.edit_btn.setChecked(False))
        self.palette.tool_clicked.connect(self.on_tool)
        self.palette.more_requested.connect(self.on_more)
        self.palette.voice_chosen.connect(self.set_voice)

    # ---------- accès au modèle ----------
    @property
    def sid(self) -> int:
        return self.ti._score.song_id

    @property
    def part(self) -> int:
        return self.ti._score.tracks[self.ti._track_idx].part_id

    def track(self):
        return self.ti._score.tracks[self.ti._track_idx]

    def editable(self) -> bool:
        t = self.ti._score.tracks[self.ti._track_idx] if self.ti._score else None
        return bool(t and not t.is_drums and t.measures)

    def modified(self) -> bool:
        return self.ti.library.version(self.sid) == "modified"

    def measure_copy(self, bar: int):
        return copy.deepcopy(self.ti._score.tracks[self.ti._track_idx].measures[bar])

    def ctx(self) -> st.Ctx:
        return st.Ctx(tuning=list(self.track().tuning), voice=self.voice, clip=self.clip)

    def commit(self, m):
        """Enregistre la mesure modifiée ; la page se redessine toute seule (écoute de la bibliothèque)."""
        lib, ti = self.ti.library, self.ti
        lib.set_edits(self.sid, se.put_measure(lib.edits(self.sid), ti._orig_score, self.part, m))

    def _show_palette(self):
        show = self.on and self.bar.tools.isChecked()
        self.palette.setVisible(show)
        for w in (self.bar.dur, self.bar.dot, self.bar.rest):          # la palette les propose déjà : on gagne de la place dans la barre
            w.setVisible(not show)

    # ---------- mode édition ----------
    def toggle(self, on: bool):
        ti = self.ti
        if on and (ti._score is None or ti._view is None):
            ti.edit_btn.setChecked(False)
            return
        if on and not self.editable():
            ti.set_status("Cette piste ne peut pas être modifiée (batterie)")
            ti.edit_btn.setChecked(False)
            return
        self.on = on
        self.sel = None
        if on:
            ti.library.set_version(self.sid, "modified")
        self.bar.setVisible(on)
        self._show_palette()
        ti._js(f"melos.setEdit({str(on).lower()}); melos.setVoice({self.voice})")
        if on:
            ti.set_status("Édition : clique un temps de la partition, tape le numéro de la case")
        self.refresh()

    def stop(self):
        """Autre morceau : on sort du mode édition sans toucher à la version."""
        if self.on:
            self.on, self.sel = False, None
            self.bar.hide()
            self.palette.hide()
            self.ti.edit_btn.blockSignals(True)
            self.ti.edit_btn.setChecked(False)
            self.ti.edit_btn.blockSignals(False)

    def track_changed(self):
        self.sel = None
        if not self.editable():
            self.ti.set_status("Cette piste ne peut pas être modifiée (batterie)")
            self.ti.edit_btn.setChecked(False)
        else:
            self.refresh()

    def choose_version(self, v: str):
        if self.ti._score is None:
            return
        self.ti.library.set_version(self.sid, v)
        self.sel = None
        self.ti._js("melos.select(-1, -1, 0)")
        self.refresh()

    def set_voice(self, v: int):
        self.voice = max(0, min(st.VOICES - 1, int(v)))
        self.sel = None
        self.ti._js(f"melos.setVoice({self.voice}); melos.select(-1, -1, 0)")
        self.palette.set_voice(self.voice)
        self.refresh()

    # ---------- sélection ----------
    def on_select(self, d: dict):
        if not self.on or self.ti._score is None:
            return
        self._digit = (0, 0.0)
        bar, beat, string = int(d.get("bar", -1)), int(d.get("beat", -1)), int(d.get("string", 0))
        tr = self.track()
        if bar >= 0 and beat < 0 and "frac" in d and bar < len(tr.measures):       # voix non dessinée : on vise le temps par sa position
            beat = self._beat_at(tr.measures[bar], float(d["frac"]))
        self.sel = (bar, beat, string) if bar >= 0 else None
        if self.sel and beat >= 0:
            self.ti._js(f"melos.select({bar}, {beat}, {string}, {self.voice})")
        self.refresh()

    def _beat_at(self, m, frac: float) -> int:
        """Indice du temps de la voix éditée qui couvre la fraction `frac` (0-1) de la mesure."""
        bs = se.view(m, self.voice)
        total = sum((b.length for b in bs), Fraction(0)) or Fraction(1)
        acc = Fraction(0)
        for j, b in enumerate(bs):
            acc += b.length
            if frac <= float(acc / total):
                return j
        return max(0, len(bs) - 1)

    def _select(self, bar: int, beat: int, string: int):
        self.sel = (bar, beat, string)
        self.ti._js(f"melos.select({bar}, {beat}, {string}, {self.voice})")
        self.refresh()

    def _beat(self):
        """(mesure copiée, indice du temps) de la sélection, ou None."""
        if not self.on or not self.sel or self.sel[1] < 0 or not self.modified() or not self.editable():
            return None
        bar, j, _ = self.sel
        tr = self.track()
        if bar >= len(tr.measures) or j >= len(se.view(tr.measures[bar], self.voice)):
            return None
        return self.measure_copy(bar), j

    def refresh(self):
        """Met à jour la barre et la palette : version, texte de sélection, outils."""
        ti = self.ti
        if ti._score is None:
            return
        version = ti.library.version(self.sid)
        info, warn, enabled, base, dots = "", False, False, None, 0
        m = None
        if version != "modified":
            info = "Version d'origine, en lecture seule : passe sur « Ma version » pour modifier"
        elif not self.editable():
            info, warn = "Cette piste ne peut pas être modifiée (batterie)", True
        elif not self.sel:
            info = "Clique un temps de la partition"
        else:
            bar, j, s = self.sel
            tr = self.track()
            m = tr.measures[bar] if bar < len(tr.measures) else None
            nstr = max(1, len(tr.tuning))
            if m is not None:
                total, want = se.fill(m, self.voice)
                bs = se.view(m, self.voice)
                vtxt = f" · voix {self.voice + 1}" if self.voice else ""
                if 0 <= j < len(bs):
                    b = bs[j]
                    n = se.find_note(b, s)
                    what = f"case {n.fret}" if n else ("silence" if b.rest else "vide")
                    info = f"Mesure {bar + 1}{vtxt} · temps {j + 1}/{len(bs)} · corde {s + 1}/{nstr} · {what}"
                    enabled, base, dots = True, b.base, b.dots
                else:
                    info = f"Mesure {bar + 1}{vtxt}"
                if total != want and not m.pickup:
                    info += f"   ⚠ mesure {'trop longue' if total > want else 'incomplète'} ({_frac(total)} au lieu de {_frac(want)})"
                    warn = True
        self.bar.set_state(version=version, info=info, warn=warn, enabled=enabled, base=base, dots=dots)
        self._update_palette(m if version == "modified" and self.editable() else None)

    def _update_palette(self, m):
        if not self.palette.isVisible() and not self.on:
            return
        sel = self.sel or (0, -1, 0)
        ctx = self.ctx()
        _, j, s = sel
        self.palette.update_states(lambda t: st.tool_state(t, m, j, s, ctx) if m is not None else (False, False))

    # ---------- actions sur le temps sélectionné ----------
    def _edit(self, fn, reselect=None):
        """Applique `fn(mesure, j, corde)` à une copie de la mesure sélectionnée et enregistre."""
        got = self._beat()
        if got is None:
            if self.on and self.sel and not self.modified():
                self.ti.set_status("Version d'origine en lecture seule : choisis « Ma version »")
            return
        m, j = got
        bar, _, s = self.sel
        try:
            out = fn(m, j, s)
        except st.ToolError as exc:
            self.ti.set_status(str(exc))
            return
        string = s
        if isinstance(out, st.Result):
            if out.clip is not None:
                self.clip = out.clip
            if out.msg:
                self.ti.set_status(out.msg)
            string = s if out.string is None else out.string
            out = out.beat
        self.commit(m)
        nb = len(se.beats(m, self.voice))
        self._select(bar, min(out, nb - 1) if isinstance(out, int) else j, string)
        self._focus_page()

    def _focus_page(self):
        """Après un clic sur un outil, le clavier doit retourner à la partition (chiffres, flèches, Suppr...)."""
        v = getattr(self.ti, "_view", None)
        if v is not None and self.on:
            v.setFocus()

    def type_digit(self, d: int):
        now = time.monotonic()
        prev, t = self._digit
        v = prev * 10 + d if (now - t) < 0.8 and prev and prev * 10 + d <= se.MAX_FRET else d
        self._digit = (v, now)
        self._edit(lambda m, j, s: se.set_fret(m, j, s, v, self.voice))

    def bump_fret(self, delta: int):
        def go(m, j, s):
            n = se.find_note(se.beats(m, self.voice)[j], s)
            se.set_fret(m, j, s, max(0, min(se.MAX_FRET, (n.fret if n else 0) + delta)) if n or delta > 0 else None, self.voice)
        self._edit(go)

    def delete(self, whole: bool = False):
        def go(m, j, s):
            b = se.beats(m, self.voice)[j]
            if whole or (b.rest and not se.find_note(b, s)):
                return se.remove_beat(m, j, self.voice)
            se.set_fret(m, j, s, None, self.voice)
        self._edit(go)

    def set_duration(self, base: int):
        self._edit(lambda m, j, s: se.set_duration(m, j, base=base, v=self.voice))

    def toggle_dot(self):
        self._edit(lambda m, j, s: se.set_duration(m, j, dots=0 if se.beats(m, self.voice)[j].dots else 1, v=self.voice))

    def make_rest(self):
        self._edit(lambda m, j, s: se.make_rest(m, j, self.voice))

    def insert_beat(self):
        self._edit(lambda m, j, s: se.insert_beat(m, j, se.beats(m, self.voice)[j].base, self.voice))

    def complete_bar(self):
        self._edit(lambda m, j, s: st.apply_tool(st.BY_ID["complete"], m, j, s, self.ctx()))

    def set_text(self, text: str):
        self._edit(lambda m, j, s: se.set_text(m, j, text, self.voice))

    def set_chord(self, text: str):
        self._edit(lambda m, j, s: se.set_chord(m, j, text, self.voice))

    def set_signature(self, text: str):
        def go(m, j, s):
            if not se.set_signature(m, text):
                raise st.ToolError("Signature invalide : écris par exemple 3/4 ou 7/8 (dénominateur 1, 2, 4, 8, 16 ou 32)")
        self._edit(go)

    def set_marker(self, text: str):
        got = self.sel[0] if self.sel else None
        if got is None or not self.modified() or not self.editable():
            return
        m = self.measure_copy(got)
        se.set_marker(m, text)
        self.commit(m)
        self.refresh()

    def set_tempo(self, text: str):
        if not self.sel:
            return
        try:
            bpm = float(text.replace(",", ".").strip())
            if not se.BPM_RANGE[0] <= bpm <= se.BPM_RANGE[1]:
                raise ValueError
        except ValueError:
            self.ti.set_status(f"Tempo invalide : entre {se.BPM_RANGE[0]} et {se.BPM_RANGE[1]}")
            return
        lib = self.ti.library
        lib.set_edits(self.sid, se.put_tempo(lib.edits(self.sid), self.ti._orig_score, self.sel[0], bpm))
        self.refresh()

    def revert_bar(self, bar: int):
        lib = self.ti.library
        lib.set_edits(self.sid, se.drop_bar(lib.edits(self.sid), self.part, bar))
        self.refresh()

    def revert_all(self):
        self.ti.library.set_edits(self.sid, [])
        self.ti.set_status("Toutes les modifications sont annulées (Ctrl+Z pour les retrouver)")
        self.refresh()

    # ---------- palette d'outils ----------
    def on_tool(self, tid: str, arg: str | None = None, pos=None):
        """Un bouton de la palette (ou une variante du menu ⋮)."""
        tool = st.BY_ID[tid]
        if not self.on or not self.sel:
            self.ti.set_status("Clique d'abord un temps de la partition")
            return
        if not self.modified():
            self.ti.set_status("Version d'origine en lecture seule : choisis « Ma version »")
            return
        if tool.scope == "prompt":
            self._prompt_tool(tid, pos or self.palette.buttons[tid].mapToGlobal(QPoint(0, self.palette.buttons[tid].height() + 2)))
            return
        if tid == "key":
            self._set_key(int(arg if arg is not None else 0))
            return
        if tid in ("del_bar", "cut_m") and self.sel[1] < 0:
            return
        self._edit(lambda m, j, s: st.apply_tool(tool, m, j, s, self.ctx(), arg))

    def _set_key(self, key: int):
        """Armure à partir de la mesure choisie jusqu'à la fin de la piste (une seule annulation)."""
        bar = self.sel[0]
        tr = self.track()
        lib, ti = self.ti.library, self.ti
        edits = lib.edits(self.sid)
        for m in [copy.deepcopy(x) for x in tr.measures[bar:]]:
            if (m.key, m.key_minor) != (key, False):
                m.key, m.key_minor = key, False
            edits = se.put_measure(edits, ti._orig_score, self.part, m)
        lib.set_edits(self.sid, edits)
        self.ti.set_status(f"Armure : {st.KEY_NAMES[key]}, de la mesure {bar + 1} à la fin")
        self.refresh()

    def on_more(self, tid: str, pos):
        """Menu des variantes d'un outil (le « ⋮ » de la palette)."""
        tool = st.BY_ID[tid]
        if self.sel is None or not self.modified() or not self.editable():
            self.ti.set_status("Clique d'abord un temps de la partition")
            return
        bar, j, s = self.sel
        m = self.track().measures[bar]
        ctx = self.ctx()
        menu = ScoreMenu(self.ti)
        menu.set_title(tool.tip.split(" (")[0].split(" ;")[0])
        for arg, text in tool.more:
            on = st.variant_on(tool, m, j, s, ctx, arg)
            menu.add_item("check" if on else None, text, lambda a=arg: self.on_tool(tid, a, pos))
        menu.popup_at(pos)
        self.ti._ctx_menu = menu

    def _prompt_tool(self, tid: str, pos):
        if tid == "text":
            got = self._beat()
            cur = se.beats(got[0], self.voice)[got[1]].text if got else ""
            self._ask(pos, "Annotation sur ce temps", cur or "", self.set_text, "Texte affiché au-dessus du temps (vide = retirer)")
        elif tid == "chord":
            got = self._beat()
            cur = se.beats(got[0], self.voice)[got[1]].chord if got else ""
            self._ask(pos, "Nom d'accord sur ce temps", cur or "", self.set_chord, "Ex. Am7, C#m, F/A (vide = retirer)")
        elif tid == "ts":
            m = self.track().measures[self.sel[0]]
            self._ask(pos, f"Signature de la mesure {self.sel[0] + 1}", f"{m.signature[0]}/{m.signature[1]}", self.set_signature,
                      "Ex. 3/4, 6/8, 7/8 : les temps de la mesure ne sont pas modifiés (complète-la ensuite)")
        elif tid == "tempo":
            self._ask_tempo(pos)
        elif tid == "sect":
            self._ask_marker(pos)

    # ---------- touches (renvoyées par la page) ----------
    def on_key(self, d: dict):
        if not self.on or self.ti._score is None:
            return
        k, shift = d.get("key", ""), bool(d.get("shift"))
        ctrl = bool(d.get("ctrl"))
        if k == "Escape":
            self.sel = None
            self.refresh()
            return
        if not self.sel:
            return
        bar, j, s = self.sel
        tr = self.track()
        nstr = max(1, len(tr.tuning))
        if ctrl and k.lower() in ("c", "x", "v"):
            self.on_tool({"c": "copy_b", "x": "cut_b", "v": "paste"}[k.lower()])
        elif k.isdigit():
            self.type_digit(int(k))
        elif k in ("ArrowLeft", "ArrowRight"):
            step = -1 if k == "ArrowLeft" else 1
            nb = j + step
            if nb < 0 and bar > 0:
                bar, nb = bar - 1, len(se.view(tr.measures[bar - 1], self.voice)) - 1
            elif nb >= len(se.view(tr.measures[bar], self.voice)) and bar + 1 < len(tr.measures):
                bar, nb = bar + 1, 0
            if 0 <= nb < len(se.view(tr.measures[bar], self.voice)):
                self._select(bar, nb, s)
        elif k in ("ArrowUp", "ArrowDown"):
            self._select(bar, j, max(0, min(nstr - 1, s + (-1 if k == "ArrowUp" else 1))))
        elif k in ("Delete", "Backspace"):
            self.delete(whole=shift)
        elif k == "Insert":
            self.insert_beat()
        elif k in ("r", "R"):
            self.make_rest()
        elif k == ".":
            self.toggle_dot()

    # ---------- menu « plus d'outils » ----------
    def open_menu(self):
        ti = self.ti
        if ti._score is None or not self.modified():
            return
        pos = self.bar.more.mapToGlobal(self.bar.more.rect().topLeft())
        menu = ScoreMenu(ti)
        menu.set_title("Ma version")
        have = self.sel is not None
        beat = self._beat() is not None
        bar = self.sel[0] if have else -1
        menu.add_item("plus", "Insérer un temps après", self.insert_beat, enabled=beat, hint="Inser")
        menu.add_item("minus", "Supprimer le temps", lambda: self.delete(True), enabled=beat, hint="Maj+Suppr")
        menu.add_item("check", "Compléter la mesure (silences)", self.complete_bar, enabled=beat)
        menu.add_separator()
        menu.add_item("edit", "Annotation sur ce temps…", lambda: self._ask_text(pos), enabled=beat)
        menu.add_item("edit", "Titre de section sur cette mesure…", lambda: self._ask_marker(pos), enabled=have)
        menu.add_item("gauge", "Tempo à partir de cette mesure…", lambda: self._ask_tempo(pos), enabled=have)
        menu.add_separator()
        edited = bar in se.edited_bars(ti.library.edits(self.sid), self.part)
        menu.add_item("refresh", f"Revenir à l'original (mesure {bar + 1})" if have else "Revenir à l'original (cette mesure)",
                      lambda: self.revert_bar(bar), enabled=have and edited)
        menu.add_item("close", "Tout revenir à l'original", self.revert_all, enabled=bool(ti.library.edits(self.sid)), color=pal()["amber"])
        menu.popup_at(pos)
        ti._ctx_menu = menu

    def _ask_text(self, pos):
        self._prompt_tool("text", pos)

    def _ask_marker(self, pos):
        m = self.track().measures[self.sel[0]]
        self._ask(pos, f"Titre de section · mesure {self.sel[0] + 1}", m.marker or "", self.set_marker, "Ex. Refrain, Solo (vide = retirer)")

    def _ask_tempo(self, pos):
        cur = se.tempo_at(self.ti._score, self.sel[0])
        self._ask(pos, f"Tempo à partir de la mesure {self.sel[0] + 1}", f"{cur:g}", self.set_tempo, "Battements par minute (20 à 400)")

    def _ask(self, pos, title, text, cb, hint):
        try:
            self.prompt.done.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.prompt.done.connect(cb)
        self.prompt.ask(pos, title, text, hint)