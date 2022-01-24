import copy
import numpy as np

from PySide2.QtCore import QSignalBlocker
from PySide2.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox

from hexrd.rotations import angles_from_rmat_xyz, rotMatOfExpMap

from hexrd.ui.calibration_crystal_editor import CalibrationCrystalEditor
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays.laue_overlay import LaueRangeShape
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import convert_angle_convention


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
        self.crystal_editor.params_modified.connect(self.update_config)
        self.crystal_editor.refinements_modified.connect(
            self.update_overlay_refinements)

        HexrdConfig().euler_angle_convention_changed.connect(
            self.euler_angle_convention_changed)

    def setup_combo_boxes(self):
        width_shapes = [x.value.capitalize() for x in LaueRangeShape]
        self.ui.width_shape.addItems(width_shapes)

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

        overlay = self.overlay
        self.ui.min_energy.setValue(overlay.min_energy)
        self.ui.max_energy.setValue(overlay.max_energy)
        self.sample_rmat = overlay.sample_rmat
        self.crystal_params = overlay.crystal_params
        self.refinements = overlay.refinements
        self.width_shape = overlay.width_shape

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
        old_convention = HexrdConfig().euler_angle_convention
        if old_convention is not None:
            angles = np.radians(angles)
            new_convention = None
            angles = convert_angle_convention(angles, old_convention,
                                              new_convention)
        return rotMatOfExpMap(np.asarray(angles))

    @sample_rmat.setter
    def sample_rmat(self, v):
        # Convert from rotation matrix
        xyz = angles_from_rmat_xyz(v)
        old_convention = {
            'axes_order': 'xyz',
            'extrinsic': True,
        }
        new_convention = HexrdConfig().euler_angle_convention
        angles = convert_angle_convention(xyz, old_convention, new_convention)
        if new_convention is not None:
            angles = np.degrees(angles)

        for w, v in zip(self.sample_orientation_widgets, angles):
            w.setValue(v)

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
        ] + self.sample_orientation_widgets
