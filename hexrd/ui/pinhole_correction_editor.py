import numpy as np

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QMessageBox, QSpinBox
)

from hexrd.xrdutil.phutil import (
    JHEPinholeDistortion, RyggPinholeDistortion, SampleLayerDistortion
)

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.pinhole_panel_buffer import generate_pinhole_panel_buffer
from hexrd.ui.ui_loader import UiLoader


class PinholeCorrectionEditor(QObject):

    settings_modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('pinhole_correction_editor.ui', parent)

        # Default to "None" tab
        self.ui.correction_type.setCurrentIndex(0)
        self.ui.tab_widget.setCurrentIndex(0)
        self.update_tab_widget_visibility()

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

    def on_settings_modified(self):
        self.settings_modified.emit()

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
        if dtype is None:
            return None
        elif dtype == 'SampleLayerDistortion':
            return {
                'layer_standoff': self.ui.sample_layer_standoff.value() * 1e-3,
                'layer_thickness': (
                    self.ui.sample_layer_thickness.value() * 1e-3),
                'pinhole_thickness': (
                    self.ui.sample_pinhole_thickness.value() * 1e-3),
            }
        elif dtype == 'JHEPinholeDistortion':
            return {
                'pinhole_radius': self.ui.jhe_radius.value() * 1e-3,
                'pinhole_thickness': self.ui.jhe_thickness.value() * 1e-3,
            }
        elif dtype == 'RyggPinholeDistortion':
            output = {
                'pinhole_radius': self.ui.rygg_radius.value() * 1e-3,
                'pinhole_thickness': self.ui.rygg_thickness.value() * 1e-3,
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

        # Values are (key, default)
        values = {
            'sample_layer_standoff': ('layer_standoff', 0.15),
            'sample_layer_thickness': ('layer_thickness', 0.005),
            'sample_pinhole_thickness': ('pinhole_thickness', 0.1),
            'rygg_radius': ('pinhole_radius', 0.2),
            'rygg_thickness': ('pinhole_thickness', 0.1),
            'rygg_num_phi_elements': ('num_phi_elements', 60),
            'rygg_absorption_length_value': ('absorption_length', 100),
            'jhe_radius': ('pinhole_radius', 0.2),
            'jhe_thickness': ('pinhole_thickness', 0.1),
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

            # Most units are in mm and we must convert to micrometer.
            # Skip the ones that we don't need to convert.
            if key in ('num_phi_elements', 'absorption_length'):
                multiplier = 1
            else:
                multiplier = 1e3

            w = getattr(self.ui, w_name)
            w.setValue(value * multiplier)

        if dtype == 'RyggPinholeDistortion':
            self.auto_select_rygg_absorption_length()

    @property
    def sample_layer_widgets(self):
        return [
            self.ui.sample_layer_standoff,
            self.ui.sample_layer_thickness,
            self.ui.sample_pinhole_thickness,
        ]

    @property
    def jhe_widgets(self):
        return [
            self.ui.jhe_radius,
            self.ui.jhe_thickness,
        ]

    @property
    def rygg_widgets(self):
        return [
            self.ui.rygg_radius,
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
        self.ui.tab_widget.setCurrentIndex(idx)

        self.update_tab_widget_visibility()

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

        config = self.correction_kwargs
        required_keys = ('pinhole_radius', 'pinhole_thickness')
        if config is None or any(x not in config for x in required_keys):
            raise Exception(f'Failed to create panel buffer with {config=}')

        kwargs = {
            'instr': instr,
            'pinhole_radius': config['pinhole_radius'],
            'pinhole_thickness': config['pinhole_thickness'],
        }
        ph_buffer = generate_pinhole_panel_buffer(**kwargs)

        # merge with any existing panel buffer
        for det_key, det in instr.detectors.items():
            pb = det.panel_buffer
            if pb is not None:
                if pb.ndim == 2:
                    new_buff = np.logical_and(pb, ph_buffer[det_key])
                elif pb.ndim == 1:
                    # have edge buffer
                    ebuff = np.ones(det.shape, dtype=bool)
                    npix_row = int(np.ceil(pb[0]/det.pixel_size_row))
                    npix_col = int(np.ceil(pb[1]/det.pixel_size_col))
                    ebuff[:npix_row, :] = False
                    ebuff[-npix_row:, :] = False
                    ebuff[:, :npix_col] = False
                    ebuff[:, -npix_col:] = False
                    new_buff = np.logical_and(ebuff, ph_buffer[det_key])
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
        name = self.ui.rygg_absorption_length_selector.currentText()
        return self.get_rygg_absorption_length(name)

    def get_rygg_absorption_length(self, name):
        if name == 'Enter Manually':
            return self.ui.rygg_absorption_length_value.value()
        elif name in self._rygg_absorption_material_names:
            mat = HexrdConfig().materials[name]
            return mat.absorption_length
        else:
            return self._rygg_absorption_preset_values[name]

    @rygg_absorption_length.setter
    def rygg_absorption_length(self, v):
        self.ui.rygg_absorption_length_value.setValue(v)
        self.auto_select_rygg_absorption_length()

    def populate_rygg_absorption_length_options(self):
        self.ui.rygg_absorption_length_selector.clear()

        mat_names = list(HexrdConfig().materials.keys())
        self._rygg_absorption_material_names = mat_names

        presets = {
            'Name': 3.57,
        }
        presets = {f'{k} ({v})': v for k, v in presets.items()}
        self._rygg_absorption_preset_values = presets

        options = [
            'Enter Manually',
            *mat_names,
            *list(presets),
        ]
        self.ui.rygg_absorption_length_selector.addItems(options)
        self.ui.rygg_absorption_length_selector.insertSeparator(1)
        self.ui.rygg_absorption_length_selector.insertSeparator(
            2 + len(mat_names))

    def on_rygg_absorption_length_selector_changed(self):
        text = self.ui.rygg_absorption_length_selector.currentText()

        enter_manually = text == 'Enter Manually'
        self.ui.rygg_absorption_length_value.setEnabled(enter_manually)
        if enter_manually:
            return

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

    @property
    def apply_panel_buffer_visible(self):
        return any(w.isVisible() for w in self.apply_panel_buffer_buttons)

    @apply_panel_buffer_visible.setter
    def apply_panel_buffer_visible(self, b):
        for w in self.apply_panel_buffer_buttons:
            w.setVisible(b)

    def auto_select_rygg_absorption_length(self):
        w = self.ui.rygg_absorption_length_selector
        value = self.ui.rygg_absorption_length_value.value()

        # Check if there is an absorption length that matches other than
        # "Enter Manually", and auto set it if there is.
        names = [w.itemText(i) for i in range(1, w.count())]
        for name in names:
            if not name:
                # It's a separator
                continue

            absorption_length = self.get_rygg_absorption_length(name)
            if np.isclose(value, absorption_length):
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


TYPE_MAP = {
    'SampleLayerDistortion': SampleLayerDistortion,
    'JHEPinholeDistortion': JHEPinholeDistortion,
    'RyggPinholeDistortion': RyggPinholeDistortion,
}
REVERSED_TYPE_MAP = {v: k for k, v in TYPE_MAP.items()}
