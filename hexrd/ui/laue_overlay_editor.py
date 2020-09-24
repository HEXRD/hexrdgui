import copy
import numpy as np

from PySide2.QtCore import QSignalBlocker
from PySide2.QtWidgets import QCheckBox, QDoubleSpinBox

from hexrd.ui.calibration_crystal_editor import CalibrationCrystalEditor
from hexrd.ui.constants import (
    DEFAULT_CRYSTAL_PARAMS, DEFAULT_CRYSTAL_REFINEMENTS
)
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class LaueOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('laue_overlay_editor.ui', parent)

        self._overlay = None

        self.crystal_editor = CalibrationCrystalEditor(parent=self.ui)
        self.ui.crystal_editor_layout.addWidget(self.crystal_editor.ui)

        self.setup_connections()

    def setup_connections(self):
        for w in self.widgets:
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)

        self.ui.enable_widths.toggled.connect(self.update_enable_states)
        self.crystal_editor.params_modified.connect(self.update_config)
        self.crystal_editor.refinements_modified.connect(
            self.update_refinements)

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        self.update_gui()

    def update_gui(self):
        if self.overlay is None:
            return

        blockers = [QSignalBlocker(w) for w in self.widgets]  # noqa: F841

        options = self.overlay.get('options', {})
        if 'min_energy' in options:
            self.ui.min_energy.setValue(options['min_energy'])
        if 'max_energy' in options:
            self.ui.max_energy.setValue(options['max_energy'])
        if 'crystal_params' in options:
            self.crystal_params = options['crystal_params']
        else:
            self.crystal_params = DEFAULT_CRYSTAL_PARAMS.copy()
        if 'refinements' in self.overlay:
            self.refinements = self.overlay['refinements']
        else:
            self.refinements = copy.deepcopy(DEFAULT_CRYSTAL_REFINEMENTS)

        if options.get('tth_width') is not None:
            self.ui.tth_width.setValue(np.degrees(options['tth_width']))
        if options.get('eta_width') is not None:
            self.ui.eta_width.setValue(np.degrees(options['eta_width']))

        widths = ['tth_width', 'eta_width']
        enable_widths = all(options.get(x) is not None for x in widths)
        self.ui.enable_widths.setChecked(enable_widths)

        self.update_enable_states()

    def update_enable_states(self):
        enable_widths = self.enable_widths
        names = [
            'tth_width_label',
            'tth_width',
            'eta_width_label',
            'eta_width'
        ]
        for name in names:
            getattr(self.ui, name).setEnabled(enable_widths)

    @property
    def crystal_params(self):
        return copy.deepcopy(self.crystal_editor.params)

    @crystal_params.setter
    def crystal_params(self, v):
        self.crystal_editor.params = v

    @property
    def refinements(self):
        return copy.deepcopy(self.crystal_editor.refinements)

    @refinements.setter
    def refinements(self, v):
        self.crystal_editor.refinements = v

    def update_config(self):
        options = self.overlay.setdefault('options', {})
        options['min_energy'] = self.ui.min_energy.value()
        options['max_energy'] = self.ui.max_energy.value()
        options['crystal_params'] = self.crystal_params
        options['tth_width'] = self.tth_width
        options['eta_width'] = self.eta_width

        self.update_refinements()

        self.overlay['update_needed'] = True
        HexrdConfig().overlay_config_changed.emit()

    def update_refinements(self):
        self.overlay['refinements'] = self.refinements

    @property
    def enable_widths(self):
        return self.ui.enable_widths.isChecked()

    @property
    def tth_width(self):
        if not self.enable_widths:
            return None

        return np.radians(self.ui.tth_width.value())

    @property
    def eta_width(self):
        if not self.enable_widths:
            return None

        return np.radians(self.ui.eta_width.value())

    @property
    def widgets(self):
        return [
            self.ui.min_energy,
            self.ui.max_energy,
            self.ui.enable_widths,
            self.ui.tth_width,
            self.ui.eta_width
        ]
