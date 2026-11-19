"""Thème de l'appli : "auto" (celui de Windows), "light" ou "dark" (réglage de la page Réglages)."""

from qfluentwidgets import Theme, isDarkTheme, qconfig, setTheme, setThemeColor

THEMES = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}


_installed = False


def apply_theme(name: str):
    """Applique le thème (clair / sombre / Windows) à toute l'appli : Fluent reprend alors la palette de la page Partition
    (couleur d'accent, fond, boutons, champs) au lieu de ses propres gris et de son cyan."""
    global _installed
    if not _installed:
        _installed = True
        from settings import load_settings
        set_contrast(load_settings()["ui"].get("contrast", False))
        from ui import fluent_style
        fluent_style.install()
        qconfig.themeChanged.connect(lambda *_: sync_fluent())
    setTheme(THEMES.get(name, Theme.AUTO))
    sync_fluent()


def sync_fluent():
    """Accorde la couleur d'accent de Fluent (curseurs, interrupteurs, sélection, indicateur du menu) à la palette courante."""
    from PySide6.QtGui import QColor
    try:
        setThemeColor(QColor(pal()["accent"]), save=False)
    except TypeError:                                    # anciennes versions de qfluentwidgets : pas de `save`
        setThemeColor(QColor(pal()["accent"]))
    _sync_app_palette()


def _sync_app_palette():
    """Palette Qt de l'appli = palette Partition : les widgets sans habillage propre (QLabel, listes, infobulles...) prennent
    ainsi la bonne couleur de texte et de fond dans les deux thèmes."""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    c, qp = pal(), QPalette(QApplication.palette())
    for roles, key in (((QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.ToolTipText), "text"),
                       ((QPalette.PlaceholderText,), "faint"), ((QPalette.Window,), "bg"),
                       ((QPalette.Base, QPalette.Button, QPalette.ToolTipBase), "raised"),
                       ((QPalette.Highlight,), "accent"), ((QPalette.HighlightedText,), "on_accent")):
        for role in roles:
            qp.setColor(role, QColor(c[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        qp.setColor(QPalette.Disabled, role, QColor(c["faint"]))
    app.setPalette(qp)


def window_background() -> tuple[str, str]:
    """(clair, sombre) : fond des pages, à donner à FluentWindow.setCustomBackgroundColor."""
    return LIGHT["bg"], DARK["bg"]


# ---------------------------------------------------------------------------------------------------------------------
# Page Partition : trois niveaux de gris pour la profondeur (fond < surface < relief) + couleurs douces (jamais fluo).
#   bg      : le fond de la page, le plus sombre ;      surface : les « cartes » (pistes, partition, lecture) ;
#   raised  : ce qui est posé sur une carte (boutons au repos, curseurs, ligne sélectionnée) ;  hover : survol.
# ---------------------------------------------------------------------------------------------------------------------
DARK = {"bg": "#0e1015", "surface": "#171920", "raised": "#20242d", "hover": "#2b303e", "border": "#2b303d",
        "text": "#eff0f4", "muted": "#a6abb9", "faint": "#707585",
        "accent": "#619af4", "on_accent": "#06122a", "solo": "#619af4", "mute": "#e66570", "preview": "#47ca8f",
        "amber": "#efb74a", "staff": "#3a404e", "bar": "#737a8b", "barnum": "#94a5c2", "glyph": "#edeef3", "glyph2": "#a6abb9"}
# Variante « Contraste » du thème sombre (Réglages) : fond presque noir, texte et accents plus vifs. Les valeurs remplacent celles de
# DARK sur place (DARK reste le même objet, les modules qui l'ont importé suivent).
_DARK_BASE = dict(DARK)
DARK_CONTRAST = {"bg": "#050609", "surface": "#0d0f14", "raised": "#171a21", "hover": "#232731", "border": "#2c313c",
                 "text": "#f7f8fb", "muted": "#b6bbc8", "faint": "#7b8191",
                 "accent": "#6ca7ff", "solo": "#6ca7ff", "mute": "#f7737e", "preview": "#3fe09a", "amber": "#ffc24f",
                 "staff": "#444b59", "bar": "#7c8394", "barnum": "#9db2d4"}
_contrast = False


def set_contrast(on: bool):
    """Active / coupe la variante Contraste du thème sombre (modifie DARK ; à suivre de refresh_theme())."""
    global _contrast
    _contrast = bool(on)
    DARK.update(_DARK_BASE)
    if _contrast:
        DARK.update(DARK_CONTRAST)


def contrast_enabled() -> bool:
    return _contrast


def refresh_theme():
    """Repeint toute l'appli après un changement de palette sans changement de thème clair / sombre."""
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets.common.style_sheet import updateStyleSheet
    updateStyleSheet(False)
    qconfig.themeChanged.emit(qconfig.theme)
    sync_fluent()
    for w in QApplication.topLevelWidgets():
        if hasattr(w, "setCustomBackgroundColor"):
            w.setCustomBackgroundColor(*window_background())
    qconfig.themeChangedFinished.emit()


LIGHT = {"bg": "#e9ecf2", "surface": "#ffffff", "raised": "#f1f3f7", "hover": "#e4e8ef", "border": "#d8dce5",
         "text": "#1b1e27", "muted": "#5e6473", "faint": "#9ca2b0",
         "accent": "#346fda", "on_accent": "#ffffff", "solo": "#346fda", "mute": "#d0434f", "preview": "#269964",
         "amber": "#c48823", "staff": "#d2d6e0", "bar": "#8890a1", "barnum": "#677a9f", "glyph": "#1d2028", "glyph2": "#5e6473"}

# les 7 emplacements de preset : exactement les couleurs de l'écran du Mighty Plug Pro (vert, orange, rouge, bleu, cyan, magenta,
# rose clair) ; pastilles de la partition, de la popup et de ses puces, boutons des presets du Dashboard / de Classique, setlist
# et éditeur de presets
SLOT_COLORS = ("#22d12a", "#f08a1e", "#ec3a35", "#1f6bf5", "#2fc8e0", "#e468d4", "#f8bff2")
PRESET_COLORS = {i: c for i, c in enumerate(SLOT_COLORS)}

# les 9 blocs d'effets, couleurs de la barre d'effets du Mighty (numéros de l'éditeur : 1 COMP, 2 EFX, 3 AMP, 4 EQ, 5 GATE,
# 6 MOD, 7 DLY, 8 RVB, 9 IR)
EFFECT_COLORS = {1: "#f4ef4a", 2: "#f07a3c", 3: "#e0383f", 4: "#e6e6e6", 5: "#b7cf3a",
                 6: "#4b64e8", 7: "#6ee3d6", 8: "#b07ad8", 9: "#4aaed0"}

# couleur d'identité de chaque module du Dashboard : teintes franches mais pas flashy, lisibles sur fond clair comme sombre
MODULE_COLORS = {"presets": "#36bb7b", "tuner": "#2bb5ce", "drums": "#eb7b51", "loop": "#a46fe8", "tempo": "#e6a327",
                 "setlist": "#4e86e7"}

# texte posé sur une couleur franche (pastille, bouton coloré)
ON_SOFT = "#10131a"

# couleurs d'état (enregistrer, lire, attendre...)
STATE_COLORS = {"rec": "#e64f58", "overdub": "#ef9f18", "play": "#37c57e", "wait": "#4f8bec", "neutral": "#8c93a7",
                "ok": "#37c57e", "warn": "#efa62f", "error": "#e64f58"}

# couleurs par famille d'instrument
INSTRUMENT_COLORS = {"guitar": "#eaa13a", "bass": "#a46fe8", "drums": "#eb7b51", "vocals": "#e5729c", "keys": "#36bb7b",
                     "wind": "#2bb5ce", "strings": "#5f8fe0", "synth": "#be71da", "other": "#8c93a7"}


def page_icon(icon, color: str):
    """Icône Fluent teintée (barre latérale, titres de cartes) : la couleur telle quelle en sombre, un peu assombrie en clair."""
    from PySide6.QtGui import QColor
    c = QColor(color)
    return icon.colored(mix(c, QColor(LIGHT["text"]), 0.22), c)


def pal() -> dict:
    return DARK if isDarkTheme() else LIGHT


def qc(name: str, alpha: float | None = None):
    """Couleur de la palette courante (`alpha` : 0 à 1)."""
    from PySide6.QtGui import QColor
    c = QColor(pal().get(name, name))
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def rgba(color, alpha: float) -> str:
    """« rgba(r,g,b,a) » d'une couleur (nom de palette, « #rrggbb » ou QColor) pour une feuille de style."""
    from PySide6.QtGui import QColor
    c = QColor(pal().get(color, color)) if isinstance(color, str) else QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def mix(a, b, t: float):
    """Mélange de deux QColor : t = 0 → a, t = 1 → b."""
    from PySide6.QtGui import QColor
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


def card_style(selector: str, radius: int = 12, border: bool = True, level: str = "surface") -> str:
    """Feuille de style d'une carte (fond d'un niveau de la palette + fine bordure)."""
    p = pal()
    return f"{selector}{{background:{p[level]};border:{'1px solid ' + p['border'] if border else 'none'};border-radius:{radius}px}}"


def score_bg() -> str:
    return pal()["surface"]


def scrollbar_qss(width: int = 8) -> str:
    """Barres de défilement fines et arrondies (poignée discrète, plus nette au survol), sans flèches."""
    p = pal()
    thumb, hover = rgba(p["muted"], 0.32), rgba(p["muted"], 0.6)
    return (f"QScrollBar:vertical{{background:transparent;width:{width}px;margin:2px 1px}}"
            f"QScrollBar::handle:vertical{{background:{thumb};border-radius:{width // 2 - 1}px;min-height:36px}}"
            f"QScrollBar::handle:vertical:hover{{background:{hover}}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;width:0}}"
            f"QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:transparent}}"
            f"QScrollBar:horizontal{{background:transparent;height:{width}px;margin:1px 2px}}"
            f"QScrollBar::handle:horizontal{{background:{thumb};border-radius:{width // 2 - 1}px;min-width:36px}}"
            f"QScrollBar::handle:horizontal:hover{{background:{hover}}}"
            f"QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{height:0;width:0}}"
            f"QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{{background:transparent}}")


def style_popup(widget, radius: int = 12, level: str = "surface"):
    """Habille une fenêtre flottante comme les popups de la partition : fond « relief » + fine bordure arrondie, coins nets
    (fond transparent), et bonne teinte quand on change de thème. Dessiné à la main : un fond en feuille de style ne s'affiche
    pas de façon fiable sur une fenêtre transparente."""
    from PySide6.QtCore import QEvent, QObject, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen

    class Painter(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Paint:
                c = pal()
                p = QPainter(obj)
                p.setRenderHint(QPainter.Antialiasing)
                p.setBrush(QColor(c[level]))
                p.setPen(QPen(QColor(c["border"]).lighter(125), 1))
                p.drawRoundedRect(QRectF(obj.rect()).adjusted(.5, .5, -.5, -.5), radius, radius)
                p.end()
            return False

    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    widget.setStyleSheet("")
    widget._popup_painter = Painter(widget)
    widget.installEventFilter(widget._popup_painter)
    qconfig.themeChanged.connect(lambda *_: _safe_update(widget))


def _safe_update(widget):
    try:
        widget.update()
    except RuntimeError:                                  # widget détruit
        pass


def accent_fg(color):
    """Texte posé sur une teinte douce d'une couleur (bouton actif) : la couleur, assombrie en thème clair / éclaircie en sombre
    pour rester lisible."""
    from PySide6.QtGui import QColor
    c = QColor(pal().get(color, color)) if isinstance(color, str) else QColor(color)
    return mix(c, QColor(pal()["text"]), 0.2 if isDarkTheme() else 0.62)