"""Thème de l'appli : "auto" (celui de Windows), "light" ou "dark" (réglage de la page Réglages)."""

from qfluentwidgets import Theme, isDarkTheme, setTheme

THEMES = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}


def apply_theme(name: str):
    setTheme(THEMES.get(name, Theme.AUTO))


# ---------------------------------------------------------------------------------------------------------------------
# Page Partition : trois niveaux de gris pour la profondeur (fond < surface < relief) + couleurs douces (jamais fluo).
#   bg      : le fond de la page, le plus sombre ;      surface : les « cartes » (pistes, partition, lecture) ;
#   raised  : ce qui est posé sur une carte (boutons au repos, curseurs, ligne sélectionnée) ;  hover : survol.
# ---------------------------------------------------------------------------------------------------------------------
DARK = {"bg": "#111214", "surface": "#1a1b1e", "raised": "#25262b", "hover": "#2f3036", "border": "#2a2b30",
        "text": "#e8e9ed", "muted": "#9c9ea9", "faint": "#6a6c77",
        "accent": "#6aa8d2", "on_accent": "#0d1822", "solo": "#6aa8d2", "mute": "#d9727c", "preview": "#6bbf90",
        "amber": "#dba65c", "staff": "#3b3d46", "bar": "#6b6e7b", "barnum": "#7f95b3", "glyph": "#e6e7ec", "glyph2": "#9fa2ae"}
LIGHT = {"bg": "#e7e8ed", "surface": "#ffffff", "raised": "#eff0f4", "hover": "#e2e4ea", "border": "#d8dae1",
         "text": "#1c1e23", "muted": "#646876", "faint": "#a2a6b2",
         "accent": "#2d7db0", "on_accent": "#ffffff", "solo": "#2d7db0", "mute": "#c8505c", "preview": "#3f9a6b",
         "amber": "#c4832a", "staff": "#d3d6de", "bar": "#8a90a0", "barnum": "#7088aa", "glyph": "#202228", "glyph2": "#5d616e"}

# une teinte douce par emplacement de preset (0-6) : pastilles de la partition, de la popup et de ses puces
SLOT_COLORS = ("#6aa8d2", "#e0a458", "#a590e0", "#dc8a6c", "#e17f9f", "#6fc3a1", "#c9b86a")

# couleurs douces par famille d'instrument
INSTRUMENT_COLORS = {"guitar": "#e0a458", "bass": "#a590e0", "drums": "#dc8a6c", "vocals": "#e17f9f", "keys": "#6fc3a1",
                     "wind": "#7fc7d1", "strings": "#86aee0", "synth": "#c58fdb", "other": "#8d96ab"}


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