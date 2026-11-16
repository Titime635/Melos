"""
Jeu d'icônes de la page Partition : un seul style (trait de 1,8 px, bouts arrondis, grille 24×24) pour que tout se
ressemble, dont les instruments. Dessinées en SVG, colorées à la demande, mises en cache.
"""

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# corps SVG (le trait prend la couleur demandée ; `fill` = pleine)
ICONS: dict[str, str] = {
    # transport
    "play": '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.2-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z" fill="{c}"/>',
    "pause": '<rect x="6" y="4.5" width="4.2" height="15" rx="1.2" fill="{c}"/><rect x="13.8" y="4.5" width="4.2" height="15" rx="1.2" fill="{c}"/>',
    "volume": '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>',
    "volume-low": '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>',
    "volume-x": '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="m16 9 5 6"/><path d="m21 9-5 6"/>',
    "gauge": '<path d="m12 14 4-4"/><path d="M3.3 19a10 10 0 1 1 17.4 0"/>',
    "metronome": '<path d="M12 11.5V8.5"/><path d="m12 17 6.6-6.6"/><path d="m15 5.5-.2-.7a3 3 0 0 0-5.6 0L4.4 19.7A1 1 0 0 0 5.4 21h13.2a1 1 0 0 0 1-1.3L18.4 16"/><circle cx="20" cy="9" r="1.6"/>',
    "repeat": '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    "count": '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 1.5"/><path d="M9.5 2.5h5"/>',
    # navigation / actions
    "library": '<path d="M4 4v16"/><path d="M8.5 7v13"/><path d="M13 5.5v14.5"/><path d="m16.8 6.4 3.6 13.2"/>',
    "history": '<path d="M3 12a9 9 0 1 0 2.64-6.36L3 8"/><path d="M3 3v5h5"/><path d="M12 7.5V12l3 2"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.6-4.6"/>',
    "external": '<path d="M14.5 3.5h6v6"/><path d="m10.5 13.5 10-10"/><path d="M18.5 13.5v5a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2h5"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/>',
    "download": '<path d="M20.5 15v3.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V15"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M12 15V3.5"/>',
    "pedal": '<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M8.5 7h7"/><circle cx="9" cy="11.2" r="1.3"/><circle cx="15" cy="11.2" r="1.3"/><circle cx="12" cy="16.4" r="2.3"/>',
    "loop": '<path d="M4 8v-.5A2.5 2.5 0 0 1 6.5 5H19"/><path d="m16 2 3 3-3 3"/><path d="M20 16v.5a2.5 2.5 0 0 1-2.5 2.5H5"/><path d="m8 22-3-3 3-3"/><path d="M12 10.2v3.6"/>',
    "amp": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><circle cx="8.2" cy="12" r="2.4"/><path d="M14 9.5h4"/><path d="M14 12h4"/><path d="M14 14.5h4"/>',
    "bookmark": '<path d="M18.5 20.5 12 16.2l-6.5 4.3v-15a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2z"/>',
    "bookmark-fill": '<path d="M18.5 20.5 12 16.2l-6.5 4.3v-15a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2z" fill="{c}"/>',
    "star": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
    "star-fill": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" fill="{c}"/>',
    "sliders": '<path d="M20.5 5h-8"/><path d="M8 5H3.5"/><path d="M20.5 12H16"/><path d="M11.5 12h-8"/><path d="M20.5 19h-5"/><path d="M11 19H3.5"/><circle cx="10" cy="5" r="2"/><circle cx="14" cy="12" r="2"/><circle cx="13" cy="19" r="2"/>',
    "panel-left": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9.5 4v16"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "close": '<path d="m6 6 12 12"/><path d="M18 6 6 18"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "save": '<path d="M5 3.5h11l3.5 3.5v11.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2z"/><path d="M7.5 3.5v5h7v-5"/><path d="M7.5 20.5v-6h9v6"/>',
    "headphones": '<path d="M3.5 15.5v-3.5a8.5 8.5 0 0 1 17 0v3.5"/><path d="M3.5 15.5h2.5a1.5 1.5 0 0 1 1.5 1.5v2a1.5 1.5 0 0 1-1.5 1.5h-1a2 2 0 0 1-2-2z"/><path d="M20.5 15.5H18a1.5 1.5 0 0 0-1.5 1.5v2a1.5 1.5 0 0 0 1.5 1.5h1a2 2 0 0 0 2-2z"/>',
    "mute": '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="m16 9 5 6"/><path d="m21 9-5 6"/>',
    # instruments
    "guitar": '<path d="m11.9 12.1 4.5-4.5"/><path d="M20.1 2.3a1 1 0 0 0-1.4 0l-1.1 1.1a2 2 0 0 0-.6 1.4v1.3a2 2 0 0 1-.6 1.4 2 2 0 0 1 1.4-.6h1.3a2 2 0 0 0 1.4-.6l1.1-1.1a1 1 0 0 0 0-1.4z"/><path d="m6 16 2 2"/><path d="M8.2 9.9A3 3 0 0 1 11 8a5 5 0 0 1 5 5 3 3 0 0 1-1.9 2.8l-.9.4A2 2 0 0 0 12 18a4 4 0 0 1-4 4 6 6 0 0 1-6-6 4 4 0 0 1 4-4 2 2 0 0 0 1.9-1.2z"/>',
    "bass": '<path d="m12.5 11.5 7.3-7.3"/><path d="m17.6 2.6 3.8 3.8-1.6 1.6-3.8-3.8z"/><path d="M9.3 9.7a2.6 2.6 0 0 0-3.1 1.4c-.7 1.5-2.7 1.9-2.7 4.9a5.5 5.5 0 0 0 5.5 5.5c3 0 3.4-2 4.9-2.700a2.600 2.600 0 0 0 1.400-3.100z"/><path d="m7.500 16.500 1.500 1.500"/>',
    "drums": '<path d="m2.5 2.5 7.5 7.5"/><path d="m21.5 2.5-7.5 7.5"/><ellipse cx="12" cy="10" rx="9.5" ry="4.5"/><path d="M2.5 10v7.5c0 2.5 4.3 4.5 9.5 4.5s9.5-2 9.5-4.5V10"/><path d="M12 14.5V22"/>',
    "mic": '<rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><path d="M12 18v3.5"/><path d="M8.5 21.5h7"/>',
    "keys": '<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M9 19v-5"/><path d="M15 19v-5"/><path d="M9 5v5.5"/><path d="M15 5v5.5"/>',
    "wind": '<path d="M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2"/><path d="M9.6 4.6A2 2 0 1 1 11 8H2"/><path d="M12.6 19.4A2 2 0 1 0 14 16H2"/>',
    "strings": '<path d="M12 2.5v6"/><path d="M9 8.5h6"/><path d="M8.5 12.5a3.5 3.5 0 0 1 7 0c0 1.3-.7 2-1 3 .5 1 1.3 2 1.3 3.2a4.3 4.3 0 0 1-8.6 0c0-1.2.8-2.2 1.3-3.2-.3-1-1-1.7-1-3z"/>',
    "synth": '<path d="M2.5 6.5c.7.6 1.3 1 2.7 1 2.4 0 2.4-2 4.9-2 2.5 0 2.5 2 5 2s2.5-2 5-2c1.4 0 2 .4 2.9 1"/><path d="M2.5 12.5c.7.6 1.3 1 2.7 1 2.4 0 2.4-2 4.9-2 2.5 0 2.5 2 5 2s2.5-2 5-2c1.4 0 2 .4 2.9 1"/><path d="M2.5 18.5c.7.6 1.3 1 2.7 1 2.4 0 2.4-2 4.9-2 2.5 0 2.5 2 5 2s2.5-2 5-2c1.4 0 2 .4 2.9 1"/>',
    "music": '<path d="M9 18V5.5l11-2V16"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
}

_cache: dict[tuple, QIcon] = {}


def _svg(name: str, color: str, width: float = 1.8) -> bytes:
    body = ICONS[name].replace("{c}", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode("utf-8")


def pixmap(name: str, color: str = "#ffffff", size: int = 18, dpr: float = 2.0, width: float = 1.8) -> QPixmap:
    """Icône `name` de `size` px logiques, dessinée en `dpr` fois plus fin pour rester nette."""
    px = round(size * dpr)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    QSvgRenderer(QByteArray(_svg(name, color, width))).render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = "#ffffff", size: int = 18) -> QIcon:
    key = (name, color, size)
    ic = _cache.get(key)
    if ic is None:
        ic = _cache[key] = QIcon(pixmap(name, color, size))
    return ic


def instrument_kind(instrument: str, family: str = "other") -> str:
    """Famille d'affichage d'une piste (guitare, basse, batterie, voix, claviers, vents, cordes, synthé, autre)."""
    n = (instrument or "").lower()
    for kind, words in (("keys", ("piano", "keys", "organ", "harpsichord", "clav", "rhodes", "accordion")),
                        ("wind", ("sax", "flute", "trumpet", "trombone", "horn", "clarinet", "oboe", "bassoon", "harmonica", "whistle", "tuba")),
                        ("strings", ("violin", "viola", "cello", "contrabass", "string", "harp", "orchestra", "banjo", "mandolin", "ukulele", "sitar")),
                        ("synth", ("synth", "pad", "lead", "fx", "sweep", "voice oo"))):
        if any(w in n for w in words):
            return kind
    return family if family in ("guitar", "bass", "drums", "vocals") else "other"


def instrument_icon_name(kind: str) -> str:
    return {"guitar": "guitar", "bass": "bass", "drums": "drums", "vocals": "mic", "keys": "keys", "wind": "wind",
            "strings": "strings", "synth": "synth"}.get(kind, "music")