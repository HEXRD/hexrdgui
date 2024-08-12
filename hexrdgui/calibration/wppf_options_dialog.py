from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QMessageBox, QSizePolicy,
    QTableWidgetItem, QWidget
)

from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict
from hexrd.material import _angstroms
from hexrd.wppf import LeBail, Rietveld
from hexrd.wppf.parameters import Parameter
from hexrd.wppf.WPPF import peakshape_dict
from hexrd.wppf.wppfsupport import (
    background_methods, _generate_default_parameters_LeBail,
    _generate_default_parameters_Rietveld,
)

from hexrdgui.dynamic_widget import DynamicWidget
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.point_picker_dialog import PointPickerDialog
from hexrdgui.scientificspinbox import ScientificDoubleSpinBox
from hexrdgui.select_items_dialog import SelectItemsDialog
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals, clear_layout, has_nan
from hexrdgui.wppf_style_picker import WppfStylePicker


inverted_peakshape_dict = {v: k for k, v in peakshape_dict.items()}

DEFAULT_PEAK_SHAPE = 'pvtch'

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

        self.spline_points = []
        self._wppf_object = None
        self._prev_background_method = None

        self.reset_params()
        self.load_settings()

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.method.currentIndexChanged.connect(self.on_method_changed)
        self.ui.select_materials_button.pressed.connect(self.select_materials)
        self.ui.peak_shape.currentIndexChanged.connect(self.update_params)
        self.ui.background_method.currentIndexChanged.connect(
            self.update_background_parameters)
        self.ui.select_experiment_file_button.pressed.connect(
            self.select_experiment_file)
        self.ui.display_wppf_plot.toggled.connect(
            self.display_wppf_plot_toggled)
        self.ui.edit_plot_style.pressed.connect(self.edit_plot_style)
        self.ui.pick_spline_points.clicked.connect(self.pick_spline_points)

        self.ui.export_table.clicked.connect(self.export_table)
        self.ui.import_table.clicked.connect(self.import_table)
        self.ui.reset_table_to_defaults.clicked.connect(self.reset_params)

        self.ui.save_plot.pressed.connect(self.save_plot)
        self.ui.reset_object.pressed.connect(self.reset_object)
        self.ui.preview_spectrum.pressed.connect(self.preview_spectrum)
        self.ui.run_button.pressed.connect(self.begin_run)
        self.ui.finished.connect(self.finish)

    def on_method_changed(self):
        self.update_params()
        self.update_enable_states()

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
            'limit_tth',
            'limit_tth_hyphen',
            'min_tth',
            'max_tth',
        ]

        for name in requires_object:
            getattr(self.ui, name).setEnabled(has_object)

        for name in requires_no_object:
            getattr(self.ui, name).setEnabled(not has_object)

        enable_tth_limits = not has_object and self.limit_tth
        widget_names = [
            'min_tth',
            'limit_tth_hyphen',
            'max_tth',
        ]
        for name in widget_names:
            getattr(self.ui, name).setEnabled(enable_tth_limits)

        enable_refinement_steps = self.method != 'Rietveld'
        self.ui.refinement_steps.setEnabled(enable_refinement_steps)

    def populate_background_methods(self):
        self.ui.background_method.addItems(list(background_methods.keys()))

    def populate_peakshape_methods(self):
        keys = list(peakshape_dict.keys())
        values = list(peakshape_dict.values())
        self.ui.peak_shape.addItems(values)

        if DEFAULT_PEAK_SHAPE in keys:
            self.ui.peak_shape.setCurrentIndex(keys.index(DEFAULT_PEAK_SHAPE))

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
        two_theta, intensity = obj.spectrum_sim.x, obj.spectrum_sim.y
        data = {
            'two_theta': two_theta,
            'intensity': intensity,
        }

        # Delete the file if it already exists
        if filename.exists():
            filename.unlink()

        # Save as HDF5
        with h5py.File(filename, 'w') as f:
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
            obj.computespectrum()
            x, y = obj.spectrum_sim.x, obj.spectrum_sim.y

            fig, ax = plt.subplots()
            fig.canvas.manager.set_window_title('HEXRD')
            ax.set_xlabel(r'2$\theta$ (deg)')
            ax.set_ylabel(r'intensity')
            ax.set_title('Computed Spectrum')

            ax.plot(x, y)
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
        if self.background_method == 'spline':
            points = self.background_method_dict['spline']
            if not points:
                # Force points to be chosen now
                self.pick_spline_points()

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

        if self.background_method == 'spline':
            points = self.background_method_dict['spline']
            if not points:
                raise Exception('Points must be chosen to use "spline" method')

    def generate_params(self):
        kwargs = {
            'method': self.method,
            'materials': self.materials,
            'peak_shape': self.peak_shape_index,
            'bkgmethod': self.background_method_dict
        }
        return generate_params(**kwargs)

    def reset_params(self):
        self.params = self.generate_params()
        self.update_table()

    def update_params(self):
        if not hasattr(self, 'params'):
            # Params have not been created yet. Nothing to update.
            return

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
        if dialog.exec() and self.selected_materials != dialog.selected_items:
            self.selected_materials = dialog.selected_items
            self.update_params()

    @property
    def powder_overlay_materials(self):
        overlays = [x for x in HexrdConfig().overlays if x.is_powder]
        return list(dict.fromkeys([x.material_name for x in overlays]))

    @property
    def selected_materials(self):
        if not hasattr(self, '_selected_materials'):
            # Choose the visible ones with powder overlays by default
            overlays = HexrdConfig().overlays
            overlays = [x for x in overlays if x.is_powder and x.visible]
            materials = [x.material_name for x in overlays]
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
            # Make sure these are updated
            self.update_background_parameters()
            widgets = self.dynamic_background_widgets

        if not widgets:
            # This background method doesn't have any widgets
            value = [None]
        else:
            value = [x.value() for x in widgets]

        if len(value) == 1:
            value = value[0]

        if method == 'spline':
            # For spline, the value is stored on self
            value = self.spline_points

        return {method: value}

    @background_method_dict.setter
    def background_method_dict(self, v):
        method = list(v)[0]

        self.background_method = method

        # Make sure these get updated (it may have already been called, but
        # calling it twice is not a problem)
        self.update_background_parameters()

        if method == 'spline':
            # Store the spline points on self
            self.spline_points = v[method]
        elif v[method]:
            widgets = self.dynamic_background_widgets
            if len(widgets) == 1:
                widgets[0].set_value(v[method])
            else:
                for w, value in zip(widgets, v[method]):
                    w.set_value(value)

        if method == 'chebyshev':
            # We probably need to update the parameters as well
            self.update_params()

    def pick_spline_points(self):
        if self.background_method != 'spline':
            # Should not be using this method
            return

        # Make a canvas with the spectrum plotted.
        expt_spectrum = self.wppf_object_kwargs['expt_spectrum']
        fig, ax = plt.subplots()
        ax.plot(*expt_spectrum.T, '-k')

        ax.set_xlabel(r'2$\theta$')
        ax.set_ylabel(r'intensity (a.u.)')

        dialog = PointPickerDialog(fig.canvas, 'Pick Background Points',
                                   parent=self.ui)
        if not dialog.exec():
            # User canceled.
            return

        # Make sure these are native types for saving
        self.spline_points = (
            np.asarray([dialog.points]).tolist() if dialog.points else []
        )

        # We must reset the WPPF object to reflect these changes
        self.reset_object()

    @property
    def limit_tth(self):
        return self.ui.limit_tth.isChecked()

    @limit_tth.setter
    def limit_tth(self, v):
        self.ui.limit_tth.setChecked(v)

    @property
    def min_tth(self):
        return self.ui.min_tth.value()

    @min_tth.setter
    def min_tth(self, v):
        self.ui.min_tth.setValue(v)

    @property
    def max_tth(self):
        return self.ui.max_tth.value()

    @max_tth.setter
    def max_tth(self, v):
        self.ui.max_tth.setValue(v)

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

        # Apply these settings first, in order. The other settings
        # can be disorded.
        apply_first_keys = [
            # background_method should no longer be in the settings, as it
            # was replaced by background_method_dict, but just in case it is...
            'background_method',
            'background_method_dict',
        ]

        with block_signals(*self.all_widgets):
            for k in apply_first_keys:
                if k in settings:
                    setattr(self, k, settings[k])

            for k, v in settings.items():
                if k == 'params' and isinstance(v, dict):
                    # The older WPPF dialog used a dict. Skip this
                    # as it is no longer compatible.
                    continue

                if not hasattr(self, k) or k in apply_first_keys:
                    # Skip it...
                    continue

                setattr(self, k, v)

        # Add/remove params depending on what are allowed
        self.update_params()
        self.update_enable_states()

    def save_settings(self):
        settings = HexrdConfig().config['calibration'].setdefault('wppf', {})
        keys = [
            'method',
            'refinement_steps',
            'peak_shape',
            'background_method_dict',
            'use_experiment_file',
            'experiment_file',
            'display_wppf_plot',
            'params_dict',
            'limit_tth',
            'min_tth',
            'max_tth',
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
        dialog.ui.exec()

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
        cb.toggled.connect(self.on_checkbox_toggled)

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
        if self.background_method == self._prev_background_method:
            # The method did not change. Just return.
            return

        self._prev_background_method = self.background_method

        # Update the visibility of this button
        self.ui.pick_spline_points.setVisible(
            self.background_method == 'spline')

        main_layout = self.ui.background_method_parameters_layout
        clear_layout(main_layout)
        self.dynamic_background_widgets.clear()
        descriptions = background_methods[self.background_method]
        if not descriptions:
            # Nothing more to do
            self.update_params()
            return

        for d in descriptions:
            layout = QHBoxLayout()
            main_layout.addLayout(layout)

            w = DynamicWidget(d, self.ui)
            if w.label is not None:
                # Add the label
                layout.addWidget(w.label)

            if w.widget is not None:
                layout.addWidget(w.widget)

            if self.background_method == 'chebyshev':
                # We need to update parameters when the chebyshev options
                # are modified.
                w.value_changed.connect(self.update_params)

            self.dynamic_background_widgets.append(w)

        # We may need to update the parameters as well, since some background
        # methods have parameters.
        self.update_params()

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
                w.setEnabled(param.vary)
                table.setCellWidget(i, COLUMNS['minimum'], w)

                w = self.create_maximum_spinbox(self.convert(name, param.ub))
                w.setEnabled(param.vary)
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

    def on_checkbox_toggled(self):
        self.update_min_max_enable_states()
        self.update_config()

    def update_min_max_enable_states(self):
        for i in range(len(self.params.param_dict)):
            enable = self.vary_checkboxes[i].isChecked()
            self.minimum_spinboxes[i].setEnabled(enable)
            self.maximum_spinboxes[i].setEnabled(enable)

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
            x, y = HexrdConfig().last_unscaled_azimuthal_integral_data
            if isinstance(y, np.ma.MaskedArray):
                # Fill any masked values with nan
                y = y.filled(np.nan)

            # Re-format it to match the expected input format
            expt_spectrum = np.array(list(zip(x, y)))

        if has_nan(expt_spectrum):
            # Store as masked array
            kwargs = {
                'data': expt_spectrum,
                'mask': np.isnan(expt_spectrum),
                'fill_value': 0.,
            }
            expt_spectrum = np.ma.masked_array(**kwargs)

        if self.limit_tth:
            expt_spectrum = expt_spectrum[expt_spectrum[:, 0] >= self.min_tth]
            expt_spectrum = expt_spectrum[expt_spectrum[:, 0] <= self.max_tth]

        if expt_spectrum.size == 0:
            msg = 'Spectrum is empty.'
            if self.limit_tth:
                msg += '\nCheck min and max two theta.'

            QMessageBox.critical(self.ui, 'HEXRD', msg)
            raise Exception(msg)

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

    def export_table(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export Table', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return self.export_params(selected_file)

    def export_params(self, filename):
        filename = Path(filename)
        if filename.exists():
            filename.unlink()

        param_dict = self.params.param_dict
        export_data = {k: param_to_dict(v) for k, v in param_dict.items()}

        with h5py.File(filename, 'w') as wf:
            unwrap_dict_to_h5(wf, export_data)

    def import_table(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Import Table', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return self.import_params(selected_file)

    def import_params(self, filename):
        filename = Path(filename)
        if not filename.exists():
            raise FileNotFoundError(filename)

        import_params = {}
        with h5py.File(filename, 'r') as rf:
            unwrap_h5_to_dict(rf, import_params)

        # No exception means we are valid
        self.validate_import_params(import_params, filename)

        # Unfortunately, hexrd.wppf.parameters.Parameter will not accept
        # np.bool_ types for Parameter.vary, only native booleans. Let's
        # do this conversion.
        def to_native_bools(d):
            for k, v in d.items():
                if isinstance(v, dict):
                    to_native_bools(v)
                elif isinstance(v, np.bool_):
                    d[k] = v.item()

        to_native_bools(import_params)

        # Keep the ordering the same as the GUI currently has
        for key in self.params.param_dict.keys():
            self.params[key] = dict_to_param(import_params[key])

        self.update_table()

    def validate_import_params(self, import_params, filename):
        here = self.params.param_dict.keys()
        there = import_params.keys()
        extra = list(set(there) - set(here))
        missing = list(set(here) - set(there))

        if extra or missing:
            msg = (f'Parameters in {filename} do not match current WPPF '
                   'parameters internally. Please ensure the same settings '
                   'are being used')

            if missing:
                missing_str = ', '.join([f'"{x}"' for x in missing])
                msg += f'\n\nMissing keys: {missing_str}'

            if extra:
                extra_str = ', '.join([f'"{x}"' for x in extra])
                msg += f'\n\nExtra keys: {extra_str}'

            QMessageBox.critical(self.ui, 'HEXRD', msg)
            raise Exception(msg)

        req_keys = ['name', 'value', 'lb', 'ub', 'vary']
        missing_reqs = []
        for key, entry in import_params.items():
            if any(x not in entry for x in req_keys):
                missing_reqs.append(key)

        if missing_reqs:
            missing_reqs_str = ', '.join([f'"{x}"' for x in missing_reqs])
            msg = f'{filename} contains parameters that are missing keys\n\n'
            msg += f'Parameters missing required keys: {missing_reqs_str}'

            QMessageBox.critical(self.ui, 'HEXRD', msg)
            raise Exception(msg)


def generate_params(method, materials, peak_shape, bkgmethod):
    func_dict = {
        'LeBail': _generate_default_parameters_LeBail,
        'Rietveld': _generate_default_parameters_Rietveld,
    }
    if method not in func_dict:
        raise Exception(f'Unknown method: {method}')

    return func_dict[method](materials, peak_shape, bkgmethod)


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
    from PySide6.QtWidgets import QApplication

    app = QApplication()

    dialog = WppfOptionsDialog()
    dialog.ui.exec()

    print(f'{dialog.method=}')
    print(f'{dialog.background_method=}')
    print(f'{dialog.experiment_file=}')
    print(f'{dialog.params=}')
