from importlib.metadata import version
import sys

from PySide6.QtCore import Qt, QObject, QSize
from PySide6.QtSvg import QSvgWidget
from PySide6.QtWidgets import QTreeWidgetItem, QLabel
from PySide6.QtGui import QPixmap

import hexrd

from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.resource_loader import load_resource

LOGO_HEIGHT = 80


class AboutDialog(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = UiLoader().load_file('about_dialog.ui', parent)

        self._populate_hexrd_logo()
        self._populate_logos()
        self._populate_versions()

    def _populate_hexrd_logo(self):
        data = load_resource(hexrd.ui.resources.icons,
                             'hexrd.ico', binary=True)
        pixmap = QPixmap()
        pixmap.loadFromData(data, 'ico')
        self.ui.image.setPixmap(pixmap)

    def _calculate_size(self, size):
        ratio = size.height()/size.width()

        return QSize(LOGO_HEIGHT/ratio, LOGO_HEIGHT)

    def _populate_logos(self):
        data = load_resource(hexrd.ui.resources.icons, 'llnl_logo.svg',
                             binary=True)

        self.ui.logos_horizontal_layout.addStretch()
        llnl = QSvgWidget()
        llnl.renderer().setAspectRatioMode(Qt.KeepAspectRatio)
        llnl.load(data)
        llnl.setFixedSize(self._calculate_size(llnl.sizeHint()))
        self.ui.logos_horizontal_layout.addWidget(llnl, stretch=1)
        self.ui.logos_horizontal_layout.addStretch()

        data = load_resource(hexrd.ui.resources.icons,
                             'kitware_logo.svg',  binary=True)

        kitware = QSvgWidget()
        kitware.renderer().setAspectRatioMode(Qt.KeepAspectRatio)
        kitware.load(data)
        kitware.setFixedSize(self._calculate_size(kitware.sizeHint()))
        self.ui.logos_horizontal_layout.addWidget(kitware, stretch=1)
        self.ui.logos_horizontal_layout.addStretch()

        data = load_resource(hexrd.ui.resources.icons,
                             'afrl_logo.png',  binary=True)

        pixmap = QPixmap()
        pixmap.loadFromData(data, 'png')
        afrl = QLabel()
        pixmap = pixmap.scaled(self._calculate_size(pixmap.size()))
        afrl.setPixmap(pixmap)
        afrl.setFixedSize(self._calculate_size(pixmap.size()))

        self.ui.logos_horizontal_layout.addWidget(afrl, stretch=1)
        self.ui.logos_horizontal_layout.addStretch()

    def _populate_versions(self):
        tree = self.ui.information

        packages = [
            "HEXRDGUI",
            "HEXRD",
            "NumPy",
            "SciPy",
            "PySide6"
        ]

        for package in packages:
            item = QTreeWidgetItem(tree)
            item.setText(0, package)
            item.setText(1, version(package.lower()))

        python = QTreeWidgetItem(tree)
        python.setText(0, "Python")
        python.setText(1, sys.version)
