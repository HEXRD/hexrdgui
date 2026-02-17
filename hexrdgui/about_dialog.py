from importlib.metadata import version
import sys

from PySide6.QtCore import Qt, QObject, QSize
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QTreeWidgetItem, QLabel
from PySide6.QtGui import QPixmap

import hexrdgui

from hexrdgui.ui_loader import UiLoader
from hexrdgui.resource_loader import load_resource

LOGO_HEIGHT = 80


class AboutDialog(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ui = UiLoader().load_file(
            'about_dialog.ui', parent  # type: ignore[arg-type]
        )

        self._populate_hexrd_logo()
        self._populate_logos()
        self._populate_versions()

    def _populate_hexrd_logo(self) -> None:
        data = load_resource(hexrdgui.resources.icons, 'hexrd.ico', binary=True)
        assert isinstance(data, bytes)
        pixmap = QPixmap()
        pixmap.loadFromData(data, b'ico')
        self.ui.image.setPixmap(pixmap)

    def _calculate_size(self, size: QSize) -> QSize:
        ratio = size.height() / size.width()

        return QSize(int(LOGO_HEIGHT / ratio), LOGO_HEIGHT)

    def _populate_logos(self) -> None:
        data = load_resource(hexrdgui.resources.icons, 'llnl_logo.svg', binary=True)

        self.ui.logos_horizontal_layout.addStretch()
        llnl = QSvgWidget()
        llnl.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        llnl.load(data)
        llnl.setFixedSize(self._calculate_size(llnl.sizeHint()))
        self.ui.logos_horizontal_layout.addWidget(llnl, stretch=1)
        self.ui.logos_horizontal_layout.addStretch()

        data = load_resource(hexrdgui.resources.icons, 'kitware_logo.svg', binary=True)

        kitware = QSvgWidget()
        kitware.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        kitware.load(data)
        kitware.setFixedSize(self._calculate_size(kitware.sizeHint()))
        self.ui.logos_horizontal_layout.addWidget(kitware, stretch=1)
        self.ui.logos_horizontal_layout.addStretch()

        data = load_resource(hexrdgui.resources.icons, 'afrl_logo.png', binary=True)
        assert isinstance(data, bytes)

        pixmap = QPixmap()
        pixmap.loadFromData(data, b'png')
        afrl = QLabel()
        pixmap = pixmap.scaled(self._calculate_size(pixmap.size()))
        afrl.setPixmap(pixmap)
        afrl.setFixedSize(self._calculate_size(pixmap.size()))

        self.ui.logos_horizontal_layout.addWidget(afrl, stretch=1)
        self.ui.logos_horizontal_layout.addStretch()

    def _populate_versions(self) -> None:
        tree = self.ui.information

        packages = [
            "HEXRDGUI",
            "HEXRD",
            "NumPy",
            "SciPy",
            "PySide6",
        ]

        for package in packages:
            item = QTreeWidgetItem(tree)
            item.setText(0, package)
            item.setText(1, version(package.lower()))

        python = QTreeWidgetItem(tree)
        python.setText(0, "Python")
        python.setText(1, sys.version)
