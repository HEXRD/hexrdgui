import copy

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from hexrd.ui import enter_key_filter

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class WppfStylePicker(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('wppf_style_picker.ui', parent)
        self.ui.installEventFilter(enter_key_filter)

        self.style = copy.deepcopy(HexrdConfig().wppf_plot_style)
        self.original_style = copy.deepcopy(self.style)

        self.setup_combo_boxes()
        self.setup_connections()
        self.update_gui()

    def setup_connections(self):
        self.ui.marker.currentIndexChanged.connect(self.update_config)
        self.ui.marker_size.editingFinished.connect(self.update_config)
        self.ui.edge_color.pressed.connect(self.pick_color)
        self.ui.face_color.pressed.connect(self.pick_color)

        # Reset the style if the dialog is rejected
        self.ui.rejected.connect(self.reset_style)

    def setup_combo_boxes(self):
        marker_styles = [
            '.',
            'o',
            '^',
            's',
            'x',
            'D'
        ]

        w = self.ui.marker
        for s in marker_styles:
            w.addItem(s)

    @property
    def all_widgets(self):
        return [
            self.ui.marker,
            self.ui.marker_size,
            self.ui.face_color,
            self.ui.edge_color,
        ]

    def reset_style(self):
        if self.style == self.original_style:
            # Nothing really to do...
            return

        self.style = copy.deepcopy(self.original_style)
        HexrdConfig().wppf_plot_style = copy.deepcopy(self.style)
        self.update_gui()

    def update_gui(self):
        style = self.style
        with block_signals(*self.all_widgets):
            self.ui.marker.setCurrentText(style['marker'])
            self.ui.marker_size.setValue(style['s'])
            self.ui.face_color.setText(style['facecolors'])
            self.ui.edge_color.setText(style['edgecolors'])

        self.update_button_colors()

    def update_config(self):
        style = self.style
        style['marker'] = self.ui.marker.currentText()
        style['s'] = self.ui.marker_size.value()
        style['facecolors'] = self.ui.face_color.text()
        style['edgecolors'] = self.ui.edge_color.text()
        HexrdConfig().wppf_plot_style = copy.deepcopy(style)

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
        buttons = [self.ui.face_color, self.ui.edge_color]
        for b in buttons:
            b.setStyleSheet(f'QPushButton {{background-color: {b.text()}}}')
