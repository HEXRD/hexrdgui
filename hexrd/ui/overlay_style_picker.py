import copy

from PySide2.QtCore import QObject, QSignalBlocker
from PySide2.QtGui import QColor
from PySide2.QtWidgets import QColorDialog

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class OverlayStylePicker(QObject):

    def __init__(self, overlay, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('overlay_style_picker.ui', parent)

        self.overlay = overlay
        self.ui.material_name.setText(overlay['material'])

        self.original_style = copy.deepcopy(self.overlay['style'])

        self.setup_connections()
        self.update_gui_from_config()

    def setup_connections(self):
        self.ui.data_color.pressed.connect(self.pick_color)
        self.ui.range_color.pressed.connect(self.pick_color)
        self.ui.data_linestyle.currentIndexChanged.connect(
            self.update_config_from_gui)
        self.ui.range_linestyle.currentIndexChanged.connect(
            self.update_config_from_gui)
        self.ui.data_linewidth.valueChanged.connect(
            self.update_config_from_gui)
        self.ui.range_linewidth.valueChanged.connect(
            self.update_config_from_gui)

        # Reset the style if the dialog is rejected
        self.ui.rejected.connect(self.reset_style)

    @property
    def style(self):
        return self.overlay['style']

    @property
    def all_widgets(self):
        return [
            self.ui.data_color,
            self.ui.data_linestyle,
            self.ui.data_linewidth,
            self.ui.range_color,
            self.ui.range_linestyle,
            self.ui.range_linewidth
        ]

    def reset_style(self):
        self.overlay['style'] = copy.deepcopy(self.original_style)
        self.update_gui_from_config()
        HexrdConfig().overlay_config_changed.emit()

    def update_gui_from_config(self):
        data = self.style['data']
        ranges = self.style['ranges']

        blockers = [QSignalBlocker(x) for x in self.all_widgets]
        self.ui.data_color.setText(data['c'])
        self.ui.data_linestyle.setCurrentText(data['ls'])
        self.ui.data_linewidth.setValue(data['lw'])
        self.ui.range_color.setText(ranges['c'])
        self.ui.range_linestyle.setCurrentText(ranges['ls'])
        self.ui.range_linewidth.setValue(ranges['lw'])

        # Unblock
        del blockers

        self.update_button_colors()

    def update_config_from_gui(self):
        data = self.style['data']
        ranges = self.style['ranges']

        data['c'] = self.ui.data_color.text()
        data['ls'] = self.ui.data_linestyle.currentText()
        data['lw'] = self.ui.data_linewidth.value()
        ranges['c'] = self.ui.range_color.text()
        ranges['ls'] = self.ui.range_linestyle.currentText()
        ranges['lw'] = self.ui.range_linewidth.value()
        HexrdConfig().overlay_config_changed.emit()

    def pick_color(self):
        # This should only be called by signals/slots
        # It uses the sender() to get the button that called it
        sender = self.sender()
        color = sender.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec_():
            sender.setText(dialog.selectedColor().name())
            self.update_button_colors()
            self.update_config_from_gui()

    def update_button_colors(self):
        buttons = [self.ui.data_color, self.ui.range_color]
        for b in buttons:
            b.setStyleSheet('QPushButton {background-color: %s}' % b.text())
