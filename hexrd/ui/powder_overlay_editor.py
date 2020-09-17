import numpy as np

from PySide2.QtCore import QSignalBlocker
from PySide2.QtWidgets import QCheckBox, QDoubleSpinBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class PowderOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('powder_overlay_editor.ui', parent)

        self._overlay = None

        self.setup_connections()

    def setup_connections(self):
        for w in self.widgets:
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)

        self.ui.enable_width.toggled.connect(self.update_enable_states)

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        self.update_gui()

    def update_enable_states(self):
        enable_width = self.ui.enable_width.isChecked()
        self.ui.tth_width.setEnabled(enable_width)

    def update_gui(self):
        if self.overlay is None:
            return

        blockers = [QSignalBlocker(w) for w in self.widgets]  # noqa: F841

        self.tth_width_gui = self.tth_width_config
        self.offset_gui = self.offset_config

        self.update_enable_states()

    def update_config(self):
        self.tth_width_config = self.tth_width_gui
        self.offset_config = self.offset_gui

        self.overlay['update_needed'] = True
        HexrdConfig().overlay_config_changed.emit()

    @property
    def tth_width_config(self):
        if self.overlay is None:
            return None

        name = self.overlay['material']
        return HexrdConfig().material(name).planeData.tThWidth

    @tth_width_config.setter
    def tth_width_config(self, v):
        if self.overlay is None:
            return

        name = self.overlay['material']
        HexrdConfig().material(name).planeData.tThWidth = v

    @property
    def tth_width_gui(self):
        if not self.ui.enable_width.isChecked():
            return None
        return np.radians(self.ui.tth_width.value())

    @tth_width_gui.setter
    def tth_width_gui(self, v):
        enable_width = v is not None
        self.ui.enable_width.setChecked(enable_width)
        if enable_width:
            self.ui.tth_width.setValue(np.degrees(v))

    @property
    def offset_config(self):
        if self.overlay is None:
            return

        options = self.overlay.get('options', {})
        if 'tvec' not in options:
            return

        return options['tvec']

    @offset_config.setter
    def offset_config(self, v):
        if self.overlay is None:
            return

        self.overlay['options']['tvec'] = v

    @property
    def offset_gui(self):
        return [w.value() for w in self.offset_widgets]

    @offset_gui.setter
    def offset_gui(self, v):
        if v is None:
            return

        for i, w in enumerate(self.offset_widgets):
            w.setValue(v[i])

    @property
    def offset_widgets(self):
        return [getattr(self.ui, f'offset_{i}') for i in range(3)]

    @property
    def widgets(self):
        return [
            self.ui.enable_width,
            self.ui.tth_width
        ] + self.offset_widgets
