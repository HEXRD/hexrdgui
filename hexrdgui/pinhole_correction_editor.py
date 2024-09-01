import h5py
import numpy as np

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QMessageBox, QSpinBox
)

import hexrd.resources
from hexrd.material import _angstroms, _kev, Material
from hexrd.xrdutil.phutil import (
    JHEPinholeDistortion, RyggPinholeDistortion, SampleLayerDistortion,
)

from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.pinhole_panel_buffer import generate_pinhole_panel_buffer
from hexrdgui.polar_distortion_object import PolarDistortionObject
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals

from hexrdgui import resource_loader


class PinholeCorrectionEditor(QObject):

    settings_modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('pinhole_correction_editor.ui', parent)

        self.pinhole_materials = {}
        self.pinhole_distortion_object = None

        # Default to "None" tab
        self.ui.correction_type.setCurrentIndex(0)
        self.correction_type_changed()

        self.load_pinhole_materials()
        self.populate_rygg_absorption_length_options()
        self.on_rygg_absorption_length_selector_changed()
        self.setup_connections()

    def setup_connections(self):
        for w in self.all_widgets:
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self.on_settings_modified)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.on_settings_modified)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self.on_settings_modified)

        self.ui.correction_type.currentIndexChanged.connect(
            self.correction_type_changed)

        for w in self.apply_panel_buffer_buttons:
            w.clicked.connect(self.apply_panel_buffers)

        self.ui.rygg_absorption_length_selector.currentIndexChanged.connect(
            self.on_rygg_absorption_length_selector_changed)

        HexrdConfig().material_modified.connect(self.on_material_modified)
        HexrdConfig().beam_energy_modified.connect(
            self.on_beam_energy_modified)
        HexrdConfig().materials_dict_modified.connect(
            self.on_materials_dict_modified)
        HexrdConfig().physics_package_modified.connect(self.synchronize_values)

        self.ui.apply_to_polar_view.toggled.connect(
            self.on_apply_to_polar_view_toggled)

    def synchronize_values(self):
        with block_signals(*self.all_widgets):
            self.correction_kwargs = {}
        self.on_settings_modified()

    def on_settings_modified(self):
        self.settings_modified.emit()
        self.update_polar_distortion_object()

    @property
    def correction_type(self):
        v = self.ui.correction_type.currentText()

        conversions = {
            'None': None,
            'Pinhole (JHE)': 'JHEPinholeDistortion',
            'Pinhole (Rygg)': 'RyggPinholeDistortion',
            'Sample Layer': 'SampleLayerDistortion',
        }
        if v in conversions:
            v = conversions[v]

        return v

    @correction_type.setter
    def correction_type(self, v):
        conversions = {
            None: 'None',
            'JHEPinholeDistortion': 'Pinhole (JHE)',
            'RyggPinholeDistortion': 'Pinhole (Rygg)',
            'SampleLayerDistortion': 'Sample Layer',
        }
        if v in conversions:
            v = conversions[v]

        self.ui.correction_type.setCurrentText(v)

    @property
    def correction_kwargs(self):
        dtype = self.correction_type
        physics = HexrdConfig().physics_package
        pinhole = HexrdConfig().pinhole_package
        if dtype is None:
            return None
        elif dtype == 'SampleLayerDistortion':
            return {
                'layer_standoff': physics.window_thickness,
                'layer_thickness': physics.sample_thickness,
                'pinhole_thickness': pinhole.thickness,
                'pinhole_radius': pinhole.radius,
            }
        elif dtype == 'JHEPinholeDistortion':
            return {
                'pinhole_radius': pinhole.radius,
                'pinhole_thickness': pinhole.thickness,
            }
        elif dtype == 'RyggPinholeDistortion':
            output = {
                'pinhole_radius': pinhole.radius,
                'pinhole_thickness': pinhole.thickness,
                'num_phi_elements': self.ui.rygg_num_phi_elements.value(),
            }
            if self.rygg_absorption_length_visible:
                # Only return an absorption length if it is visible
                output['absorption_length'] = self.rygg_absorption_length
            return output

        raise Exception(f'Not implemented for: {dtype}')

    @correction_kwargs.setter
    def correction_kwargs(self, v):
        if v is None:
            return

        pinhole = HexrdConfig().pinhole_package
        physics = HexrdConfig().physics_package
        absorption = pinhole.absorption_length(HexrdConfig().beam_energy)
        # Values are (key, default)
        values = {
            'sample_layer_standoff': ('layer_standoff', physics.window_thickness),
            'sample_layer_thickness': ('layer_thickness', physics.sample_thickness),
            'sample_pinhole_thickness': ('pinhole_thickness', pinhole.thickness),
            'sample_pinhole_diameter': ('pinhole_diameter', pinhole.diameter),
            'rygg_diameter': ('pinhole_diameter', pinhole.diameter),
            'rygg_thickness': ('pinhole_thickness', pinhole.thickness),
            'rygg_num_phi_elements': ('num_phi_elements', 30),
            'rygg_absorption_length_value': ('absorption_length', absorption),
            'jhe_diameter': ('pinhole_diameter', pinhole.diameter),
            'jhe_thickness': ('pinhole_thickness', pinhole.thickness),
        }

        dtype = self.correction_type
        if dtype == 'SampleLayerDistortion':
            widget_prefix = 'sample_'
        elif dtype == 'RyggPinholeDistortion':
            widget_prefix = 'rygg_'
        elif dtype == 'JHEPinholeDistortion':
            widget_prefix = 'jhe_'
        elif dtype is None:
            widget_prefix = '_'
        else:
            raise Exception(f'Not implemented for: {dtype}')

        for w_name, (key, value) in values.items():
            if w_name.startswith(widget_prefix):
                # Extract the value from the dict
                value = v.get(key, value)

            w = getattr(self.ui, w_name)
            w.setValue(value)

        if dtype == 'RyggPinholeDistortion':
            self.auto_select_rygg_absorption_length()

    @property
    def sample_layer_widgets(self):
        return [
            self.ui.sample_layer_standoff,
            self.ui.sample_layer_thickness,
            self.ui.sample_pinhole_thickness,
            self.ui.sample_pinhole_diameter,
        ]

    @property
    def jhe_widgets(self):
        return [
            self.ui.jhe_diameter,
            self.ui.jhe_thickness,
        ]

    @property
    def rygg_widgets(self):
        return [
            self.ui.rygg_diameter,
            self.ui.rygg_thickness,
            self.ui.rygg_num_phi_elements,
        ] + self.rygg_absorption_length_widgets

    @property
    def rygg_absorption_length_widgets(self):
        return [
            self.ui.rygg_absorption_length_label,
            self.ui.rygg_absorption_length_selector,
            self.ui.rygg_absorption_length_value,
        ]

    @property
    def apply_panel_buffer_buttons(self):
        return [
            self.ui.jhe_apply_panel_buffers,
            self.ui.rygg_apply_panel_buffers,
        ]

    @property
    def all_widgets(self):
        # Except for the correction type
        return [
            *self.sample_layer_widgets,
            *self.jhe_widgets,
            *self.rygg_widgets,
            *self.apply_panel_buffer_buttons,
        ]

    def correction_type_changed(self):
        idx = self.ui.correction_type.currentIndex()
        self.ui.tab_widget.set_current_index_later(idx)

        enable = self.correction_type is not None
        self.ui.apply_to_polar_view.setEnabled(enable)
        if self.apply_to_polar_view and not enable:
            self.apply_to_polar_view = False

        self.update_tab_widget_visibility()

        if self.correction_type == 'RyggPinholeDistortion':
            self.auto_select_rygg_absorption_length()

        self.validate()
        self.on_settings_modified()

    def update_tab_widget_visibility(self):
        self.ui.tab_widget.setVisible(self.correction_type is not None)

    def validate(self):
        if self.correction_type is None:
            # No validation needed
            return

        # Warn the user if there is a non-zero oscillation stage vector
        stage = HexrdConfig().instrument_config['oscillation_stage']
        if not np.all(np.isclose(stage['translation'], 0)):
            msg = (
                'WARNING: a non-zero oscillation stage vector is being '
                'used with the Pinhole Camera Correction.'
            )
            QMessageBox.critical(self.ui, 'HEXRD', msg)

        source_distance_needed_types = (
            'SampleLayerDistortion',
            'RyggPinholeDistortion',
        )
        if self.correction_type in source_distance_needed_types:
            beam = HexrdConfig().instrument_config['beam']
            source_distance = beam.get('source_distance', np.inf)
            if source_distance is None or source_distance == np.inf:
                msg = (
                    'WARNING: the source distance is infinite.\n\nThe '
                    'pinhole distortion will not be correct '
                    'unless the source distance is finite.\n\nThe source '
                    'distance may be edited in the Instrument "Form View"'
                )
                QMessageBox.critical(self.ui, 'HEXRD', msg)

    def apply_panel_buffers(self):
        instr = create_hedm_instrument()
        ph_buffer = generate_pinhole_panel_buffer(instr)

        # merge with any existing panel buffer
        for det_key, det in instr.detectors.items():
            # "True" means keep, "False" means ignore
            pb = det.panel_buffer
            if pb is not None:
                if pb.ndim == 2:
                    new_buff = np.logical_and(pb, ph_buffer[det_key])
                elif pb.ndim == 1 and not np.allclose(pb, 0):
                    # have edge buffer
                    ebuff = np.ones(det.shape, dtype=bool)
                    npix_row = int(np.ceil(pb[0]/det.pixel_size_row))
                    npix_col = int(np.ceil(pb[1]/det.pixel_size_col))
                    ebuff[:npix_row, :] = False
                    ebuff[-npix_row:, :] = False
                    ebuff[:, :npix_col] = False
                    ebuff[:, -npix_col:] = False
                    new_buff = np.logical_and(ebuff, ph_buffer[det_key])
                else:
                    new_buff = ph_buffer[det_key]

                det.panel_buffer = new_buff
            else:
                det.panel_buffer = ph_buffer[det_key]

        # Now set them in the hexrdgui config
        iconfig = HexrdConfig().config['instrument']
        for det_key, det in instr.detectors.items():
            det_config = iconfig['detectors'][det_key]
            det_config['buffer']['value'] = det.panel_buffer

        msg = 'Pinhole dimensions were applied to the panel buffers'
        QMessageBox.information(self.ui, 'HEXRD', msg)

    @property
    def rygg_absorption_length(self):
        pinhole = HexrdConfig().pinhole_package
        return pinhole.absorption_length(HexrdConfig().beam_energy)

    def load_pinhole_materials(self):
        module = hexrd.resources

        # Use a high dmin since we do not care about the HKLs here.
        # We only care about the absorption length.
        dmin = _angstroms(2)
        energy = _kev(HexrdConfig().beam_energy)
        materials = {}
        with resource_loader.path(module, 'pinhole_materials.h5') as file_path:
            with h5py.File(file_path) as f:
                mat_names = list(f.keys())

            for name in mat_names:
                materials[name] = Material(name, file_path, dmin=dmin,
                                           kev=energy)

        self.pinhole_materials = materials

    def on_material_modified(self, name):
        # Just make sure the value is up-to-date
        self.on_rygg_absorption_length_selector_changed()

    def on_beam_energy_modified(self):
        # Just make sure the value is up-to-date
        self.on_rygg_absorption_length_selector_changed()

    def on_materials_dict_modified(self):
        # This gets called if materials get added/removed/deleted/renamed
        with block_signals(self, self.ui.rygg_absorption_length_selector):
            self.populate_rygg_absorption_length_options()

    def populate_rygg_absorption_length_options(self):
        self.ui.rygg_absorption_length_selector.clear()

        pinhole_names = list(self.pinhole_materials)
        mat_names = list(HexrdConfig().materials.keys())

        options = [
            'Enter Manually',
            *pinhole_names,
            *mat_names,
        ]
        self.ui.rygg_absorption_length_selector.addItems(options)
        self.ui.rygg_absorption_length_selector.insertSeparator(1)
        self.ui.rygg_absorption_length_selector.insertSeparator(
            2 + len(pinhole_names))

    @property
    def user_material_names_start_idx(self):
        # 0 is "Enter Manually" and there are 2 separators.
        return 3 + len(self.pinhole_materials)

    @property
    def pinhole_material_names_start_idx(self):
        # 0 is "Enter Manually", 1 is a separator, and 2 is the start
        return 2

    @property
    def enter_manually_idx(self):
        return 0

    def on_rygg_absorption_length_selector_changed(self):
        # self.rygg_absorption_length should be updated
        self.ui.rygg_absorption_length_value.setValue(
            self.rygg_absorption_length)

    @property
    def none_option_visible(self):
        return not self.ui.correction_type.view().isRowHidden(0)

    @none_option_visible.setter
    def none_option_visible(self, b):
        self.ui.correction_type.view().setRowHidden(0, not b)

    @property
    def rygg_absorption_length_visible(self):
        return any(w.isVisible() for w in self.rygg_absorption_length_widgets)

    @rygg_absorption_length_visible.setter
    def rygg_absorption_length_visible(self, b):
        for w in self.rygg_absorption_length_widgets:
            w.setVisible(b)

        # This must be hidden as well if there is no absorption length
        self.apply_to_polar_view_visible = False

    @property
    def apply_to_polar_view_visible(self):
        return self.ui.apply_to_polar_view.isVisible()

    @apply_to_polar_view_visible.setter
    def apply_to_polar_view_visible(self, b):
        if b and not self.rygg_absorption_length_visible:
            raise Exception('Absorption length must be visible first')

        self.ui.apply_to_polar_view.setVisible(b)

    @property
    def apply_panel_buffer_visible(self):
        return any(w.isVisible() for w in self.apply_panel_buffer_buttons)

    @apply_panel_buffer_visible.setter
    def apply_panel_buffer_visible(self, b):
        for w in self.apply_panel_buffer_buttons:
            w.setVisible(b)

    def auto_select_rygg_absorption_length(self):
        w = self.ui.rygg_absorption_length_selector

        # Set the material to match the pinhole package if it exists.
        # If not default to "Enter Manually"
        for i in range(1, w.count()):
            name = w.itemText(i)
            if not name:
                # It's a separator
                continue
            if name == HexrdConfig().pinhole_package.material:
                w.setCurrentText(name)
                return

        # Set it to `Enter Manually` if nothing else matched
        w.setCurrentText('Enter Manually')

    def update_from_object(self, obj):
        if type(obj) not in REVERSED_TYPE_MAP:
            raise NotImplementedError(type(obj))

        self.correction_type = REVERSED_TYPE_MAP[type(obj)]
        kwargs = self.correction_kwargs
        for key in kwargs:
            # These should have identical names on the object
            kwargs[key] = getattr(obj, key)

        self.correction_kwargs = kwargs

    def create_object(self, panel):
        if self.correction_type is None:
            return None

        kwargs = {
            'panel': panel,
            **self.correction_kwargs,
        }
        return TYPE_MAP[self.correction_type](**kwargs)

    def create_object_dict(self, instr):
        if self.correction_type is None:
            return None

        ret = {}
        for det_key, panel in instr.detectors.items():
            ret[det_key] = self.create_object(panel)

        return ret

    def on_apply_to_polar_view_toggled(self, b):
        self.apply_to_polar_view = b

    @property
    def apply_to_polar_view(self):
        return self.ui.apply_to_polar_view.isChecked()

    @apply_to_polar_view.setter
    def apply_to_polar_view(self, b):
        if b:
            obj = PolarDistortionObject(self.correction_type,
                                        self.correction_kwargs)
            HexrdConfig().custom_polar_tth_distortion_object = obj
            self.pinhole_distortion_object = obj
        else:
            HexrdConfig().custom_polar_tth_distortion_object = None
            self.pinhole_distortion_object = None

        with block_signals(self.ui.apply_to_polar_view):
            self.ui.apply_to_polar_view.setChecked(b)

        self.on_settings_modified()

    def update_polar_distortion_object(self):
        obj = self.pinhole_distortion_object
        if (
            not obj or
            not self.apply_to_polar_view_visible or
            not self.apply_to_polar_view or
            self.correction_type is None
        ):
            return

        any_changes = False
        if obj.pinhole_distortion_type != self.correction_type:
            obj.pinhole_distortion_type = self.correction_type
            any_changes = True

        if obj.pinhole_distortion_kwargs != self.correction_kwargs:
            obj.pinhole_distortion_kwargs = self.correction_kwargs
            any_changes = True

        if any_changes:
            # Make sure the polar view gets rerendered.
            HexrdConfig().flag_overlay_updates_for_all_materials()
            HexrdConfig().rerender_needed.emit()

    def update_gui_from_polar_distortion_object(self):
        if not (obj := HexrdConfig().saved_custom_polar_tth_distortion_object):
            return

        self.correction_type = obj.pinhole_distortion_type
        self.correction_kwargs = obj.pinhole_distortion_kwargs

        checked = HexrdConfig().custom_polar_tth_distortion_object is obj
        with block_signals(self.ui.apply_to_polar_view):
            self.ui.apply_to_polar_view.setChecked(checked)


TYPE_MAP = {
    'SampleLayerDistortion': SampleLayerDistortion,
    'JHEPinholeDistortion': JHEPinholeDistortion,
    'RyggPinholeDistortion': RyggPinholeDistortion,
}
REVERSED_TYPE_MAP = {v: k for k, v in TYPE_MAP.items()}
