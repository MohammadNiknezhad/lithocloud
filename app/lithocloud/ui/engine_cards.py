"""Engine cards (amendment A3, 2026-09-22).

The engine list stays a ``QListWidget`` - selection, current-row signals and
keyboard navigation are untouched - switched to icon mode with a delegate
that paints each engine as a rounded card: its icon (the manifest's SVG via
QtSvg, or a neutral dot-grid fallback), its name and its version.

States, in the BRAND.md palette (ink #1B2430, ÉTS red #DE002B and its
tint/shade, tagline grey #5A6470):

* normal   - 1 px grey border
* hover    - thicker grey border, slightly emphasised background
* selected - brand-red border, always stronger than hover

The fallback is drawn, never a file, so an engine without an icon - or with
an unreadable one - can never leave a broken image on screen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
)

# -- BRAND.md palette ------------------------------------------------------- #
INK = QColor("#1B2430")
RED = QColor("#DE002B")
RED_TINT = QColor("#FF4B66")
RED_SHADE = QColor("#9C001E")
GREY = QColor("#5A6470")


def _alpha(color: QColor, alpha: int) -> QColor:
    out = QColor(color)
    out.setAlpha(alpha)
    return out


CARD_SIZE = QSize(200, 72)
CARD_RADIUS = 8
ICON_PX = 32
CARD_SPACING = 8

BORDER_NORMAL = (_alpha(GREY, 110), 1.0)
BORDER_HOVER = (_alpha(GREY, 200), 2.0)
BORDER_SELECTED = (RED, 2.5)
FILL_NORMAL = QColor("#FFFFFF")
FILL_HOVER = _alpha(INK, 12)
FILL_SELECTED = _alpha(RED, 18)

#: item data roles
ENGINE_ROLE = Qt.ItemDataRole.UserRole
ICON_PATH_ROLE = Qt.ItemDataRole.UserRole + 1


# --------------------------------------------------------------------------- #
# Icons
# --------------------------------------------------------------------------- #

_cache: dict[str, QPixmap] = {}


def render_svg_icon(path: "Path | str | None", size: int = ICON_PX) -> "QPixmap | None":
    """The SVG at *path* rendered to *size* px, or None when absent/unreadable."""
    if not path:
        return None
    key = "{0}@{1}".format(path, size)
    if key in _cache:
        return _cache[key]
    file = Path(path)
    if not file.is_file():
        return None
    renderer = QSvgRenderer(str(file))
    if not renderer.isValid():
        return None
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    _cache[key] = pixmap
    return pixmap


def fallback_icon(size: int = ICON_PX) -> QPixmap:
    """A neutral 3x3 dot grid in tagline grey - the 'no icon' mark."""
    key = "<fallback>@{0}".format(size)
    if key in _cache:
        return _cache[key]
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_alpha(GREY, 160))
    step = size / 4.0
    radius = size / 14.0
    for row in range(1, 4):
        for column in range(1, 4):
            painter.drawEllipse(QRectF(column * step - radius, row * step - radius,
                                       2 * radius, 2 * radius))
    painter.end()
    _cache[key] = pixmap
    return pixmap


def engine_icon(icon_path: "Path | str | None", size: int = ICON_PX) -> QPixmap:
    """The engine's icon or the fallback - never None, never a broken image."""
    return render_svg_icon(icon_path, size) or fallback_icon(size)


# --------------------------------------------------------------------------- #
# The delegate
# --------------------------------------------------------------------------- #


class EngineCardDelegate(QStyledItemDelegate):
    """Paints one engine as a rounded card. Data: ENGINE_ROLE -> Engine."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt API
        return CARD_SIZE

    def paint(self, painter: QPainter, option, index) -> None:
        engine = index.data(ENGINE_ROLE)
        name = getattr(engine, "name", None) or index.data(Qt.ItemDataRole.DisplayRole) or ""
        version = getattr(engine, "version", "") or ""
        icon = engine_icon(index.data(ICON_PATH_ROLE))

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            border_color, border_width, fill = *BORDER_SELECTED, FILL_SELECTED
        elif hovered:
            border_color, border_width, fill = *BORDER_HOVER, FILL_HOVER
        else:
            border_color, border_width, fill = *BORDER_NORMAL, FILL_NORMAL

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(1, 1, -1, -1)
        inset = border_width / 2.0
        rect = rect.adjusted(inset, inset, -inset, -inset)
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

        # icon, vertically centred at the left
        icon_x = rect.left() + 12
        icon_y = rect.top() + (rect.height() - ICON_PX) / 2.0
        painter.drawPixmap(int(icon_x), int(icon_y), icon)

        # name (bold ink) over version (grey)
        text_left = icon_x + ICON_PX + 12
        text_rect = QRectF(text_left, rect.top() + 12, rect.right() - text_left - 10,
                           rect.height() - 24)
        name_font = QFont(option.font)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(INK)
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(str(name), Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(QRectF(text_rect.left(), text_rect.top(), text_rect.width(),
                                metrics.height()), Qt.AlignmentFlag.AlignLeft, elided)
        painter.setFont(QFont(option.font))
        painter.setPen(RED_SHADE if selected else GREY)
        vmetrics = painter.fontMetrics()
        painter.drawText(QRectF(text_rect.left(), text_rect.top() + metrics.height() + 2,
                                text_rect.width(), vmetrics.height()),
                         Qt.AlignmentFlag.AlignLeft, "v{0}".format(version) if version else "")
        painter.restore()


def configure_card_view(view: QListWidget) -> EngineCardDelegate:
    """Turn a QListWidget into the flowing card grid, keeping its behaviour."""
    view.setViewMode(QListView.ViewMode.IconMode)
    view.setFlow(QListView.Flow.LeftToRight)
    view.setWrapping(True)
    view.setResizeMode(QListView.ResizeMode.Adjust)
    view.setMovement(QListView.Movement.Static)
    view.setSpacing(CARD_SPACING)
    view.setUniformItemSizes(True)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setMouseTracking(True)                 # hover state for the delegate
    view.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    view.setFrameShape(view.Shape.NoFrame)
    delegate = EngineCardDelegate(view)
    view.setItemDelegate(delegate)
    return delegate
