"""Help > About LithoCloud.

Identity block, version, license and repository, plus a "Copy diagnostics"
button that puts the environment versions on the clipboard - the first thing
worth having when something breaks on another machine.

Plain Qt, no images: the logo is a later task and drops into ``_identity()``
without touching anything else.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lithocloud import __version__

RESOURCES = Path(__file__).parent / "resources"
LOCKUP = RESOURCES / "lithocloud-lockup-stacked-1200.png"

#: Displayed width of the lockup. BRAND.md: never below 120 px on screen.
LOGO_WIDTH = 200
#: BRAND.md clear space: at least ~28% of the mark's height, nothing inside it.
LOGO_CLEAR_SPACE = 24

PRODUCT_NAME = "LithoCloud"
TAGLINE = "See into the rock — LiDAR, photogrammetry, machine learning"
AUTHOR = "Mohammad Niknezhad · ÉTS Montréal"
REPOSITORY = "https://github.com/MohammadNiknezhad/lithocloud"
LICENSE_NAME = "MIT"


def diagnostics() -> str:
    """Versions worth quoting in a bug report."""
    lines = [
        "{0} {1}".format(PRODUCT_NAME, __version__),
        "Python {0}".format(sys.version.split()[0]),
        "Platform {0}".format(platform.platform()),
    ]
    for module in ("PySide6", "numpy", "laspy", "scipy", "pandas"):
        try:
            imported = __import__(module)
            version = getattr(imported, "__version__", "(no __version__)")
        except ImportError:
            version = "not installed"
        lines.append("{0} {1}".format(module, version))
    return "\n".join(lines)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About {0}".format(PRODUCT_NAME))

        layout = QVBoxLayout(self)
        for widget in self._identity():
            layout.addWidget(widget)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        details = QLabel(
            "Version {0}\n{1} License\n{2}".format(__version__, LICENSE_NAME, REPOSITORY),
            self,
        )
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        details.setOpenExternalLinks(True)
        layout.addWidget(details)

        self._copy = QPushButton("Copy diagnostics", self)
        self._copy.setToolTip(
            "Copy the Python, Qt and library versions to the clipboard, ready "
            "to paste into a bug report."
        )
        self._copy.clicked.connect(self._copy_diagnostics)
        layout.addWidget(self._copy)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _identity(self) -> list[QWidget]:
        """The lockup above the identity lines.

        The lockup already renders the product name, so the big name label is
        omitted when it loads - the PRODUCT_NAME text itself is unchanged, and
        the label returns if the artwork is ever missing.
        """
        widgets: list[QWidget] = []
        logo = self._logo()
        if logo is not None:
            widgets.append(logo)
        else:
            name = QLabel(PRODUCT_NAME, self)
            font = name.font()
            font.setPointSize(font.pointSize() + 6)
            font.setBold(True)
            name.setFont(font)
            widgets.append(name)

        tagline = QLabel(TAGLINE, self)
        tagline.setWordWrap(True)

        author = QLabel(AUTHOR, self)
        author.setWordWrap(True)
        return widgets + [tagline, author]

    def _logo(self) -> QLabel | None:
        """The stacked lockup, or None when the artwork is unavailable."""
        pixmap = QPixmap(str(LOCKUP))
        if pixmap.isNull():
            return None

        # Scale in device pixels and tag the ratio, so the mark stays crisp on
        # a HiDPI display instead of being upscaled from 200 logical pixels.
        ratio = self.devicePixelRatioF()
        scaled = pixmap.scaledToWidth(
            round(LOGO_WIDTH * ratio), Qt.TransformationMode.SmoothTransformation
        )
        scaled.setDevicePixelRatio(ratio)

        label = QLabel(self)
        label.setPixmap(scaled)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        label.setContentsMargins(0, 0, 0, LOGO_CLEAR_SPACE)
        label.setAccessibleName(PRODUCT_NAME)
        return label

    def _copy_diagnostics(self) -> None:
        QGuiApplication.clipboard().setText(diagnostics())
        self._copy.setText("Copied")
