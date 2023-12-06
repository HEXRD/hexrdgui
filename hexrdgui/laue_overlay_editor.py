import copy
import numpy as np

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox

from hexrdgui.calibration_crystal_editor import CalibrationCrystalEditor
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays.laue_overlay import LaueLabelType, LaueRangeShape
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import (
    block_signals, euler_angles_to_rmat, rmat_to_euler_angles
)


class LaueOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('laue_overlay_editor.ui', parent)

        self._overlay = None

        self.crystal_editor = CalibrationCrystalEditor(parent=self.ui)
        self.ui.crystal_editor_layout.addWidget(self.crystal_editor.ui)

        self.setup_combo_boxes()
        self.setup_connections()

    def setup_connections(self):
        for w in self.widgets:
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self.update_config)

        self.ui.enable_widths.toggled.connect(self.update_enable_states)
        self.ui.label_type.currentIndexChanged.connect(
            self.update_enable_states)
        self.crystal_editor.params_modified.connect(self.update_config)
        self.crystal_editor.refinements_modified.connect(
            self.update_overlay_refinements)

        HexrdConfig().euler_angle_convention_changed.connect(
            self.euler_angle_convention_changed)

    def setup_combo_boxes(self):
        width_shapes = [x.value.capitalize() for x in LaueRangeShape]
        self.ui.width_shape.addItems(width_shapes)

        self.ui.label_type.addItem('None', None)
        for t in LaueLabelType:
            self.ui.label_type.addItem(t.value.capitalize(), t.value)

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
            overlay = self.overlay
            self.ui.min_energy.setValue(overlay.min_energy)
            self.ui.max_energy.setValue(overlay.max_energy)
            self.sample_rmat = overlay.sample_rmat
            self.crystal_params = overlay.crystal_params
            self.refinements = overlay.refinements
            self.width_shape = overlay.width_shape
            self.label_type = overlay.label_type
            self.label_offsets = overlay.label_offsets

            self.ui.enable_widths.setChecked(overlay.has_widths)
            if overlay.has_widths:
                self.ui.tth_width.setValue(np.degrees(overlay.tth_width))
                self.ui.eta_width.setValue(np.degrees(overlay.eta_width))

            self.update_enable_states()
            self.update_orientation_suffixes()

    def update_enable_states(self):
        enable_widths = self.enable_widths
        names = [
            'tth_width_label',
            'tth_width',
            'eta_width_label',
            'eta_width',
            'width_shape_label',
            'width_shape',
        ]
        for name in names:
            getattr(self.ui, name).setEnabled(enable_widths)

        enable_label_options = self.label_type is not None
        names = [
            'label_offset_x_label',
            'label_offset_x',
            'label_offset_y_label',
            'label_offset_y',
        ]
        for name in names:
            getattr(self.ui, name).setEnabled(enable_label_options)

    def euler_angle_convention_changed(self):
        self.update_gui()

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

    def update_config(self):
        overlay = self.overlay
        overlay.min_energy = self.ui.min_energy.value()
        overlay.max_energy = self.ui.max_energy.value()
        overlay.crystal_params = self.crystal_params
        overlay.tth_width = self.tth_width
        overlay.eta_width = self.eta_width
        overlay.width_shape = self.width_shape
        overlay.sample_rmat = self.sample_rmat
        overlay.refinements = self.refinements
        overlay.label_type = self.label_type
        overlay.label_offsets = self.label_offsets

        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

    def update_overlay_refinements(self):
        # update_config() does this, but it will also force a redraw
        # of the overlay, which we don't need.
        self.overlay.refinements = self.refinements

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
    def width_shape(self):
        return self.ui.width_shape.currentText().lower()

    @width_shape.setter
    def width_shape(self, v):
        self.ui.width_shape.setCurrentText(v.capitalize())

    def update_orientation_suffixes(self):
        suffix = '' if HexrdConfig().euler_angle_convention is None else '°'
        for w in self.sample_orientation_widgets:
            w.setSuffix(suffix)

    @property
    def sample_rmat(self):
        # Convert to rotation matrix
        angles = [w.value() for w in self.sample_orientation_widgets]
        return euler_angles_to_rmat(angles)

    @sample_rmat.setter
    def sample_rmat(self, v):
        angles = rmat_to_euler_angles(v)
        for w, v in zip(self.sample_orientation_widgets, angles):
            w.setValue(v)

    @property
    def label_type(self):
        return self.ui.label_type.currentData()

    @label_type.setter
    def label_type(self, v):
        found = False
        w = self.ui.label_type
        for i in range(w.count()):
            if w.itemData(i) == v:
                w.setCurrentIndex(i)
                found = True
                break

        if not found:
            raise Exception(f'Unknown label type: {v}')

    @property
    def label_offsets(self):
        return [
            self.ui.label_offset_x.value(),
            self.ui.label_offset_y.value(),
        ]

    @label_offsets.setter
    def label_offsets(self, v):
        self.ui.label_offset_x.setValue(v[0])
        self.ui.label_offset_y.setValue(v[1])

    @property
    def sample_orientation_widgets(self):
        return [
            self.ui.sample_orientation_0,
            self.ui.sample_orientation_1,
            self.ui.sample_orientation_2,
        ]

    @property
    def widgets(self):
        return [
            self.ui.min_energy,
            self.ui.max_energy,
            self.ui.enable_widths,
            self.ui.tth_width,
            self.ui.eta_width,
            self.ui.width_shape,
            self.ui.label_type,
            self.ui.label_offset_x,
            self.ui.label_offset_y,
        ] + self.sample_orientation_widgets
