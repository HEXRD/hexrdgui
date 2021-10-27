import copy

import numpy as np

from PySide2.QtWidgets import QCheckBox, QDoubleSpinBox

from hexrd.ui.calibration_crystal_editor import CalibrationCrystalEditor
from hexrd.ui.constants import (
    DEFAULT_CRYSTAL_PARAMS, DEFAULT_CRYSTAL_REFINEMENTS
)
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.ranges_table_editor import RangesTableEditor
from hexrd.ui.reflections_table import ReflectionsTable
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class RotationSeriesOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('rotation_series_overlay_editor.ui', parent)

        self._overlay = None

        self.eta_ranges_editor = RangesTableEditor(parent=self.ui)
        self.eta_ranges_editor.set_title('η ranges')
        self.ui.eta_ranges_layout.addWidget(self.eta_ranges_editor.ui)

        self.omega_ranges_editor = RangesTableEditor(parent=self.ui)
        self.omega_ranges_editor.set_title('ω ranges')
        self.ui.omega_ranges_layout.addWidget(self.omega_ranges_editor.ui)

        self.crystal_editor = CalibrationCrystalEditor(parent=self.ui)
        self.ui.crystal_editor_layout.addWidget(self.crystal_editor.ui)

        self.update_enable_states()

        self.setup_connections()

    def setup_connections(self):
        self.eta_ranges_editor.data_modified.connect(self.update_config)
        self.omega_ranges_editor.data_modified.connect(self.update_config)
        self.crystal_editor.params_modified.connect(self.update_config)
        self.crystal_editor.refinements_modified.connect(
            self.update_refinements)

        for w in self.widgets:
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)

        self.ui.reflections_table.pressed.connect(self.show_reflections_table)

        self.ui.aggregated.toggled.connect(self.update_enable_states)
        self.ui.enable_widths.toggled.connect(self.update_enable_states)

        ImageLoadManager().new_images_loaded.connect(self.new_images_loaded)

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        self.validate_options()
        self.update_enable_states()
        self.update_gui()

    def new_images_loaded(self):
        if self.overlay:
            self.validate_options()
            self.update_enable_states()
            self.update_gui()

    def validate_options(self):
        options = self.overlay.get('options', {})

        force_aggregated = (
            not HexrdConfig().has_omega_ranges or
            'aggregated' not in options
        )
        if force_aggregated:
            options['aggregated'] = True
            self.overlay['update_needed'] = True

        if self.overlay['update_needed']:
            HexrdConfig().overlay_config_changed.emit()

    def update_enable_states(self):
        self.ui.aggregated.setEnabled(HexrdConfig().has_omega_ranges)
        self.ui.omega_width_label.setDisabled(self.aggregated)
        self.ui.omega_width.setDisabled(self.aggregated)

        enable_widths = self.enable_widths
        names = [
            'tth_width_label',
            'tth_width',
            'eta_width_label',
            'eta_width',
        ]
        for name in names:
            getattr(self.ui, name).setEnabled(enable_widths)

    def update_gui(self):
        if self.overlay is None:
            return

        with block_signals(*self.widgets):
            options = self.overlay.get('options', {})
            if 'crystal_params' in options:
                self.crystal_params = options['crystal_params']
            if 'ome_period' in options:
                self.omega_period = options['ome_period']
            if 'aggregated' in options:
                self.aggregated = options['aggregated']
            if 'ome_width' in options:
                self.ome_width = options['ome_width']
            if 'eta_ranges' in options:
                self.eta_ranges = options['eta_ranges']
            if 'ome_ranges' in options:
                self.ome_ranges = options['ome_ranges']
            if 'tth_width' in options:
                self.tth_width = options['tth_width']
            if 'eta_width' in options:
                self.eta_width = options['eta_width']

        if 'crystal_params' in options:
            self.crystal_params = options['crystal_params']
        else:
            self.crystal_params = DEFAULT_CRYSTAL_PARAMS.copy()

        if 'refinements' in self.overlay:
            self.refinements = self.overlay['refinements']
        else:
            self.refinements = copy.deepcopy(DEFAULT_CRYSTAL_REFINEMENTS)

        widths = ['tth_width', 'eta_width']
        self.enable_widths = all(options.get(x) is not None for x in widths)
        self.update_reflections_table()

    def update_config(self):
        if self.overlay is None:
            return

        options = self.overlay.setdefault('options', {})
        options['crystal_params'] = self.crystal_params
        options['ome_period'] = self.omega_period
        options['aggregated'] = self.aggregated
        options['ome_width'] = self.ome_width
        options['eta_ranges'] = self.eta_ranges
        options['ome_ranges'] = self.ome_ranges
        options['tth_width'] = self.tth_width
        options['eta_width'] = self.eta_width

        self.update_refinements()

        self.overlay['update_needed'] = True
        HexrdConfig().overlay_config_changed.emit()

    def update_refinements(self):
        self.overlay['refinements'] = self.refinements

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

    @property
    def aggregated(self):
        return self.ui.aggregated.isChecked()

    @aggregated.setter
    def aggregated(self, b):
        self.ui.aggregated.setChecked(b)

    @property
    def ome_width(self):
        return self.ui.omega_width.value()

    @ome_width.setter
    def ome_width(self, v):
        self.ui.omega_width.setValue(v)

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
    def enable_widths(self):
        return self.ui.enable_widths.isChecked()

    @enable_widths.setter
    def enable_widths(self, b):
        self.ui.enable_widths.setChecked(b)

    @property
    def tth_width(self):
        if not self.enable_widths:
            return None

        return np.radians(self.ui.tth_width.value())

    @tth_width.setter
    def tth_width(self, v):
        if v is None:
            return

        self.ui.tth_width.setValue(np.degrees(v))

    @property
    def eta_width(self):
        if not self.enable_widths:
            return None

        return np.radians(self.ui.eta_width.value())

    @eta_width.setter
    def eta_width(self, v):
        if v is None:
            return

        self.ui.eta_width.setValue(np.degrees(v))

    @property
    def widgets(self):
        return [
            self.ui.aggregated,
            self.ui.omega_width,
            self.ui.enable_widths,
            self.ui.tth_width,
            self.ui.eta_width,
        ] + self.omega_period_widgets

    @property
    def material(self):
        if self.overlay is None:
            return None

        name = self.overlay['material']
        return HexrdConfig().material(name)

    def update_reflections_table(self):
        if hasattr(self, '_table'):
            self._table.material = self.material

    def show_reflections_table(self):
        if not hasattr(self, '_table'):
            kwargs = {
                'material': self.material,
                'parent': self.ui,
            }
            self._table = ReflectionsTable(**kwargs)
        else:
            # Make sure the material is up to date
            self._table.material = self.material

        self._table.show()
