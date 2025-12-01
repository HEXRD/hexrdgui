import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from hexrdgui.tree_views.multi_column_dict_tree_view import (
    MultiColumnDictTreeItemModel
)


def _tree_columns_to_indices(columns):
    return {
        'Key': 0,
        **{
            k: list(columns).index(k) + 1 for k in columns
        }
    }


class CalibrationTreeItemModel(MultiColumnDictTreeItemModel):
    """Subclass the tree item model so we can customize some behavior"""

    # The tolerance for determining if a value and one of its boundaries are
    # too close and should be colored red in the UI.
    RED_COLOR_TOLERANCE = 1e-12

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

        if attribute in ('value', 'min', 'max', 'delta'):
            # Check if there is a conversion we need to make before proceeding
            config = self.config_path(path[:-1])
            if config.get('_conversion_funcs'):
                # Apply the conversion
                value = config['_conversion_funcs']['from_display'](value)
                # Swap the min/max if they ought to be swapped
                # (due to the conversion resulting in an inverse proportionality)
                if (
                    config.get('_min_max_inverted') and
                    attribute in ('min', 'max')
                ):
                    attribute = 'max' if attribute == 'min' else 'min'

        if attribute == 'value':
            # Make sure the min/max are shifted to accomodate this value
            if value < param.min or value > param.max:
                config = self.config_path(path[:-1])
                conversion_funcs = config.get('_conversion_funcs')
                min_key = '_min'
                max_key = '_max'
                if conversion_funcs and config.get('_min_max_inverted'):
                    min_key, max_key = max_key, min_key

                def convert_if_needed(v):
                    if conversion_funcs is None:
                        return v

                    return conversion_funcs['to_display'](v)

                # Shift the min/max to accomodate, because lmfit won't
                # let us set the value otherwise.
                param.min = value - (param.value - param.min)
                param.max = value + (param.max - param.value)
                super().set_config_val(
                    path[:-1] + [min_key], convert_if_needed(param.min),
                )
                super().set_config_val(
                    path[:-1] + [max_key], convert_if_needed(param.max),
                )

                col = list(self.COLUMNS.values()).index(path[-1]) + 1
                index = self.create_index(path[:-1], col)
                self.dict_modified.emit(index)

                if '_min' in self.COLUMNS.values():
                    # Get the GUI to update
                    for name, key in zip(('_min', '_max'), (min_key, max_key)):
                        col = list(self.COLUMNS.values()).index(name) + 1
                        index = self.create_index(path[:-1], col)
                        item = self.get_item(index)
                        item.set_data(
                            index.column(),
                            convert_if_needed(getattr(param, key[1:])),
                        )
                        self.dataChanged.emit(index, index)

        setattr(param, attribute, value)

        if attribute == 'vary' and hasattr(param, '_on_vary_modified'):
            # Trigger the callback function
            param._on_vary_modified()

    def data(self, index, role):
        if (
            role in (Qt.BackgroundRole, Qt.ForegroundRole) and
            index.column() in (self.VALUE_IDX, self.VARY_IDX) and
            self.has_uneditable_paths
        ):
            # Check if this value is uneditable. If so, gray it out.
            item = self.get_item(index)
            path = tuple(self.path_to_item(item) + [self.VALUE_IDX])
            if path in self.uneditable_paths:
                color = 'gray'
                if (
                    index.column() == self.VALUE_IDX and
                    role == Qt.ForegroundRole
                ):
                    color = 'white'

                return QColor(color)

        data = super().data(index, role)

        if (
            role in (Qt.DisplayRole, Qt.EditRole) and
            index.column() in self.BOUND_INDICES and
            data is not None
        ):
            # Check if there are any units that should be displayed
            item = self.get_item(index)
            path = self.path_to_item(item)
            config = self.config_path(path)

            if role == Qt.DisplayRole and config.get('_units'):
                is_inf = isinstance(data, float) and np.isinf(data)
                # Don't attach units to infinity
                if not is_inf:
                    if isinstance(data, float):
                        # Format it into a string
                        data = f'{data:.6g}'

                    data = f"{data}{config['_units']}"

        return data


class DefaultCalibrationTreeItemModel(CalibrationTreeItemModel):
    """This model uses minimum/maximum for the boundary constraints"""
    COLUMNS = {
        'Value': '_value',
        'Vary': '_vary',
        'Minimum': '_min',
        'Maximum': '_max',
    }
    COLUMN_INDICES = _tree_columns_to_indices(COLUMNS)

    VALUE_IDX = COLUMN_INDICES['Value']
    VARY_IDX = COLUMN_INDICES['Vary']
    MAX_IDX = COLUMN_INDICES['Maximum']
    MIN_IDX = COLUMN_INDICES['Minimum']
    BOUND_INDICES = (VALUE_IDX, MAX_IDX, MIN_IDX)

    def data(self, index, role):
        if role == Qt.ForegroundRole and index.column() in self.BOUND_INDICES:
            # If a value hit the boundary, color both the boundary and the
            # value red.
            item = self.get_item(index)
            if not item.child_items and item.data(self.VALUE_IDX) is not None:
                atol = self.RED_COLOR_TOLERANCE
                pairs = [
                    (self.VALUE_IDX, self.MAX_IDX),
                    (self.VALUE_IDX, self.MIN_IDX),
                ]
                for pair in pairs:
                    if index.column() not in pair:
                        continue

                    data0 = item.data(pair[0])
                    data1 = item.data(pair[1])
                    if (
                        np.all([np.isinf(x) for x in (data0, data1)]) or
                        abs(data0 - data1) < atol
                    ):
                        return QColor('red')

        return super().data(index, role)


class DeltaCalibrationTreeItemModel(CalibrationTreeItemModel):
    """This model uses the delta for the parameters"""
    COLUMNS = {
        'Value': '_value',
        'Vary': '_vary',
        'Delta': '_delta',
    }
    COLUMN_INDICES = _tree_columns_to_indices(COLUMNS)

    VALUE_IDX = COLUMN_INDICES['Value']
    VARY_IDX = COLUMN_INDICES['Vary']
    DELTA_IDX = COLUMN_INDICES['Delta']
    BOUND_INDICES = (VALUE_IDX, DELTA_IDX)

    def data(self, index, role):
        if role == Qt.ForegroundRole and index.column() in self.BOUND_INDICES:
            # If a delta is zero, color both the delta and the value red.
            item = self.get_item(index)
            if not item.child_items and item.data(self.VALUE_IDX) is not None:
                atol = self.RED_COLOR_TOLERANCE
                if abs(item.data(self.DELTA_IDX)) < atol:
                    return QColor('red')

        return super().data(index, role)
