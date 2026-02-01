import copy
from functools import partial
from pathlib import Path
import re
import sys
import time

import h5py
import lmfit
import matplotlib.pyplot as plt
import numpy as np
import yaml

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
)

from hexrd import constants as ct
from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict
from hexrd.material import _angstroms
from hexrd.projections.polar import bin_polar_view
from hexrd.utils.hkl import hkl_to_str
from hexrd.wppf import LeBail, Rietveld
from hexrd.wppf.amorphous import AMORPHOUS_MODEL_TYPES, Amorphous
from hexrd.wppf.phase import Material_Rietveld
from hexrd.wppf.tds import (
    TDS,
    TDS_MODEL_TYPES,
    TDS_material,
    VALID_SGNUMS as VALID_TDS_SGNUMS,
)
from hexrd.wppf.texture import HarmonicModel
from hexrd.wppf.WPPF import peakshape_dict
from hexrd.wppf.wppfsupport import (
    background_methods,
    _generate_default_parameters_LeBail,
    _generate_default_parameters_Rietveld,
)

from hexrdgui import resource_loader
from hexrdgui.async_runner import AsyncRunner
from hexrdgui.calibration.tree_item_models import (
    _tree_columns_to_indices,
    DefaultCalibrationTreeItemModel,
    DeltaCalibrationTreeItemModel,
)
from hexrdgui.calibration.wppf_simulated_polar_dialog import (
    WppfSimulatedPolarDialog,
)
from hexrdgui.dynamic_widget import DynamicWidget
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.html_delegate import aligned_sub_sup_html, HtmlDelegate
from hexrdgui.point_picker_dialog import PointPickerDialog
from hexrdgui.select_items_dialog import SelectItemsDialog
from hexrdgui.tree_views.multi_column_dict_tree_view import (
    MultiColumnDictTreeView,
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
        self.populate_tds_options()

        self.dynamic_background_widgets = []

        self.spline_points = []
        self._wppf_object = None
        self._prev_background_method = None
        self._undo_stack = []
        self._texture_simulated_polar_dialog = None

        self.amorphous_experiment_files = []
        self._texture_settings = self._default_texture_settings
        self._tds_settings = {}

        self.params = self.generate_params()
        self.initialize_tree_view()

        self.load_settings()

        # Default setting for delta boundaries
        self.delta_boundaries = False

        self.async_runner = AsyncRunner(parent)

        # Trigger logic for changing amorphous setting
        self.on_include_amorphous_toggled()

        # Always default to the first tab
        self.ui.tab_widget.setCurrentIndex(0)

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.method.currentIndexChanged.connect(self.on_method_changed)
        self.ui.select_materials_button.pressed.connect(self.select_materials)
        self.ui.peak_shape.currentIndexChanged.connect(self.update_params)
        self.ui.delta_boundaries.toggled.connect(self.on_delta_boundaries_toggled)
        self.ui.select_experiment_file_button.pressed.connect(
            self.select_experiment_file
        )

        self.ui.background_method.currentIndexChanged.connect(
            self.update_background_parameters
        )

        self.ui.display_wppf_plot.toggled.connect(self.display_wppf_plot_toggled)
        self.ui.plot_background.toggled.connect(self.plot_background_toggled)
        self.ui.plot_amorphous.toggled.connect(self.plot_amorphous_toggled)
        self.ui.plot_tds.toggled.connect(self.plot_tds_toggled)
        self.ui.edit_plot_style.pressed.connect(self.edit_plot_style)
        self.ui.pick_spline_points.clicked.connect(self.pick_spline_points)
        self.ui.show_difference_curve.toggled.connect(
            self.on_show_difference_curve_toggled
        )
        self.ui.show_difference_as_percent.toggled.connect(
            self.on_show_difference_as_percent_toggled
        )

        self.ui.include_amorphous.toggled.connect(self.on_include_amorphous_toggled)
        self.ui.amorphous_model.currentIndexChanged.connect(
            self.on_amorphous_model_changed
        )
        self.ui.num_amorphous_peaks.valueChanged.connect(
            self.on_num_amorphous_peaks_value_changed
        )
        self.ui.amorphous_select_experiment_files.clicked.connect(
            self.select_amorphous_experiment_files
        )

        self.ui.selected_texture_material.currentIndexChanged.connect(
            self.on_selected_texture_material_changed
        )
        for w in self.texture_material_setting_widgets:
            changed_signal(w).connect(self.on_texture_material_setting_changed)
        for w in self.texture_binning_settings_widgets:
            changed_signal(w).connect(self.on_texture_binning_setting_changed)
        self.ui.texture_show_simulated_spectrum.clicked.connect(
            self.on_texture_show_simulated_spectrum_clicked
        )
        self.ui.texture_plot_pole_figures.clicked.connect(
            self.on_texture_plot_pole_figures_clicked
        )

        self.ui.selected_tds_material.currentIndexChanged.connect(
            self.on_selected_tds_material_changed
        )
        self.ui.include_tds_model.toggled.connect(self.on_include_tds_model_toggled)
        self.ui.tds_model_type.currentIndexChanged.connect(
            self.on_tds_model_type_changed
        )
        self.ui.tds_temperature_atom_type.currentIndexChanged.connect(
            self.on_tds_temperature_atom_type_changed
        )
        self.ui.tds_debye_temperature.valueChanged.connect(
            self.on_tds_debye_temperature_value_changed
        )
        self.ui.tds_select_experimental_data_file.clicked.connect(
            self.on_tds_select_experimental_data_file_clicked
        )
        self.ui.tds_experimental_data_file.textChanged.connect(
            self.save_tds_experimental_settings
        )
        self.ui.tds_experimental_scale.valueChanged.connect(
            self.save_tds_experimental_settings
        )
        self.ui.tds_experimental_shift.valueChanged.connect(
            self.save_tds_experimental_settings
        )

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

        self.ui.show_difference_as_percent.setVisible(self.show_difference_curve)

        self.update_texture_model_enable_states()
        self.update_tds_enabled()

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

    def populate_tds_options(self):
        w = self.ui.tds_model_type
        prev = w.currentText()
        types = list(TDS_MODEL_TYPES)

        with block_signals(w):
            w.clear()
            for name in types:
                w.addItem(name)

            if prev in types:
                w.setCurrentIndex(types.index(prev))

    def save_plot(self):
        obj = self._wppf_object
        if obj is None:
            raise Exception('No WPPF object!')

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui,
            'Save Data',
            HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)',
        )

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
        bkg = obj.background.y
        data = {
            'two_theta': two_theta,
            'intensity': intensity,
            'lineout_intensity': lineout_intensity,
            'difference_curve': intensity - lineout_intensity,
            'background': bkg,
        }
        if obj.amorphous_model is not None:
            data['amorphous'] = obj.amorphous_model.amorphous_lineout

        if obj.tds_model is not None and obj.tds_model.TDSmodels:
            tds_models = obj.tds_model.TDSmodels
            tds_dict = {}
            for p in tds_models:
                for w, tds_material in tds_models[p].items():
                    tds_dict.setdefault(p, {})[w] = tds_material.tds_lineout

            data['tds'] = tds_dict

        # Delete the file if it already exists
        if filename.exists():
            filename.unlink()

        def recursive_create_datasets(key, data, group):
            if isinstance(data, dict):
                if not data:
                    return

                group2 = group.create_group(key)
                for key2, data2 in data.items():
                    recursive_create_datasets(key2, data2, group2)
                return

            group.create_dataset(key, data=data)

        # Save as HDF5
        with h5py.File(filename, 'w') as f:
            for key, value in data.items():
                recursive_create_datasets(key, value, f)

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
            if len(files) < self.num_amorphous_peaks or any(not x for x in files):
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

        if self.varying_texture_params:
            # Ensure texture data is set on the WPPF object.
            # This might be time-consuming.
            # We also have to ensure there is a WPPF object
            self.wppf_object
            try:
                self.ensure_texture_data()
            except Exception:
                # If there was some exception, remove the last undo stack entry
                self.remove_last_undo_stack_entry()
                raise
        else:
            # If there are any non-texture refinements, we ought
            # to clear the texture data.
            self.clear_texture_data()

        self.run.emit()

    def finish(self):
        self.finished.emit()

    def validate(self):
        use_experiment_file = self.use_experiment_file
        if use_experiment_file and not Path(self.experiment_file).exists():
            raise Exception(
                f'Experiment file, {self.experiment_file}, ' 'does not exist'
            )

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

        if self.varying_texture_and_non_texture_params:
            msg = (
                'Texture parameters cannot be varied at the same time as '
                'non-texture parameters.'
            )
            raise Exception(msg)

    def generate_params(self):
        kwargs = {
            'method': self.method,
            'materials': self.materials,
            'peak_shape': self.peak_shape_index,
            'bkgmethod': self.background_method_dict,
            'amorphous_model': None,
            'texture_model': self.texture_model_dict,
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

    def update_params(self, update_tree_view=True):
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

        if update_tree_view:
            self.update_tree_view()

    def show(self):
        self.ui.show()

    def select_materials(self):
        materials = self.powder_overlay_materials
        selected = self.selected_materials
        items = [(name, name in selected) for name in materials]
        dialog = SelectItemsDialog(items, 'Select Materials', self.ui)
        while True:
            if dialog.exec() and self.selected_materials != dialog.selected_items:
                if not dialog.selected_items:
                    msg = 'At least one material must be selected'
                    QMessageBox.critical(self.ui, 'Material Required', msg)
                    print(msg, file=sys.stderr)
                    continue

                self.selected_materials = dialog.selected_items
                self.update_params()
            break

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
        self.update_texture_material_options()
        self.update_tds_material_options()

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
            'scale': 1.0,
            'shift': 0.0,
            'center': 30.0,
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
            kwargs['center'][k] += i * 25

        if self.amorphous_model_is_experimental:
            kwargs['model_data'] = {
                key: np.loadtxt(path)
                for key, path in zip(key_names, self.amorphous_experiment_files)
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

        dialog = PointPickerDialog(fig.canvas, 'Pick Background Points', parent=self.ui)
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
    def plot_tds(self) -> bool:
        return self.ui.plot_tds.isChecked()

    @plot_tds.setter
    def plot_tds(self, b: bool):
        self.ui.plot_tds.setChecked(b)

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

            old_param = self.params[key]
            self.params[key] = dict_to_param(val)

            if old_param.expr:
                # If there was an expression, restore that expression
                self.params[key].expr = old_param.expr

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

        skip_list = [
            'params_dict',
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

                if k in skip_list:
                    # We apply this later...
                    continue

                if not hasattr(self, k) or k in apply_first_keys:
                    # Skip it...
                    continue

                setattr(self, k, v)

        # Add/remove params depending on what are allowed
        self.update_params()
        self.update_enable_states()

        # Now apply the params dict after updating default parameters.
        # This is so that settings specific to things like texture, or
        # Rietveld, can be loaded correctly.
        if 'params_dict' in settings:
            v = settings['params_dict']
            # For backward-compatibility
            for d in v.values():
                if 'lb' in d:
                    d['min'] = d.pop('lb')

                if 'ub' in d:
                    d['max'] = d.pop('ub')

            self.params_dict = v

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
            'plot_tds',
            'params_dict',
            'limit_tth',
            'min_tth',
            'max_tth',
            'texture_settings',
            'tds_settings',
        ]
        for key in keys:
            settings[key] = getattr(self, key)

    def select_experiment_file(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui,
            'Select Experiment File',
            HexrdConfig().working_dir,
            'TXT files (*.txt)',
        )

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

    def plot_tds_toggled(self):
        HexrdConfig().display_wppf_tds = self.plot_tds

    def edit_plot_style(self):
        dialog = WppfStylePicker(
            amorphous_visible=self.include_amorphous,
            tds_visible=self.any_tds_models_enabled,
            parent=self.ui,
        )
        dialog.exec()

    def update_gui(self):
        to_block = [
            self.ui.display_wppf_plot,
            self.ui.plot_background,
            self.ui.plot_amorphous,
            self.ui.plot_tds,
            self.ui.show_difference_curve,
            self.ui.show_difference_as_percent,
        ]
        with block_signals(*to_block):
            self.display_wppf_plot = HexrdConfig().display_wppf_plot
            self.plot_background = HexrdConfig().display_wppf_background
            self.plot_amorphous = HexrdConfig().display_wppf_amorphous
            self.plot_tds = HexrdConfig().display_wppf_tds

            self.show_difference_curve = HexrdConfig().show_wppf_difference_axis
            self.show_difference_as_percent = (
                HexrdConfig().show_wppf_difference_as_percent
            )

            self.update_background_parameters()
            self.update_tree_view()

        self.update_enable_states()
        self.update_texture_material_options()
        self.update_tds_material_options()
        self.update_texture_gui()
        self.update_tds_gui()

    def update_background_parameters(self):
        if self.background_method == self._prev_background_method:
            # The method did not change. Just return.
            return

        self._prev_background_method = self.background_method

        # Update the visibility of this button
        self.ui.pick_spline_points.setVisible(self.background_method == 'spline')

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
                w.value_changed.connect(self.on_chebyshev_num_params_changed)

            self.dynamic_background_widgets.append(w)

        # We may need to update the parameters as well, since some background
        # methods have parameters.
        self.update_params(update_tree_view=False)
        self.reset_background_param_values()

    def clear_background_stderr(self):
        obj = getattr(self, '_wppf_object', None)
        if obj is None:
            return

        res = getattr(obj, 'res', None)
        if res is None:
            return

        i = 0
        name = f'bkg_{i}'
        while name in res.params:
            res.params[name].stderr = None
            i += 1
            name = f'bkg_{i}'

    def reset_background_param_values(self):
        # The WPPF object will calculate and set new background parameters
        # during initialization.
        self.create_wppf_object(reset_background_params=True)

        # Get rid of stderr values for background params
        self.clear_background_stderr()

        self.update_tree_view()

    def on_chebyshev_num_params_changed(self):
        # Reset the background parameters
        self.update_params(update_tree_view=False)
        self.reset_background_param_values()

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
        is_experiment = self.include_amorphous and self.amorphous_model_is_experimental
        files = self.amorphous_experiment_files
        if is_experiment:
            # Trim off extra experiment files
            while len(files) > self.num_amorphous_peaks:
                files.pop()

        self.on_amorphous_model_changed()

    def on_amorphous_model_changed(self):
        is_experiment = self.include_amorphous and self.amorphous_model_is_experimental
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
        # Use html so we can render superscripts and subscripts
        self.tree_view.setItemDelegate(HtmlDelegate())
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
        # Keep the same scroll position
        scrollbar = self.tree_view.verticalScrollBar()
        scroll_value = scrollbar.value()

        tree_dict = self.tree_view_dict_of_params
        self.tree_view.model().config = tree_dict
        self.update_disabled_paths()
        self.tree_view.reset_gui()

        if scroll_value != 0:
            # Restore scroll bar position
            # We only do this if the value wasn't zero because
            # scrollbar.value() won't reflect the actual value until
            # the next iteration of the event loop, and repeated calls
            # to `scrollbar.value()` ultimately turn to 0.
            scrollbar.setValue(scroll_value)

    @property
    def tree_view_dict_of_params(self):
        params = self.params

        # Store stderr values so we can use them later
        stderr_values = self._get_stderr_values()

        tree_dict = {}
        template_dict = self.tree_view_mapping

        # Keep track of which params have been used.
        used_params = []

        def create_param_item(
            param, units=None, conversion_funcs=None, min_max_inverted=False
        ):
            # Convert to display units if needed
            def convert_if_needed(x):
                if conversion_funcs is None:
                    return x

                return conversion_funcs['to_display'](x)

            def convert_stderr_if_needed(x):
                if x == '--':
                    return x

                if conversion_funcs is None:
                    return x

                if 'to_display_stderr' in conversion_funcs:
                    # Special conversion needed
                    return conversion_funcs['to_display_stderr'](
                        param.value,
                        x,
                    )

                # Default to the regular conversion
                return convert_if_needed(x)

            used_params.append(param.name)
            stderr = stderr_values.get(param.name, '--')
            d = {
                '_param': param,
                '_value': convert_if_needed(param.value),
                '_vary': bool(param.vary),
                '_stderr': convert_stderr_if_needed(stderr),
                '_units': units,
                '_conversion_funcs': conversion_funcs,
                '_min_max_inverted': min_max_inverted,
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

                d['_delta'] = convert_if_needed(param.delta)
            else:
                d.update(
                    **{
                        '_min': convert_if_needed(param.min),
                        '_max': convert_if_needed(param.max),
                    }
                )
                if min_max_inverted:
                    # Swap the min and max
                    d['_min'], d['_max'] = d['_max'], d['_min']

            # Make a callback for when `vary` gets modified by the user.
            f = partial(self.on_param_vary_modified, param=param)
            param._on_vary_modified = f

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
                        units = None
                        if v == 'zero_error':
                            units = '°'

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

        def recursively_format_site_id(mat, site_id, this_config, this_template):
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

                    # Determine if units and conversion funcs are needed
                    # We can't have a global dict of these, because some
                    # labels are the same. For example, 'α' is also in the
                    # stacking fault parameters.
                    units = None
                    conversion_funcs = None
                    min_max_inverted = False
                    prefix = sanitized_mat
                    if v == f'{prefix}_X':
                        # Provide wavelength in micrometers
                        wlen = HexrdConfig().beam_wavelength / 1e4
                        units = ' µm'
                        conversion_funcs = mat_lx_to_p_funcs_factory(wlen)
                        min_max_inverted = True
                    elif v == f'{prefix}_Y':
                        units = '%'
                        conversion_funcs = mat_ly_to_s_funcs
                    elif v == f'{prefix}_P':
                        # Provide wavelength in micrometers
                        wlen = HexrdConfig().beam_wavelength / 1e4
                        units = ' µm'
                        conversion_funcs = mat_gp_to_p_funcs_factory(wlen)
                        min_max_inverted = True
                    elif v in [f'{prefix}_{k}' for k in ('a', 'b', 'c')]:
                        units = ' Å'
                        conversion_funcs = nm_to_angstroms_funcs
                    elif v in [f'{prefix}_{k}' for k in ('α', 'β', 'γ')]:
                        units = '°'
                    elif re.search(rf'^{prefix}_s\d\d\d$', v):
                        # It is a stacking parameter
                        conversion_funcs = shkl_to_angstroms_minus_4_funcs
                        units = ' Å⁻⁴'

                    if v in params:
                        this_config[k] = create_param_item(
                            params[v],
                            units,
                            conversion_funcs,
                            min_max_inverted,
                        )

        mat_dict = tree_dict.setdefault('Materials', {})
        for mat in self.selected_materials:
            this_config = mat_dict.setdefault(mat, {})
            this_template = copy.deepcopy(materials_template)
            recursively_format_mat(mat, this_config, this_template)

        # Add texture parameters
        if self.includes_texture:
            texture_dict = tree_dict.setdefault('Texture', {})
            for mat_name in self.textured_materials:
                # Look for param names that match
                mat_name_sanitized = mat_name.replace('-', '_')
                prefix = f'{mat_name_sanitized}_c_'
                matching_names = [k for k in params if k.startswith(prefix)]
                if not matching_names:
                    continue

                mat_config = texture_dict.setdefault(mat_name, {})
                for name in matching_names:
                    suffix = name[len(prefix) :]
                    ell, i, j = [int(k) for k in suffix.split('_')]
                    # Align the superscript and subscript vertically
                    k = aligned_sub_sup_html('C', f'{ell}', f'{i},{j}')
                    mat_config[k] = create_param_item(params[name])

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
        method_dict['Instrumental Parameters'][
            'Peak Parameters'
        ] = self.peak_shape_tree_dict
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

    def update_disabled_paths(self):
        uneditable_paths = self.tree_view.model().uneditable_paths
        disabled_paths = self.tree_view.disabled_editor_paths

        uneditable_paths.clear()
        disabled_paths.clear()

        # Recurse through all params and find any that have an expression
        # Those will be disabled.
        results = []
        cur_path = []

        def recurse(d):
            if isinstance(d, list):
                for i, v in enumerate(d):
                    cur_path.append(i)
                    recurse(v)
                    cur_path.pop(-1)
                return

            # Should be a dict
            if '_param' in d:
                param = d['_param']
                if param.expr is not None:
                    results.append(cur_path.copy())
                return

            for k, v in d.items():
                cur_path.append(k)
                recurse(v)
                cur_path.pop(-1)

        config = self.tree_view.model().config
        recurse(config)

        for path in results:
            value_idx = self.tree_view_model_class.VALUE_IDX
            vary_idx = self.tree_view_model_class.VARY_IDX

            # The checkbox is disabled
            disabled_paths.append(tuple(path) + (vary_idx,))

            # The value is uneditable
            uneditable_paths.append(tuple(path) + (value_idx,))

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

        return {k: v.stderr for k, v in res.params.items() if v.vary and v.stderr}

    def on_param_vary_modified(self, param):
        # If it is a texture parameter, mark all other texture
        # parameters as the same for that material.
        if '_c_' in param.name:
            mat_name = param.name.split('_c_')[0]
            for p in self.params.values():
                if p.name.startswith(f'{mat_name}_c_'):
                    p.vary = param.vary

            self.update_tree_view()

    def on_show_difference_curve_toggled(self):
        HexrdConfig().show_wppf_difference_axis = self.show_difference_curve
        self.update_enable_states()

    def on_show_difference_as_percent_toggled(self):
        HexrdConfig().show_wppf_difference_as_percent = self.show_difference_as_percent

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
            'plot_tds',
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

    def create_wppf_object(self, reset_background_params=False):
        class_types = {
            'LeBail': LeBail,
            'Rietveld': Rietveld,
        }

        if self.method not in class_types:
            raise Exception(f'Unknown method: {self.method}')

        class_type = class_types[self.method]
        obj = class_type(
            **self.wppf_object_kwargs,
            reset_background_params=reset_background_params,
        )

        if self.method == 'Rietveld':
            # Add the TDS model to it, if applicable
            self.set_tds_model(obj)

        return obj

    @property
    def wppf_object_kwargs(self):
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
                'fill_value': 0.0,
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

        extra_kwargs = {}
        if self.includes_texture:
            extra_kwargs = {
                **extra_kwargs,
                'texture_model': self.texture_model_dict,
                'eta_max': HexrdConfig().polar_res_eta_max,
                'eta_min': HexrdConfig().polar_res_eta_min,
                # We have to make sure this is correct every time we update
                # the 2D spectrum.
                'eta_step': self.texture_settings['azimuthal_interval'],
            }

        return {
            'expt_spectrum': expt_spectrum,
            'params': self.params,
            # Make a deep copy of the materials so that WPPF
            # won't modify any arrays in place shared by our materials.
            'phases': copy.deepcopy(self.materials),
            'wavelength': self._wppf_wavelength_arg,
            'bkgmethod': self.background_method_dict,
            'peakshape': self.peak_shape,
            'amorphous_model': amorphous_model,
            **extra_kwargs,
        }

    @property
    def _wppf_wavelength_arg(self) -> dict[str, list[float, float]]:
        # We only support one wavelength currently
        # For the value, the first is the wavelength, the second is the weight
        return {'synchrotron': [_angstroms(HexrdConfig().beam_wavelength), 1.0]}

    def update_wppf_object(self):
        obj = self._wppf_object
        kwargs = self.wppf_object_kwargs

        skip_list = ['expt_spectrum', 'amorphous_model', 'texture_model']

        for key, val in kwargs.items():
            if key in skip_list:
                continue

            if not hasattr(obj, key):
                raise Exception(f'{obj} does not have attribute: {key}')

            setattr(obj, key, val)

        self.update_degree_of_crystallinity()

        # Update the Rietveld TDS model, if applicable
        self.update_rietveld_tds_model()

    def export_params(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui,
            'Export Parameters',
            HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)',
        )

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
            self.ui,
            'Import Parameters',
            HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)',
        )

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
        for key, old_param in self.params.items():
            self.params[key] = dict_to_param(import_params[key])
            if old_param.expr:
                # If there was an expression, restore that expression
                self.params[key].expr = old_param.expr

        self.update_tree_view()
        self.save_settings()

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
            msg = (
                f'Parameters in {filename} do not match current WPPF '
                'parameters internally. Please ensure the same settings '
                'are being used'
            )

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

        # Copy texture figures over. We need to keep the originals.
        self._copy_texture_figs(self._wppf_object, stack_item['_wppf_object'])

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

        if self.varying_texture_params:
            # The texture parameters must have changed from this "undo".
            self.on_texture_params_modified()

        self.undo_clicked.emit()

    def remove_last_undo_stack_entry(self):
        if not self._undo_stack:
            return

        self._undo_stack.pop()
        self.update_undo_enable_state()

    def update_undo_enable_state(self):
        self.ui.undo_last_run.setEnabled(len(self._undo_stack) > 0)

    @property
    def texture_material_setting_widgets(self) -> list:
        return [
            self.ui.include_texture_model,
            self.ui.texture_ell_max,
            self.ui.texture_sample_symmetry,
        ]

    @property
    def texture_binning_settings_widgets(self) -> list:
        return [
            self.ui.texture_azimuthal_interval,
            self.ui.texture_integration_range,
        ]

    def update_texture_material_options(self):
        valid_mats = self.selected_materials

        w = self.ui.selected_texture_material
        prev_selected = w.currentText()
        with block_signals(w):
            w.clear()
            w.addItems(valid_mats)
            if prev_selected in valid_mats:
                w.setCurrentText(prev_selected)

        # Also verify all modeled materials are present. Remove any
        # that are not.
        self.prune_invalid_texture_materials()
        self.on_selected_texture_material_changed()

    def on_selected_texture_material_changed(self):
        self.update_texture_model_gui()

    def update_texture_model_gui(self):
        mat_name = self.ui.selected_texture_material.currentText()
        model_kwargs = self.texture_model_kwargs
        checked = mat_name in model_kwargs
        if checked:
            settings = model_kwargs[mat_name]
        else:
            settings = self._default_texture_model_settings

        with block_signals(*self.texture_material_setting_widgets):
            self.ui.include_texture_model.setChecked(checked)
            self.ui.texture_sample_symmetry.setCurrentText(settings['ssym'])
            self.ui.texture_ell_max.setValue(settings['ell_max'])

        self.update_texture_model_enable_states()
        self.update_texture_index_label()

    def update_texture_model_enable_states(self):
        # Determine whether we should disable the model texture
        # and
        w = self.ui.include_texture_model
        is_rietveld = self.method == 'Rietveld'
        if not is_rietveld:
            w.setChecked(False)

        has_object = self._wppf_object is not None
        enable = is_rietveld and not has_object
        w.setEnabled(enable)

        # Now enable/disable all the other widgets
        enable = w.isChecked() and not has_object
        widgets = [
            self.ui.texture_sample_symmetry_label,
            self.ui.texture_sample_symmetry,
            self.ui.texture_ell_max_label,
            self.ui.texture_ell_max,
        ]

        for w in widgets:
            w.setEnabled(enable)

        self.ui.spectrum_binning_group.setEnabled(is_rietveld)

        # Now figure out if we should enable pole figure plotting
        self.ui.texture_plot_pole_figures.setEnabled(self.can_plot_pole_figures)

    def on_texture_material_setting_changed(self):
        mat_name = self.ui.selected_texture_material.currentText()
        checked = self.ui.include_texture_model.isChecked()
        model_kwargs = self.texture_model_kwargs

        if not checked:
            if mat_name in model_kwargs:
                del model_kwargs[mat_name]
        else:
            ssym = self.ui.texture_sample_symmetry.currentText()
            # Force ell_max to be an even number
            ell_max = self.ui.texture_ell_max.value()
            if ell_max % 2 != 0:
                msg = 'Spherical harmonic max must be an even number'
                QMessageBox.critical(self.ui, 'HEXRD', msg)
                print(msg, file=sys.stderr)

                ell_max += 1
                w = self.ui.texture_ell_max
                with block_signals(w):
                    w.setValue(ell_max)

            model_kwargs[mat_name] = {
                'ssym': ssym,
                'ell_max': ell_max,
            }

        self.update_texture_model_enable_states()

        # New params might be present
        # This will update the tree view
        self.update_params()

    def update_texture_binning_settings_gui(self):
        settings = self.texture_settings
        settings_map = {
            'azimuthal_interval': 'texture_azimuthal_interval',
            'integration_range': 'texture_integration_range',
        }
        for key, w_name in settings_map.items():
            w = getattr(self.ui, w_name)
            w.setValue(settings[key])

    def save_texture_binning_settings(self):
        settings = self.texture_settings
        settings_map = {
            'azimuthal_interval': 'texture_azimuthal_interval',
            'integration_range': 'texture_integration_range',
        }
        for key, w_name in settings_map.items():
            w = getattr(self.ui, w_name)
            settings[key] = w.value()

    def invalidate_texture_data(self):
        self.clear_texture_data()

    def on_texture_binning_setting_changed(self):
        self.save_texture_binning_settings()

        # Invalidate the texture data
        self.invalidate_texture_data()
        self.update_simulated_polar_dialog()

    def _compute_2d_pv_bin_mask(self):
        canvas = HexrdConfig().active_canvas
        if canvas.mode != 'polar' or canvas.iviewer is None:
            return

        settings = self.texture_settings

        # Make a float image so that any pixels touched by nans
        # in the binning will be nan.
        mask_float = np.zeros(canvas.iviewer.pv.shape, dtype=float)
        pv = canvas.iviewer.pv
        mask = np.logical_or(pv.all_masks_pv_array, pv.warp_mask)
        mask_float[mask] = np.nan
        binned = bin_polar_view(
            canvas.iviewer.pv,
            mask_float,
            settings['azimuthal_interval'],
            settings['integration_range'],
        )
        return np.isnan(binned)

    def _compute_2d_pv_bin(self):
        canvas = HexrdConfig().active_canvas
        if canvas.mode != 'polar' or canvas.iviewer is None:
            return

        settings = self.texture_settings

        return bin_polar_view(
            canvas.iviewer.pv,
            canvas.iviewer.img,
            settings['azimuthal_interval'],
            settings['integration_range'],
        )

    def _compute_2d_pv_sim(self):
        # We have to have an object to do this.
        # If we must, temporarily create one and destroy it later...
        had_object = self._wppf_object is not None

        obj = self.wppf_object
        if not isinstance(obj, Rietveld):
            # Nothing we can do
            return None

        # Compute the mask to apply
        mask = self._compute_2d_pv_bin_mask()

        try:
            # Make sure the `eta_step` is up-to-date
            obj.eta_step = self.texture_settings['azimuthal_interval']
            obj.computespectrum_2D()
            img = obj.simulated_2d.copy()
            img[mask] = np.nan
            return img
        finally:
            if not had_object:
                self.reset_object()

    @property
    def polar_extent(self) -> list[float] | None:
        canvas = HexrdConfig().active_canvas
        if canvas.mode != 'polar' or canvas.iviewer is None:
            return

        return canvas.iviewer._extent

    @property
    def varying_texture_params(self):
        for mat_name in self.textured_materials_sanitized:
            prefix = f'{mat_name}_c_'
            for param in self.params.values():
                if param.name.startswith(prefix) and param.vary:
                    return True

        return False

    @property
    def varying_texture_and_non_texture_params(self):
        if not self.varying_texture_params:
            return False

        prefixes = [f'{mat_name}_c_' for mat_name in self.textured_materials_sanitized]
        for name, param in self.params.items():
            if param.vary and not any(name.startswith(x) for x in prefixes):
                return True

        return False

    @property
    def can_plot_pole_figures(self) -> bool:
        obj = self._wppf_object
        if not isinstance(obj, Rietveld):
            # Nothing to do
            return False

        def is_zero(v: float) -> bool:
            return np.isclose(v, 0)

        params = self.params

        # If we find any non-zero parameters, we can plot pole figures
        for model in obj.texture_model.values():
            if model is None:
                continue

            for name in model.parameter_names:
                if name in params and not is_zero(params[name].value):
                    return True

        return False

    def _copy_texture_figs(self, obj1, obj2):
        # We need to keep the original texture figures, so copy those over.
        if obj1 is None or obj2 is None:
            return

        if any(not hasattr(x, 'texture_model') for x in (obj1, obj2)):
            return

        for model_key, model1 in obj1.texture_model.items():
            model2 = obj2.texture_model[model_key]
            if model1 is None or model2 is None:
                continue

            if hasattr(model1, 'fig_new'):
                model2.fig_new = model1.fig_new
                model2.ax_new = model1.ax_new

    def clear_texture_data(self):
        obj = self._wppf_object
        if not isinstance(obj, Rietveld):
            # Nothing to do
            return

        for model in obj.texture_model.values():
            if model is None or not model.pfdata:
                continue

            # Clear it
            model.pfdata = {}

    def ensure_texture_data(self) -> bool:
        obj = self._wppf_object
        if not isinstance(obj, Rietveld):
            raise Exception('Cannot make texture data without Rietveld object')

        if obj.texture_models_have_pfdata:
            # Nothing to do
            return

        had_error = False

        def on_error():
            nonlocal had_error
            had_error = True

        self.async_runner.progress_title = 'Generating texture data...'
        self.async_runner.error_callback = on_error
        self.async_runner.run(self.update_texture_data)
        while not obj.texture_models_have_pfdata and not had_error:
            # Process events until we have pfdata. This will allows the
            # progress dialog to animate.
            QCoreApplication.processEvents()
            time.sleep(0.05)

        if had_error:
            msg = 'Failed to generate texture data'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            raise Exception(msg)

    def update_texture_data(self):
        obj = self._wppf_object
        if not isinstance(obj, Rietveld):
            return

        pv_bin = self._compute_2d_pv_bin()
        settings = self.texture_settings

        # This also updates the texture data on all of the texture models
        obj.compute_texture_data(
            pv_bin,
            bvec=HexrdConfig().beam_vector,
            evec=ct.eta_vec,
            azimuthal_interval=settings['azimuthal_interval'],
        )

    def on_texture_show_simulated_spectrum_clicked(self):
        pv_bin = self._compute_2d_pv_bin()
        pv_sim = self._compute_2d_pv_sim()
        extent = self.polar_extent

        d = self._texture_simulated_polar_dialog
        if d is None:
            d = WppfSimulatedPolarDialog(pv_bin, pv_sim, extent)
            self._texture_simulated_polar_dialog = d
        else:
            # Ensure the data is up-to-date
            d.extent = extent
            d.set_data(pv_bin, pv_sim)

        d.ui.show()

    def on_texture_plot_pole_figures_clicked(self):
        obj = self._wppf_object
        if not isinstance(obj, Rietveld):
            return

        if len(self.textured_materials) > 1:
            # Get the user to pick a material
            items = self.textured_materials
            mat_name, ok = QInputDialog.getItem(
                self.ui, 'Pole Figures', 'Select material', items, 0, False
            )
            if not ok:
                return
        else:
            mat_name = self.textured_materials[0]

        mat = HexrdConfig().material(mat_name)
        hkls = mat.planeData.getHKLs()

        items = []
        for hkl in hkls:
            items.append([hkl_to_str(hkl), False])

        # Only select the first one by default
        items[0][1] = True

        # Get the user to select HKLs to use
        dialog = SelectItemsDialog(items, 'Select HKLs')
        if not dialog.exec():
            return

        hkl_is_selected = [x[1] for x in dialog.items]
        selected_hkls = hkls[hkl_is_selected]
        if selected_hkls.size == 0:
            return

        model = obj.texture_model[mat_name]

        if hasattr(model, 'fig_new'):
            # Hide the old plot for this harmonic model
            model.fig_new.canvas.manager.window.hide()

        model.calc_new_pole_figure(self.params, selected_hkls, plot=True)

    def on_texture_params_modified(self):
        self.update_simulated_polar_dialog()
        self.update_pole_figure_plots()
        self.update_texture_index_label()

    def update_simulated_polar_dialog(self):
        d = self._texture_simulated_polar_dialog
        if d is None or not d.ui.isVisible():
            return

        pv_bin = self._compute_2d_pv_bin()
        pv_sim = self._compute_2d_pv_sim()

        d.set_data(pv_bin, pv_sim)

    def update_pole_figure_plots(self):
        obj = self._wppf_object
        if not isinstance(obj, Rietveld):
            return

        for model in obj.texture_model.values():
            if model is None:
                continue

            if model.new_pf_plots_visible:
                model.update_new_pf_plot_data(self.params)

    def update_texture_gui(self):
        self.update_texture_model_gui()
        self.update_texture_binning_settings_gui()

    @property
    def texture_settings(self):
        return self._texture_settings

    @texture_settings.setter
    def texture_settings(self, v):
        self._texture_settings = v

        # Validate materials in the texture model dict are selected
        # materials. Remove materials that are not.
        self.prune_invalid_texture_materials()
        self.update_texture_gui()

    def prune_invalid_texture_materials(self):
        valid_mats = self.selected_materials
        for name in list(self.texture_model_kwargs):
            if name not in valid_mats:
                self.texture_model_kwargs.pop(name)

    @property
    def _default_texture_settings(self):
        return {
            'model_kwargs': {},
            'azimuthal_interval': 5,
            'integration_range': 1,
        }

    @property
    def _default_texture_model_settings(self):
        return {
            'ssym': 'axial',
            'ell_max': 16,
        }

    @property
    def includes_texture(self) -> bool:
        return bool(self.textured_materials)

    @property
    def textured_materials(self) -> list[str]:
        if self.method != 'Rietveld':
            return []

        return list(self.texture_model_kwargs)

    @property
    def textured_materials_sanitized(self) -> list[str]:
        return [name.replace('-', '_') for name in self.textured_materials]

    @property
    def texture_model_kwargs(self) -> dict[str]:
        return self.texture_settings['model_kwargs']

    @property
    def texture_model_dict(self) -> dict[str, HarmonicModel]:
        if self.method != 'Rietveld':
            return {}

        ret = {}
        settings = self.texture_settings
        for k, kwargs in settings['model_kwargs'].items():
            mat = HexrdConfig().material(k)
            ret[k] = HarmonicModel(
                **{
                    'material': Material_Rietveld(material_obj=mat),
                    'bvec': HexrdConfig().beam_vector,
                    'evec': ct.eta_vec,
                    'sample_rmat': HexrdConfig().sample_rmat,
                    **kwargs,
                }
            )
        return ret

    def update_texture_index_label(self):
        obj = self._wppf_object
        mat_name = self.ui.selected_texture_material.currentText()
        w = self.ui.texture_index_label

        if not isinstance(obj, Rietveld) or obj.texture_model.get(mat_name) is None:
            v = 'None'
        else:
            j = obj.texture_model[mat_name].J(self.params)
            v = f'{j:.2f}'

        w.setText(f'Texture index: {v}')

    @property
    def tds_settings(self):
        return self._tds_settings

    @tds_settings.setter
    def tds_settings(self, v):
        self._tds_settings = v

        # Validate materials in the tds model dict are selected
        # materials. Remove materials that are not.
        self.prune_invalid_tds_materials()
        self.update_tds_gui()

    def prune_invalid_tds_materials(self):
        valid_mats = self.selected_materials
        for name in list(self.tds_settings):
            if name not in valid_mats:
                self.tds_settings.pop(name)

    @property
    def selected_tds_material(self) -> str:
        return self.ui.selected_tds_material.currentText()

    def update_tds_material_options(self):
        valid_mats = self.selected_materials

        w = self.ui.selected_tds_material
        prev_selected = w.currentText()
        with block_signals(w):
            w.clear()
            w.addItems(valid_mats)
            if prev_selected in valid_mats:
                w.setCurrentText(prev_selected)

        # Also verify all TDS materials are present.
        # Remove any that are not.
        self.prune_invalid_tds_materials()
        self.on_selected_tds_material_changed()

    def on_selected_tds_material_changed(self):
        self.update_tds_gui()

    def tds_setup_default_material_if_missing(self):
        mat_name = self.selected_tds_material
        if mat_name not in self.tds_settings:
            self.tds_settings[mat_name] = self._default_tds_new_material_settings

    def on_include_tds_model_toggled(self):
        self.tds_setup_default_material_if_missing()
        settings = self.tds_settings[self.selected_tds_material]

        # Verify we can enable TDS for this material
        mat = HexrdConfig().material(self.selected_tds_material)

        if mat.sgnum not in VALID_TDS_SGNUMS:
            valid_str = ', '.join([str(i) for i in VALID_TDS_SGNUMS])
            msg = f'TDS currently only supports the following space groups: {valid_str}'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            print(msg, file=sys.stderr)
            self.update_tds_gui()
            return

        settings['enabled'] = self.ui.include_tds_model.isChecked()
        self.update_tds_gui()

    def on_tds_model_type_changed(self):
        self.tds_setup_default_material_if_missing()
        settings = self.tds_settings[self.selected_tds_material]
        settings['model_type'] = self.ui.tds_model_type.currentText()
        self.update_tds_gui()

    def update_tds_temperature_atom_types(self):
        mat = HexrdConfig().material(self.selected_tds_material)

        if mat is not None:
            options = [ct.ptableinverse[x] for x in mat.atom_type]

            w = self.ui.tds_temperature_atom_type
            prev = w.currentText()
            with block_signals(w):
                w.clear()
                w.addItems(options)

                if prev in options:
                    w.setCurrentIndex(options.index(prev))

    def on_tds_temperature_atom_type_changed(self):
        # Load the saved Debye temperature, if available
        self.update_tds_debye_temperature()
        self.update_tds_equivalent_temperature()

    def on_tds_debye_temperature_value_changed(self):
        # Save the modified Debye temperature so we will remember it
        self.save_tds_debye_temperature()
        self.update_tds_equivalent_temperature()

    def update_tds_equivalent_temperature(self):
        enabled = self.tds_settings.get(self.selected_tds_material, {}).get(
            'enabled', False
        )
        if not enabled:
            # This is not visible, so don't bother updating.
            return

        mat = HexrdConfig().material(self.selected_tds_material)
        mat_rietveld = Material_Rietveld(material_obj=mat)

        selected_atom_type = self.ui.tds_temperature_atom_type.currentText()
        debye_temperatures = {
            selected_atom_type: self.ui.tds_debye_temperature.value(),
        }
        output = mat_rietveld.calc_temperature(debye_temperatures)
        equiv_temp = output[selected_atom_type]
        text = f'{equiv_temp:.2f} K'
        self.ui.tds_computed_equivalent_temperature.setText(text)

    def on_tds_select_experimental_data_file_clicked(self):
        default_path = self.ui.tds_experimental_data_file.currentText()
        if not default_path:
            default_path = HexrdConfig().working_dir

        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui,
            'Select Experiment File',
            default_path,
            'XY files (*.xy)',
        )

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            self.ui.tds_experimental_data_file.setText(selected_file)

    def save_tds_experimental_settings(self):
        self.tds_setup_default_material_if_missing()
        settings = self.tds_settings[self.selected_tds_material]

        experimental_settings = settings['experimental']
        experimental_settings['data_file'] = self.ui.tds_experimental_data_file.text()
        experimental_settings['scale'] = self.ui.tds_experimental_scale.value()
        experimental_settings['shift'] = self.ui.tds_experimental_shift.value()

    def update_tds_enabled(self):
        is_rietveld = self.method == 'Rietveld'
        self.ui.tds_tab.setEnabled(is_rietveld)

    def update_tds_gui(self):
        self.update_tds_enabled()
        self.tds_setup_default_material_if_missing()
        settings = self.tds_settings[self.selected_tds_material]

        model_type = settings['model_type']
        is_enabled = settings['enabled']

        with block_signals(self.ui.tds_model_type):
            self.ui.tds_model_type.setCurrentText(model_type)

        with block_signals(self.ui.include_tds_model):
            self.ui.include_tds_model.setChecked(is_enabled)

        is_experimental = model_type == 'experimental'

        self.ui.tds_model_type_label.setEnabled(is_enabled)
        self.ui.tds_model_type.setEnabled(is_enabled)
        self.ui.tds_temperature_settings_group.setVisible(is_enabled)
        self.ui.tds_experimental_settings_group.setVisible(
            is_enabled and is_experimental
        )

        experimental_settings = settings['experimental']
        self.ui.tds_experimental_data_file.setText(experimental_settings['data_file'])
        self.ui.tds_experimental_scale.setValue(experimental_settings['scale'])
        self.ui.tds_experimental_shift.setValue(experimental_settings['shift'])

        self.update_tds_temperature_atom_types()
        self.update_tds_debye_temperature()
        self.update_tds_equivalent_temperature()

        self.ui.plot_tds.setEnabled(self.any_tds_models_enabled)

    def update_tds_debye_temperature(self):
        self.tds_setup_default_material_if_missing()
        settings = self.tds_settings[self.selected_tds_material]

        selected_atom_type = self.ui.tds_temperature_atom_type.currentText()

        temperature_settings = settings['debye_temperatures']
        debye_temperature = temperature_settings.setdefault(selected_atom_type, 200)
        self.ui.tds_debye_temperature.setValue(debye_temperature)

    def save_tds_debye_temperature(self):
        self.tds_setup_default_material_if_missing()
        settings = self.tds_settings[self.selected_tds_material]

        selected_atom_type = self.ui.tds_temperature_atom_type.currentText()

        temperature_settings = settings['debye_temperatures']
        temperature_settings[selected_atom_type] = self.ui.tds_debye_temperature.value()

    @property
    def _default_tds_new_material_settings(self) -> dict:
        return {
            'enabled': False,
            'model_type': 'warren',
            'debye_temperatures': {},
            'experimental': self._default_tds_experimental_settings,
        }

    @property
    def _default_tds_experimental_settings(self) -> dict:
        return {
            'data_file': '',
            'scale': 1.0,
            'shift': 0.0,
        }

    @property
    def any_tds_models_enabled(self) -> bool:
        if self.method != 'Rietveld':
            return False

        for settings in self.tds_settings.values():
            if settings.get('enabled', False):
                return True

        return False

    def update_rietveld_tds_model(self):
        if not isinstance(self._wppf_object, Rietveld):
            # Nothing to do
            return

        # Update the TDS model on the Rietveld object
        self.set_tds_model(self._wppf_object)

    def set_tds_model(self, obj: Rietveld):
        if not self.any_tds_models_enabled:
            # If there are no TDS models, just set the tds model to None
            obj.tds_model = None
            return

        # Make a default TDS model with all warren model types
        tds = TDS(
            model_type='warren',
            phases=obj.phases,
            tth=obj.tth_list,
        )

        # Loop through the materials. Delete any TDS_material objects
        # that should NOT be modeled. Also update any material objects
        # that are not warren.
        for mat_name, settings in self.tds_settings.items():
            if not settings.get('enabled', False):
                # This material shouldn't be modeled. Eliminate it.
                tds.TDSmodels.pop(mat_name, None)
                continue

            for wlen_name, tds_mat in tds.TDSmodels[mat_name].items():
                _set_tds_settings_to_tds_material(settings, tds_mat)

        # Set the TDS model. The smoothing will be updated automatically.
        obj.tds_model = tds


def generate_params(
    method, materials, peak_shape, bkgmethod, amorphous_model, texture_model
):
    func_dict = {
        'LeBail': _generate_default_parameters_LeBail,
        'Rietveld': _generate_default_parameters_Rietveld,
    }
    if method not in func_dict:
        raise Exception(f'Unknown method: {method}')

    kwargs = {
        'amorphous_model': amorphous_model,
    }
    if method == 'Rietveld':
        kwargs['texture_model'] = texture_model

    return func_dict[method](
        materials,
        peak_shape,
        bkgmethod,
        **kwargs,
    )


def param_to_dict(param):
    return _dict_to_basic(
        {
            'name': param.name,
            'value': param.value,
            'min': param.min,
            'max': param.max,
            'vary': param.vary,
        }
    )


def dict_to_param(d):
    # Exclude stderr when converting a dict to a param
    if 'stderr' in d:
        d = d.copy()
        del d['stderr']

    d = _dict_to_basic(d.copy())
    return lmfit.Parameter(**d)


# Ensure dict values are basic types, and not numpy types
def _dict_to_basic(d):
    for k, v in list(d.items()):
        if isinstance(v, np.generic):
            d[k] = v.item()

    return d


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

    def on_boolean_toggled(self, b, path):
        pass


class DeltaWPPFTreeItemModel(DeltaCalibrationTreeItemModel):
    COLUMNS = {
        **DeltaCalibrationTreeItemModel.COLUMNS,
        'Uncertainty': '_stderr',
    }
    COLUMN_INDICES = _tree_columns_to_indices(COLUMNS)
    UNEDITABLE_COLUMN_INDICES = [COLUMN_INDICES['Uncertainty']]

    def on_boolean_toggled(self, b, path):
        pass


def changed_signal(w):
    if isinstance(w, QCheckBox):
        return w.toggled
    elif isinstance(w, QComboBox):
        return w.currentIndexChanged

    return w.valueChanged


nm_to_angstroms_funcs = {
    'to_display': lambda x: x * 10,
    'from_display': lambda x: x / 10,
}


shkl_to_angstroms_minus_4_funcs = {
    'to_display': lambda x: x / 1000,
    'from_display': lambda x: x * 1000,
}


mat_ly_to_s_funcs = {
    'to_display': lambda ly: ly * 100 * np.pi / 18000,
    'from_display': lambda s: s / 100 / np.pi * 18000,
    'to_display_stderr': lambda ly, ly_stderr: 100 * np.pi / 18000 * ly_stderr,
}


def mat_lx_to_p_funcs_factory(wlen: float) -> dict:
    k = 0.91

    def to_display(lx: float):
        if abs(lx) <= 1e-8:
            return np.inf
        elif np.isinf(lx):
            return 0

        return 18000 * k * wlen / np.pi / lx

    def from_display(p: float):
        if abs(p) <= 1e-8:
            return np.inf
        elif np.isinf(p):
            return 0

        return 18000 * k * wlen / np.pi / p

    def to_display_stderr(lx: float, lx_stderr: float) -> float:
        return 18000 * k * wlen / np.pi / (lx**2) * lx_stderr

    return {
        'to_display': to_display,
        'from_display': from_display,
        'to_display_stderr': to_display_stderr,
    }


def mat_gp_to_p_funcs_factory(wlen: float) -> dict:
    k = 0.91

    def to_display(gp: float) -> float:
        if abs(gp) <= 1e-8:
            return np.inf
        elif np.isinf(gp):
            return 0

        return 18000 * k * wlen / np.pi / np.sqrt(gp)

    def from_display(p: float) -> float:
        if abs(p) <= 1e-8:
            return np.inf
        elif np.isinf(p):
            return 0

        return (18000 * k * wlen / np.pi / p) ** 2

    def to_display_stderr(gp: float, gp_stderr: float) -> float:
        return 9000 * k * wlen / np.pi / (gp**1.5) * gp_stderr

    return {
        'to_display': to_display,
        'from_display': from_display,
        'to_display_stderr': to_display_stderr,
    }


def _set_tds_settings_to_tds_material(tds_mat_settings: dict, tds_mat: TDS_material):
    tds_mat.model_type = tds_mat_settings['model_type']
    if tds_mat.model_type == 'experimental':
        # Set the relevant experimental settings
        tds_mat.model_data = np.loadtxt(tds_mat_settings['data_file'])
        tds_mat.scale = tds_mat_settings['scale']
        tds_mat.shift = tds_mat_settings['shift']


if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication

    app = QApplication()

    dialog = WppfOptionsDialog()
    dialog.ui.exec()

    print(f'{dialog.method=}')
    print(f'{dialog.background_method=}')
    print(f'{dialog.experiment_file=}')
    print(f'{dialog.params=}')
