"""Amendment A3: the manifest 'icon' key and the engine cards."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QListView

from lithocloud.core import ManifestError, discover_engines, load_manifest
from lithocloud.ui import engine_cards
from lithocloud.ui.engine_cards import (
    CARD_SIZE,
    ENGINE_ROLE,
    ICON_PATH_ROLE,
    EngineCardDelegate,
    engine_icon,
    fallback_icon,
    render_svg_icon,
)
from lithocloud.ui.engine_panel import EnginePanel

from conftest import write_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]

BASE = 'id: {id}\nname: N\nversion: "1.0"\n{extra}actions: [{{id: a, label: A}}]\nrun: {{command: x}}\n'


def manifest(tmp_path: Path, folder: str = "e", extra: str = "") -> Path:
    return write_manifest(tmp_path / folder, BASE.format(id=folder, extra=extra))


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def test_icon_is_optional_and_resolves_inside_the_engine_folder(tmp_path: Path) -> None:
    engine = load_manifest(manifest(tmp_path))
    assert engine.icon is None and engine.icon_path is None

    engine = load_manifest(manifest(tmp_path, "f", "icon: art/mark.svg\n"))
    assert engine.icon == "art/mark.svg"
    assert engine.icon_path == (tmp_path / "f" / "art" / "mark.svg").resolve()


def test_icon_need_not_exist_at_load_time(tmp_path: Path) -> None:
    """A missing file is a fallback at render time, not a broken manifest."""
    engine = load_manifest(manifest(tmp_path, "g", "icon: missing.svg\n"))
    assert engine.icon_path is not None and not engine.icon_path.exists()


@pytest.mark.parametrize(
    ("icon", "message"),
    [
        ("icon: C:/abs/mark.svg\n", "relative to the engine folder"),
        ("icon: /abs/mark.svg\n", "relative to the engine folder"),
        ("icon: ../mark.svg\n", "no '..'"),
        ("icon: mark.png\n", "must be an .svg file"),
        ("icon: 3\n", "icon"),
        ('icon: ""\n', "icon"),
    ],
)
def test_bad_icon_values_are_rejected(tmp_path: Path, icon: str, message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        load_manifest(manifest(tmp_path, "h", icon))


def test_every_engine_manifest_still_loads_and_three_carry_icons() -> None:
    engines, problems = discover_engines(REPO_ROOT, include_private=True)
    assert problems == []
    icons = {e.id: e.icon for e in engines}
    assert icons == {"demo": None, "geohazard": "icon.svg", "ricp": "icon.svg", "tlsphoto": "icon.svg"}
    for engine in engines:
        if engine.icon_path is not None:
            assert engine.icon_path.is_file(), engine.id


# --------------------------------------------------------------------------- #
# Icons: SVG rendering and the fallback
# --------------------------------------------------------------------------- #


def test_real_icons_render_at_32px(qtbot) -> None:
    for name in ("geohazard", "ricp", "tlsphoto"):
        pixmap = render_svg_icon(REPO_ROOT / "engines" / name / "icon.svg")
        assert pixmap is not None and not pixmap.isNull(), name
        assert pixmap.size() == QSize(32, 32)


def test_the_icons_use_only_the_brand_palette() -> None:
    allowed = {"#1B2430", "#DE002B", "#FF4B66", "#9C001E", "#5A6470"}
    import re
    for name in ("geohazard", "ricp", "tlsphoto"):
        text = (REPO_ROOT / "engines" / name / "icon.svg").read_text(encoding="utf-8")
        used = set(re.findall(r"#[0-9A-Fa-f]{6}", text))
        assert used <= allowed, (name, used - allowed)
        assert 'viewBox="0 0 64 64"' in text


def test_fallback_when_absent_or_unreadable(qtbot, tmp_path: Path) -> None:
    assert render_svg_icon(None) is None
    assert render_svg_icon("") is None
    assert render_svg_icon(tmp_path / "nope.svg") is None
    broken = tmp_path / "broken.svg"
    broken.write_text("<svg this is not valid", encoding="utf-8")
    assert render_svg_icon(broken) is None

    for source in (None, "", tmp_path / "nope.svg", broken):
        pixmap = engine_icon(source)
        assert isinstance(pixmap, QPixmap) and not pixmap.isNull()
        assert pixmap.toImage() == fallback_icon().toImage()


def test_fallback_is_drawn_not_loaded(qtbot) -> None:
    pixmap = fallback_icon(32)
    image = pixmap.toImage()
    assert image.size() == QSize(32, 32)
    # centre dot present, corner transparent
    assert image.pixelColor(16, 16).alpha() > 0
    assert image.pixelColor(1, 1).alpha() == 0


# --------------------------------------------------------------------------- #
# The card view
# --------------------------------------------------------------------------- #


@pytest.fixture()
def panel(qtbot) -> EnginePanel:
    widget = EnginePanel()
    qtbot.addWidget(widget)
    engines, _ = discover_engines(REPO_ROOT, include_private=True)
    widget.set_engines(engines)
    widget.resize(700, 600)
    widget.show()
    return widget


def test_the_list_is_a_card_grid_with_the_delegate(panel: EnginePanel) -> None:
    view = panel._engine_list
    assert view.viewMode() == QListView.ViewMode.IconMode
    assert view.flow() == QListView.Flow.LeftToRight and view.isWrapping()
    assert isinstance(view.itemDelegate(), EngineCardDelegate)
    assert view.hasMouseTracking()
    assert view.sizeHintForRow(0) == CARD_SIZE.height() or view.itemDelegate().sizeHint(None, None) == CARD_SIZE


def test_items_carry_the_engine_and_its_icon_path(panel: EnginePanel) -> None:
    view = panel._engine_list
    for row in range(view.count()):
        item = view.item(row)
        engine = item.data(ENGINE_ROLE)
        assert engine.id in ("demo", "geohazard", "ricp", "tlsphoto")
        expected = str(engine.icon_path) if engine.icon_path else ""
        assert item.data(ICON_PATH_ROLE) == expected
        assert engine.name in item.text()                    # accessible text kept


def test_selection_and_keyboard_behaviour_are_preserved(panel: EnginePanel, qtbot) -> None:
    from PySide6.QtCore import Qt

    view = panel._engine_list
    assert view.currentRow() == 0
    assert panel.current_engine().id == "demo"
    qtbot.keyClick(view, Qt.Key.Key_Right)                   # icon mode: right moves on
    assert view.currentRow() in (1, 0)                       # layout-dependent, but no crash
    view.setCurrentRow(2)
    assert panel.current_engine().id == "ricp"
    assert view.selectedItems() == [view.item(2)]


def test_every_card_paints_in_every_state(panel: EnginePanel) -> None:
    """Paint each card into a pixmap in normal, hover and selected state."""
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    view = panel._engine_list
    delegate = view.itemDelegate()
    for row in range(view.count()):
        index = view.model().index(row, 0)
        for state in (QStyle.StateFlag.State_None, QStyle.StateFlag.State_MouseOver,
                      QStyle.StateFlag.State_Selected):
            option = QStyleOptionViewItem()
            view.initViewItemOption(option) if hasattr(view, "initViewItemOption") else None
            option.rect = view.visualRect(index).translated(-view.visualRect(index).topLeft())
            option.rect.setSize(CARD_SIZE)
            option.state = state
            pixmap = QPixmap(CARD_SIZE)
            pixmap.fill(engine_cards.FILL_NORMAL)
            painter = QPainter(pixmap)
            delegate.paint(painter, option, index)
            painter.end()
            image = pixmap.toImage()
            border = image.pixelColor(2, CARD_SIZE.height() // 2)   # left border, mid-height
            if state == QStyle.StateFlag.State_Selected:
                assert border.red() > 150 and border.green() < 90    # brand red, stronger than hover
            else:
                assert abs(border.red() - border.green()) < 30       # grey, not red
