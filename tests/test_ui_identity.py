"""The LithoCloud identity: version, About dialog, and the settings migration."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

import lithocloud
from lithocloud.ui import settings
from lithocloud.ui.about_dialog import (
    AUTHOR,
    PRODUCT_NAME,
    REPOSITORY,
    TAGLINE,
    AboutDialog,
    diagnostics,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def isolated_settings(monkeypatch, tmp_path: Path):
    """Bind the settings module to throwaway INI files.

    QSettings.setDefaultFormat / setPath are NOT enough: they are global, take
    effect only before the first QSettings is built, and silently fall back to
    the real per-user store (the Windows registry) otherwise. Replacing the two
    store factories is the only way to guarantee a test cannot reach Mohammad's
    real settings.
    """
    new_ini = str(tmp_path / "lithocloud.ini")
    legacy_ini = str(tmp_path / "legacy.ini")
    monkeypatch.setattr(
        settings, "_store", lambda: QSettings(new_ini, QSettings.Format.IniFormat)
    )
    monkeypatch.setattr(
        settings,
        "_legacy_store",
        lambda: QSettings(legacy_ini, QSettings.Format.IniFormat),
    )
    return tmp_path


def _legacy(isolated: Path) -> QSettings:
    return QSettings(str(isolated / "legacy.ini"), QSettings.Format.IniFormat)


def _new(isolated: Path) -> QSettings:
    return QSettings(str(isolated / "lithocloud.ini"), QSettings.Format.IniFormat)


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


def test_the_package_carries_a_version() -> None:
    assert lithocloud.__version__ == "0.1.0"


def test_the_identity_block_is_the_approved_wording() -> None:
    assert PRODUCT_NAME == "LithoCloud"
    assert TAGLINE == "See into the rock — LiDAR, photogrammetry, machine learning"
    assert AUTHOR == "Mohammad Niknezhad · ÉTS Montréal"
    assert REPOSITORY == "https://github.com/MohammadNiknezhad/lithocloud"


def test_ets_is_plain_text_attribution_only() -> None:
    """BRAND.md: ÉTS never appears inside the mark, only as plain text.

    The dialog now carries the LithoCloud lockup, so this checks the artwork
    it references is ours and that nothing recolours it - rather than banning
    images outright, which it did before there was a logo.
    """
    import re

    source = (REPO_ROOT / "app" / "lithocloud" / "ui" / "about_dialog.py").read_text(
        encoding="utf-8"
    )
    assert "ÉTS Montréal" in source            # the attribution line, as text
    assert "setStyleSheet" not in source       # no recolouring of the mark

    images = re.findall(r"[\w.-]+\.(?:png|svg|ico)", source)
    assert images == ["lithocloud-lockup-stacked-1200.png"]
    assert not any("ets" in name.lower() for name in images)


def test_the_about_dialog_shows_the_identity_and_version(qtbot) -> None:
    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    labels = [w.text() for w in dialog.findChildren(type(dialog._copy).__mro__[0])]
    texts = " ".join(
        child.text() for child in dialog.findChildren(object) if hasattr(child, "text")
    )
    # The product name is carried by the lockup artwork, which exposes it as an
    # accessible name; it falls back to a text label if the artwork is missing.
    from PySide6.QtWidgets import QLabel

    identity = texts + " " + " ".join(
        label.accessibleName() for label in dialog.findChildren(QLabel)
    )
    assert PRODUCT_NAME in identity
    assert TAGLINE in texts
    assert AUTHOR in texts
    assert lithocloud.__version__ in texts
    assert "MIT" in texts
    assert REPOSITORY in texts
    assert labels  # the Copy diagnostics button exists


def test_diagnostics_lists_the_versions_worth_quoting() -> None:
    text = diagnostics()
    assert "LithoCloud 0.1.0" in text
    for module in ("Python", "Platform", "PySide6", "numpy", "laspy"):
        assert module in text


def test_copy_diagnostics_puts_them_on_the_clipboard(qtbot) -> None:
    from PySide6.QtGui import QGuiApplication

    dialog = AboutDialog()
    qtbot.addWidget(dialog)
    dialog._copy.click()

    assert "LithoCloud 0.1.0" in QGuiApplication.clipboard().text()
    assert dialog._copy.text() == "Copied"


# --------------------------------------------------------------------------- #
# QSettings migration from the pre-rename store
# --------------------------------------------------------------------------- #


def test_migration_carries_the_old_settings_across(isolated_settings) -> None:
    legacy = _legacy(isolated_settings)
    legacy.setValue(settings._RECENT_KEY, [r"D:\sites\Francon\project.json"])
    legacy.setValue(settings._CLOUDCOMPARE_KEY, r"C:\CC\CloudCompare.exe")
    legacy.setValue("{0}/abc123".format(settings._BROWSE_DIR_KEY), r"D:\raw")
    legacy.sync()

    copied = settings.migrate_legacy_settings()

    assert set(copied) == {
        settings._RECENT_KEY,
        settings._CLOUDCOMPARE_KEY,
        "{0}/abc123".format(settings._BROWSE_DIR_KEY),
    }
    store = _new(isolated_settings)
    assert store.value(settings._RECENT_KEY) == [r"D:\sites\Francon\project.json"]
    assert store.value(settings._CLOUDCOMPARE_KEY) == r"C:\CC\CloudCompare.exe"


def test_migration_never_overwrites_the_new_store(isolated_settings) -> None:
    """Run twice, or after the user has set something: the new store wins."""
    legacy = _legacy(isolated_settings)
    legacy.setValue(settings._RECENT_KEY, ["old"])
    legacy.sync()

    store = _new(isolated_settings)
    store.setValue(settings._RECENT_KEY, ["new"])
    store.sync()

    assert settings.migrate_legacy_settings() == []
    assert _new(isolated_settings).value(settings._RECENT_KEY) == ["new"]


def test_migration_is_a_no_op_without_a_legacy_store(isolated_settings) -> None:
    assert settings.migrate_legacy_settings() == []


def test_migration_ignores_unrelated_legacy_keys(isolated_settings) -> None:
    legacy = _legacy(isolated_settings)
    legacy.setValue(settings._RECENT_KEY, ["keep"])
    legacy.setValue("something/else", "drop")
    legacy.sync()

    copied = settings.migrate_legacy_settings()

    assert copied == [settings._RECENT_KEY]
    assert _new(isolated_settings).value("something/else") is None


# --------------------------------------------------------------------------- #
# The rename left nothing behind
# --------------------------------------------------------------------------- #


def test_no_old_package_name_survives_in_code() -> None:
    """Acceptance: the old package name is gone from all code."""
    needle = "rockslope" + "_studio"
    offenders = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {
            ".py", ".toml", ".bat", ".yaml", ".yml", ".cff"
        }:
            continue
        if any(part in (".git", "__pycache__", "runs") for part in path.parts):
            continue
        if needle in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_the_old_launcher_is_a_shim_to_the_new_one() -> None:
    shim = (REPO_ROOT / "run_studio.bat").read_text(encoding="utf-8")
    assert "lithocloud.bat" in shim
    assert (REPO_ROOT / "lithocloud.bat").is_file()


def test_citation_file_is_valid_and_names_the_author() -> None:
    import yaml

    data = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert data["cff-version"] == "1.2.0"
    assert data["title"] == "LithoCloud"
    assert data["type"] == "software"
    assert data["license"] == "MIT"
    assert data["repository-code"] == REPOSITORY
    author = data["authors"][0]
    assert author["family-names"] == "Niknezhad"
    assert author["given-names"] == "Mohammad"
    assert "École de technologie supérieure" in author["affiliation"]


def test_the_license_names_the_person() -> None:
    assert "Copyright (c) 2026 Mohammad Niknezhad" in (
        REPO_ROOT / "LICENSE"
    ).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Branding resources (wired in 2026-08-27)
# --------------------------------------------------------------------------- #

RESOURCES = REPO_ROOT / "app" / "lithocloud" / "ui" / "resources"


def test_the_resource_files_ship_with_the_package() -> None:
    """Resolved from the module, so they must live beside it - lithocloud.bat
    cds before launching and a cwd-relative path would break."""
    for name in (
        "lithocloud.ico",
        "lithocloud-lockup-stacked-1200.png",
        "lithocloud-lockup-800.png",
    ):
        path = RESOURCES / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_the_copied_artwork_is_byte_identical_to_branding() -> None:
    """Nothing about the artwork is altered - the copies are verbatim."""
    pairs = [
        ("lithocloud.ico", REPO_ROOT / "branding" / "ico" / "lithocloud.ico"),
        (
            "lithocloud-lockup-stacked-1200.png",
            REPO_ROOT / "branding" / "png" / "lithocloud-lockup-stacked-1200.png",
        ),
        (
            "lithocloud-lockup-800.png",
            REPO_ROOT / "branding" / "png" / "lithocloud-lockup-800.png",
        ),
    ]
    for name, source in pairs:
        assert (RESOURCES / name).read_bytes() == source.read_bytes(), name


def test_the_app_icon_loads_with_every_frame(qtbot) -> None:
    from PySide6.QtGui import QIcon

    from lithocloud.ui.app import APP_ICON

    assert APP_ICON.is_file()
    icon = QIcon(str(APP_ICON))
    assert not icon.isNull()

    sizes = {s.width() for s in icon.availableSizes()}
    # BRAND.md: the ico carries both cuts, 16 through 256
    assert {16, 20, 24, 32, 48, 64, 128, 256} <= sizes


def test_the_about_lockup_loads(qtbot) -> None:
    from PySide6.QtGui import QPixmap

    from lithocloud.ui.about_dialog import LOCKUP

    pixmap = QPixmap(str(LOCKUP))
    assert not pixmap.isNull()
    assert pixmap.width() > 0 and pixmap.height() > 0


def test_the_start_dialog_lockup_loads(qtbot) -> None:
    from PySide6.QtGui import QPixmap

    from lithocloud.ui.start_dialog import LOCKUP

    pixmap = QPixmap(str(LOCKUP))
    assert not pixmap.isNull()


def test_displayed_widths_respect_the_brand_minimum() -> None:
    """BRAND.md: a lockup is never shown below 120 px wide on screen."""
    from lithocloud.ui import about_dialog, start_dialog

    assert about_dialog.LOGO_WIDTH >= 120
    assert start_dialog.LOGO_WIDTH >= 120
    assert about_dialog.LOGO_CLEAR_SPACE > 0
    assert start_dialog.LOGO_CLEAR_SPACE > 0


def test_the_about_dialog_shows_the_lockup_instead_of_the_name_label(qtbot) -> None:
    """The lockup already renders the product name, so the big heading is
    omitted - but PRODUCT_NAME itself is untouched."""
    from PySide6.QtWidgets import QLabel

    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    pixmaps = [
        label for label in dialog.findChildren(QLabel) if label.pixmap() is not None
        and not label.pixmap().isNull()
    ]
    assert pixmaps, "the About dialog shows no logo"
    assert pixmaps[0].accessibleName() == PRODUCT_NAME

    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert PRODUCT_NAME not in texts        # not repeated beneath the artwork
    assert TAGLINE in texts                 # tagline and author still shown
    assert AUTHOR in texts
    assert PRODUCT_NAME == "LithoCloud"     # the constant is unchanged


def test_the_start_dialog_shows_the_lockup(qtbot) -> None:
    from PySide6.QtWidgets import QLabel

    from lithocloud.ui.start_dialog import StartDialog

    dialog = StartDialog()
    qtbot.addWidget(dialog)

    pixmaps = [
        label for label in dialog.findChildren(QLabel) if label.pixmap() is not None
        and not label.pixmap().isNull()
    ]
    assert pixmaps, "the start dialog shows no logo"


def test_the_readme_shows_the_lockup() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "branding/png/lithocloud-lockup-800.png" in readme
    assert (REPO_ROOT / "branding" / "png" / "lithocloud-lockup-800.png").is_file()
