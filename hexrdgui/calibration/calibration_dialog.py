import copy

import yaml

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QMessageBox, QSpinBox

from hexrd.fitting.calibration.lmfit_param_handling import (
    normalize_euler_convention,
    param_names_euler_convention,
)

from hexrdgui import resource_loader
from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.pinhole_correction_editor import PinholeCorrectionEditor
from hexrdgui.tree_views.multi_column_dict_tree_view import (
    MultiColumnDictTreeItemModel, MultiColumnDictTreeView
)
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url
from hexrdgui.utils.guess_instrument_type import guess_instrument_type

import hexrdgui.resources.calibration


class CalibrationDialog(QObject):

    draw_picks_toggled = Signal(bool)

    edit_picks_clicked = Signal()
    save_picks_clicked = Signal()
    load_picks_clicked = Signal()
    engineering_constraints_changed = Signal(str)

    pinhole_correction_settings_modified = Signal()

    run = Signal()
    undo_run = Signal()
    finished = Signal()

    def __init__(self, instr, params_dict, format_extra_params_func=None,
                 parent=None, engineering_constraints=None,
                 window_title='Calibration Dialog', help_url='calibration/'):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('calibration_dialog.ui',
                                   parent)

        self.ui.setWindowFlags(self.ui.windowFlags() | Qt.Tool)
        add_help_url(self.ui.button_box, help_url)
        self.ui.setWindowTitle(window_title)

        self.pinhole_correction_editor = PinholeCorrectionEditor(self.ui)
        editor = self.pinhole_correction_editor
        editor.update_gui_from_polar_distortion_object()
        self.ui.pinhole_distortion_layout.addWidget(editor.ui)
        editor.apply_panel_buffer_visible = False
        editor.settings_modified.connect(
            self.on_pinhole_correction_settings_modified)

        self.instr = instr
        self._params_dict = params_dict
        self.format_extra_params_func = format_extra_params_func
        self.engineering_constraints = engineering_constraints

        instr_type = guess_instrument_type(instr.detectors)
        # Use delta boundaries by default for anything other than TARDIS
        # and PXRDIP. We might want to change this to a whitelist later.
        use_delta_boundaries = instr_type not in ('TARDIS', 'PXRDIP')
        self.delta_boundaries = use_delta_boundaries

        self.initialize_advanced_options()

        self.load_tree_view_mapping()
        self.initialize_tree_view()

        self.update_edit_picks_enable_state()

        self.load_settings()
        self.setup_connections()

    def setup_connections(self):
        self.ui.draw_picks.toggled.connect(self.on_draw_picks_toggled)
        self.ui.engineering_constraints.currentIndexChanged.connect(
            self.on_engineering_constraints_changed)
        self.ui.delta_boundaries.toggled.connect(
            self.on_delta_boundaries_toggled)
        self.ui.mirror_vary_from_first_detector.clicked.connect(
            self.mirror_vary_from_first_detector)
        self.ui.edit_picks_button.clicked.connect(self.on_edit_picks_clicked)
        self.ui.save_picks_button.clicked.connect(self.on_save_picks_clicked)
        self.ui.load_picks_button.clicked.connect(self.on_load_picks_clicked)
        self.ui.run_button.clicked.connect(self.on_run_button_clicked)
        self.ui.undo_run_button.clicked.connect(
            self.on_undo_run_button_clicked)
        self.ui.finished.connect(self.finish)

        # Picks editing is currently only supported in the polar mode
        HexrdConfig().image_mode_changed.connect(
            self.update_edit_picks_enable_state)

    def show(self):
        self.ui.show()

    def hide(self):
        self.ui.hide()

    def load_settings(self):
        pass

    def update_edit_picks_enable_state(self):
        is_polar = HexrdConfig().image_mode == ViewType.polar

        polar_tooltip = ''
        not_polar_tooltip = 'Must be in polar view to edit picks'
        tooltip = polar_tooltip if is_polar else not_polar_tooltip

        self.ui.edit_picks_button.setEnabled(is_polar)
        self.ui.edit_picks_button.setToolTip(tooltip)

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
        if self.delta_boundaries:
            # If delta boundaries are being used, set the min/max according to
            # the delta boundaries. Lmfit requires min/max to run.
            self.apply_delta_boundaries()

        try:
            self.validate_parameters()
        except Exception as e:
            msg = 'Parameter settings are invalid!\n\n' + str(e)
            print(msg)
            QMessageBox.critical(self.parent(), 'Invalid Parameters', msg)
            return

        self.run.emit()

    def on_undo_run_button_clicked(self):
        self.undo_run.emit()

    def finish(self):
        self.finished.emit()

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

    def validate_parameters(self):
        # Recursively look through the tree dict, and add on errors
        config = self.tree_view.model().config
        errors = []
        path = []

        def recurse(cur):
            for k, v in cur.items():
                path.append(k)
                if '_param' in v:
                    param = v['_param']
                    if param.min > param.max:
                        full_path = '->'.join(path)
                        msg = f'{full_path}: min is greater than max'
                        errors.append(msg)
                    elif param.min == param.max:
                        # Slightly modify these to prevent lmfit
                        # from raising an exception.
                        param.min -= 1e-8
                        param.max += 1e-8
                elif isinstance(v, dict):
                    recurse(v)
                path.pop(-1)

        recurse(config)
        if errors:
            error_str = '\n\n'.join(errors)
            raise Exception(error_str)

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

    @property
    def delta_boundaries(self):
        return self.ui.delta_boundaries.isChecked()

    @delta_boundaries.setter
    def delta_boundaries(self, b):
        self.ui.delta_boundaries.setChecked(b)

    def on_edit_picks_clicked(self):
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

    def on_delta_boundaries_toggled(self, b):
        # The columns have changed, so we need to reinitialize the tree view
        self.reinitialize_tree_view()

    def mirror_vary_from_first_detector(self):
        config = self.tree_view.model().config
        detector_iterator = iter(config['detectors'])
        first_detector_name = next(detector_iterator)
        first_detector = config['detectors'][first_detector_name]
        tilts = first_detector['transform']['tilt']
        translations = first_detector['transform']['translation']

        statuses = {
            'tilt': {k: v['_param'].vary for k, v in tilts.items()},
            'translation': {
                k: v['_param'].vary for k, v in translations.items()
            },
        }

        # Now loop through all other detectors and update them
        for det_name in detector_iterator:
            detector = config['detectors'][det_name]
            for transform, transform_vary in statuses.items():
                det_transform = detector['transform'][transform]
                for k, v in transform_vary.items():
                    det_transform[k]['_param'].vary = v
                    det_transform[k]['_vary'] = v

        self.tree_view.reset_gui()

    def update_from_calibrator(self, calibrator):
        self.engineering_constraints = calibrator.engineering_constraints
        self.tth_distortion = calibrator.tth_distortion
        self.params_dict = calibrator.params

    def load_tree_view_mapping(self):
        module = hexrdgui.resources.calibration
        filename = 'calibration_params_tree_view.yml'
        text = resource_loader.load_resource(module, filename)
        self.tree_view_mapping = yaml.safe_load(text)

    @property
    def tree_view_dict_of_params(self):
        params_dict = self.params_dict

        tree_dict = {}
        template_dict = copy.deepcopy(self.tree_view_mapping)

        # Keep track of which params have been used.
        used_params = []

        def create_param_item(param):
            used_params.append(param.name)
            d = {
                '_param': param,
                '_value': param.value,
                '_vary': bool(param.vary),
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
                elif k == 'tilt':
                    # Special case. Take into account euler angles.
                    convention = HexrdConfig().euler_angle_convention
                    normalized = normalize_euler_convention(convention)
                    param_names = param_names_euler_convention(det, convention)
                    labels = TILT_LABELS_EULER[normalized]
                    this_dict = this_config.setdefault(k, {})
                    for label, param_name in zip(labels, param_names):
                        param = params_dict[param_name]
                        this_dict[label] = create_param_item(param)
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

        if self.format_extra_params_func is not None:
            self.format_extra_params_func(params_dict, tree_dict,
                                          create_param_item)

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

    @property
    def tree_view_columns(self):
        return self.tree_view_model_class.COLUMNS

    @property
    def tree_view_model_class(self):
        if self.delta_boundaries:
            return DeltaTreeItemModel
        else:
            return DefaultTreeItemModel


def _tree_columns_to_indices(columns):
    return {
        'Key': 0,
        **{
            k: list(columns).index(k) + 1 for k in columns
        }
    }


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


class DefaultTreeItemModel(TreeItemModel):
    """This model uses minimum/maximum for the boundary constraints"""
    COLUMNS = {
        'Value': '_value',
        'Vary': '_vary',
        'Minimum': '_min',
        'Maximum': '_max',
    }
    COLUMN_INDICES = _tree_columns_to_indices(COLUMNS)

    VALUE_IDX = COLUMN_INDICES['Value']
    MAX_IDX = COLUMN_INDICES['Maximum']
    MIN_IDX = COLUMN_INDICES['Minimum']
    BOUND_INDICES = (VALUE_IDX, MAX_IDX, MIN_IDX)

    def data(self, index, role):
        if role == Qt.ForegroundRole and index.column() in self.BOUND_INDICES:
            # If a value hit the boundary, color both the boundary and the
            # value red.
            item = self.get_item(index)
            if not item.child_items:
                atol = 1e-3
                pairs = [
                    (self.VALUE_IDX, self.MAX_IDX),
                    (self.VALUE_IDX, self.MIN_IDX),
                ]
                for pair in pairs:
                    if index.column() not in pair:
                        continue

                    if abs(item.data(pair[0]) - item.data(pair[1])) < atol:
                        return QColor('red')

        return super().data(index, role)


class DeltaTreeItemModel(TreeItemModel):
    """This model uses the delta for the parameters"""
    COLUMNS = {
        'Value': '_value',
        'Vary': '_vary',
        'Delta': '_delta',
    }
    COLUMN_INDICES = _tree_columns_to_indices(COLUMNS)

    VALUE_IDX = COLUMN_INDICES['Value']
    DELTA_IDX = COLUMN_INDICES['Delta']
    BOUND_INDICES = (VALUE_IDX, DELTA_IDX)

    def data(self, index, role):
        if role == Qt.ForegroundRole and index.column() in self.BOUND_INDICES:
            # If a delta is zero, color both the delta and the value red.
            item = self.get_item(index)
            if not item.child_items:
                atol = 1e-3
                if abs(item.data(self.DELTA_IDX)) < atol:
                    return QColor('red')

        return super().data(index, role)


TILT_LABELS_EULER = {
    None: ('X', 'Y', 'Z'),
    ('xyz', True): ('X', 'Y', 'Z'),
    ('zxz', False): ('Z', "X'", "Z''"),
}


def guess_engineering_constraints(instr) -> str | None:
    # First guess the instrument type.
    instr_type = guess_instrument_type(instr.detectors)

    # If it matches one of our expected engineering constraints, use it.
    expected_options = [
        'TARDIS',
    ]
    if instr_type in expected_options:
        return instr_type

    return None
