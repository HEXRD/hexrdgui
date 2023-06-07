import copy
import yaml

from PySide2.QtCore import QObject, Qt, Signal
from PySide2.QtWidgets import QComboBox, QDoubleSpinBox, QMessageBox, QSpinBox

from hexrd.ui import resource_loader
from hexrd.ui.tree_views.multi_column_dict_tree_view import (
    MultiColumnDictTreeItemModel, MultiColumnDictTreeView
)
from hexrd.ui.pinhole_correction_editor import PinholeCorrectionEditor
from hexrd.ui.ui_loader import UiLoader

import hexrd.ui.calibration.structureless


class StructurelessCalibrationDialog(QObject):

    draw_picks_toggled = Signal(bool)

    edit_picks_clicked = Signal()
    save_picks_clicked = Signal()
    load_picks_clicked = Signal()
    engineering_constraints_changed = Signal(str)

    pinhole_correction_settings_modified = Signal()

    run = Signal()
    undo_run = Signal()
    finished = Signal()

    def __init__(self, instr, params_dict, parent=None,
                 engineering_constraints=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('structureless_calibration_dialog.ui',
                                   parent)

        self.ui.setWindowFlags(self.ui.windowFlags() | Qt.Tool)

        self.pinhole_correction_editor = PinholeCorrectionEditor(self.ui)
        self.ui.pinhole_distortion_layout.addWidget(
            self.pinhole_correction_editor.ui)
        self.pinhole_correction_editor.apply_panel_buffer_visible = False
        self.pinhole_correction_editor.settings_modified.connect(
            self.on_pinhole_correction_settings_modified)

        self.instr = instr
        self._params_dict = params_dict
        self.engineering_constraints = engineering_constraints

        self.initialize_advanced_options()

        self.load_tree_view_mapping()
        self.initialize_tree_view()

        self.load_settings()
        self.setup_connections()

    def setup_connections(self):
        self.ui.draw_picks.toggled.connect(self.on_draw_picks_toggled)
        self.ui.engineering_constraints.currentIndexChanged.connect(
            self.on_engineering_constraints_changed)
        self.ui.edit_picks_button.clicked.connect(self.on_edit_picks_clicked)
        self.ui.save_picks_button.clicked.connect(self.on_save_picks_clicked)
        self.ui.load_picks_button.clicked.connect(self.on_load_picks_clicked)
        self.ui.run_button.clicked.connect(self.on_run_button_clicked)
        self.ui.undo_run_button.clicked.connect(
            self.on_undo_run_button_clicked)
        self.ui.finished.connect(self.finish)

    def show(self):
        self.ui.show()

    def hide(self):
        self.ui.hide()

    def load_settings(self):
        pass

    def initialize_advanced_options(self):
        self.ui.advanced_options_group.setVisible(
            self.ui.show_advanced_options.isChecked())

        self.advanced_options = self.default_advanced_options

    @property
    def default_advanced_options(self):
        return {
            "ftol": 1e-8,
            "xtol": 1e-8,
            "gtol": 1e-8,
            "verbose": 2,
            "max_nfev": 1000,
            # Skip x_scale until we find a way to present it in the GUI
            # "x_scale": "jac",
            "method": "trf",
            "jac": "3-point",
        }

    @property
    def advanced_options(self):
        options = {}
        for key in self.default_advanced_options:
            # Widget name is the same name as the key
            w = getattr(self.ui, key)
            if isinstance(w, (QSpinBox, QDoubleSpinBox)):
                v = w.value()
            elif isinstance(w, QComboBox):
                v = w.currentText()
            else:
                raise NotImplementedError(w)

            options[key] = v

        return options

    @advanced_options.setter
    def advanced_options(self, odict):
        for key in self.default_advanced_options:
            if key not in odict:
                continue

            v = odict[key]
            w = getattr(self.ui, key)
            if isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setValue(v)
            elif isinstance(w, QComboBox):
                w.setCurrentText(v)
            else:
                raise NotImplementedError(w)

    def on_draw_picks_toggled(self, b):
        self.draw_picks_toggled.emit(b)

    def on_run_button_clicked(self):
        self.clear_polar_view_tth_correction()
        self.run.emit()

    def on_undo_run_button_clicked(self):
        self.clear_polar_view_tth_correction()
        self.undo_run.emit()

    def finish(self):
        self.clear_polar_view_tth_correction(False)
        self.finished.emit()

    @property
    def params_dict(self):
        return self._params_dict

    @params_dict.setter
    def params_dict(self, v):
        self._params_dict = v
        self.update_tree_view()

    @property
    def undo_enabled(self):
        return self.ui.undo_run_button.isEnabled()

    @undo_enabled.setter
    def undo_enabled(self, b):
        self.ui.undo_run_button.setEnabled(b)

    @property
    def engineering_constraints(self):
        return self.ui.engineering_constraints.currentText()

    @engineering_constraints.setter
    def engineering_constraints(self, v):
        v = str(v)
        w = self.ui.engineering_constraints
        options = [w.itemText(i) for i in range(w.count())]
        if v not in options:
            raise Exception(f'Invalid engineering constraint: {v}')

        w.setCurrentText(v)

    def on_edit_picks_clicked(self):
        self.clear_polar_view_tth_correction()
        self.edit_picks_clicked.emit()

    def on_save_picks_clicked(self):
        self.save_picks_clicked.emit()

    def on_load_picks_clicked(self):
        self.load_picks_clicked.emit()

    @property
    def tth_distortion(self):
        return self.pinhole_correction_editor.create_object_dict(self.instr)

    @tth_distortion.setter
    def tth_distortion(self, v):
        if v is None:
            self.pinhole_correction_editor.correction_type = None
            return

        # They should all have identical settings. Just take the first one.
        first = next(iter(v.values()))
        self.pinhole_correction_editor.update_from_object(first)

    def on_engineering_constraints_changed(self):
        self.engineering_constraints_changed.emit(self.engineering_constraints)

    def update_from_calibrator(self, calibrator):
        self.engineering_constraints = calibrator.engineering_constraints
        self.tth_distortion = calibrator.tth_distortion
        self.params_dict = calibrator.params

    def load_tree_view_mapping(self):
        module = hexrd.ui.calibration.structureless
        text = resource_loader.load_resource(module, 'params_tree_view.yml')
        self.yaml_tree_view = yaml.safe_load(text)

    @property
    def tree_view_dict_of_params(self):
        params_dict = self.params_dict

        tree_dict = {}
        template_dict = copy.deepcopy(self.yaml_tree_view)

        # Keep track of which params have been used.
        used_params = []

        def create_param_item(param):
            used_params.append(param.name)
            return {
                '_param': param,
                '_value': param.value,
                '_vary': bool(param.vary),
                '_min': param.min,
                '_max': param.max,
            }

        # Treat these root keys specially
        special_cases = [
            'detectors',
            'Debye-Scherrer ring means',
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

        # Now generate the detectors
        detector_template = template_dict['detectors'].pop('{det}')

        def recursively_format_det(det, this_config, this_template):
            for k, v in this_template.items():
                if isinstance(v, dict):
                    this_config.setdefault(k, {})
                    recursively_format_det(det, this_config[k], v)
                elif k == 'distortion parameters':
                    # Special case. Generate distortion parameters if needed.
                    template = '{det}_distortion_param_{i}'
                    i = 0
                    current = template.format(det=det, i=i)
                    while current in params_dict:
                        param = params_dict[current]
                        # Wait to create this dict until now
                        # (when we know that we have at least one parameter)
                        this_dict = this_config.setdefault(k, {})
                        this_dict[i + 1] = create_param_item(param)
                        i += 1
                        current = template.format(det=det, i=i)
                else:
                    # Should be a string. Replace {det} with det if needed
                    if '{det}' in v:
                        v = v.format(det=det)

                    if v in params_dict:
                        this_config[k] = create_param_item(params_dict[v])

        det_dict = tree_dict.setdefault('detectors', {})
        for det_key in self.instr.detectors:
            this_config = det_dict.setdefault(det_key, {})
            this_template = copy.deepcopy(detector_template)

            # For the parameters, we need to convert dashes to underscores
            det = det_key.replace('-', '_')
            recursively_format_det(det, this_config, this_template)

        # Now make the debye scherrer ring means
        key = 'Debye-Scherrer ring means'
        template = 'DS_ring_{i}'
        i = 0
        current = template.format(i=i)
        while current in params_dict:
            param = params_dict[current]
            # Wait to create this dict until now
            # (when we know that we have at least one parameter)
            this_dict = tree_dict.setdefault(key, {})
            this_dict[i + 1] = create_param_item(param)
            i += 1
            current = template.format(i=i)

        # Now all keys should have been used. Verify this is true.
        if sorted(used_params) != sorted(list(params_dict)):
            used = ', '.join(sorted(used_params))
            params = ', '.join(sorted(params_dict))
            msg = (
                f'Internal error: used_params ({used}) did not match '
                f'params_dict! ({params})'
            )
            raise Exception(msg)

        return tree_dict

    def initialize_tree_view(self):
        if hasattr(self, 'tree_view'):
            # It has already been initialized
            return

        columns = {
            'Value': '_value',
            'Vary': '_vary',
            'Minimum': '_min',
            'Maximum': '_max',
        }
        tree_dict = self.tree_view_dict_of_params
        self.tree_view = MultiColumnDictTreeView(tree_dict, columns,
                                                 parent=self.parent(),
                                                 model_class=TreeItemModel)
        self.tree_view.check_selection_index = 2
        self.ui.tree_view_layout.addWidget(self.tree_view)

        # Make the key section a little larger
        self.tree_view.header().resizeSection(0, 300)

    def update_tree_view(self):
        tree_dict = self.tree_view_dict_of_params
        self.tree_view.model().config = tree_dict
        self.tree_view.reset_gui()

    def on_pinhole_correction_settings_modified(self):
        self.pinhole_correction_settings_modified.emit()

    def clear_polar_view_tth_correction(self, show_warning=True):
        editor = self.pinhole_correction_editor
        if editor.apply_to_polar_view:
            if show_warning:
                msg = (
                    'Polar view correction will be disabled for this operation'
                )
                QMessageBox.information(self.parent(), 'HEXRD', msg)
            editor.apply_to_polar_view = False


class TreeItemModel(MultiColumnDictTreeItemModel):
    """Subclass the tree item model so we can customize some behavior"""
    def set_config_val(self, path, value):
        super().set_config_val(path, value)
        # Now set the parameter too
        param_path = path[:-1] + ['_param']
        try:
            param = self.config_val(param_path)
        except KeyError:
            raise Exception('Failed to set parameter!', param_path)

        # Now set the attribute on the param
        attribute = path[-1].removeprefix('_')
        setattr(param, attribute, value)
