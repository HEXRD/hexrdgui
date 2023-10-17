import copy

from matplotlib.markers import MarkerStyle

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class BeamMarkerStyleEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('beam_marker_style_editor.ui', parent)

        self.setup_combo_boxes()
        self.setup_connections()
        self.update_gui()

    def show(self):
        self.update_gui()
        self.ui.show()

    def setup_connections(self):
        self.ui.color.pressed.connect(self.pick_color)
        self.ui.marker.currentIndexChanged.connect(self.update_config)
        self.ui.markersize.valueChanged.connect(self.update_config)
        HexrdConfig().beam_marker_modified.connect(self.update_gui)

    def setup_combo_boxes(self):
        self.ui.marker.clear()
        self.ui.marker.addItems(self.marker_options)

    @property
    def marker_options(self):
        options = list(MarkerStyle.markers)

        # Blacklist these
        blacklist = [
            'None',
            ' ',
            '',
        ]
        options = [x for x in options if x not in blacklist]

        # Only keep strings
        return [x for x in options if isinstance(x, str)]

    @property
    def all_widgets(self):
        return [
            self.ui.color,
            self.ui.marker,
            self.ui.markersize,
        ]

    def update_gui(self):
        style = HexrdConfig().beam_marker_style
        with block_signals(*self.all_widgets):
            self.ui.color.setText(style['color'])
            self.ui.marker.setCurrentText(style['marker'])
            self.ui.markersize.setValue(style['markersize'])

        self.update_button_colors()

    def update_config(self):
        style = copy.deepcopy(HexrdConfig().beam_marker_style)

        style['color'] = self.ui.color.text()
        style['marker'] = self.ui.marker.currentText()
        style['markersize'] = self.ui.markersize.value()

        HexrdConfig().beam_marker_style = style

    def pick_color(self):
        w = self.ui.color
        color = w.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec():
            w.setText(dialog.selectedColor().name())
            self.update_button_colors()
            self.update_config()

    def update_button_colors(self):
        b = self.ui.color
        style = f'QPushButton {{background-color: {b.text()}}}'
        self.ui.color.setStyleSheet(style)
