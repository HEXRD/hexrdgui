from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class AzimuthalOverlayStylePicker(QObject):

    def __init__(self, overlay: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file(
            'azimuthal_overlay_style_picker.ui',
            parent,  # type: ignore[arg-type]
        )

        self.color = overlay['color']
        self.opacity = overlay['opacity']
        self.overlay = overlay
        self.ui.material_name.setText(overlay['material'])

        self.setup_connections()
        self.update_gui()

    def exec(self) -> int:
        self.ui.adjustSize()
        return self.ui.exec()

    def setup_connections(self) -> None:
        self.ui.color.pressed.connect(self.pick_color)
        self.ui.opacity.valueChanged.connect(self.update_config)

    @property
    def all_widgets(self) -> list:
        return [
            self.ui.color,
            self.ui.opacity,
        ]

    def reset_style(self) -> None:
        any_changes = (
            self.color != self.overlay['color']
            or self.opacity != self.overlay['opacity']
        )
        if not any_changes:
            # Nothing really to do...
            return

        self.color = self.overlay['color']
        self.opacity = self.overlay['opacity']
        self.update_gui()
        HexrdConfig().azimuthal_options_modified.emit()

    def update_gui(self) -> None:
        with block_signals(*self.all_widgets):
            self.ui.color.setText(self.overlay['color'])
            self.ui.opacity.setValue(self.overlay['opacity'])

        self.update_button_colors()

    def update_config(self) -> None:
        self.overlay['color'] = self.ui.color.text()
        self.overlay['opacity'] = self.ui.opacity.value()

        HexrdConfig().azimuthal_options_modified.emit()

    def pick_color(self) -> None:
        # This should only be called by signals/slots
        # It uses the sender() to get the button that called it
        sender = self.sender()
        color = sender.text()  # type: ignore[attr-defined]

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec():
            sender.setText(dialog.selectedColor().name())  # type: ignore[attr-defined]
            self.update_button_colors()
            self.update_config()

    def update_button_colors(self) -> None:
        self.ui.color.setStyleSheet(
            'QPushButton {background-color: %s}' % self.ui.color.text()
        )
