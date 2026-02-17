import copy

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from hexrdgui import enter_key_filter

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class WppfStylePicker(QObject):

    def __init__(
        self,
        amorphous_visible: bool = False,
        tds_visible: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file(
            'wppf_style_picker.ui', parent  # type: ignore[arg-type]
        )
        self.ui.installEventFilter(enter_key_filter)

        self.original_style = copy.deepcopy(self.style_config)

        self.ui.amorphous_group.setVisible(amorphous_visible)
        self.ui.tds_group.setVisible(tds_visible)

        self.setup_combo_boxes()
        self.setup_connections()
        self.update_gui()

    def exec(self) -> int:
        self.ui.adjustSize()
        return self.ui.exec()

    def setup_connections(self) -> None:
        self.ui.marker.currentIndexChanged.connect(self.update_config)
        self.ui.marker_size.editingFinished.connect(self.update_config)
        self.ui.edge_color.pressed.connect(self.pick_color)
        self.ui.face_color.pressed.connect(self.pick_color)

        self.ui.background_color.clicked.connect(self.pick_color)
        self.ui.background_line_style.currentIndexChanged.connect(self.update_config)
        self.ui.background_line_width.valueChanged.connect(self.update_config)

        self.ui.amorphous_color.clicked.connect(self.pick_color)
        self.ui.amorphous_line_style.currentIndexChanged.connect(self.update_config)
        self.ui.amorphous_line_width.valueChanged.connect(self.update_config)

        self.ui.tds_color.clicked.connect(self.pick_color)
        self.ui.tds_line_style.currentIndexChanged.connect(self.update_config)
        self.ui.tds_line_width.valueChanged.connect(self.update_config)

        # Reset the style if the dialog is rejected
        self.ui.rejected.connect(self.reset_style)

    def setup_combo_boxes(self) -> None:
        line_styles = ['solid', 'dotted', 'dashed', 'dashdot']

        marker_styles = ['.', 'o', '^', 's', 'x', 'D']

        w = self.ui.marker
        for s in marker_styles:
            w.addItem(s)

        for s in line_styles:
            self.ui.background_line_style.addItem(s)
            self.ui.amorphous_line_style.addItem(s)
            self.ui.tds_line_style.addItem(s)

    @property
    def all_widgets(self) -> list:
        return [
            self.ui.marker,
            self.ui.marker_size,
            self.ui.face_color,
            self.ui.edge_color,
            self.ui.background_color,
            self.ui.background_line_style,
            self.ui.background_line_width,
            self.ui.amorphous_color,
            self.ui.amorphous_line_style,
            self.ui.amorphous_line_width,
            self.ui.tds_color,
            self.ui.tds_line_style,
            self.ui.tds_line_width,
        ]

    def reset_style(self) -> None:
        if self.style_config == self.original_style:
            # Nothing really to do...
            return

        self.style_config = copy.deepcopy(self.original_style)
        self.update_gui()

    def update_gui(self) -> None:
        with block_signals(*self.all_widgets):
            self.style_gui = self.style_config

        self.update_button_colors()

    def update_config(self) -> None:
        self.style_config = self.style_gui

    @property
    def style_config(self) -> dict:
        return {
            'plot': HexrdConfig().wppf_plot_style,
            'background': HexrdConfig().wppf_background_style,
            'amorphous': HexrdConfig().wppf_amorphous_style,
            'tds': HexrdConfig().wppf_tds_style,
        }

    @style_config.setter
    def style_config(self, v: dict) -> None:
        HexrdConfig().wppf_plot_style = v['plot']
        HexrdConfig().wppf_background_style = v['background']
        HexrdConfig().wppf_amorphous_style = v['amorphous']
        HexrdConfig().wppf_tds_style = v['tds']

    @property
    def style_gui(self) -> dict:
        return {
            'plot': self.plot_style_gui,
            'background': self.background_style_gui,
            'amorphous': self.amorphous_style_gui,
            'tds': self.tds_style_gui,
        }

    @style_gui.setter
    def style_gui(self, v: dict) -> None:
        self.plot_style_gui = v['plot']
        self.background_style_gui = v['background']
        self.amorphous_style_gui = v['amorphous']
        self.tds_style_gui = v['tds']

    @property
    def plot_style_gui(self) -> dict:
        return {
            'marker': self.ui.marker.currentText(),
            's': self.ui.marker_size.value(),
            'facecolors': self.ui.face_color.text(),
            'edgecolors': self.ui.edge_color.text(),
        }

    @plot_style_gui.setter
    def plot_style_gui(self, v: dict) -> None:
        self.ui.marker.setCurrentText(v['marker'])
        self.ui.marker_size.setValue(v['s'])
        self.ui.face_color.setText(v['facecolors'])
        self.ui.edge_color.setText(v['edgecolors'])

    @property
    def background_style_gui(self) -> dict:
        return {
            'c': self.ui.background_color.text(),
            'ls': self.ui.background_line_style.currentText(),
            'lw': self.ui.background_line_width.value(),
        }

    @background_style_gui.setter
    def background_style_gui(self, v: dict) -> None:
        self.ui.background_color.setText(v['c'])
        self.ui.background_line_style.setCurrentText(v['ls'])
        self.ui.background_line_width.setValue(v['lw'])

    @property
    def amorphous_style_gui(self) -> dict:
        return {
            'c': self.ui.amorphous_color.text(),
            'ls': self.ui.amorphous_line_style.currentText(),
            'lw': self.ui.amorphous_line_width.value(),
        }

    @amorphous_style_gui.setter
    def amorphous_style_gui(self, v: dict) -> None:
        self.ui.amorphous_color.setText(v['c'])
        self.ui.amorphous_line_style.setCurrentText(v['ls'])
        self.ui.amorphous_line_width.setValue(v['lw'])

    @property
    def tds_style_gui(self) -> dict:
        return {
            'c': self.ui.tds_color.text(),
            'ls': self.ui.tds_line_style.currentText(),
            'lw': self.ui.tds_line_width.value(),
        }

    @tds_style_gui.setter
    def tds_style_gui(self, v: dict) -> None:
        self.ui.tds_color.setText(v['c'])
        self.ui.tds_line_style.setCurrentText(v['ls'])
        self.ui.tds_line_width.setValue(v['lw'])

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
        buttons = [
            self.ui.face_color,
            self.ui.edge_color,
            self.ui.background_color,
            self.ui.amorphous_color,
            self.ui.tds_color,
        ]
        for b in buttons:
            b.setStyleSheet(f'QPushButton {{background-color: {b.text()}}}')
