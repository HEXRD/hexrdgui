from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlay_style_picker import OverlayStylePicker
from hexrdgui.overlays.diffraction_angle_overlay import DiffractionAngleOverlay


class DiffractionAngleContourDialog(QDialog):
    def __init__(
        self,
        overlay: DiffractionAngleOverlay,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.overlay = overlay
        self.original_style = copy.deepcopy(overlay.style)
        self.setWindowTitle('Diffraction Angle Contour')

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.tth_start = self._create_spin_box(overlay.tth_start)
        self.tth_max = self._create_spin_box(overlay.tth_max)
        self.tth_step = self._create_spin_box(overlay.tth_step, minimum=0.001)
        form.addRow('Starting 2θ:', self.tth_start)
        form.addRow('Maximum 2θ:', self.tth_max)
        form.addRow('2θ Step:', self.tth_step)

        self.edit_line_properties = QPushButton('Edit Line Properties…')
        self.edit_line_properties.clicked.connect(self.show_style_picker)
        layout.addWidget(self.edit_line_properties)

        buttons = (
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box = QDialogButtonBox(buttons)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.tth_start.valueChanged.connect(self.update_accept_enabled)
        self.tth_max.valueChanged.connect(self.update_accept_enabled)
        self.rejected.connect(self.restore_style)
        self.update_accept_enabled()

    @staticmethod
    def _create_spin_box(value: float, minimum: float = 0.0) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setDecimals(3)
        widget.setRange(minimum, 180.0)
        widget.setValue(value)
        widget.setSuffix('°')
        widget.setKeyboardTracking(False)
        return widget

    def update_accept_enabled(self) -> None:
        button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        button.setEnabled(self.tth_start.value() <= self.tth_max.value())

    def show_style_picker(self) -> None:
        OverlayStylePicker(self.overlay, self, include_ranges=False).exec()

    def restore_style(self) -> None:
        if self.overlay.style != self.original_style:
            self.overlay.style = copy.deepcopy(self.original_style)
            HexrdConfig().overlay_config_changed.emit()

    def apply(self) -> None:
        self.overlay.tth_start = self.tth_start.value()
        self.overlay.tth_max = self.tth_max.value()
        self.overlay.tth_step = self.tth_step.value()
        self.overlay.update_needed = True
