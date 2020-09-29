import copy
import importlib.resources
import os
from pathlib import Path

import numpy as np
import yaml

from PySide2.QtCore import Qt, QObject, QSignalBlocker, Signal
from PySide2.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QMessageBox, QSizePolicy,
    QTableWidgetItem, QWidget
)

from hexrd.material import _angstroms
from hexrd.WPPF import LeBail, Rietveld, Parameters

from hexrd.ui import enter_key_filter

import hexrd.ui.resources.calibration as calibration_resources
from hexrd.ui.constants import OverlayType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox
from hexrd.ui.select_items_dialog import SelectItemsDialog
from hexrd.ui.ui_loader import UiLoader


COLUMNS = {
    'name': 0,
    'value': 1,
    'minimum': 2,
    'maximum': 3,
    'vary': 4
}

LENGTH_SUFFIXES = ['_a', '_b', '_c']


class WppfOptionsDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('wppf_options_dialog.ui', parent)
        self.ui.setWindowTitle('WPPF Options Dialog')
        self.ui.installEventFilter(enter_key_filter)

        self.load_initial_params()
        self.load_settings()
        self.update_extra_params()

        self.value_spinboxes = []
        self.minimum_spinboxes = []
        self.maximum_spinboxes = []
        self.vary_checkboxes = []

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.select_materials_button.pressed.connect(self.select_materials)
        self.ui.background_method.currentIndexChanged.connect(
            self.update_visible_background_parameters)
        self.ui.select_experiment_file_button.pressed.connect(
            self.select_experiment_file)
        self.ui.reset_table_to_defaults.pressed.connect(
            self.reset_table_to_defaults)

        self.ui.accepted.connect(self.accept)
        self.ui.rejected.connect(self.reject)

    def accept(self):
        try:
            self.validate()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            self.show()
            return

        self.save_settings()
        self.accepted.emit()

    def reject(self):
        self.rejected.emit()

    def validate(self):
        use_experiment_file = self.use_experiment_file
        if use_experiment_file and not os.path.exists(self.experiment_file):
            raise Exception(f'Experiment file, {self.experiment_file}, '
                            'does not exist')

    def load_initial_params(self):
        text = importlib.resources.read_text(calibration_resources,
                                             'wppf_params.yml')
        self.default_params = yaml.load(text, Loader=yaml.FullLoader)
        self.params = copy.deepcopy(self.default_params)

    def update_extra_params(self):
        # First, make a copy of the old params object. We will remove all
        # extra params currently in place.
        old_params = copy.deepcopy(self.params)
        for key in list(self.params.keys()):
            if key not in self.default_params:
                del self.params[key]

        # Temporarily set the background method to chebyshev
        # so that the spline lineplot won't pop up
        blocker = QSignalBlocker(self.ui.background_method)  # noqa: F841
        previous = self.background_method
        self.background_method = 'chebyshev'

        try:
            # Next, create the WPPF object and allow it to add whatever params
            # it wants to. Then we will add them to the new params.
            wppf_object = self.create_wppf_object(add_params=True)
        finally:
            # Restore the old background method
            self.background_method = previous

        for key, obj in wppf_object.params.param_dict.items():
            if key in self.params:
                # Already present. Continue
                continue

            if all(key in x for x in [old_params, self.default_params]):
                # Copy over the previous info for the key
                # Only copy over default params, no extra params
                self.params[key] = old_params[key]
                continue

            # Otherwise, copy it straight from the WPPF object.
            self.params[key] = [
                obj.value,
                obj.lb,
                obj.ub,
                obj.vary
            ]

    def show(self):
        self.ui.show()

    @property
    def selected_materials(self):
        if not hasattr(self, '_selected_materials'):
            # Choose the visible ones with powder overlays by default
            overlays = [x for x in HexrdConfig().overlays if x['visible']]
            overlays = [x for x in overlays if x['type'] == OverlayType.powder]
            materials = [x['material'] for x in overlays]
            self._selected_materials = list(dict.fromkeys(materials))

        return self._selected_materials

    @selected_materials.setter
    def selected_materials(self, v):
        self._selected_materials = v

    @property
    def powder_overlay_materials(self):
        overlays = HexrdConfig().overlays
        overlays = [x for x in overlays if x['type'] == OverlayType.powder]
        return list(dict.fromkeys([x['material'] for x in overlays]))

    def select_materials(self):
        materials = self.powder_overlay_materials
        selected = self.selected_materials
        items = [(name, name in selected) for name in materials]
        dialog = SelectItemsDialog(items, self.ui)
        if dialog.exec_():
            self.selected_materials = dialog.selected_items
            self.update_extra_params()
            self.update_table()

    def update_visible_background_parameters(self):
        is_chebyshev = self.background_method == 'chebyshev'
        chebyshev_widgets = [
            self.ui.chebyshev_polynomial_degree,
            self.ui.chebyshev_polynomial_degree_label
        ]
        for w in chebyshev_widgets:
            w.setVisible(is_chebyshev)

    @property
    def wppf_method(self):
        return self.ui.wppf_method.currentText()

    @wppf_method.setter
    def wppf_method(self, v):
        self.ui.wppf_method.setCurrentText(v)

    @property
    def refinement_steps(self):
        return self.ui.refinement_steps.value()

    @refinement_steps.setter
    def refinement_steps(self, v):
        self.ui.refinement_steps.setValue(v)

    @property
    def background_method(self):
        return self.ui.background_method.currentText()

    @background_method.setter
    def background_method(self, v):
        self.ui.background_method.setCurrentText(v)

    @property
    def chebyshev_polynomial_degree(self):
        return self.ui.chebyshev_polynomial_degree.value()

    @chebyshev_polynomial_degree.setter
    def chebyshev_polynomial_degree(self, v):
        self.ui.chebyshev_polynomial_degree.setValue(v)

    @property
    def background_method_dict(self):
        # This returns the background information in the format that
        # the WPPF classes expect in hexrd.
        method = self.background_method
        if method == 'spline':
            value = None
        elif method == 'chebyshev':
            value = self.chebyshev_polynomial_degree
        else:
            raise Exception(f'Unknown background method: {method}')

        return {method: value}

    @property
    def use_experiment_file(self):
        return self.ui.use_experiment_file.isChecked()

    @use_experiment_file.setter
    def use_experiment_file(self, b):
        self.ui.use_experiment_file.setChecked(b)

    @property
    def experiment_file(self):
        return self.ui.experiment_file.text()

    @experiment_file.setter
    def experiment_file(self, v):
        self.ui.experiment_file.setText(v)

    def load_settings(self):
        settings = HexrdConfig().config['calibration'].get('wppf')
        if not settings:
            return

        blockers = [QSignalBlocker(w) for w in self.all_widgets]  # noqa: F841
        for k, v in settings.items():
            setattr(self, k, v)

    def save_settings(self):
        settings = HexrdConfig().config['calibration'].setdefault('wppf', {})
        keys = [
            'wppf_method',
            'refinement_steps',
            'background_method',
            'chebyshev_polynomial_degree',
            'use_experiment_file',
            'experiment_file',
            'params'
        ]
        for key in keys:
            settings[key] = getattr(self, key)

    def select_experiment_file(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Select Experiment File', HexrdConfig().working_dir,
            'TXT files (*.txt)')

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)
            self.ui.experiment_file.setText(selected_file)

    def reset_table_to_defaults(self):
        self.params = copy.deepcopy(self.default_params)
        self.update_extra_params()
        self.update_table()

    def create_label(self, v):
        w = QTableWidgetItem(v)
        w.setTextAlignment(Qt.AlignCenter)
        return w

    def create_spinbox(self, v):
        sb = ScientificDoubleSpinBox(self.ui.table)
        sb.setKeyboardTracking(False)
        sb.setValue(float(v))
        sb.valueChanged.connect(self.update_params)

        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sb.setSizePolicy(size_policy)
        return sb

    def create_value_spinbox(self, v):
        sb = self.create_spinbox(v)
        self.value_spinboxes.append(sb)
        return sb

    def create_minimum_spinbox(self, v):
        sb = self.create_spinbox(v)
        self.minimum_spinboxes.append(sb)
        return sb

    def create_maximum_spinbox(self, v):
        sb = self.create_spinbox(v)
        self.maximum_spinboxes.append(sb)
        return sb

    def create_vary_checkbox(self, b):
        cb = QCheckBox(self.ui.table)
        cb.setChecked(b)
        cb.toggled.connect(self.update_params)

        self.vary_checkboxes.append(cb)
        return self.create_table_widget(cb)

    def create_table_widget(self, w):
        # These are required to center the widget...
        tw = QWidget(self.ui.table)
        layout = QHBoxLayout(tw)
        layout.addWidget(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return tw

    def update_gui(self):
        self.update_visible_background_parameters()
        self.update_table()

    def clear_table(self):
        self.value_spinboxes.clear()
        self.minimum_spinboxes.clear()
        self.maximum_spinboxes.clear()
        self.vary_checkboxes.clear()
        self.ui.table.clearContents()

    def update_table(self):
        blocker = QSignalBlocker(self.ui.table)  # noqa: F841

        self.clear_table()
        self.ui.table.setRowCount(len(self.params))
        for i, (name, vals) in enumerate(self.params.items()):
            w = self.create_label(name)
            self.ui.table.setItem(i, COLUMNS['name'], w)

            w = self.create_value_spinbox(self.value(name, vals))
            self.ui.table.setCellWidget(i, COLUMNS['value'], w)

            w = self.create_minimum_spinbox(self.minimum(name, vals))
            self.ui.table.setCellWidget(i, COLUMNS['minimum'], w)

            w = self.create_maximum_spinbox(self.maximum(name, vals))
            self.ui.table.setCellWidget(i, COLUMNS['maximum'], w)

            w = self.create_vary_checkbox(self.vary(name, vals))
            self.ui.table.setCellWidget(i, COLUMNS['vary'], w)

    def update_params(self):
        for i, (name, vals) in enumerate(self.params.items()):
            if any(name.endswith(x) for x in LENGTH_SUFFIXES):
                # Convert from angstrom to nm for WPPF
                vals = copy.deepcopy(vals)
                for j in range(3):
                    vals[j] /= 10.0

            vals[0] = self.value_spinboxes[i].value()
            vals[1] = self.minimum_spinboxes[i].value()
            vals[2] = self.maximum_spinboxes[i].value()
            vals[3] = self.vary_checkboxes[i].isChecked()

    @property
    def all_widgets(self):
        names = [
            'wppf_method',
            'refinement_steps',
            'background_method',
            'chebyshev_polynomial_degree',
            'experiment_file',
            'table'
        ]
        return [getattr(self.ui, x) for x in names]

    def convert(self, name, val):
        # Check if we need to convert this data to other units
        if any(name.endswith(x) for x in LENGTH_SUFFIXES):
            # Convert from nm to Angstroms
            return val * 10.0
        return val

    def value(self, name, vals):
        return self.convert(name, vals[0])

    def minimum(self, name, vals):
        return self.convert(name, vals[1])

    def maximum(self, name, vals):
        return self.convert(name, vals[2])

    def vary(self, name, vals):
        return vals[3]

    def create_wppf_params_object(self):
        params = Parameters()
        for name, val in self.params.items():
            kwargs = {
                'name': name,
                'value': float(val[0]),
                'lb': float(val[1]),
                'ub': float(val[2]),
                'vary': bool(val[3])
            }
            params.add(**kwargs)
        return params

    def create_wppf_object(self, add_params=False):
        # If add_params is True, it allows WPPF to add more parameters
        # This is mostly for material lattice parameters

        method = self.wppf_method
        if method == 'LeBail':
            class_type = LeBail
        elif method == 'Rietveld':
            class_type = Rietveld
        else:
            raise Exception(f'Unknown method: {method}')

        if add_params:
            params = self.params
        else:
            params = self.create_wppf_params_object()

        wavelength = {
            'synchrotron': _angstroms(HexrdConfig().beam_wavelength)
        }

        if self.use_experiment_file:
            expt_spectrum = np.loadtxt(self.experiment_file)
        else:
            expt_spectrum = HexrdConfig().last_azimuthal_integral_data
            # Re-format it to match the expected input format
            expt_spectrum = np.array(list(zip(*expt_spectrum)))

        phases = [HexrdConfig().material(x) for x in self.selected_materials]
        kwargs = {
            'expt_spectrum': expt_spectrum,
            'params': params,
            'phases': phases,
            'wavelength': wavelength,
            'bkgmethod': self.background_method_dict
        }

        return class_type(**kwargs)


if __name__ == '__main__':
    from PySide2.QtWidgets import QApplication

    app = QApplication()

    dialog = WppfOptionsDialog()
    dialog.ui.exec_()

    print(f'{dialog.wppf_method=}')
    print(f'{dialog.background_method=}')
    print(f'{dialog.chebyshev_polynomial_degree=}')
    print(f'{dialog.experiment_file=}')
    print(f'{dialog.params=}')
