from PySide2.QtCore import Qt, Signal
from PySide2.QtWidgets import (
    QGridLayout, QPushButton, QSlider, QSpinBox, QWidget
)

from hexrd.ui.hexrd_config import HexrdConfig


class ImageSeriesToolbar(QWidget):

    def __init__(self, name, tabbed, parent=None):
        super(ImageSeriesToolbar, self).__init__(parent)

        self.tabbed = tabbed
        self.ims = HexrdConfig().ims_image(name)
        self.slider = None
        self.frame = None
        self.done = None

        self.h1_layout = None
        self.h2_layout = None
        self.layout = None

        self.widget = None

        self.create_widget()
        self.set_range()
        self.set_visible()

        self.name = name

        self.setup_connections()

    def setup_connections(self):
        self.slider.valueChanged.connect(self.val_changed)
        self.slider.valueChanged.connect(self.frame.setValue)
        self.frame.valueChanged.connect(
            self.slider.setSliderPosition)
        self.done.clicked.connect(self.restore_view)
        self.close_editor.connect(self.parent().close_editor)

    def create_widget(self):
        self.slider = QSlider(Qt.Horizontal, self.parent())
        self.frame = QSpinBox(self.parent())
        self.done = QPushButton('Done', self.parent())

        self.widget = QWidget(self.parent())

        self.layout = QGridLayout(self.widget)
        self.layout.addWidget(self.slider, 0, 0, 1, 9)
        self.layout.addWidget(self.frame, 0, 9, 1, 1)
        self.layout.addWidget(self.done, 1, 8, 1, 1)

        self.widget.setLayout(self.layout)

    def set_range(self):
        self.slider.setMaximum(len(self.ims)-1)
        self.slider.setMinimumWidth(self.parent().width()/2)

        self.frame.setMaximum(len(self.ims)-1)

    def update_range(self):
        self.ims = HexrdConfig().ims_image(self.name)
        self.set_range()

    def set_visible(self, b=False):
        self.widget.setVisible(b)

    def val_changed(self, pos):
        self.parent().change_ims_image(pos, self.name)
