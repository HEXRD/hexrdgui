from PySide2.QtCore import Qt
from PySide2.QtWidgets import QGridLayout, QSlider, QSpinBox, QWidget

from hexrd.ui.hexrd_config import HexrdConfig


class ImageSeriesToolbar(QWidget):

    def __init__(self, name, parent=None):
        super(ImageSeriesToolbar, self).__init__(parent)

        self.ims = HexrdConfig().imageseries(name)
        self.slider = None
        self.frame = None
        self.layout = None
        self.widget = None

        self.show = False
        self.name = name

        self.create_widget()
        self.set_range()

        self.setup_connections()

    def setup_connections(self):
        self.slider.valueChanged.connect(self.val_changed)
        self.slider.valueChanged.connect(self.frame.setValue)
        self.frame.valueChanged.connect(
            self.slider.setSliderPosition)

    def create_widget(self):
        self.slider = QSlider(Qt.Horizontal, self.parent())
        self.frame = QSpinBox(self.parent())

        self.widget = QWidget(self.parent())

        self.layout = QGridLayout(self.widget)
        self.layout.addWidget(self.slider, 0, 0, 1, 9)
        self.layout.addWidget(self.frame, 0, 9, 1, 1)

        self.widget.setLayout(self.layout)

        if self.ims and len(self.ims) > 1:
            self.show = True
        self.widget.setVisible(self.show)

    def set_range(self):
        if self.ims:
            size = len(self.ims) - 1
            if not size and self.show:
                self.show = False
            elif size and not self.show:
                self.show = True
            self.widget.setVisible(self.show)
            self.slider.setMaximum(size)
            self.slider.setMinimumWidth(self.parent().width()/2)
            self.frame.setMaximum(size)
            self.slider.setValue(HexrdConfig().current_imageseries_idx)
        else:
            self.show = False
            self.widget.setVisible(self.show)

    def update_range(self):
        self.ims = HexrdConfig().imageseries(self.name)
        self.set_range()
        HexrdConfig().current_imageseries_idx = 0

    def set_visible(self, b=False):
        if self.show:
            self.widget.setVisible(b)

    def val_changed(self, pos):
        self.parent().change_ims_image(pos)
