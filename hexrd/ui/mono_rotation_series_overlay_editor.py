import copy
import numpy as np

from hexrd.ui.calibration_crystal_editor import CalibrationCrystalEditor
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ranges_table_editor import RangesTableEditor
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class MonoRotationSeriesOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('mono_rotation_series_overlay_editor.ui',
                                   parent)

        self._overlay = None

        self.eta_ranges_editor = RangesTableEditor(parent=self.ui)
        self.eta_ranges_editor.set_title('η ranges')
        self.ui.eta_ranges_layout.addWidget(self.eta_ranges_editor.ui)

        self.omega_ranges_editor = RangesTableEditor(parent=self.ui)
        self.omega_ranges_editor.set_title('ω ranges')
        self.ui.omega_ranges_layout.addWidget(self.omega_ranges_editor.ui)

        self.crystal_editor = CalibrationCrystalEditor(parent=self.ui)
        self.ui.crystal_editor_layout.addWidget(self.crystal_editor.ui)

        self.setup_connections()

    def setup_connections(self):
        self.eta_ranges_editor.data_modified.connect(self.update_config)
        self.omega_ranges_editor.data_modified.connect(self.update_config)
        self.ui.aggregation.currentIndexChanged.connect(self.update_config)
        self.crystal_editor.params_modified.connect(self.update_config)

        for w in self.omega_period_widgets:
            w.valueChanged.connect(self.update_config)

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

        with block_signals(*self.widgets):
            options = self.overlay.get('options', {})
            if 'crystal_params' in options:
                self.crystal_params = options['crystal_params']
            if 'ome_period' in options:
                self.omega_period = options['ome_period']
            if 'aggregation_mode' in options:
                self.ui.aggregation.setCurrentText(options['aggregation_mode'])
            if 'eta_ranges' in options:
                self.eta_ranges = options['eta_ranges']
            if 'ome_ranges' in options:
                self.ome_ranges = options['ome_ranges']

    def update_config(self):
        if self.overlay is None:
            return

        options = self.overlay.setdefault('options', {})
        options['crystal_params'] = self.crystal_params
        options['ome_period'] = self.omega_period
        options['aggregation_mode'] = self.ui.aggregation.currentText()
        options['eta_ranges'] = self.eta_ranges
        options['ome_ranges'] = self.ome_ranges

        self.overlay['update_needed'] = True
        HexrdConfig().overlay_config_changed.emit()

    @property
    def crystal_params(self):
        return copy.deepcopy(self.crystal_editor.params)

    @crystal_params.setter
    def crystal_params(self, v):
        self.crystal_editor.params = v

    @property
    def eta_ranges(self):
        return self.eta_ranges_editor.data

    @eta_ranges.setter
    def eta_ranges(self, v):
        self.eta_ranges_editor.data = v

    @property
    def ome_ranges(self):
        return self.omega_ranges_editor.data

    @ome_ranges.setter
    def ome_ranges(self, v):
        self.omega_ranges_editor.data = v

    @property
    def omega_period_widgets(self):
        return [getattr(self.ui, f'omega_period_{i}') for i in range(2)]

    @property
    def omega_period(self):
        return [np.radians(w.value()) for w in self.omega_period_widgets]

    @omega_period.setter
    def omega_period(self, v):
        for val, w in zip(v, self.omega_period_widgets):
            w.setValue(np.degrees(val))

    @property
    def widgets(self):
        return [
            self.ui.aggregation
        ] + self.omega_period_widgets
