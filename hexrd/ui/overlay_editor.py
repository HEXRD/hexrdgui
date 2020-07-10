import copy
import numpy as np

from PySide2.QtCore import QSignalBlocker
from PySide2.QtWidgets import QCheckBox, QDoubleSpinBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import convert_angle_convention


class OverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('overlay_editor.ui', parent)

        self._overlay = None
        self.update_type_tab()

        self.ui.tab_widget.tabBar().hide()

        self.update_orientation_suffixes()

        self.setup_connections()

    def setup_connections(self):
        for w in self.laue_widgets:
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)

        self.ui.laue_enable_widths.toggled.connect(
            self.update_laue_enable_states)

        HexrdConfig().euler_angle_convention_changed.connect(
            self.euler_angle_convention_changed)

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        if self.overlay is not None:
            self.update_gui()
        else:
            self.update_type_tab()

    @property
    def type(self):
        return self.overlay['type'] if self.overlay else None

    def update_type_tab(self):
        if self.type is None:
            w = getattr(self.ui, 'blank_tab')
        else:
            # Take advantage of the naming scheme...
            w = getattr(self.ui, self.type + '_tab')

        self.ui.tab_widget.setCurrentWidget(w)

    def update_gui(self):
        self.update_type_tab()

        if self.type == 'laue':
            self.update_gui_laue()

    def update_gui_laue(self):
        blockers = [QSignalBlocker(w) for w in self.all_widgets]  # noqa: F841

        options = self.overlay.get('options', {})
        if 'min_energy' in options:
            self.ui.laue_min_energy.setValue(options['min_energy'])
        if 'max_energy' in options:
            self.ui.laue_max_energy.setValue(options['max_energy'])
        if 'crystal_params' in options:
            self.laue_crystal_params = options['crystal_params']

        if options.get('tth_width') is not None:
            self.ui.laue_tth_width.setValue(np.degrees(options['tth_width']))
        if options.get('eta_width') is not None:
            self.ui.laue_eta_width.setValue(np.degrees(options['eta_width']))

        widths = ['tth_width', 'eta_width']
        enable_widths = all(options.get(x) is not None for x in widths)
        self.ui.laue_enable_widths.setChecked(enable_widths)

        self.update_laue_enable_states()

    def update_laue_enable_states(self):
        enable_widths = self.laue_enable_widths
        names = [
            'laue_tth_width_label',
            'laue_tth_width',
            'laue_eta_width_label',
            'laue_eta_width'
        ]
        for name in names:
            getattr(self.ui, name).setEnabled(enable_widths)

    def update_config(self):
        if self.type == 'laue':
            self.update_config_laue()

        if self.overlay['visible']:
            # Only cause a re-render if the overlay is visible
            HexrdConfig().overlay_config_changed.emit()

    def update_config_laue(self):
        options = self.overlay.setdefault('options', {})
        options['min_energy'] = self.ui.laue_min_energy.value()
        options['max_energy'] = self.ui.laue_max_energy.value()
        options['crystal_params'] = self.laue_crystal_params
        options['tth_width'] = self.laue_tth_width
        options['eta_width'] = self.laue_eta_width

    def euler_angle_convention_changed(self):
        self.update_orientation_suffixes()
        self.update_gui()

    def update_orientation_suffixes(self):
        suffix = '' if HexrdConfig().euler_angle_convention is None else '°'
        widgets = self.laue_cc_widgets
        for i in self.laue_orientation_indices:
            widgets[i].setSuffix(suffix)

    def convert_orientation_angle_convention(self, values, old_conv,
                                             new_conv):
        # Converts the angle convention of crystal params in place
        indices = self.laue_orientation_indices
        angles = [values[i] for i in indices]
        angles = convert_angle_convention(angles, old_conv, new_conv)
        for i, angle in zip(indices, angles):
            values[i] = angle

    @property
    def laue_orientation_indices(self):
        return [0, 1, 2]

    @property
    def laue_crystal_params(self):
        values = [x.value() for x in self.laue_cc_widgets]
        if HexrdConfig().euler_angle_convention is not None:
            # Convert the angles to None
            convention = HexrdConfig().euler_angle_convention
            self.convert_orientation_angle_convention(values, convention, None)

        return values

    @laue_crystal_params.setter
    def laue_crystal_params(self, v):
        if HexrdConfig().euler_angle_convention is not None:
            # Convert the angles
            v = copy.deepcopy(v)
            convention = HexrdConfig().euler_angle_convention
            self.convert_orientation_angle_convention(v, None, convention)

        for i, w in enumerate(self.laue_cc_widgets):
            w.setValue(v[i])

    @property
    def laue_enable_widths(self):
        return self.ui.laue_enable_widths.isChecked()

    @property
    def laue_tth_width(self):
        if not self.laue_enable_widths:
            return None

        return np.radians(self.ui.laue_tth_width.value())

    @property
    def laue_eta_width(self):
        if not self.laue_enable_widths:
            return None

        return np.radians(self.ui.laue_eta_width.value())

    @property
    def powder_widgets(self):
        return []

    @property
    def laue_cc_widgets(self):
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'laue_cc_{i}') for i in range(12)]

    @property
    def laue_widgets(self):
        return [
            self.ui.laue_min_energy,
            self.ui.laue_max_energy,
            self.ui.laue_enable_widths,
            self.ui.laue_tth_width,
            self.ui.laue_eta_width
        ] + self.laue_cc_widgets

    @property
    def mono_rotation_series_widgets(self):
        return []

    @property
    def tab_widgets(self):
        return [
            self.ui.tab_widget,
            self.ui.powder_tab,
            self.ui.laue_tab,
            self.ui.mono_rotation_series_tab,
            self.ui.blank_tab
        ]

    @property
    def all_widgets(self):
        return (
            self.powder_widgets +
            self.laue_widgets +
            self.mono_rotation_series_widgets +
            self.tab_widgets
        )
