from pathlib import Path
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QSlider, QSpinBox, QWidget
from PySide6.QtGui import QFontMetrics, QPixmap
from hexrdgui import resource_loader

import hexrdgui.resources.icons
from hexrdgui.hexrd_config import HexrdConfig


class ImageSeriesInfoToolbar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = None
        self.widget = None
        self.file_label = None

        self.create_widget()

        self.setup_connections()

    def setup_connections(self):
        HexrdConfig().recent_images_changed.connect(
            self.update_file_tooltip)

    def create_widget(self):
        self.widget = QWidget(self.parent())

        data = resource_loader.load_resource(hexrdgui.resources.icons,
                                             'file.svg', binary=True)
        pixmap = QPixmap()
        pixmap.loadFromData(data, 'svg')
        self.file_label = QLabel(self.parent())
        self.file_label.setPixmap(pixmap)
        self.update_file_tooltip()

        self.layout = QGridLayout(self.widget)
        self.layout.addWidget(self.file_label, 0, 0, 1, 1)

        self.widget.setLayout(self.layout)

    def set_visible(self, b=False):
        self.widget.setVisible(b)

    def update_file_tooltip(self):
        tips = []
        for det, images in HexrdConfig().recent_images.items():
            fnames = [Path(img).name for img in images]
            tips.append(
                f'{det}: {", ".join(fnames)}'
            )
        self.file_label.setToolTip('\n'.join(tips))


class ImageSeriesToolbar(QWidget):

    def __init__(self, ims, parent=None):
        super().__init__(parent)

        self.ims = ims
        self.slider = None
        self.frame = None
        self.layout = None
        self.widget = None

        self.show = False

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
        self.frame.setKeyboardTracking(False)

        self.widget = QWidget(self.parent())
        self.omega_label = QLabel(self.parent())
        self.omega_label.setVisible(False)

        # Compute the text width for the maximum size label we will have
        # with the current font, and set the label width to be fixed at
        # this width. This will prevent the slider from shifting around
        # while we are sliding.
        metrics = QFontMetrics(QCoreApplication.instance().font())
        example_label_text = omega_label_text(359.999, 359.999)
        text_width = metrics.boundingRect(example_label_text).width()
        self.omega_label.setFixedWidth(text_width)

        self.layout = QGridLayout(self.widget)
        self.layout.addWidget(self.slider, 0, 0, 1, 9)
        self.layout.addWidget(self.frame, 0, 9, 1, 1)
        self.layout.addWidget(self.omega_label, 0, 10, 1, 1)

        self.widget.setLayout(self.layout)

        if self.ims and len(self.ims) > 1:
            self.show = True
        self.widget.setVisible(self.show)

    def set_range(self, current_tab=False):
        if self.ims:
            size = len(self.ims) - 1
            if (not size or not current_tab) and self.show:
                self.show = False
            elif size and not self.show and current_tab:
                self.show = True
            self.widget.setVisible(self.show)
            if not self.slider.minimumWidth():
                self.slider.setMinimumWidth(self.parent().width()//2)
            if not size == self.slider.maximum():
                self.slider.setMaximum(size)
                self.frame.setMaximum(size)
                self.frame.setToolTip(f'Max: {size}')
                self.slider.setToolTip(f'Max: {size}')
                self.slider.setValue(0)
                self.frame.setValue(self.slider.value())
        else:
            self.show = False
            self.widget.setVisible(self.show)

        self.update_omega_label_text()

    def update_range(self, current_tab):
        self.set_range(current_tab)

        if self.slider.value() != HexrdConfig().current_imageseries_idx:
            self.val_changed(self.slider.value())

    def update_ims(self, ims):
        self.ims = ims

    def set_visible(self, b=False):
        self.widget.setVisible(b and len(self.ims)>1)
        self.update_omega_label_text()

    def setEnabled(self, b):
        self.widget.setEnabled(b)

    def val_changed(self, pos):
        self.parent().change_ims_image(pos)
        self.update_omega_label_text()

    def update_omega_label_text(self):
        is_aggregated = HexrdConfig().is_aggregated
        ome_range = HexrdConfig().omega_ranges

        enable = not is_aggregated and ome_range is not None
        self.omega_label.setVisible(enable)
        if not enable:
            return

        self.omega_label.setText(omega_label_text(*ome_range))


def omega_label_text(ome_min, ome_max):
    # We will display 6 digits at most, because omegas go up to 360
    # degrees (so up to 3 digits before the decimal place), and we
    # will always show at least 3 digits after the decimal place.
    return f'  Omega range: [{ome_min:.6g}°, {ome_max:.6g}°]'
