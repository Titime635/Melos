"""
Composants de la page « Éditeur » : cartes d'emplacement, blocs de la chaîne d'effets (glisser-déposer pour réordonner),
cellules de réglage, lignes et étiquettes de la bibliothèque, boîte d'informations d'un preset.

Tous les composants dessinés à la main partagent les mêmes règles (rayon, bordure, survol, couleurs d'état) pour que
la page reste cohérente en thème clair comme en thème sombre. Les textes longs passent à la ligne puis sont rognés
avec « … » : jamais de barre de défilement pour atteindre un élément qui pourrait tenir.
"""

import hashlib
import math

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QStackedLayout, QVBoxLayout,
                               QWidget)
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon, LineEdit, MessageBoxBase, SegmentedWidget,
                            SubtitleLabel, TextEdit, ToolTipFilter, ToolTipPosition, isDarkTheme, qconfig, themeColor)

from ui.widgets import NoWheelComboBox, NoWheelSlider

GREEN, ORANGE, GREY, RED = "#3FB950", "#E98D32", "#8A8A8A", "#E5534B"
RADIUS = 8
MIME_BLOCK = "application/x-melos-fx"

# Noms et couleurs des blocs, repris de MightyEditor (identifiant 1..9 du Mighty ; le catalogue garde CMP, NG, CAB)
from editor.diff import BLOCK_NAMES as EFFECT_NAME  # noqa: E402
EFFECT_COLOR = {1: "#F2E34C", 2: "#F2762E", 3: "#E3342F", 4: "#E8E8E8", 5: "#A4C639",
                6: "#2E5BE0", 7: "#7DD3CF", 8: "#A66DD8", 9: "#3B9FD6"}
TAG_COLORS = ["#4C8DF6", "#3FB950", "#E98D32", "#B05FE0", "#2BB3C0", "#E5534B", "#C79A4B", "#DF74D6"]


def tag_color(tag: str) -> QColor:
    """Couleur stable d'une étiquette (la même à chaque lancement)."""
    h = int(hashlib.md5(tag.lower().encode("utf-8")).hexdigest()[:6], 16)
    return QColor(TAG_COLORS[h % len(TAG_COLORS)])


def fluent_tip(widget, text: str | None = None, position=ToolTipPosition.TOP):
    """Infobulle au style Fluent (une seule installation par composant ; le texte reste modifiable avec setToolTip)."""
    if text is not None:
        widget.setToolTip(text)
    if not getattr(widget, "_fluent_tip", False):
        widget._fluent_tip = True
        widget.installEventFilter(ToolTipFilter(widget, 350, position))
    return widget


def readable(color) -> str:
    """Couleur du bloc assombrie si elle serait illisible comme texte sur fond clair (jaune COMP, blanc EQ…)."""
    c = QColor(color)
    if not isDarkTheme() and c.lightness() > 140:
        c = c.darker(190 if c.lightness() > 200 else 160)
    return c.name()


def with_alpha(color, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def text_color(level: str = "primary") -> QColor:
    base = QColor(255, 255, 255) if isDarkTheme() else QColor(0, 0, 0)
    base.setAlpha({"primary": 235, "secondary": 160, "dim": 105}[level])
    return base


def surface(selected=False, hover=False, accent=None, dim=False):
    """(fond, bordure) communs à toutes les cartes de la page."""
    dark = isDarkTheme()
    if dark:
        fill = QColor(255, 255, 255, 24 if hover else 12)
        border = QColor(255, 255, 255, 34)
    else:
        fill = QColor(255, 255, 255, 255 if hover else 220)
        border = QColor(0, 0, 0, 32)
    if accent is not None:
        c = QColor(accent)
        fill = QColor(c.red(), c.green(), c.blue(), (60 if hover else 44) if selected else (34 if hover else 22))
        border = with_alpha(c, 230 if selected else 120)
    elif selected:
        c = themeColor()
        fill = QColor(c.red(), c.green(), c.blue(), 40)
        border = c
    if dim:
        fill.setAlpha(fill.alpha() // 2)
    return fill, border


def paint_icon(p: QPainter, icon, rect: QRectF, color):
    p.save()
    icon.render(p, rect.toRect(), fill=QColor(color).name())
    p.restore()


def wrap_lines(text: str, font: QFont, width: float, max_lines: int) -> list[str]:
    """Coupe `text` en lignes de `width` pixels au plus ; la dernière est rognée avec « … » s'il en reste."""
    fm = QFontMetrics(font)
    words = text.replace("/", "/​").replace("​", " ​").split()
    lines, cur = [], ""
    for w in words:
        glue = "" if w.startswith("​") else " "
        w = w.lstrip("​")
        trial = (cur + (glue if cur else "") + w) if cur else w
        if fm.horizontalAdvance(trial) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        rest = " ".join(lines[max_lines - 1:])
        lines = lines[:max_lines - 1] + [rest]
    return [fm.elidedText(l, Qt.ElideRight, int(width)) for l in lines] or [""]


def draw_text(p, x, y, lines, font, color, line_h):
    p.setFont(font)
    p.setPen(color)
    for i, l in enumerate(lines):
        p.drawText(QPointF(x, y + i * line_h), l)


def small_font(base: QFont, delta=1.0, bold=False) -> QFont:
    f = QFont(base)
    f.setPointSizeF(max(7.0, base.pointSizeF() - delta))
    f.setBold(bold)
    return f


def pill(p: QPainter, x, y, text, color, font, icon=None, h=16, solid=False) -> float:
    """Petite pastille arrondie (fond teinté + texte) ; rend sa largeur."""
    fm = QFontMetrics(font)
    iw = (h - 4 + 3) if icon is not None else 0
    w = fm.horizontalAdvance(text) + 12 + iw
    r = QRectF(x, y, w, h)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color) if solid else with_alpha(color, 46))
    p.drawRoundedRect(r, h / 2, h / 2)
    fg = QColor("white") if solid else QColor(color)
    if icon is not None:
        paint_icon(p, icon, QRectF(x + 5, y + 2, h - 4, h - 4), fg)
    p.setFont(font)
    p.setPen(fg)
    p.drawText(QPointF(x + 6 + iw, y + h / 2 + fm.ascent() / 2 - 1), text)
    return w


class ElidedLabel(QLabel):
    """Texte rogné avec « … » quand il ne tient pas (le texte complet reste dans l'infobulle)."""

    def __init__(self, text="", parent=None, bold=False, point_size=None, dim=False):
        super().__init__(parent)
        self._full = ""
        self._dim = dim
        f = self.font()
        f.setBold(bold)
        if point_size:
            f.setPointSizeF(point_size)
        self.setFont(f)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(10)
        fluent_tip(self)
        self._apply_color()
        qconfig.themeChanged.connect(lambda *_: self._apply_color())
        self.setText(text)

    def _apply_color(self):
        a = 150 if self._dim else 235
        self.setStyleSheet(f"color: {f'rgba(255,255,255,{a})' if isDarkTheme() else f'rgba(0,0,0,{a})'}; background: transparent;")

    def setText(self, text):
        self._full = text
        super().setText(text)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.ElideRight, max(0, self.width()))
        if shown != self.text():
            super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")          # infobulle seulement si le texte est rogné


class _Card(QWidget):
    """Base commune : survol, curseur, clic."""
    clicked = Signal(int)

    def __init__(self, key: int, parent=None):
        super().__init__(parent)
        self.key = key
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        fluent_tip(self)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.key)

    def _frame(self, p, r, selected, accent=None, dim=False, dashed=False, width=None):
        fill, border = surface(selected, self._hover, accent, dim)
        pen = QPen(border, width or (1.6 if selected else 1))
        if dashed:
            pen.setStyle(Qt.DashLine)
        p.setBrush(fill)
        p.setPen(pen)
        p.drawRoundedRect(r, RADIUS, RADIUS)


def index_name(i: int) -> str:
    return f"Emplacement {i + 1}"


# --------------------------------------------------------------------------------------------- pictogrammes
def draw_glyph(p: QPainter, fid: int, r: QRectF, color, width=2.0):
    """Pictogramme vectoriel du bloc `fid` dans le carré `r` (traits de la couleur du bloc)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    x0, y0, s = r.left(), r.top(), min(r.width(), r.height())

    def pt(a, b):
        return QPointF(x0 + a * s, y0 + b * s)

    def rc(a, b, c, d):
        return QRectF(x0 + a * s, y0 + b * s, (c - a) * s, (d - b) * s)

    pen = QPen(QColor(color), max(1.4, width * s / 30.0))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if fid == 5:                                                  # GATE : bruit sous un seuil, signal au-dessus
        dash = QPen(pen)
        dash.setStyle(Qt.DashLine)
        dash.setWidthF(pen.widthF() * 0.7)
        p.setPen(dash)
        p.drawLine(pt(0.08, 0.66), pt(0.92, 0.66))
        p.setPen(pen)
        pts = [(0.08, .5), (.14, .58), (.2, .44), (.26, .56), (.32, .46), (.38, .5), (.46, .5),
               (.52, .12), (.6, .88), (.68, .18), (.76, .82), (.84, .3), (.92, .5)]
        for a, b in zip(pts, pts[1:]):
            p.drawLine(pt(*a), pt(*b))
    elif fid == 1:                                                # COMP : deux droites qui se croisent
        p.drawLine(pt(.1, .2), pt(.9, .8))
        p.drawLine(pt(.1, .8), pt(.9, .2))
        p.drawLine(pt(.1, .5), pt(.3, .5))
        p.drawLine(pt(.7, .5), pt(.9, .5))
    elif fid == 2:                                                # EFX : pédale (potards + interrupteur)
        p.drawRoundedRect(rc(.24, .08, .76, .92), s * .07, s * .07)
        for cx in (.4, .6):
            p.drawEllipse(pt(cx, .27), s * .06, s * .06)
        p.drawLine(pt(.34, .46), pt(.66, .46))
        p.drawEllipse(pt(.5, .7), s * .1, s * .1)
    elif fid == 7:                                                # DLY : spires qui se répètent
        for i in range(4):
            p.drawEllipse(rc(.06 + i * .2, .22, .36 + i * .2, .78))
    elif fid == 9:                                                # IR : haut-parleur et ondes
        p.drawRect(rc(.08, .4, .24, .6))
        poly = [pt(.24, .4), pt(.5, .2), pt(.5, .8), pt(.24, .6)]
        p.drawPolygon(poly)
        for k, rad in enumerate((.14, .26, .38)):                 # ondes : arcs de plus en plus larges
            p.drawArc(rc(.46 - rad * .2, .5 - rad, .46 + rad * 1.6, .5 + rad), -48 * 16, 96 * 16)
    elif fid == 3:                                                # AMP : façade, potards, grille
        p.drawRoundedRect(rc(.08, .18, .92, .82), s * .08, s * .08)
        for cx in (.26, .5, .74):
            p.drawEllipse(pt(cx, .33), s * .045, s * .045)
        for cy in (.5, .6, .7):
            p.drawLine(pt(.2, cy), pt(.8, cy))
        p.drawLine(pt(.35, .46), pt(.35, .74))
        p.drawLine(pt(.65, .46), pt(.65, .74))
    elif fid == 4:                                                # EQ : trois curseurs verticaux
        for cx, cy in ((.24, .62), (.5, .3), (.76, .5)):
            p.drawLine(pt(cx, .1), pt(cx, .9))
            p.setBrush(QColor(color))
            p.drawEllipse(pt(cx, cy), s * .08, s * .08)
            p.setBrush(Qt.NoBrush)
    elif fid == 6:                                                # MOD : deux sinusoïdes déphasées
        for dy, ph in ((.36, 0), (.64, 3.14159)):
            prev = None
            for i in range(0, 41):
                t = i / 40
                q = pt(.08 + t * .84, dy + .15 * math.sin(t * 2 * math.pi * 1.5 + ph))
                if prev is not None:
                    p.drawLine(prev, q)
                prev = q
    elif fid == 8:                                                # RVB : deux carrés qui se recouvrent
        dash = QPen(pen)
        dash.setStyle(Qt.DashLine)
        p.setPen(dash)
        p.drawRoundedRect(rc(.1, .1, .6, .6), s * .05, s * .05)
        p.setPen(pen)
        p.drawRoundedRect(rc(.4, .4, .9, .9), s * .05, s * .05)
    p.restore()


TILE_FILL = QColor(34, 36, 42)


class GlyphWidget(QWidget):
    """Petite tuile (fond sombre + pictogramme) servant d'icône dans l'en-tête de la carte du bloc."""

    def __init__(self, fid=3, size=26, parent=None):
        super().__init__(parent)
        self.fid = fid
        self.setFixedSize(size, size)

    def set_effect(self, fid: int):
        if fid != self.fid:
            self.fid = fid
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        c = QColor(EFFECT_COLOR[self.fid])
        p.setPen(QPen(c, 1.4))
        p.setBrush(TILE_FILL)
        p.drawRoundedRect(r, 6, 6)
        draw_glyph(p, self.fid, r.adjusted(4, 4, -4, -4), c)


# --------------------------------------------------------------------------------------------- états
RED_STATE = "#E5534B"
STATE_INFO = {                  # clé -> (libellé, couleur, icône) ; la couleur de « sel » suit le thème
    "sel": ("Preset édité", None, FluentIcon.EDIT),
    "play": ("Joué par l'ampli", GREEN, FluentIcon.PLAY_SOLID),
    "synced": ("À jour", GREEN, FluentIcon.ACCEPT),
    "ahead": ("À renvoyer", ORANGE, None),
    "changed": ("Modifié sur l'ampli", RED_STATE, None),
    "unknown": ("Hors bibliothèque", GREY, FluentIcon.INFO),
    "unread": ("Non lu", GREY, None),
}
STATE_SHORT = {"synced": "À jour", "ahead": "À renvoyer", "changed": "Modifié", "unknown": "Hors biblio.",
               "unread": "Non lu"}
STATE_HELP = {
    "synced": "identique au preset de la bibliothèque",
    "ahead": "le preset de la bibliothèque a été modifié depuis l'envoi : à renvoyer vers l'ampli",
    "changed": "le contenu de l'ampli a changé en dehors de Melos (différent de ce qui y a été envoyé)",
    "unknown": "ce contenu n'est pas dans la bibliothèque (clic droit : l'importer)",
    "unread": "emplacement pas encore lu sur l'ampli",
}


def draw_badge(p: QPainter, rect: QRectF, kind: str):
    """Pastille d'état commune aux cartes et à la légende."""
    label, col, icon = STATE_INFO[kind]
    col = QColor(col) if col else themeColor()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if kind == "unread":
        pen = QPen(col, 1.2)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
    elif kind in ("sel", "play"):
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(rect)
        paint_icon(p, icon, rect.adjusted(rect.width() * .24, rect.height() * .24, -rect.width() * .24,
                                          -rect.height() * .24), QColor("white"))
    elif kind in ("ahead", "changed"):
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(rect.center(), rect.width() * .26, rect.height() * .26)
    else:
        paint_icon(p, icon, rect, col)
    p.restore()


class StateLegend(QWidget):
    """Ligne de légende sous les emplacements : explique chaque pastille / bordure."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        fluent_tip(self, "Clic sur un emplacement : l'ampli le joue · clic droit : importer, copier, envoyer…\n"
                         "À jour : identique à la bibliothèque · À renvoyer : bibliothèque modifiée depuis l'envoi\n"
                         "Modifié ampli : changé hors de Melos · Hors biblio. : contenu absent de la bibliothèque")
        self._items = [("play", "Joué"), ("sel", "Preset édité"), ("synced", "À jour"), ("ahead", "À renvoyer"),
                       ("changed", "Modifié ampli"), ("unknown", "Hors biblio."), ("unread", "Non lu")]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = small_font(self.font(), 1.5)
        fm = QFontMetrics(f)
        x = 2.0
        for kind, text in self._items:
            w = 19 + fm.horizontalAdvance(text) + 14
            if x + w > self.width():
                break
            draw_badge(p, QRectF(x, 3, 14, 14), kind)
            p.setFont(f)
            p.setPen(text_color("secondary"))
            p.drawText(QPointF(x + 19, 10 + fm.ascent() / 2 - 1), text)
            x += w


class SlotCard(_Card):
    """Un des 7 emplacements du Mighty. États indépendants, lus à des endroits fixes :
      - bordure épaisse (couleur du thème) + pastille crayon : contient le preset de la bibliothèque qu'on édite ;
      - fond et bordure verts + pastille lecture : preset joué par l'ampli ;
      - ligne du bas : À jour (coche) / À renvoyer (point orange) / Modifié ampli (point rouge) / Hors biblio. / Non lu.
    Clic = jouer (l'ampli bascule sur ce preset), clic droit = autres actions."""
    context = Signal(int, QPoint)

    def __init__(self, index: int, color: str, parent=None):
        super().__init__(index, parent)
        self.index = index
        self.color = QColor(color)
        self.title, self.subtitle = f"Preset {index + 1}", ""
        self.state, self.contains, self.current = "unread", False, False
        self._dbl = False
        self.setFixedHeight(112)
        self.setMinimumWidth(92)

    @property
    def empty(self) -> bool:
        return self.state == "unread"

    def set_info(self, title, subtitle, state, contains, current):
        new = (title, subtitle, state, contains, current)
        if new == (self.title, self.subtitle, self.state, self.contains, self.current):
            return
        self.title, self.subtitle, self.state, self.contains, self.current = new
        lines = [f"{index_name(self.index)} — {title}"]
        if subtitle:
            lines.append(subtitle)
        if current:
            lines.append("Joué par l'ampli")
        if contains:
            lines.append("Contient le preset édité")
        lines.append(f"{STATE_INFO[state][0]} : {STATE_HELP[state]}")
        lines.append("Clic : jouer · clic droit : autres actions")
        self.setToolTip("\n".join(lines))
        self.update()

    def mouseDoubleClickEvent(self, e):                     # un double clic = un seul « jouer »
        self._dbl = True

    def mouseReleaseEvent(self, e):
        if self._dbl:
            self._dbl = False
            return
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        self.context.emit(self.index, e.globalPos())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self.current:
            fill, border = surface(self.contains, self._hover, GREEN)
        else:
            fill, border = surface(self.contains, self._hover, None, self.empty)
        if self.current and self.contains:
            border = themeColor()
        pen = QPen(border, 2.4 if self.contains else (1.6 if self.current else 1))
        if self.empty and not self.contains and not self.current:
            pen.setStyle(Qt.DashLine)
        p.setBrush(fill)
        p.setPen(pen)
        p.drawRoundedRect(r, RADIUS, RADIUS)
        x0, pad = r.left() + 9, 9
        p.setPen(Qt.NoPen)
        p.setBrush(self.color if not self.empty else with_alpha(self.color, 90))
        p.drawEllipse(QRectF(x0, r.top() + 8, 22, 22))
        p.setFont(small_font(self.font(), 0, True))
        p.setPen(QColor("black") if self.color.lightness() > 150 else QColor("white"))
        p.drawText(QRectF(x0, r.top() + 8, 22, 22), Qt.AlignCenter, str(self.index + 1))
        bx = r.right() - pad - 18
        if self.current:
            draw_badge(p, QRectF(bx, r.top() + 10, 18, 18), "play")
            bx -= 22
        if self.contains:
            draw_badge(p, QRectF(bx, r.top() + 10, 18, 18), "sel")
        wtxt = r.width() - 2 * pad
        tf = small_font(self.font(), 0, True)
        lines = wrap_lines(self.title, tf, wtxt, 2)
        draw_text(p, x0, r.top() + 49, lines, tf, text_color("dim" if self.empty else "primary"), 15)
        sf = small_font(self.font(), 1.5)
        y = r.top() + 49 + 15 * len(lines) + 1
        draw_text(p, x0, y, wrap_lines(self.subtitle or ("—" if self.empty else ""), sf, wtxt, 1), sf,
                  text_color("secondary"), 13)
        label, col, _ = STATE_INFO[self.state]
        by = r.bottom() - 9
        draw_badge(p, QRectF(x0, by - 11, 13, 13), self.state)
        p.setFont(small_font(self.font(), 1.5, True))
        p.setPen(QColor(col))
        p.drawText(QPointF(x0 + 17, by), QFontMetrics(p.font()).elidedText(STATE_SHORT[self.state], Qt.ElideRight,
                                                                           int(wtxt - 17)))


class BlockChip(_Card):
    """Un bloc de la chaîne, à la manière de MightyEditor : tuile sombre à bordure colorée avec pictogramme, nom
    (COMP, EFX…) dessous, modèle en petit. Sélectionné : bordure épaisse + halo + barre sous le nom ; désactivé :
    tuile éteinte avec pastille « power ». Clic = sélection, glisser = changer l'ordre."""
    dropped = Signal(int, int, bool)     # (bloc glissé, bloc visé, déposé après le bloc visé ?)
    TILE = 66

    def __init__(self, fid: int, key: str = "", parent=None):
        super().__init__(fid, parent)
        self.fid = fid
        self.key_text = EFFECT_NAME[fid]
        self.color = QColor(EFFECT_COLOR[fid])
        self.model_name, self.on, self.selected = "", False, False
        self._press = None
        self._dragging = False
        self._drop_side = None                     # None | "before" | "after"
        self.setFixedHeight(118)
        self.setMinimumWidth(62)
        self.setAcceptDrops(True)

    def set_info(self, model_name, on, selected):
        if (model_name, on, selected) == (self.model_name, self.on, self.selected):
            return
        self.model_name, self.on, self.selected = model_name, on, selected
        self.setToolTip(f"{self.key_text} : {model_name} — {'actif' if on else 'désactivé'}\n"
                        "Clic : régler ce bloc (interrupteur dans le panneau du bas)\nGlisser : changer l'ordre dans la chaîne")
        self.update()

    def tile_rect(self) -> QRectF:
        side = min(self.width() - 6, self.TILE)
        return QRectF((self.width() - side) / 2, 4, side, side)

    # --- glisser-déposer ---
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if (e.buttons() & Qt.LeftButton) and self._press is not None \
                and (e.position().toPoint() - self._press).manhattanLength() > 10:
            self._press = None
            self.start_drag()

    def start_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_BLOCK, str(self.fid).encode())
        drag.setMimeData(mime)
        t = self.tile_rect().toRect()
        pm = self.grab(t.adjusted(-2, -2, 2, 2))
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        self._dragging = True
        self.update()
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self._dragging = False
            self.update()

    def mouseReleaseEvent(self, e):
        was_press = self._press is not None
        self._press = None
        if was_press:
            super().mouseReleaseEvent(e)

    def _side_at(self, x: float) -> str:
        return "after" if x > self.width() / 2 else "before"

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_BLOCK) and int(bytes(e.mimeData().data(MIME_BLOCK)).decode()) != self.fid:
            e.acceptProposedAction()
            self._drop_side = self._side_at(e.position().x())
            self.update()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME_BLOCK):
            side = self._side_at(e.position().x())
            if side != self._drop_side:
                self._drop_side = side
                self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drop_side = None
        self.update()

    def dropEvent(self, e):
        after = self._side_at(e.position().x()) == "after"
        self._drop_side = None
        self.update()
        src = int(bytes(e.mimeData().data(MIME_BLOCK)).decode())
        if src != self.fid:
            self.dropped.emit(src, self.fid, after)
        e.acceptProposedAction()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.tile_rect()
        on, c = self.on, self.color
        ink = c if on else QColor(GREY)
        # halo de la sélection
        if self.selected:
            for k, a in ((5, 28), (3, 46)):
                p.setPen(QPen(with_alpha(c if on else GREY, a), k))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(t.adjusted(-k / 2 + 1, -k / 2 + 1, k / 2 - 1, k / 2 - 1), 11, 11)
        # tuile
        fill = QColor(TILE_FILL) if on else QColor(46, 46, 50)
        if self._hover and not self._dragging:
            fill = fill.lighter(125)
        if self._dragging:
            fill.setAlpha(120)
        pen = QPen(with_alpha(c, 255) if on else QColor(95, 95, 100), 3.4 if self.selected else 2.2)
        p.setPen(pen)
        p.setBrush(fill)
        p.drawRoundedRect(t.adjusted(1.5, 1.5, -1.5, -1.5), 10, 10)
        g = t.adjusted(t.width() * .2, t.height() * .2, -t.width() * .2, -t.height() * .2)
        draw_glyph(p, self.fid, g, ink if on else QColor(125, 125, 130))
        if not on:                                                         # pastille « éteint »
            b = QRectF(t.right() - 20, t.bottom() - 20, 17, 17)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 22))
            p.drawEllipse(b)
            paint_icon(p, FluentIcon.POWER_BUTTON, b.adjusted(3, 3, -3, -3), QColor("#E5534B"))
        # nom
        nf = small_font(self.font(), -0.5, True)
        fm = QFontMetrics(nf)
        ty = t.bottom() + 16
        p.setFont(nf)
        p.setPen(text_color("primary") if on else text_color("dim"))
        p.drawText(QRectF(0, ty - fm.ascent() - 1, self.width(), fm.height()), Qt.AlignHCenter | Qt.AlignVCenter,
                   self.key_text)
        if self.selected:
            bw = fm.horizontalAdvance(self.key_text)
            p.setPen(Qt.NoPen)
            p.setBrush(text_color("primary"))
            p.drawRoundedRect(QRectF((self.width() - bw) / 2, ty + 4, bw, 2.4), 1.2, 1.2)
        # modèle (1 ligne rognée ; le texte complet est dans l'infobulle)
        mf = small_font(self.font(), 1.5)
        p.setFont(mf)
        p.setPen(text_color("secondary" if on else "dim"))
        shown = QFontMetrics(mf).elidedText(self.model_name, Qt.ElideRight, self.width() - 4)
        p.drawText(QRectF(2, ty + 9, self.width() - 4, 16), Qt.AlignHCenter | Qt.AlignVCenter, shown)
        # repère d'insertion pendant un glisser
        if self._drop_side:
            x = 1.5 if self._drop_side == "before" else self.width() - 1.5
            p.setPen(QPen(themeColor(), 3.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, t.top() - 2), QPointF(x, t.bottom() + 2))


class ChainArrow(QWidget):
    """Petit chevron entre deux blocs : sens du signal (aligné sur le centre des tuiles)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 118)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_icon(p, FluentIcon.CHEVRON_RIGHT, QRectF(0, 4 + BlockChip.TILE / 2 - 6, 12, 12), text_color("dim"))


class _LineEdit(QLineEdit):
    cancelled = Signal()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(e)


class EditableValue(QWidget):
    """Valeur numérique cliquable : double clic = saisie directe (Entrée valide, Échap annule, 0–100)."""
    committed = Signal(int)

    def __init__(self, accent="#4C8DF6", width=40, lo=0, hi=100, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self._value = lo, hi, lo
        self.setFixedSize(width, 22)
        lay = QStackedLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("0")
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f = self.label.font()
        f.setBold(True)
        self.label.setFont(f)
        self.label.setStyleSheet(f"color: {accent}; background: transparent;")
        self.edit = _LineEdit()
        self.edit.setValidator(QIntValidator(lo, hi))
        self.edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.edit.setFont(f)
        self.edit.setStyleSheet(f"QLineEdit {{ color: {accent}; background: rgba(128,128,128,40); "
                                f"border: 1px solid {accent}; border-radius: 4px; padding: 0 3px; }}")
        self.edit.editingFinished.connect(self._commit)
        self.edit.cancelled.connect(self._cancel)
        lay.addWidget(self.label)
        lay.addWidget(self.edit)
        self._stack = lay
        self.label.setCursor(Qt.IBeamCursor)
        fluent_tip(self, f"Double clic pour saisir une valeur ({lo}–{hi})")
        self._editing = False

    def set_accent(self, accent: str):
        self.label.setStyleSheet(f"color: {accent}; background: transparent;")

    def setValue(self, v: int):
        self._value = v
        self.label.setText(str(v))

    def value(self) -> int:
        return self._value

    def mouseDoubleClickEvent(self, e):
        self.begin_edit()

    def begin_edit(self):
        self._editing = True
        self.edit.setText(str(self._value))
        self._stack.setCurrentWidget(self.edit)
        self.edit.setFocus()
        self.edit.selectAll()

    def _finish(self):
        self._editing = False
        self._stack.setCurrentWidget(self.label)

    def _commit(self):
        if not self._editing:
            return
        txt = self.edit.text().strip()
        self._finish()
        if txt.lstrip("-").isdigit():
            v = max(self.lo, min(self.hi, int(txt)))
            if v != self._value:
                self.setValue(v)
                self.committed.emit(v)

    def _cancel(self):
        self._finish()


class ParamRow(QWidget):
    """Un réglage : nom à gauche, valeur colorée à droite (double clic pour la saisir), curseur dessous.
    `changed(valeur)` n'est émis que pour une action de l'utilisateur."""
    changed = Signal(int)

    def __init__(self, pdef, parent=None, accent="#4C8DF6"):
        super().__init__(parent)
        self.pdef = pdef
        self.setMinimumWidth(190)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        head = QHBoxLayout()
        head.setContentsMargins(10, 0, 10, 0)           # aligné sur la rainure du curseur (la poignée déborde de 10 px)
        self.label = ElidedLabel(pdef.name)
        self.value_label = EditableValue(accent)
        head.addWidget(self.label, 1)
        head.addWidget(self.value_label)
        col.addLayout(head)
        self.slider = self.combo = self.segment = None
        if pdef.kind == "choice":
            col.addWidget(self._choice_widget())
            self.value_label.hide()
        else:
            self.slider = NoWheelSlider(Qt.Horizontal)
            self.slider.setRange(0, 100)
            self.slider.valueChanged.connect(self._on_slider)
            self.value_label.committed.connect(self.slider.setValue)      # saisie directe -> même chemin qu'un curseur
            col.addWidget(self.slider)

    def _choice_widget(self):
        names = [c[1] for c in self.pdef.choices]
        if len(names) <= 3:
            self.segment = SegmentedWidget()
            for val, name in self.pdef.choices:
                self.segment.addItem(routeKey=str(val), text=name, onClick=lambda _=False, v=val: self.changed.emit(v))
            return self.segment
        self.combo = NoWheelComboBox()
        self.combo.addItems(names)
        self.combo.currentIndexChanged.connect(lambda i: self.changed.emit(self.pdef.choices[i][0]))
        return self.combo

    def _on_slider(self, v):
        self.value_label.setValue(v)
        if not self.slider.signalsBlocked():
            self.changed.emit(v)

    def set_value(self, v: int):
        """Affiche `v` sans émettre de signal ; ne touche pas à un curseur que l'utilisateur est en train de tirer."""
        if self.slider is not None:
            if self.slider.isSliderDown():
                return
            self.slider.blockSignals(True)
            self.slider.setValue(v)
            self.slider.blockSignals(False)
            self.value_label.setValue(v)
        elif self.segment is not None:
            if str(v) in self.segment.items:
                self.segment.setCurrentItem(str(v))
        elif self.combo is not None:
            vals = [c[0] for c in self.pdef.choices]
            if v in vals:
                self.combo.blockSignals(True)
                self.combo.setCurrentIndex(vals.index(v))
                self.combo.blockSignals(False)


class ParamGrid(QWidget):
    """Grille de réglages dont le nombre de colonnes suit la largeur disponible."""
    MIN_COL = 230

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(28)
        self._grid.setVerticalSpacing(12)
        self._rows: list[QWidget] = []
        self._cols = 0

    def set_rows(self, rows):
        self.clear()
        self._rows = list(rows)
        self._cols = 0
        self._layout_rows()

    def clear(self):
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
                it.widget().deleteLater()
        self._rows = []

    def columns(self) -> int:
        n = max(1, len(self._rows))
        return max(1, min(4, n, self.width() // self.MIN_COL if self.width() > 0 else 2))

    def _layout_rows(self):
        cols = self.columns()
        if cols == self._cols and self._grid.count() == len(self._rows):
            return
        while self._grid.count():
            self._grid.takeAt(0)
        for n, w in enumerate(self._rows):
            self._grid.addWidget(w, n // cols, n % cols, Qt.AlignTop)
            w.show()
        for c in range(4):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        self._cols = cols

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_rows()


class LibraryRow(_Card):
    """Une ligne de la bibliothèque : nom, étiquettes colorées, pastilles des emplacements du Mighty qui contiennent ce
    preset (anneau orange : l'ampli a une version plus ancienne ; rouge : modifié hors de Melos), point orange si le
    preset a été modifié depuis sa version d'origine."""
    doubleClicked = Signal(str)

    def __init__(self, entry_id: str, name: str, tags, slots, amp: str, modified=False, parent=None):
        super().__init__(0, parent)
        self.entry_id, self.name, self.tags, self.slots, self.amp = entry_id, name, list(tags), list(slots), amp
        self.modified = modified
        self.selected = False
        self.setFixedHeight(58)
        self._tip()

    def _tip(self):
        t = f"{self.name}\n{self.amp}" + (("\n" + ", ".join(self.tags)) if self.tags else "")
        if self.modified:
            t += "\nModifié depuis la version d'origine"
        if self.slots:
            t += "\nSur le Mighty : " + ", ".join(f"{s + 1} ({STATE_INFO[st][0].lower() if st in STATE_INFO else st})"
                                                  for s, _c, st in self.slots)
        else:
            t += "\nPas sur le Mighty"
        t += "\nDouble clic : écouter sur l'ampli"
        self.setToolTip(t)

    def set_state(self, slots, modified, name=None):
        if slots != self.slots or modified != self.modified or (name is not None and name != self.name):
            self.slots, self.modified = list(slots), modified
            if name is not None:
                self.name = name
            self._tip()
            self.update()

    def set_selected(self, v: bool):
        if v != self.selected:
            self.selected = v
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(0)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.entry_id)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        self._frame(p, r, self.selected)
        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(themeColor())
            p.drawRoundedRect(QRectF(r.left() + 1, r.top() + 8, 3.5, r.height() - 16), 1.75, 1.75)
        pad = 12
        right = r.right() - 8
        for s, color, st in reversed(self.slots):
            right -= 18
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(right, r.top() + 9, 16, 16))
            if st in ("ahead", "changed"):
                p.setPen(QPen(QColor(ORANGE if st == "ahead" else RED_STATE), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QRectF(right - 1, r.top() + 8, 18, 18))
            f = small_font(self.font(), 2.5, True)
            p.setFont(f)
            p.setPen(QColor("black") if QColor(color).lightness() > 150 else QColor("white"))
            p.drawText(QRectF(right, r.top() + 9, 16, 16), Qt.AlignCenter, str(s + 1))
            right -= 3
        nx = r.left() + pad
        if self.modified:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ORANGE))
            p.drawEllipse(QPointF(nx + 3.5, r.top() + 16.5), 3.5, 3.5)
            nx += 12
        nf = small_font(self.font(), 0, True)
        p.setFont(nf)
        p.setPen(text_color())
        name = QFontMetrics(nf).elidedText(self.name, Qt.ElideRight, int(right - nx))
        p.drawText(QPointF(nx, r.top() + 21), name)
        x, y, tf = r.left() + pad, r.top() + 31, small_font(self.font(), 2.5, True)
        if not self.tags:
            p.setFont(small_font(self.font(), 2))
            p.setPen(text_color("dim"))
            p.drawText(QPointF(x, y + 12), self.amp or "sans étiquette")
        else:
            for i, t in enumerate(self.tags):
                w = QFontMetrics(tf).horizontalAdvance(t) + 12
                if x + w > r.right() - 8:
                    pill(p, x, y, "…", GREY, tf)
                    break
                pill(p, x, y, t, tag_color(t), tf)
                x += w + 4


class TagPill(QWidget):
    """Étiquette cliquable de la barre de filtre (active = pleine, inactive = teintée)."""
    toggled = Signal(str, bool)

    def __init__(self, tag: str, active=False, parent=None):
        super().__init__(parent)
        self.tag, self.active, self._hover = tag, active, False
        self._font = small_font(self.font(), 1.5, True)
        self.setFixedSize(QFontMetrics(self._font).horizontalAdvance(tag) + 18, 22)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.active = not self.active
            self.toggled.emit(self.tag, self.active)
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = tag_color(self.tag)
        p.setPen(QPen(with_alpha(c, 255 if self.active else 110), 1))
        p.setBrush(c if self.active else with_alpha(c, 50 if self._hover else 30))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
        p.setFont(self._font)
        p.setPen(QColor("white") if self.active else c)
        p.drawText(self.rect(), Qt.AlignCenter, self.tag)


class PresetInfoDialog(MessageBoxBase):
    """Nom, étiquettes (séparées par des virgules) et notes d'un preset de la bibliothèque."""

    def __init__(self, parent, title: str, name="", tags=(), notes="", all_tags=()):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(title))
        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("Nom du preset")
        self.name_edit.setText(name)
        self.viewLayout.addWidget(self.name_edit)
        self.tags_edit = LineEdit()
        self.tags_edit.setPlaceholderText("Étiquettes, séparées par des virgules (ex. rock, clean, Nirvana)")
        self.tags_edit.setText(", ".join(tags))
        self.viewLayout.addWidget(self.tags_edit)
        if all_tags:
            hint = CaptionLabel("Déjà utilisées : " + ", ".join(all_tags))
            hint.setWordWrap(False)
            self.viewLayout.addWidget(hint)
        self.notes_edit = TextEdit()
        self.notes_edit.setPlaceholderText("Notes (facultatif)")
        self.notes_edit.setPlainText(notes)
        self.notes_edit.setFixedHeight(80)
        self.viewLayout.addWidget(self.notes_edit)
        self.widget.setMinimumWidth(420)
        self.yesButton.setText("Valider")
        self.cancelButton.setText("Annuler")
        self.name_edit.setFocus()

    def values(self):
        tags = [t.strip() for t in self.tags_edit.text().split(",")]
        return self.name_edit.text().strip(), [t for t in tags if t], self.notes_edit.toPlainText().strip()