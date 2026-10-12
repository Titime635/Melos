"""
Icônes vectorielles des catégories de styles de batterie (dessinées au QPainter, dans une grille 24x24,
donc nettes à toute taille et dans les deux thèmes) + étoile des favoris.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF


def _poly(*pts) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _star_path(cx, cy, r_out, r_in, points=5, rotation=-90.0) -> QPainterPath:
    path = QPainterPath()
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rotation + i * 180.0 / points)
        pt = QPointF(cx + r * math.cos(a), cy + r * math.sin(a))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


def draw_star(p: QPainter, rect: QRectF, color: QColor, filled: bool):
    """Étoile de favori."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.center())
    s = min(rect.width(), rect.height()) / 24.0
    p.scale(s, s)
    path = _star_path(0, 0.6, 10.5, 4.6)
    p.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(color if filled else Qt.NoBrush)
    p.drawPath(path)
    p.restore()


def _metro(p, c):
    p.setPen(QPen(c, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(_poly((8, 21), (16, 21), (14, 3.5), (10, 3.5)))
    p.drawLine(QPointF(12, 17), QPointF(16.5, 7))
    p.setBrush(c)
    p.drawEllipse(QPointF(15.2, 9.8), 1.5, 1.5)


def _rock(p, c):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawPolygon(_poly((14, 2), (5, 13.5), (11, 13.5), (9.5, 22), (19, 10), (13, 10)))


def _country(p, c):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    crown = QPainterPath()
    crown.moveTo(7.5, 14)
    crown.quadTo(7.5, 5, 12, 6.5)
    crown.quadTo(16.5, 5, 16.5, 14)
    crown.closeSubpath()
    p.drawPath(crown)
    brim = QPainterPath()
    brim.moveTo(2.5, 15)
    brim.quadTo(12, 20.5, 21.5, 15)
    brim.quadTo(20, 13.8, 17.5, 14.8)
    brim.quadTo(12, 16.3, 6.5, 14.8)
    brim.quadTo(4, 13.8, 2.5, 15)
    p.drawPath(brim)


def _note(p, c):
    p.setPen(QPen(c, 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(c)
    p.drawEllipse(QRectF(5, 15.5, 7, 5.2))
    p.drawLine(QPointF(11.7, 18), QPointF(11.7, 4))
    p.setBrush(Qt.NoBrush)
    flag = QPainterPath()
    flag.moveTo(11.7, 4)
    flag.cubicTo(14, 6.5, 18.5, 7, 18.5, 11.5)
    p.drawPath(flag)


def _metal(p, c):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawPath(_star_path(12, 12, 10.5, 5.2, points=8, rotation=-90 + 11.25))
    p.setBrush(Qt.NoBrush)


def _funk(p, c):
    p.setPen(QPen(c, 1.8, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(12, 12), 9.2, 9.2)
    p.drawEllipse(QPointF(12, 12), 5.2, 5.2)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 12), 1.7, 1.7)


def _jazz(p, c):
    p.setPen(QPen(c, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    body = QPainterPath()
    body.moveTo(7, 3.5)
    body.lineTo(12.5, 3.5)
    body.lineTo(12.5, 15)
    body.cubicTo(12.5, 21, 5.5, 21, 5.5, 15.5)
    p.drawPath(body)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(2.6, 13.6, 5.8, 4.6))
    p.setPen(QPen(c, 1.6, Qt.SolidLine, Qt.RoundCap))
    for y in (7.5, 11):
        p.drawPoint(QPointF(9.6, y))
    p.drawLine(QPointF(15.5, 3.5), QPointF(19.5, 3.5))


def _ballad(p, c):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    heart = QPainterPath()
    heart.moveTo(12, 21)
    heart.cubicTo(2, 14, 2.5, 5.5, 8, 5.5)
    heart.cubicTo(10.3, 5.5, 11.5, 7, 12, 8.2)
    heart.cubicTo(12.5, 7, 13.7, 5.5, 16, 5.5)
    heart.cubicTo(21.5, 5.5, 22, 14, 12, 21)
    p.drawPath(heart)


def _pop(p, c):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    spark = QPainterPath()
    spark.moveTo(10, 3)
    spark.quadTo(10.7, 9.3, 17, 10)
    spark.quadTo(10.7, 10.7, 10, 17)
    spark.quadTo(9.3, 10.7, 3, 10)
    spark.quadTo(9.3, 9.3, 10, 3)
    p.drawPath(spark)
    small = QPainterPath()
    small.moveTo(18, 14)
    small.quadTo(18.4, 17.6, 22, 18)
    small.quadTo(18.4, 18.4, 18, 22)
    small.quadTo(17.6, 18.4, 14, 18)
    small.quadTo(17.6, 17.6, 18, 14)
    p.drawPath(small)


def _reggae(p, c):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    leaf = QPainterPath()
    leaf.moveTo(5, 20)
    leaf.cubicTo(3, 9, 10, 3, 20, 3.5)
    leaf.cubicTo(20.5, 13, 14, 20.5, 5, 20)
    p.drawPath(leaf)
    p.setPen(QPen(QColor(0, 0, 0, 90), 1.5, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(6, 19), QPointF(15, 9.5))


def _elec(p, c):
    p.setPen(QPen(c, 2.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    wave = QPolygonF([QPointF(x, y) for x, y in
                      ((2.5, 12), (5.5, 12), (5.5, 5), (9.5, 5), (9.5, 19), (13.5, 19), (13.5, 8), (16.5, 8),
                       (16.5, 14), (21.5, 14))])
    p.drawPolyline(wave)


_DRAW = {"MET": _metro, "ROCK": _rock, "CTRY": _country, "BLUES": _note, "METAL": _metal, "FUNK": _funk,
         "JAZZ": _jazz, "BALD": _ballad, "POP": _pop, "REGGAE": _reggae, "ELEC": _elec}


def draw_category_icon(p: QPainter, key: str, rect: QRectF, color: QColor):
    """Dessine l'icône de la catégorie `key` (ou l'étoile pour "FAV") centrée dans `rect`."""
    if key == "FAV":
        draw_star(p, rect, color, True)
        return
    fn = _DRAW.get(key)
    if fn is None:
        return
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    s = min(rect.width(), rect.height()) / 24.0
    p.translate(rect.center().x() - 12 * s, rect.center().y() - 12 * s)
    p.scale(s, s)
    fn(p, color)
    p.restore()
