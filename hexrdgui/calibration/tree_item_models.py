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


class DeltaCalibrationTreeItemModel(CalibrationTreeItemModel):
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
