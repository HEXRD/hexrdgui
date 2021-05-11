from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np

from PySide2.QtCore import Qt, QObject, QTimer, Signal
from PySide2.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QMessageBox, QSizePolicy,
    QTableWidgetItem, QWidget
)

from hexrd.material import _angstroms
from hexrd.wppf import LeBail, Rietveld
from hexrd.wppf.parameters import Parameter
from hexrd.wppf.WPPF import peakshape_dict
from hexrd.wppf.wppfsupport import (
    background_methods, _generate_default_parameters_LeBail,
    _generate_default_parameters_Rietveld,
)

from hexrd.ui.constants import OverlayType
from hexrd.ui.dynamic_widget import DynamicWidget
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox
from hexrd.ui.select_items_dialog import SelectItemsDialog
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals, clear_layout, has_nan
from hexrd.ui.wppf_style_picker import WppfStylePicker


inverted_peakshape_dict = {v: k for k, v in peakshape_dict.items()}

COLUMNS = {
    'name': 0,
    'value': 1,
    'minimum': 2,
    'maximum': 3,
    'vary': 4
}

LENGTH_SUFFIXES = ['_a', '_b', '_c']


class WppfOptionsDialog(QObject):

    run = Signal()
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('wppf_options_dialog.ui', parent)
        self.ui.setWindowTitle('WPPF Options Dialog')

        self.populate_background_methods()
        self.populate_peakshape_methods()

        self.value_spinboxes = []
        self.minimum_spinboxes = []
        self.maximum_spinboxes = []
        self.vary_checkboxes = []

        self.dynamic_background_widgets = []

        self._wppf_object = None

        self.reset_params()
        self.load_settings()

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.method.currentIndexChanged.connect(self.update_params)
        self.ui.select_materials_button.pressed.connect(self.select_materials)
        self.ui.peak_shape.currentIndexChanged.connect(self.update_params)
        self.ui.background_method.currentIndexChanged.connect(
            self.update_background_parameters)
        self.ui.select_experiment_file_button.pressed.connect(
            self.select_experiment_file)
        self.ui.reset_table_to_defaults.pressed.connect(self.reset_params)
        self.ui.display_wppf_plot.toggled.connect(
            self.display_wppf_plot_toggled)
        self.ui.edit_plot_style.pressed.connect(self.edit_plot_style)

        self.ui.save_plot.pressed.connect(self.save_plot)
        self.ui.reset_object.pressed.connect(self.reset_object)
        self.ui.preview_spectrum.pressed.connect(self.preview_spectrum)
        self.ui.run_button.pressed.connect(self.begin_run)
        self.ui.finished.connect(self.finish)

    def update_enable_states(self):
        has_object = self._wppf_object is not None

        requires_object = [
            'reset_object',
            'save_plot',
        ]

        requires_no_object = [
            'method',
            'method_label',
            'use_experiment_file',
            'experiment_file',
            'select_experiment_file_button',
        ]

        for name in requires_object:
            getattr(self.ui, name).setEnabled(has_object)

        for name in requires_no_object:
            getattr(self.ui, name).setEnabled(not has_object)

    def populate_background_methods(self):
        self.ui.background_method.addItems(list(background_methods.keys()))

    def populate_peakshape_methods(self):
        self.ui.peak_shape.addItems(list(peakshape_dict.values()))

    def save_plot(self):
        obj = self._wppf_object
        if obj is None:
            raise Exception('No WPPF object!')

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Data', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return self.write_data(selected_file)

    def write_data(self, filename):
        filename = Path(filename)

        obj = self._wppf_object
        if obj is None:
            raise Exception('No WPPF object!')

        # Prepare the data to write out
        two_theta, intensity = obj.spectrum_sim.data
        data = {
            'two_theta': two_theta,
            'intensity': intensity,
        }

        # Delete the file if it already exists
        if filename.exists():
            filename.unlink()

        # Save as HDF5
        f = h5py.File(filename, 'w')
        for key, value in data.items():
            f.create_dataset(key, data=value)

        # Save parameters as well
        to_save = ('value',)
        params_group = f.create_group('params')
        for name, param in self.params.param_dict.items():
            group = params_group.create_group(name)
            for item in to_save:
                group.create_dataset(item, data=getattr(param, item))

    def reset_object(self):
        self._wppf_object = None
        self.update_enable_states()

    def preview_spectrum(self):
        had_object = self._wppf_object is not None

        obj = self.wppf_object
        try:
            tth = obj.tth_list
            spectrum = obj.computespectrum()

            fig, ax = plt.subplots()
            ax.set_xlabel(r'2$\theta$ (deg)')
            ax.set_ylabel(r'intensity')
            fig.canvas.set_window_title('HEXRD')
            ax.set_title('Computed Spectrum')

            ax.plot(tth, spectrum)
            ax.relim()
            ax.autoscale_view()
            ax.axis('auto')
            fig.tight_layout()

            fig.canvas.draw_idle()
            fig.show()
        finally:
            if not had_object:
                self.reset_object()

    def begin_run(self):
        try:
            self.validate()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            return

        self.save_settings()
        self.run.emit()

    def finish(self):
        self.finished.emit()

    def validate(self):
        use_experiment_file = self.use_experiment_file
        if use_experiment_file and not Path(self.experiment_file).exists():
            raise Exception(f'Experiment file, {self.experiment_file}, '
                            'does not exist')

        if not any(x.vary for x in self.params.param_dict.values()):
            msg = 'All parameters are fixed. Need to vary at least one'
            raise Exception(msg)

    def generate_params(self):
        kwargs = {
            'method': self.method,
            'materials': self.materials,
            'peak_shape': self.peak_shape_index,
        }
        return generate_params(**kwargs)

    def reset_params(self):
        self.params = self.generate_params()
        self.update_table()

    def update_params(self):
        params = self.generate_params()

        # Remake the dict to use the ordering of `params`
        param_dict = {}
        for key, param in params.param_dict.items():
            if key in self.params:
                # Preserve previous settings
                param = self.params[key]
            param_dict[key] = param

        self.params.param_dict = param_dict
        self.update_table()

    def show(self):
        self.ui.show()

    def select_materials(self):
        materials = self.powder_overlay_materials
        selected = self.selected_materials
        items = [(name, name in selected) for name in materials]
        dialog = SelectItemsDialog(items, self.ui)
        if dialog.exec_() and self.selected_materials != dialog.selected_items:
            self.selected_materials = dialog.selected_items
            self.update_params()

    @property
    def powder_overlay_materials(self):
        overlays = HexrdConfig().overlays
        overlays = [x for x in overlays if x['type'] == OverlayType.powder]
        return list(dict.fromkeys([x['material'] for x in overlays]))

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
    def materials(self):
        return [HexrdConfig().material(x) for x in self.selected_materials]

    @property
    def method(self):
        return self.ui.method.currentText()

    @method.setter
    def method(self, v):
        self.ui.method.setCurrentText(v)

    @property
    def refinement_steps(self):
        return self.ui.refinement_steps.value()

    @refinement_steps.setter
    def refinement_steps(self, v):
        self.ui.refinement_steps.setValue(v)

    @property
    def peak_shape(self):
        text = self.ui.peak_shape.currentText()
        return inverted_peakshape_dict[text]

    @peak_shape.setter
    def peak_shape(self, v):
        label = peakshape_dict[v]
        self.ui.peak_shape.setCurrentText(label)

    @property
    def peak_shape_index(self):
        return self.ui.peak_shape.currentIndex()

    @peak_shape_index.setter
    def peak_shape_index(self, v):
        self.ui.peak_shape.setCurrentIndex(v)

    @property
    def background_method(self):
        return self.ui.background_method.currentText()

    @background_method.setter
    def background_method(self, v):
        self.ui.background_method.setCurrentText(v)

    @property
    def background_method_dict(self):
        # This returns the background information in the format that
        # the WPPF classes expect in hexrd.
        method = self.background_method
        widgets = self.dynamic_background_widgets
        if not widgets:
            value = None
        elif len(widgets) == 1:
            value = widgets[0].value()
        else:
            value = [x.value() for x in widgets]

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

    @property
    def display_wppf_plot(self):
        return self.ui.display_wppf_plot.isChecked()

    @display_wppf_plot.setter
    def display_wppf_plot(self, v):
        self.ui.display_wppf_plot.setChecked(v)

    @property
    def params_dict(self):
        ret = {}
        for key, param in self.params.param_dict.items():
            ret[key] = param_to_dict(param)

        return ret

    @params_dict.setter
    def params_dict(self, v):
        for key, val in v.items():
            if key not in self.params:
                continue

            self.params[key] = dict_to_param(val)

    def load_settings(self):
        settings = HexrdConfig().config['calibration'].get('wppf')
        if not settings:
            return

        with block_signals(*self.all_widgets):
            for k, v in settings.items():
                if k == 'params' and isinstance(v, dict):
                    # The older WPPF dialog used a dict. Skip this
                    # as it is no longer compatible.
                    continue

                if not hasattr(self, k):
                    # Skip it...
                    continue

                setattr(self, k, v)

        # Add/remove params depending on what are allowed
        self.update_params()

    def save_settings(self):
        settings = HexrdConfig().config['calibration'].setdefault('wppf', {})
        keys = [
            'method',
            'refinement_steps',
            'peak_shape',
            'background_method',
            'use_experiment_file',
            'experiment_file',
            'display_wppf_plot',
            'params_dict',
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

    def display_wppf_plot_toggled(self):
        HexrdConfig().display_wppf_plot = self.display_wppf_plot

    def edit_plot_style(self):
        dialog = WppfStylePicker(self.ui)
        dialog.ui.exec_()

    def create_label(self, v):
        w = QTableWidgetItem(v)
        w.setTextAlignment(Qt.AlignCenter)
        return w

    def create_spinbox(self, v):
        sb = ScientificDoubleSpinBox(self.ui.table)
        sb.setKeyboardTracking(False)
        sb.setValue(float(v))
        sb.valueChanged.connect(self.update_config)

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
        cb.toggled.connect(self.update_config)

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
        with block_signals(self.ui.display_wppf_plot):
            self.display_wppf_plot = HexrdConfig().display_wppf_plot
            self.update_background_parameters()
            self.update_table()

    def update_background_parameters(self):
        main_layout = self.ui.background_method_parameters_layout
        clear_layout(main_layout)
        self.dynamic_background_widgets.clear()
        descriptions = background_methods[self.background_method]
        if not descriptions:
            # Nothing more to do
            return

        for d in descriptions:
            layout = QHBoxLayout()
            main_layout.addLayout(layout)

            w = DynamicWidget(d)
            if w.label is not None:
                # Add the label
                layout.addWidget(w.label)

            if w.widget is not None:
                layout.addWidget(w.widget)

            self.dynamic_background_widgets.append(w)

    def clear_table(self):
        self.value_spinboxes.clear()
        self.minimum_spinboxes.clear()
        self.maximum_spinboxes.clear()
        self.vary_checkboxes.clear()
        self.ui.table.clearContents()

    def update_table(self):
        table = self.ui.table

        # Keep the same scroll position
        scrollbar = table.verticalScrollBar()
        scroll_value = scrollbar.value()

        with block_signals(table):
            self.clear_table()
            self.ui.table.setRowCount(len(self.params.param_dict))
            for i, (key, param) in enumerate(self.params.param_dict.items()):
                name = param.name
                w = self.create_label(name)
                table.setItem(i, COLUMNS['name'], w)

                w = self.create_value_spinbox(self.convert(name, param.value))
                table.setCellWidget(i, COLUMNS['value'], w)

                w = self.create_minimum_spinbox(self.convert(name, param.lb))
                table.setCellWidget(i, COLUMNS['minimum'], w)

                w = self.create_maximum_spinbox(self.convert(name, param.ub))
                table.setCellWidget(i, COLUMNS['maximum'], w)

                w = self.create_vary_checkbox(param.vary)
                table.setCellWidget(i, COLUMNS['vary'], w)

        # During event processing, it looks like the scrollbar gets resized
        # so its maximum is one less than one it actually is. Thus, if we
        # set the value to the maximum right now, it will end up being one
        # less than the actual maximum.
        # Thus, we need to post an event to the event loop to set the
        # scroll value after the other event processing. This works, but
        # the UI still scrolls back one and then to the maximum. So it
        # doesn't look that great. FIXME: figure out how to fix this.
        QTimer.singleShot(0, lambda: scrollbar.setValue(scroll_value))

    def update_config(self):
        for i, (name, param) in enumerate(self.params.param_dict.items()):
            if any(name.endswith(x) for x in LENGTH_SUFFIXES):
                # Convert from angstrom to nm for WPPF
                multiplier = 0.1
            else:
                multiplier = 1

            param.value = self.value_spinboxes[i].value() * multiplier
            param.lb = self.minimum_spinboxes[i].value() * multiplier
            param.ub = self.maximum_spinboxes[i].value() * multiplier
            param.vary = self.vary_checkboxes[i].isChecked()

    @property
    def all_widgets(self):
        names = [
            'method',
            'refinement_steps',
            'peak_shape',
            'background_method',
            'experiment_file',
            'table',
            'display_wppf_plot',
        ]
        return [getattr(self.ui, x) for x in names]

    def convert(self, name, val):
        # Check if we need to convert this data to other units
        if any(name.endswith(x) for x in LENGTH_SUFFIXES):
            # Convert from nm to Angstroms
            return val * 10.0
        return val

    @property
    def wppf_object(self):
        if self._wppf_object is None:
            self._wppf_object = self.create_wppf_object()
            self.update_enable_states()
        else:
            self.update_wppf_object()

        return self._wppf_object

    def create_wppf_object(self):
        class_types = {
            'LeBail': LeBail,
            'Rietveld': Rietveld,
        }

        if self.method not in class_types:
            raise Exception(f'Unknown method: {self.method}')

        class_type = class_types[self.method]
        return class_type(**self.wppf_object_kwargs)

    @property
    def wppf_object_kwargs(self):
        wavelength = {
            'synchrotron': [_angstroms(
                HexrdConfig().beam_wavelength), 1.0]
        }

        if self.use_experiment_file:
            expt_spectrum = np.loadtxt(self.experiment_file)
        else:
            expt_spectrum = HexrdConfig().last_azimuthal_integral_data
            # Re-format it to match the expected input format
            expt_spectrum = np.array(list(zip(*expt_spectrum)))

        if has_nan(expt_spectrum):
            # Store as masked array
            kwargs = {
                'data': expt_spectrum,
                'mask': np.isnan(expt_spectrum),
                'fill_value': 0.,
            }
            expt_spectrum = np.ma.masked_array(**kwargs)

        return {
            'expt_spectrum': expt_spectrum,
            'params': self.params,
            'phases': self.materials,
            'wavelength': wavelength,
            'bkgmethod': self.background_method_dict,
            'peakshape': self.peak_shape,
        }

    def update_wppf_object(self):
        obj = self._wppf_object
        kwargs = self.wppf_object_kwargs

        skip_list = ['expt_spectrum']

        for key, val in kwargs.items():
            if key in skip_list:
                continue

            if not hasattr(obj, key):
                raise Exception(f'{obj} does not have attribute: {key}')

            setattr(obj, key, val)


def generate_params(method, materials, peak_shape):
    func_dict = {
        'LeBail': _generate_default_parameters_LeBail,
        'Rietveld': _generate_default_parameters_Rietveld,
    }
    if method not in func_dict:
        raise Exception(f'Unknown method: {method}')

    return func_dict[method](materials, peak_shape)


def param_to_dict(param):
    return {
        'name': param.name,
        'value': param.value,
        'lb': param.lb,
        'ub': param.ub,
        'vary': param.vary,
    }


def dict_to_param(d):
    return Parameter(**d)


if __name__ == '__main__':
    from PySide2.QtWidgets import QApplication

    app = QApplication()

    dialog = WppfOptionsDialog()
    dialog.ui.exec_()

    print(f'{dialog.method=}')
    print(f'{dialog.background_method=}')
    print(f'{dialog.experiment_file=}')
    print(f'{dialog.params=}')
