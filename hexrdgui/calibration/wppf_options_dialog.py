import copy
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np
import re
import yaml

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox

from hexrdgui import resource_loader
from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict
from hexrd.material import _angstroms
from hexrd.wppf import LeBail, Rietveld
from hexrd.wppf.parameters import Parameter
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
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('wppf_options_dialog.ui', parent)
        self.ui.setWindowTitle('WPPF Options Dialog')

        self.populate_background_methods()
        self.populate_peakshape_methods()

        self.dynamic_background_widgets = []

        self.spline_points = []
        self._wppf_object = None
        self._prev_background_method = None
        self._undo_stack = []

        self.params = self.generate_params()
        self.initialize_tree_view()

        self.load_settings()

        # Default setting for delta boundaries
        self.delta_boundaries = False

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.method.currentIndexChanged.connect(self.on_method_changed)
        self.ui.select_materials_button.pressed.connect(self.select_materials)
        self.ui.peak_shape.currentIndexChanged.connect(self.update_params)
        self.ui.background_method.currentIndexChanged.connect(
            self.update_background_parameters)
        self.ui.delta_boundaries.toggled.connect(
            self.on_delta_boundaries_toggled)
        self.ui.select_experiment_file_button.pressed.connect(
            self.select_experiment_file)
        self.ui.display_wppf_plot.toggled.connect(
            self.display_wppf_plot_toggled)
        self.ui.edit_plot_style.pressed.connect(self.edit_plot_style)
        self.ui.pick_spline_points.clicked.connect(self.pick_spline_points)

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
        self.params.param_dict = self.generate_params().param_dict
        self.update_tree_view()

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

    def update_gui(self):
        with block_signals(self.ui.display_wppf_plot):
            self.display_wppf_plot = HexrdConfig().display_wppf_plot
            self.update_background_parameters()
            self.update_tree_view()

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
        params_dict = self.params.param_dict

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
                    # Assume it is a string. Grab it if in the params dict.
                    if v in params_dict:
                        this_config[k] = create_param_item(params_dict[v])
                        param_set = True

            return param_set

        # First, recursively set items (except special cases)
        recursively_set_items(tree_dict, template_dict)

        # If the background method is chebyshev, fill those in
        if self.background_method == 'chebyshev':
            # Put the background first
            tree_dict = {'Background': {}, **tree_dict}
            background = tree_dict['Background']
            i = 0
            while f'bkg_{i}' in params_dict:
                background[i] = create_param_item(params_dict[f'bkg_{i}'])
                i += 1

        # Now generate the materials
        materials_template = template_dict['Materials'].pop('{mat}')

        def recursively_format_site_id(mat, site_id, this_config,
                                       this_template):
            for k, v in this_template.items():
                if isinstance(v, dict):
                    this_config.setdefault(k, {})
                    recursively_format_site_id(mat, site_id, this_config[k], v)
                else:
                    # Should be a string. Replace {mat} and {site_id} if needed
                    kwargs = {}
                    if '{mat}' in v:
                        kwargs['mat'] = mat

                    if '{site_id}' in v:
                        kwargs['site_id'] = site_id

                    if kwargs:
                        v = v.format(**kwargs)

                    if v in params_dict:
                        this_config[k] = create_param_item(params_dict[v])

        def recursively_format_mat(mat, this_config, this_template):
            for k, v in this_template.items():
                if k == 'Atomic Site: {site_id}':
                    # Identify all site IDs by regular expression
                    expr = re.compile(f'^{mat}_(.*)_x$')
                    site_ids = []
                    for name in params_dict:
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
                        v = v.format(mat=mat)

                    if v in params_dict:
                        this_config[k] = create_param_item(params_dict[v])

        mat_dict = tree_dict.setdefault('Materials', {})
        for mat in self.selected_materials:
            this_config = mat_dict.setdefault(mat, {})
            this_template = copy.deepcopy(materials_template)

            # For the parameters, we need to convert dashes to underscores
            mat = mat.replace('-', '_')
            recursively_format_mat(mat, this_config, this_template)

        # Now all keys should have been used. Verify this is true.
        if sorted(used_params) != sorted(list(params_dict)):
            used = ', '.join(sorted(used_params))
            params = ', '.join(sorted(params_dict))
            msg = (
                f'Internal error: used_params ({used})\n\ndid not match '
                f'params_dict! ({params})'
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

    @property
    def all_widgets(self):
        names = [
            'method',
            'refinement_steps',
            'peak_shape',
            'background_method',
            'experiment_file',
            'display_wppf_plot',
        ]
        return [getattr(self.ui, x) for x in names]

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
            # Make a deep copy of the materials so that WPPF
            # won't modify any arrays in place shared by our materials.
            'phases': copy.deepcopy(self.materials),
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

        param_dict = self.params.param_dict
        export_data = {k: param_to_dict(v) for k, v in param_dict.items()}

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

        self.update_tree_view()

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

    def push_undo_stack(self):
        settings = HexrdConfig().config['calibration'].get('wppf', {})

        stack_item = {
            'settings': settings,
            'spline_points': self.spline_points,
            'method': self.method,
            'refinement_steps': self.refinement_steps,
            'peak_shape': self.peak_shape,
            'background_method': self.background_method,
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
    # Exclude stderr when converting a dict to a param
    if 'stderr' in d:
        d = d.copy()
        del d['stderr']

    return Parameter(**d)


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
