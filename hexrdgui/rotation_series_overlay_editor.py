import copy

import numpy as np

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QInputDialog

from hexrdgui.calibration_crystal_editor import CalibrationCrystalEditor
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_load_manager import ImageLoadManager
from hexrdgui.ranges_table_editor import RangesTableEditor
from hexrdgui.reflections_table import ReflectionsTable
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


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
            self.update_overlay_refinements)

        for w in self.widgets:
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)

        self.ui.reflections_table.pressed.connect(self.show_reflections_table)

        self.ui.aggregated.toggled.connect(self.update_enable_states)
        self.ui.enable_widths.toggled.connect(self.update_enable_states)

        self.ui.mask_eta_by_wedge.clicked.connect(self.mask_eta_by_wedge)
        self.ui.sync_ome_period.toggled.connect(self.sync_ome_period_toggled)
        self.ui.sync_ome_ranges.toggled.connect(self.sync_ome_ranges_toggled)

        ImageLoadManager().new_images_loaded.connect(self.new_images_loaded)

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        self.update_gui()

    def new_images_loaded(self):
        self.update_gui()

    def update_enable_states(self):
        is_aggregated = HexrdConfig().is_aggregated
        has_omegas = HexrdConfig().has_omegas

        self.ui.aggregated.setEnabled(has_omegas and not is_aggregated)

        if self.overlay is not None:
            sync_ome_ranges = self.overlay.sync_ome_ranges
            disable = sync_ome_ranges and has_omegas
            self.omega_ranges_editor.ui.setDisabled(disable)

            sync_ome_period = self.overlay.sync_ome_period
            disable = sync_ome_period and has_omegas
            for w in self.ome_period_widgets:
                w.setDisabled(disable)

        enable_widths = self.enable_widths
        names = [
            'tth_width_label',
            'tth_width',
            'eta_width_label',
            'eta_width',
        ]
        for name in names:
            getattr(self.ui, name).setEnabled(enable_widths)

    @property
    def matching_attributes(self):
        return [
            'crystal_params',
            'refinements',
            'ome_period',
            'aggregated',
            'ome_width',
            'eta_ranges',
            'ome_ranges',
            'tth_width',
            'eta_width',
            'sync_ome_ranges',
            'sync_ome_period',
        ]

    def update_gui(self):
        overlay = self.overlay
        if overlay is None:
            return

        with block_signals(*self.widgets):
            for attr in self.matching_attributes:
                setattr(self, attr, getattr(overlay, attr))

        self.enable_widths = overlay.has_widths
        self.update_reflections_table()
        self.update_enable_states()

    def update_config(self):
        if self.overlay is None:
            return

        for attr in self.matching_attributes:
            setattr(self.overlay, attr, getattr(self, attr))

        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

    def update_overlay_refinements(self):
        # update_config() does this, but it will also force a redraw
        # of the overlay, which we don't need.
        self.overlay.refinements = self.refinements

    @property
    def crystal_params(self):
        return copy.deepcopy(self.crystal_editor.params)

    @crystal_params.setter
    def crystal_params(self, v):
        self.crystal_editor.params = v

    @property
    def refinements(self):
        return self.crystal_editor.refinements

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
        return np.radians(self.ui.omega_width.value())

    @ome_width.setter
    def ome_width(self, v):
        self.ui.omega_width.setValue(np.degrees(v))

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
    def sync_ome_ranges(self):
        return self.ui.sync_ome_ranges.isChecked()

    @sync_ome_ranges.setter
    def sync_ome_ranges(self, b):
        self.ui.sync_ome_ranges.setChecked(b)

    @property
    def sync_ome_period(self):
        return self.ui.sync_ome_period.isChecked()

    @sync_ome_period.setter
    def sync_ome_period(self, b):
        self.ui.sync_ome_period.setChecked(b)

    @property
    def ome_period_widgets(self):
        return [getattr(self.ui, f'omega_period_{i}') for i in range(2)]

    @property
    def ome_period(self):
        return [np.radians(w.value()) for w in self.ome_period_widgets]

    @ome_period.setter
    def ome_period(self, v):
        for val, w in zip(v, self.ome_period_widgets):
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
        ] + self.ome_period_widgets

    @property
    def material(self):
        return self.overlay.material if self.overlay is not None else None

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

    def mask_eta_by_wedge(self):
        title = 'Select Width'
        label = 'η Mask Width (°)'
        kwargs = {
            'value': 5,
            'min': 0.001,
            'max': 360,
            'decimals': 4,
        }
        mask, accepted = QInputDialog.getDouble(self.ui, title, label,
                                                **kwargs)
        if not accepted:
            return

        self.eta_ranges = np.radians([[-90 + mask, 90 - mask],
                                      [90 + mask, 270 - mask]])
        self.update_config()

    def sync_ome_ranges_toggled(self):
        if self.overlay is None:
            return

        self.overlay.sync_ome_ranges = self.sync_ome_ranges
        self.update_enable_states()

    def sync_ome_period_toggled(self):
        if self.overlay is None:
            return

        self.overlay.sync_ome_period = self.sync_ome_period
        self.update_enable_states()
