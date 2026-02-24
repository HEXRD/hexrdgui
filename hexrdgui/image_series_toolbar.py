from __future__ import annotations

from pathlib import Path
from typing import Any, cast, TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QWidget,
)
from PySide6.QtGui import QFontMetrics, QPixmap
from hexrdgui import resource_loader

if TYPE_CHECKING:
    from hexrdgui.image_tab_widget import ImageTabWidget

import hexrdgui.resources.icons
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils import block_signals


class ImageSeriesInfoToolbar(QWidget):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.layout: QGridLayout | None = None  # type: ignore[assignment]
        self.widget: QWidget | None = None
        self.file_label: QLabel | None = None

        self.create_widget()

        self.setup_connections()

    def setup_connections(self) -> None:
        HexrdConfig().recent_images_changed.connect(self.update_file_tooltip)

    def _parent_widget(self) -> QWidget | None:
        parent = self.parent()
        return cast(QWidget, parent) if parent is not None else None

    def create_widget(self) -> None:
        self.widget = QWidget(self._parent_widget())

        data = resource_loader.load_resource(
            hexrdgui.resources.icons, 'file.svg', binary=True
        )
        assert isinstance(data, bytes)
        pixmap = QPixmap()
        pixmap.loadFromData(data, 'svg')  # type: ignore[call-overload]
        self.file_label = QLabel(self._parent_widget())
        self.file_label.setPixmap(pixmap)
        self.update_file_tooltip()

        self.layout = QGridLayout(self.widget)
        self.layout.addWidget(self.file_label, 0, 0, 1, 1)

        self.widget.setLayout(self.layout)

    def set_visible(self, b: bool = False) -> None:
        assert self.widget is not None
        self.widget.setVisible(b)

    def update_file_tooltip(self) -> None:
        assert self.file_label is not None
        tips = []
        for det, images in HexrdConfig().recent_images.items():
            fnames = [Path(img).name for img in images]
            tips.append(f'{det}: {", ".join(fnames)}')
        self.file_label.setToolTip('\n'.join(tips))


class ImageSeriesToolbar(QWidget):

    def __init__(self, ims: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.ims = ims
        self.slider: QSlider | None = None
        self.frame: QLineEdit | None = None
        self.back_button: QPushButton | None = None
        self.forward_button: QPushButton | None = None
        self.layout: QGridLayout | None = None  # type: ignore[assignment]
        self.widget: QWidget | None = None
        self.omega_label: QLabel | None = None

        self._show = False

        self.create_widget()
        self.set_range()

        self.setup_connections()

    def setup_connections(self) -> None:
        assert self.slider is not None
        assert self.frame is not None
        assert self.back_button is not None
        assert self.forward_button is not None
        self.slider.valueChanged.connect(self.val_changed)
        self.slider.valueChanged.connect(lambda i: self.frame.setText(str(i)))
        self.frame.editingFinished.connect(self.on_frame_edited)
        self.back_button.clicked.connect(lambda: self.shift_frame(-1))
        self.forward_button.clicked.connect(lambda: self.shift_frame(1))

    def text_width(self, text: str) -> int:
        app = QCoreApplication.instance()
        assert app is not None
        metrics = QFontMetrics(app.font())  # type: ignore[attr-defined]
        return metrics.boundingRect(text).width()

    def _parent_widget(self) -> QWidget | None:
        parent = self.parent()
        return cast(QWidget, parent) if parent is not None else None

    def create_widget(self) -> None:
        self.slider = QSlider(Qt.Orientation.Horizontal, self._parent_widget())
        self.frame = QLineEdit(self._parent_widget())
        self.back_button = QPushButton('<<')
        self.back_button.setFixedSize(35, 22)
        self.forward_button = QPushButton('>>')
        self.forward_button.setFixedSize(35, 22)

        self.widget = QWidget(self._parent_widget())
        self.omega_label = QLabel(self._parent_widget())
        self.omega_label.setVisible(False)

        # Compute the text width for the maximum size label we will have
        # with the current font, and set the label width to be fixed at
        # this width. This will prevent the slider from shifting around
        # while we are sliding.
        example_label_text = omega_label_text(359.999, 359.999)
        text_width = self.text_width(example_label_text)
        self.omega_label.setFixedWidth(text_width)
        self.frame.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.layout = QGridLayout(self.widget)
        self.layout.addWidget(self.slider, 0, 0, 1, 7)
        self.layout.addWidget(self.back_button, 0, 7, 1, 1)
        self.layout.addWidget(self.frame, 0, 8, 1, 1)
        self.layout.addWidget(self.forward_button, 0, 9, 1, 1)
        self.layout.addWidget(self.omega_label, 0, 10, 1, 1)

        self.widget.setLayout(self.layout)

        if self.ims and len(self.ims) > 1:
            self._show = True
        self.widget.setVisible(self._show)

    def set_range(self, current_tab: bool = False) -> None:
        assert self.frame is not None
        assert self.widget is not None
        assert self.slider is not None
        assert self.back_button is not None
        if self.ims:
            size = len(self.ims) - 1
            # Compute the text width for the maximum size label based on the
            # maximum number of frames. Multiply by 100 to add a little padding
            frame_text_width = self.text_width(str(size * 100))
            self.frame.setFixedWidth(frame_text_width)
            if (not size or not current_tab) and self._show:
                self._show = False
            elif size and not self._show and current_tab:
                self._show = True
            self.widget.setVisible(self._show)
            if not self.slider.minimumWidth():
                parent = self._parent_widget()
                if parent is not None:
                    self.slider.setMinimumWidth(parent.width() // 2)
            if not size == self.slider.maximum():
                self.slider.setMaximum(size)
                self.frame.setToolTip(f'Max: {size}')
                self.slider.setToolTip(f'Max: {size}')
                self.slider.setValue(0)
                self.frame.setText(str(self.slider.value()))
                self.back_button.setEnabled(False)
        else:
            self._show = False
            self.widget.setVisible(self._show)

        self.update_omega_label_text()

    def update_range(self, current_tab: bool) -> None:
        self.set_range(current_tab)

        assert self.slider is not None
        if self.slider.value() != HexrdConfig().current_imageseries_idx:
            self.val_changed(self.slider.value())

    def update_ims(self, ims: Any) -> None:
        self.ims = ims

    def set_visible(self, b: bool = False) -> None:
        assert self.widget is not None
        self.widget.setVisible(b and len(self.ims) > 1)
        self.update_omega_label_text()

    def setEnabled(self, b: bool) -> None:
        assert self.widget is not None
        self.widget.setEnabled(b)

    def val_changed(self, pos: int) -> None:
        parent = cast('ImageTabWidget', self.parent())
        parent.change_ims_image(pos)
        self.update_back_forward_buttons(pos)
        self.update_omega_label_text()

    def update_omega_label_text(self) -> None:
        assert self.omega_label is not None
        is_aggregated = HexrdConfig().is_aggregated
        ome_range = HexrdConfig().omega_ranges

        enable = not is_aggregated and ome_range is not None
        self.omega_label.setVisible(enable)
        if not enable:
            return

        self.omega_label.setText(omega_label_text(*ome_range))  # type: ignore[misc]

    def update_back_forward_buttons(self, val: int) -> None:
        assert self.back_button is not None
        assert self.forward_button is not None
        assert self.slider is not None
        self.back_button.setEnabled(self.slider.minimum() != val)
        self.forward_button.setEnabled(self.slider.maximum() != val)

    def shift_frame(self, value: int) -> None:
        assert self.frame is not None
        assert self.slider is not None
        with block_signals(self.frame, self.slider):
            new_frame = int(self.frame.text()) + value
            self.frame.setText(str(new_frame))
            self.slider.setSliderPosition(new_frame)
        self.val_changed(new_frame)

    def on_frame_edited(self) -> None:
        assert self.frame is not None
        assert self.slider is not None
        try:
            val = int(self.frame.text())
        except ValueError:
            # Not a valid integer. Restore the previous value.
            val = self.slider.value()

        # Clip the value to the min/max range
        val = max(self.slider.minimum(), val)
        val = min(self.slider.maximum(), val)

        # Set the frame text to the new value
        with block_signals(self.frame, self.slider):
            self.frame.setText(str(val))

        # Set the slider position to the new value
        self.slider.setSliderPosition(val)


def omega_label_text(ome_min: float, ome_max: float) -> str:
    # We will display 6 digits at most, because omegas go up to 360
    # degrees (so up to 3 digits before the decimal place), and we
    # will always show at least 3 digits after the decimal place.
    return f'  Omega range: [{ome_min:.6g}°, {ome_max:.6g}°]'
