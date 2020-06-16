import copy

from PySide2.QtCore import QObject, QSignalBlocker
from PySide2.QtGui import QColor
from PySide2.QtWidgets import QColorDialog

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class OverlayStylePicker(QObject):

    def __init__(self, material_name, parent=None):
        super(OverlayStylePicker, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('overlay_style_picker.ui', parent)

        self.material_name = material_name
        self.ui.material_name.setText(material_name)

        self.original_styles = copy.deepcopy(self.styles)

        self.setup_connections()
        self.update_gui_from_config()

    def setup_connections(self):
        self.ui.ring_color.pressed.connect(self.pick_color)
        self.ui.range_color.pressed.connect(self.pick_color)
        self.ui.ring_linestyle.currentIndexChanged.connect(
            self.update_config_from_gui)
        self.ui.range_linestyle.currentIndexChanged.connect(
            self.update_config_from_gui)
        self.ui.ring_linewidth.valueChanged.connect(
            self.update_config_from_gui)
        self.ui.range_linewidth.valueChanged.connect(
            self.update_config_from_gui)

        # Reset the style if the dialog is rejected
        self.ui.rejected.connect(self.reset_style)

    @property
    def styles(self):
        return HexrdConfig().overlay_styles[self.material_name]

    @property
    def all_widgets(self):
        return [
            self.ui.ring_color,
            self.ui.ring_linestyle,
            self.ui.ring_linewidth,
            self.ui.range_color,
            self.ui.range_linestyle,
            self.ui.range_linewidth
        ]

    def reset_style(self):
        styles = HexrdConfig().overlay_styles
        styles[self.material_name] = copy.deepcopy(self.original_styles)
        self.update_gui_from_config()
        HexrdConfig().ring_config_changed.emit()

    def update_gui_from_config(self):
        rings = self.styles['powder']['rings']
        rbnds = self.styles['powder']['rbnds']

        blocker_list = [QSignalBlocker(x) for x in self.all_widgets]
        self.ui.ring_color.setText(rings['c'])
        self.ui.ring_linestyle.setCurrentText(rings['ls'])
        self.ui.ring_linewidth.setValue(rings['lw'])
        self.ui.range_color.setText(rbnds['c'])
        self.ui.range_linestyle.setCurrentText(rbnds['ls'])
        self.ui.range_linewidth.setValue(rbnds['lw'])

        # Unblock
        del blocker_list

        self.update_button_colors()

    def update_config_from_gui(self):
        rings = self.styles['powder']['rings']
        rbnds = self.styles['powder']['rbnds']

        rings['c'] = self.ui.ring_color.text()
        rings['ls'] = self.ui.ring_linestyle.currentText()
        rings['lw'] = self.ui.ring_linewidth.value()
        rbnds['c'] = self.ui.range_color.text()
        rbnds['ls'] = self.ui.range_linestyle.currentText()
        rbnds['lw'] = self.ui.range_linewidth.value()
        HexrdConfig().ring_config_changed.emit()

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
        buttons = [self.ui.ring_color, self.ui.range_color]
        for b in buttons:
            b.setStyleSheet('QPushButton {background-color: %s}' % b.text())
