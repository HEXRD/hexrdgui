from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class AzimuthalOverlayStylePicker(QObject):

    def __init__(self, overlay, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('azimuthal_overlay_style_picker.ui', parent)

        self.color = overlay['color']
        self.opacity = overlay['opacity']
        self.overlay = overlay
        self.ui.material_name.setText(overlay['material'])

        self.setup_connections()
        self.update_gui()

    def exec(self):
        self.ui.adjustSize()
        return self.ui.exec()

    def setup_connections(self):
        self.ui.color.pressed.connect(self.pick_color)
        self.ui.opacity.valueChanged.connect(self.update_config)

    @property
    def all_widgets(self):
        return [
            self.ui.color,
            self.ui.opacity,
        ]

    def reset_style(self):
        any_changes = (
            self.color != self.overlay['color'] or
            self.opacity != self.overlay['opacity']
        )
        if not any_changes:
            # Nothing really to do...
            return

        self.color = self.overlay['color']
        self.opacity = self.overlay['opacity']
        self.update_gui()
        HexrdConfig().azimuthal_plot_modified.emit()

    def update_gui(self):
        with block_signals(*self.all_widgets):
            self.ui.color.setText(self.overlay['color'])
            self.ui.opacity.setValue(self.overlay['opacity'])

        self.update_button_colors()

    def update_config(self):
        self.overlay['color'] = self.ui.color.text()
        self.overlay['opacity'] = self.ui.opacity.value()

        HexrdConfig().azimuthal_plot_modified.emit()

    def pick_color(self):
        # This should only be called by signals/slots
        # It uses the sender() to get the button that called it
        sender = self.sender()
        color = sender.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec():
            sender.setText(dialog.selectedColor().name())
            self.update_button_colors()
            self.update_config()

    def update_button_colors(self):
        self.ui.color.setStyleSheet(
            'QPushButton {background-color: %s}' % self.ui.color.text())
