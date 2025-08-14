import copy
from pathlib import Path

import h5py
import lmfit
import matplotlib.pyplot as plt
import numpy as np
import re
import yaml

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QWidget

from hexrdgui import resource_loader
from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict
from hexrd.material import _angstroms
from hexrd.wppf import LeBail, Rietveld
from hexrd.wppf.amorphous import AMORPHOUS_MODEL_TYPES, Amorphous
from hexrd.wppf.WPPF import peakshape_dict
from hexrd.wppf.wppfsupport import (
    background_methods, _generate_default_parameters_LeBail,
    _generate_default_parameters_Rietveld,
)

from hexrdgui.calibration.tree_item_models import (
    _tree_columns_to_indices,
    DefaultCalibrationTreeItemModel,
    DeltaCalibrationTreeItemModel,
)
from hexrdgui.dynamic_widget import DynamicWidget
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.point_picker_dialog import PointPickerDialog
from hexrdgui.select_items_dialog import SelectItemsDialog
from hexrdgui.tree_views.multi_column_dict_tree_view import (
    MultiColumnDictTreeView
)
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals, clear_layout, has_nan
from hexrdgui.wppf_style_picker import WppfStylePicker
import hexrdgui.resources.wppf.tree_views as tree_view_resources


inverted_peakshape_dict = {v: k for k, v in peakshape_dict.items()}

DEFAULT_PEAK_SHAPE = 'pvtch'


class WppfOptionsDialog(QObject):

    run = Signal()
    undo_clicked = Signal()
    object_reset = Signal()
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('wppf_options_dialog.ui', parent)
        self.ui.setWindowTitle('WPPF Options Dialog')

        self.populate_background_methods()
        self.populate_peakshape_methods()
        self.populate_amorphous_options()

        self.dynamic_background_widgets = []

        self.spline_points = []
        self._wppf_object = None
        self._prev_background_method = None
        self._undo_stack = []

        self.amorphous_experiment_files = []

        self.params = self.generate_params()
        self.initialize_tree_view()

        self.load_settings()

        # Default setting for delta boundaries
        self.delta_boundaries = False

        # Trigger logic for changing amorphous setting
        self.on_include_amorphous_toggled()

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.method.currentIndexChanged.connect(self.on_method_changed)
        self.ui.select_materials_button.pressed.connect(self.select_materials)
        self.ui.peak_shape.currentIndexChanged.connect(self.update_params)
        self.ui.delta_boundaries.toggled.connect(
            self.on_delta_boundaries_toggled)
        self.ui.select_experiment_file_button.pressed.connect(
            self.select_experiment_file)

        self.ui.background_method.currentIndexChanged.connect(
            self.update_background_parameters)

        self.ui.display_wppf_plot.toggled.connect(
            self.display_wppf_plot_toggled)
        self.ui.plot_background.toggled.connect(self.plot_background_toggled)
        self.ui.plot_amorphous.toggled.connect(self.plot_amorphous_toggled)
        self.ui.edit_plot_style.pressed.connect(self.edit_plot_style)
        self.ui.pick_spline_points.clicked.connect(self.pick_spline_points)
        self.ui.show_difference_curve.toggled.connect(
            self.on_show_difference_curve_toggled)
        self.ui.show_difference_as_percent.toggled.connect(
            self.on_show_difference_as_percent_toggled)

        self.ui.include_amorphous.toggled.connect(
            self.on_include_amorphous_toggled)
        self.ui.amorphous_model.currentIndexChanged.connect(
            self.on_amorphous_model_changed)
        self.ui.num_amorphous_peaks.valueChanged.connect(
            self.on_num_amorphous_peaks_value_changed)
        self.ui.amorphous_select_experiment_files.clicked.connect(
            self.select_amorphous_experiment_files)

        self.ui.export_params.clicked.connect(self.export_params)
        self.ui.import_params.clicked.connect(self.import_params)
        self.ui.reset_params_to_defaults.clicked.connect(self.reset_params)
        self.ui.undo_last_run.clicked.connect(self.pop_undo_stack)

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
            'include_amorphous',
            'amorphous_model',
            'amorphous_model_label',
            'num_amorphous_peaks',
            'num_amorphous_peaks_label',
            'amorphous_select_experiment_files',
            'amorphous_expt_smoothing',
            'amorphous_expt_smoothing_label',
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
        if not enable_refinement_steps:
            # Also set the value to 1
            self.ui.refinement_steps.setValue(1)

        self.ui.show_difference_as_percent.setVisible(
            self.show_difference_curve)

    def populate_background_methods(self):
        self.ui.background_method.addItems(list(background_methods.keys()))

    def populate_peakshape_methods(self):
        keys = list(peakshape_dict.keys())
        values = list(peakshape_dict.values())
        self.ui.peak_shape.addItems(values)

        if DEFAULT_PEAK_SHAPE in keys:
            self.ui.peak_shape.setCurrentIndex(keys.index(DEFAULT_PEAK_SHAPE))

    def populate_amorphous_options(self):
        w = self.ui.amorphous_model
        prev = w.currentText()
        all_labels = list(AMORPHOUS_MODEL_TYPES)

        with block_signals(w):
            w.clear()
            for label in all_labels:
                w.addItem(label)

            if prev in all_labels:
                w.setCurrentIndex(all_labels.index(prev))

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

        last_lineout = HexrdConfig().last_unscaled_azimuthal_integral_data
        lineout_intensity = last_lineout[1].filled(np.nan)

        # Prepare the data to write out
        two_theta, intensity = obj.spectrum_sim.x, obj.spectrum_sim.y
        data = {
            'two_theta': two_theta,
            'intensity': intensity,
            'lineout_intensity': lineout_intensity,
            'difference_curve': intensity - lineout_intensity,
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
            for name, param in self.params.items():
                group = params_group.create_group(name)
                for item in to_save:
                    group.create_dataset(item, data=getattr(param, item))

    def reset_object(self):
        self._wppf_object = None
        self.update_enable_states()
        self.update_degree_of_crystallinity()
        self.object_reset.emit()

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

        # Pick experiment files for amorphous if needed
        if self.include_amorphous and self.amorphous_model_is_experimental:
            files = self.amorphous_experiment_files
            if (
                len(files) < self.num_amorphous_peaks or
                any(not x for x in files)
            ):
                self.select_amorphous_experiment_files()

        try:
            self.validate()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            return

        if self.delta_boundaries:
            # If delta boundaries are being used, set the min/max according to
            # the delta boundaries. Lmfit requires min/max to run.
            self.apply_delta_boundaries()

        self.save_settings()
        self.push_undo_stack()
        self.run.emit()

    def finish(self):
        self.finished.emit()

    def validate(self):
        use_experiment_file = self.use_experiment_file
        if use_experiment_file and not Path(self.experiment_file).exists():
            raise Exception(f'Experiment file, {self.experiment_file}, '
                            'does not exist')

        if not any(x.vary for x in self.params.values()):
            msg = 'All parameters are fixed. Need to vary at least one'
            raise Exception(msg)

        if self.background_method == 'spline':
            points = self.background_method_dict['spline']
            if not points:
                raise Exception('Points must be chosen to use "spline" method')

        if self.include_amorphous and self.amorphous_model_is_experimental:
            num_amorphous = self.num_amorphous_peaks
            if len(self.amorphous_experiment_files) < num_amorphous:
                msg = (
                    'Experiment files must be selected to use the '
                    'amorphous model: "Experimental"'
                )
                raise Exception(msg)

            for i in range(num_amorphous):
                path = self.amorphous_experiment_files[i]
                try:
                    np.loadtxt(path)
                except Exception as e:
                    msg = f'Failed to load amorphous experiment file: {e}'
                    raise Exception(msg)

    def generate_params(self):
        kwargs = {
            'method': self.method,
            'materials': self.materials,
            'peak_shape': self.peak_shape_index,
            'bkgmethod': self.background_method_dict,
            'amorphous_model': None,
        }
        if self.include_amorphous:
            kwargs['amorphous_model'] = Amorphous(
                [],
                **self.amorphous_kwargs,
            )

        return generate_params(**kwargs)

    def reset_params(self):
        self.params = self.generate_params()
        self.update_tree_view()

    def update_params(self):
        if not hasattr(self, 'params'):
            # Params have not been created yet. Nothing to update.
            return

        params = self.generate_params()

        # Remake the dict to use the ordering of `params`
        for key, param in params.items():
            if key in self.params:
                # Preserve previous settings
                param = self.params[key]
            params[key] = param

        self.params = params
        self.update_tree_view()

    def show(self):
        self.ui.show()

    def select_materials(self):
        materials = self.powder_overlay_materials
        selected = self.selected_materials
        items = [(name, name in selected) for name in materials]
        dialog = SelectItemsDialog(items, 'Select Materials', self.ui)
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
    def peak_shape_tree_dict(self):
        filename = f'peak_{self.peak_shape}.yml'
        return load_yaml_dict(tree_view_resources, filename)

    @property
    def background_tree_dict(self):
        filename = f'background_{self.background_method}.yml'
        return load_yaml_dict(tree_view_resources, filename)

    @property
    def method_tree_dict(self):
        filename = f'{self.method}.yml'
        return load_yaml_dict(tree_view_resources, filename)

    @property
    def amorphous_tree_dict(self):
        filename = 'amorphous.yml'
        return load_yaml_dict(tree_view_resources, filename)

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

    @property
    def include_amorphous(self) -> bool:
        return self.ui.include_amorphous.isChecked()

    @include_amorphous.setter
    def include_amorphous(self, b: bool):
        self.ui.include_amorphous.setChecked(b)

    @property
    def amorphous_model(self) -> str:
        return self.ui.amorphous_model.currentText()

    @amorphous_model.setter
    def amorphous_model(self, v: str):
        self.ui.amorphous_model.setCurrentText(v)

    @property
    def amorphous_model_is_experimental(self) -> bool:
        return self.amorphous_model == 'Experimental'

    @property
    def num_amorphous_peaks(self) -> int:
        return self.ui.num_amorphous_peaks.value()

    @num_amorphous_peaks.setter
    def num_amorphous_peaks(self, v: int):
        self.ui.num_amorphous_peaks.setValue(v)

    @property
    def amorphous_peak_names(self) -> list[str]:
        return [f'peak_{i + 1}' for i in range(self.num_amorphous_peaks)]

    @property
    def amorphous_expt_smoothing(self) -> int:
        return self.ui.amorphous_expt_smoothing.value()

    @amorphous_expt_smoothing.setter
    def amorphous_expt_smoothing(self, v: int):
        self.ui.amorphous_expt_smoothing.setValue(v)

    @property
    def amorphous_kwargs(self) -> dict | None:
        if not self.include_amorphous:
            return None

        # Each amorphous phase will contain these defaults
        key_names = self.amorphous_peak_names
        defaults = {
            'scale': 1.,
            'shift': 0.,
            'center': 30.,
        }

        model_type = AMORPHOUS_MODEL_TYPES[self.amorphous_model]
        if model_type == 'split_pv':
            defaults['fwhm'] = np.array([5, 5, 5, 5])
        else:
            defaults['fwhm'] = np.array([5, 5])

        # Set the amorphous model type to return.
        kwargs = {
            'model_type': AMORPHOUS_MODEL_TYPES[self.amorphous_model],
        }

        # Set the defaults for every amorphous phase.
        for name, default_value in defaults.items():
            # Make a deep copy of the defaults.
            kwargs[name] = {k: copy.deepcopy(default_value) for k in key_names}

        # Space out the default centers to be 25 between them
        for i, k in enumerate(key_names):
            kwargs['center'][k] += (i * 25)

        if self.amorphous_model_is_experimental:
            kwargs['model_data'] = {
                key: np.loadtxt(path) for key, path in
                zip(key_names, self.amorphous_experiment_files)
            }
            kwargs['smoothing'] = self.amorphous_expt_smoothing

        return kwargs

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
    def plot_background(self) -> bool:
        return self.ui.plot_background.isChecked()

    @plot_background.setter
    def plot_background(self, b: bool):
        self.ui.plot_background.setChecked(b)

    @property
    def plot_amorphous(self) -> bool:
        return self.ui.plot_amorphous.isChecked()

    @plot_amorphous.setter
    def plot_amorphous(self, b: bool):
        self.ui.plot_amorphous.setChecked(b)

    @property
    def params_dict(self):
        ret = {}
        for key, param in self.params.items():
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

                if k == 'params_dict':
                    # For backward-compatibility
                    for d in v.values():
                        if 'lb' in d:
                            d['min'] = d.pop('lb')

                        if 'ub' in d:
                            d['max'] = d.pop('ub')

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
            'plot_background',
            'plot_amorphous',
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

    def plot_background_toggled(self):
        HexrdConfig().display_wppf_background = self.plot_background

    def plot_amorphous_toggled(self):
        HexrdConfig().display_wppf_amorphous = self.plot_amorphous

    def edit_plot_style(self):
        dialog = WppfStylePicker(
            amorphous_visible=self.include_amorphous,
            parent=self.ui,
        )
        dialog.exec()

    def update_gui(self):
        to_block = [
            self.ui.display_wppf_plot,
            self.ui.plot_background,
            self.ui.plot_amorphous,
            self.ui.show_difference_curve,
            self.ui.show_difference_as_percent,
        ]
        with block_signals(*to_block):
            self.display_wppf_plot = HexrdConfig().display_wppf_plot
            self.plot_background = HexrdConfig().display_wppf_background
            self.plot_amorphous = HexrdConfig().display_wppf_amorphous

            self.show_difference_curve = (
                HexrdConfig().show_wppf_difference_axis
            )
            self.show_difference_as_percent = (
                HexrdConfig().show_wppf_difference_as_percent
            )

            self.update_background_parameters()
            self.update_tree_view()

        self.update_enable_states()

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

    def on_include_amorphous_toggled(self):
        b = self.include_amorphous

        # Update visibility of amorphous options
        layout = self.ui.amorphous_options_layout
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w is not None:
                w.setVisible(b)

        self.ui.degree_of_crystallinity_label.setVisible(b)

        self.ui.plot_amorphous.setEnabled(b)
        self.on_amorphous_model_changed()

    def on_num_amorphous_peaks_value_changed(self):
        is_experiment = (
            self.include_amorphous and self.amorphous_model_is_experimental
        )
        files = self.amorphous_experiment_files
        if is_experiment:
            # Trim off extra experiment files
            while len(files) > self.num_amorphous_peaks:
                files.pop()

        self.on_amorphous_model_changed()

    def on_amorphous_model_changed(self):
        is_experiment = (
            self.include_amorphous and self.amorphous_model_is_experimental
        )
        require_expt = [
            self.ui.amorphous_select_experiment_files,
            self.ui.amorphous_expt_smoothing,
            self.ui.amorphous_expt_smoothing_label,
        ]
        for w in require_expt:
            w.setVisible(is_experiment)

        if not is_experiment:
            self.amorphous_experiment_files.clear()

        self.update_degree_of_crystallinity()
        self.update_params()

    def select_amorphous_experiment_files(self):
        files = self.amorphous_experiment_files
        for i in range(self.num_amorphous_peaks):
            if i < len(files) and files[i]:
                path = files[i]
            else:
                path = HexrdConfig().working_dir

            selected_file, selected_filter = QFileDialog.getOpenFileName(
                self.ui,
                f'Select Amorphous Experiment File (Phase {i + 1})',
                path,
                'XY files (*.xy)',
            )

            if not selected_file:
                # Just abort the whole thing.
                break

            if i < len(files):
                files[i] = selected_file
            else:
                files.append(selected_file)

    def update_degree_of_crystallinity(self):
        w = self.ui.degree_of_crystallinity_label

        obj = self._wppf_object
        doc = 1 if obj is None else obj.DOC

        w.setText(f'Degree of Crystallinity: {doc:.3g}')

    def initialize_tree_view(self):
        if hasattr(self, 'tree_view'):
            # It has already been initialized
            return

        tree_dict = self.tree_view_dict_of_params
        self.tree_view = MultiColumnDictTreeView(
            tree_dict,
            self.tree_view_columns,
            parent=self.parent(),
            model_class=self.tree_view_model_class,
        )
        self.tree_view.check_selection_index = 2
        self.ui.tree_view_layout.addWidget(self.tree_view)

        # Make the key section a little larger
        self.tree_view.header().resizeSection(0, 300)

    def reinitialize_tree_view(self):
        # Keep the same scroll position
        scrollbar = self.tree_view.verticalScrollBar()
        scroll_value = scrollbar.value()

        self.ui.tree_view_layout.removeWidget(self.tree_view)
        self.tree_view.deleteLater()
        del self.tree_view
        self.initialize_tree_view()

        # Restore scroll bar position
        self.tree_view.verticalScrollBar().setValue(scroll_value)

    def update_tree_view(self):
        tree_dict = self.tree_view_dict_of_params
        self.tree_view.model().config = tree_dict
        self.tree_view.reset_gui()

    @property
    def tree_view_dict_of_params(self):
        params = self.params

        # Store stderr values so we can use them later
        stderr_values = self._get_stderr_values()

        tree_dict = {}
        template_dict = self.tree_view_mapping

        # Keep track of which params have been used.
        used_params = []

        def create_param_item(param):
            used_params.append(param.name)
            d = {
                '_param': param,
                '_value': param.value,
                '_vary': bool(param.vary),
                '_stderr': stderr_values.get(param.name, '--'),
            }
            if self.delta_boundaries:
                if not hasattr(param, 'delta'):
                    # We store the delta on the param object
                    # Default the delta to the minimum of the differences
                    diffs = [
                        abs(param.min - param.value),
                        abs(param.max - param.value),
                    ]
                    param.delta = min(diffs)

                d['_delta'] = param.delta
            else:
                d.update(**{
                    '_min': param.min,
                    '_max': param.max,
                })

            return d

        # Treat these root keys specially
        special_cases = [
            'Materials',
        ]

        def recursively_set_items(this_config, this_template):
            param_set = False
            for k, v in this_template.items():
                if k in special_cases:
                    # Skip over it
                    continue

                if isinstance(v, dict):
                    this_config.setdefault(k, {})
                    if recursively_set_items(this_config[k], v):
                        param_set = True
                    else:
                        # Pop this key if no param was set
                        this_config.pop(k)
                else:
                    # Assume it is a string. Grab it if in the params.
                    if v in params:
                        this_config[k] = create_param_item(params[v])
                        param_set = True

            return param_set

        # First, recursively set items (except special cases)
        recursively_set_items(tree_dict, template_dict)

        def recursively_format_amorphous(key, this_config, this_template):
            any_set = False
            for k, v in this_template.items():
                if isinstance(v, dict):
                    this_config.setdefault(k, {})
                    b = recursively_format_amorphous(key, this_config[k], v)
                    if not b:
                        # No parameters were used. We can eliminate this.
                        del this_config[k]
                else:
                    # Should be a string. Replace {k} with the key
                    v = v.format(k=key)

                    if v in params:
                        this_config[k] = create_param_item(params[v])
                        any_set = True

            return any_set

        if self.include_amorphous:
            # Add in amorphous parameters
            # Put the amorphous section first
            tree_dict = {'Amorphous': {}, **tree_dict}
            amorphous = tree_dict['Amorphous']
            template = template_dict['Amorphous']

            names = self.amorphous_peak_names
            if len(names) == 1:
                recursively_format_amorphous(names[0], amorphous, template)
            else:
                for name in names:
                    # Reformat the name to make it look nice in the tree view
                    formatted_name = name.replace('_', ' ').capitalize()
                    this_config = amorphous.setdefault(formatted_name, {})
                    recursively_format_amorphous(name, this_config, template)

        # If the background method is chebyshev, fill those in
        if self.background_method == 'chebyshev':
            # Put the background first
            tree_dict = {'Background': {}, **tree_dict}
            background = tree_dict['Background']
            i = 0
            while f'bkg_{i}' in params:
                background[i] = create_param_item(params[f'bkg_{i}'])
                i += 1

        # Now generate the materials
        materials_template = template_dict['Materials'].pop('{mat}')

        def recursively_format_site_id(mat, site_id, this_config,
                                       this_template):
            sanitized_mat = mat.replace('-', '_')
            for k, v in this_template.items():
                if isinstance(v, dict):
                    this_config.setdefault(k, {})
                    recursively_format_site_id(mat, site_id, this_config[k], v)
                else:
                    # Should be a string. Replace {mat} and {site_id} if needed
                    kwargs = {}
                    if '{mat}' in v:
                        kwargs['mat'] = sanitized_mat

                    if '{site_id}' in v:
                        kwargs['site_id'] = site_id

                    if kwargs:
                        v = v.format(**kwargs)

                    if v in params:
                        this_config[k] = create_param_item(params[v])

        def recursively_format_mat(mat, this_config, this_template):
            sanitized_mat = mat.replace('-', '_')
            for k, v in this_template.items():
                if k == 'Atomic Site: {site_id}':
                    # Identify all site IDs by regular expression
                    expr = re.compile(f'^{sanitized_mat}_(.*)_x$')
                    site_ids = []
                    for name in params:
                        m = expr.match(name)
                        if m:
                            site_id = m.group(1)
                            if site_id not in site_ids:
                                site_ids.append(site_id)

                    for site_id in site_ids:
                        new_k = k.format(site_id=site_id)
                        this_config.setdefault(new_k, {})
                        recursively_format_site_id(
                            mat,
                            site_id,
                            this_config[new_k],
                            v,
                        )
                elif isinstance(v, dict):
                    this_config.setdefault(k, {})
                    recursively_format_mat(mat, this_config[k], v)
                else:
                    # Should be a string. Replace {mat} if needed
                    if '{mat}' in v:
                        v = v.format(mat=sanitized_mat)

                    if v in params:
                        this_config[k] = create_param_item(params[v])

        mat_dict = tree_dict.setdefault('Materials', {})
        for mat in self.selected_materials:
            this_config = mat_dict.setdefault(mat, {})
            this_template = copy.deepcopy(materials_template)
            recursively_format_mat(mat, this_config, this_template)

        # Now all keys should have been used. Verify this is true.
        if sorted(used_params) != sorted(list(params.keys())):
            used = ', '.join(sorted(used_params))
            params = ', '.join(sorted(params.keys()))
            msg = (
                f'Internal error: used_params ({used})\n\ndid not match '
                f'params! ({params})'
            )
            raise Exception(msg)

        return tree_dict

    @property
    def tree_view_mapping(self):
        # This will always be a deep copy, so we can modify.
        method_dict = self.method_tree_dict

        # Insert the background and peak shape dicts too
        method_dict['Background'] = self.background_tree_dict
        method_dict['Instrumental Parameters']['Peak Parameters'] = (
            self.peak_shape_tree_dict
        )
        method_dict['Amorphous'] = self.amorphous_tree_dict

        return method_dict

    @property
    def tree_view_columns(self):
        return self.tree_view_model_class.COLUMNS

    @property
    def tree_view_model_class(self):
        if self.delta_boundaries:
            return DeltaWPPFTreeItemModel
        else:
            return DefaultWPPFTreeItemModel

    @property
    def show_difference_curve(self) -> bool:
        return self.ui.show_difference_curve.isChecked()

    @show_difference_curve.setter
    def show_difference_curve(self, b: bool):
        return self.ui.show_difference_curve.setChecked(b)

    @property
    def show_difference_as_percent(self) -> bool:
        return self.ui.show_difference_as_percent.isChecked()

    @show_difference_as_percent.setter
    def show_difference_as_percent(self, b: bool):
        return self.ui.show_difference_as_percent.setChecked(b)

    @property
    def delta_boundaries(self):
        return self.ui.delta_boundaries.isChecked()

    @delta_boundaries.setter
    def delta_boundaries(self, b):
        self.ui.delta_boundaries.setChecked(b)

    def on_delta_boundaries_toggled(self, b):
        # The columns have changed, so we need to reinitialize the tree view
        self.reinitialize_tree_view()

    def apply_delta_boundaries(self):
        # lmfit only uses min/max, not delta
        # So if we used a delta, apply that to the min/max

        if not self.delta_boundaries:
            # We don't actually need to apply delta boundaries...
            return

        def recurse(cur):
            for k, v in cur.items():
                if '_param' in v:
                    param = v['_param']
                    # There should be a delta.
                    # We want an exception if it is missing.
                    param.min = param.value - param.delta
                    param.max = param.value + param.delta
                elif isinstance(v, dict):
                    recurse(v)

        recurse(self.tree_view.model().config)

    def _get_stderr_values(self) -> dict[str, float]:
        # Get stderr values from the results object
        obj = getattr(self, '_wppf_object', None)
        if obj is None:
            return {}

        res = getattr(obj, 'res', None)
        if res is None:
            return {}

        return {k: v.stderr for k, v in res.params.items()}

    def on_show_difference_curve_toggled(self):
        HexrdConfig().show_wppf_difference_axis = (
            self.show_difference_curve
        )
        self.update_enable_states()

    def on_show_difference_as_percent_toggled(self):
        HexrdConfig().show_wppf_difference_as_percent = (
            self.show_difference_as_percent
        )

    @property
    def all_widgets(self):
        names = [
            'method',
            'refinement_steps',
            'peak_shape',
            'background_method',
            'experiment_file',
            'display_wppf_plot',
            'show_difference_curve',
            'show_difference_as_percent',
            'plot_background',
            'plot_amorphous',
        ]
        return [getattr(self.ui, x) for x in names]

    @property
    def wppf_object(self):
        if self._wppf_object is None:
            self._wppf_object = self.create_wppf_object()
            self.update_enable_states()
            self.update_degree_of_crystallinity()
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

        amorphous_model = None
        if self.include_amorphous:
            amorphous_model = Amorphous(
                tth_list=expt_spectrum[:, 0],
                **self.amorphous_kwargs,
            )

        return {
            'expt_spectrum': expt_spectrum,
            'params': self.params,
            # Make a deep copy of the materials so that WPPF
            # won't modify any arrays in place shared by our materials.
            'phases': copy.deepcopy(self.materials),
            'wavelength': wavelength,
            'bkgmethod': self.background_method_dict,
            'peakshape': self.peak_shape,
            'amorphous_model': amorphous_model,
        }

    def update_wppf_object(self):
        obj = self._wppf_object
        kwargs = self.wppf_object_kwargs

        skip_list = ['expt_spectrum', 'amorphous_model']

        for key, val in kwargs.items():
            if key in skip_list:
                continue

            if not hasattr(obj, key):
                raise Exception(f'{obj} does not have attribute: {key}')

            setattr(obj, key, val)

        self.update_degree_of_crystallinity()

    def export_params(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export Parameters', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return self.save_params(selected_file)

    def save_params(self, filename):
        filename = Path(filename)
        if filename.exists():
            filename.unlink()

        export_data = {k: param_to_dict(v) for k, v in self.params.items()}

        # Also add in any stderr if it exists
        stderr_values = self._get_stderr_values()
        for k, v in stderr_values.items():
            if k in export_data:
                export_data[k]['stderr'] = v

        with h5py.File(filename, 'w') as wf:
            unwrap_dict_to_h5(wf, export_data)

    def import_params(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Import Parameters', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return self.load_params(selected_file)

    def load_params(self, filename):
        filename = Path(filename)
        if not filename.exists():
            raise FileNotFoundError(filename)

        import_params = {}
        with h5py.File(filename, 'r') as rf:
            unwrap_h5_to_dict(rf, import_params)

        # No exception means we are valid
        self.validate_import_params(import_params, filename)

        # Keep the ordering the same as the GUI currently has
        for key in self.params.keys():
            self.params[key] = dict_to_param(import_params[key])

        self.update_tree_view()

    def validate_import_params(self, import_params, filename):
        here = self.params.keys()
        there = import_params.keys()
        extra = list(set(there) - set(here))
        missing = list(set(here) - set(there))

        # Do a backwards-compatibility conversion
        for key, entry in import_params.items():
            if 'lb' in entry:
                # This is the old format. Convert it to the lmfit one.
                entry['min'] = entry.pop('lb')
            if 'ub' in entry:
                # This is the old format. Convert it to the lmfit one.
                entry['max'] = entry.pop('ub')

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

        req_keys = ['name', 'value', 'min', 'max', 'vary']
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

    def push_undo_stack(self):
        settings = HexrdConfig().config['calibration'].get('wppf', {})

        stack_item = {
            'settings': settings,
            'spline_points': self.spline_points,
            'method': self.method,
            'refinement_steps': self.refinement_steps,
            'peak_shape': self.peak_shape,
            'background_method': self.background_method,
            'amorphous_experiment_files': self.amorphous_experiment_files,
            'selected_materials': self.selected_materials,
            '_wppf_object': self._wppf_object,
            'params': self.params,
        }

        stack_item = {k: copy.deepcopy(v) for k, v in stack_item.items()}

        self._undo_stack.append(stack_item)
        self.update_undo_enable_state()

    def pop_undo_stack(self):
        stack_item = self._undo_stack.pop(-1)

        for k, v in stack_item.items():
            setattr(self, k, v)

        self.save_settings()
        self.update_undo_enable_state()
        self.update_enable_states()
        self.update_tree_view()

        self.undo_clicked.emit()

    def update_undo_enable_state(self):
        self.ui.undo_last_run.setEnabled(len(self._undo_stack) > 0)


def generate_params(method, materials, peak_shape, bkgmethod, amorphous_model):
    func_dict = {
        'LeBail': _generate_default_parameters_LeBail,
        'Rietveld': _generate_default_parameters_Rietveld,
    }
    if method not in func_dict:
        raise Exception(f'Unknown method: {method}')

    return func_dict[method](
        materials,
        peak_shape,
        bkgmethod,
        amorphous_model=amorphous_model,
    )


def param_to_dict(param):
    return {
        'name': param.name,
        'value': param.value,
        'min': param.min,
        'max': param.max,
        'vary': param.vary,
    }


def dict_to_param(d):
    # Exclude stderr when converting a dict to a param
    if 'stderr' in d:
        d = d.copy()
        del d['stderr']

    return lmfit.Parameter(**d)


LOADED_YAML_DICTS = {}


def load_yaml_dict(module, filename):
    key = (module.__name__, filename)
    if key not in LOADED_YAML_DICTS:
        text = resource_loader.load_resource(module, filename)
        LOADED_YAML_DICTS[key] = yaml.safe_load(text)

    return copy.deepcopy(LOADED_YAML_DICTS[key])


class DefaultWPPFTreeItemModel(DefaultCalibrationTreeItemModel):
    COLUMNS = {
        **DefaultCalibrationTreeItemModel.COLUMNS,
        'Uncertainty': '_stderr',
    }
    COLUMN_INDICES = _tree_columns_to_indices(COLUMNS)
    UNEDITABLE_COLUMN_INDICES = [COLUMN_INDICES['Uncertainty']]


class DeltaWPPFTreeItemModel(DeltaCalibrationTreeItemModel):
    COLUMNS = {
        **DeltaCalibrationTreeItemModel.COLUMNS,
        'Uncertainty': '_stderr',
    }
    COLUMN_INDICES = _tree_columns_to_indices(COLUMNS)
    UNEDITABLE_COLUMN_INDICES = [COLUMN_INDICES['Uncertainty']]


if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication

    app = QApplication()

    dialog = WppfOptionsDialog()
    dialog.ui.exec()

    print(f'{dialog.method=}')
    print(f'{dialog.background_method=}')
    print(f'{dialog.experiment_file=}')
    print(f'{dialog.params=}')
