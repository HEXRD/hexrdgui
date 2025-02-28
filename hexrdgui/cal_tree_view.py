from PySide6.QtCore import QObject, QModelIndex, Qt
from PySide6.QtWidgets import (
    QCheckBox, QMenu, QMessageBox, QStyledItemDelegate, QTreeView
)
from PySide6.QtGui import QCursor

import numpy as np

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.tree_views.base_tree_item_model import BaseTreeItemModel
from hexrdgui.tree_views.tree_item import TreeItem
from hexrdgui.tree_views.value_column_delegate import ValueColumnDelegate
from hexrdgui import constants
from hexrdgui.utils import is_int

# Global constants
FIXED = 0
REFINABLE = 1

KEY_COL = BaseTreeItemModel.KEY_COL
VALUE_COL = KEY_COL + 1
STATUS_COL = VALUE_COL + 1


class CalTreeItemModel(BaseTreeItemModel):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root_item = TreeItem(['key', 'value', 'refinable'])
        self.cfg = HexrdConfig()
        self.rebuild_tree()

    def data(self, index, role):
        if not index.isValid():
            return None

        if role != Qt.DisplayRole and role != Qt.EditRole:
            return None

        item = self.get_item(index)

        value = item.data(index.column())
        if index.column() == STATUS_COL:
            if role == Qt.EditRole:
                return value
            if role == Qt.DisplayRole:
                return None

        if isinstance(value, np.generic):
            # Get a native python type for display. Otherwise,
            # it won't display anything...
            value = value.item()

        return value

    def setData(self, index, value, role):
        item = self.get_item(index)
        path = self.path_to_value(item, index.column())

        # If they are identical, don't do anything
        # (we exclude np.ndarray's from this)
        is_numpy = isinstance(value, np.ndarray) or \
            isinstance(item.data(index.column()), np.ndarray)
        if not is_numpy and value == item.data(index.column()):
            return True

        key = item.data(KEY_COL)
        # Note: We don't want todo this check for panel buffers as they
        # can be a list or numpy.ndarray
        if index.column() == VALUE_COL and key != constants.BUFFER_KEY:
            old_value = self.cfg.get_instrument_config_val(path)

            # As a validation step, ensure that the new value can be
            # converted to the old value's type
            try:
                value = type(old_value)(value)
            except ValueError:
                msg = ('Could not convert ' + str(value) + ' to type ' +
                       str(type(old_value).__name__))
                QMessageBox.warning(None, 'HEXRD', msg)
                return False

        item.set_data(index.column(), value)

        if item.child_count() == 0:
            parent = item.parent_item.data(KEY_COL)
            chi_path = ['oscillation_stage', 'chi', 'value']
            if path == chi_path:
                # Convert to radians before saving
                value = np.radians(value).item()
            if (parent == 'tilt' and
                    HexrdConfig().rotation_matrix_euler() is not None and
                    len(path) > 1 and path[-2] == 'value'):
                # Convert tilt values to radians before saving
                value = np.radians(value).item()
            self.cfg.set_instrument_config_val(path, value)
            dist_func_path = ['distortion', 'function_name', 'value']
            if len(path) > 4 and path[2:5] == dist_func_path:
                # Rebuild the tree if the distortion function changed
                QObject.parent(self).rebuild_tree()

        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super(CalTreeItemModel, self).flags(index)

        item = self.get_item(index)

        non_editable_keys = (
            'detector_type',
            'group',
        )

        non_editable_parent_keys = (
            'roi',
        )

        # The second and third columns with no children are editable
        editable = (
            index.column() == STATUS_COL or
            (index.column() == VALUE_COL and
             item.child_count() == 0 and
             item.data(KEY_COL) not in non_editable_keys and
             item.parent_item.data(KEY_COL) not in non_editable_parent_keys)
        )

        if editable:
            flags = flags | Qt.ItemIsEditable

        return flags

    def add_tree_item(self, key, value, status, parent):
        # In the case of the panel buffer we don't want to added children
        # The editor will take care of this.
        if parent.data(KEY_COL) == constants.BUFFER_KEY:
            return

        data = [key, value, status]
        tree_item = TreeItem(data, parent)
        return tree_item

    def rebuild_tree(self):
        # Rebuild the tree from scratch
        self.clear()
        for key in self.cfg.internal_instrument_config.keys():
            tree_item = self.add_tree_item(key, None, REFINABLE,
                                           self.root_item)
            self.recursive_add_tree_items(
                self.cfg.internal_instrument_config[key], tree_item)
            self.update_parent_status(tree_item)

    def recursive_add_tree_items(self, cur_config, cur_tree_item):
        if isinstance(cur_config, dict):
            keys = cur_config.keys()
        elif isinstance(cur_config, list):
            keys = range(len(cur_config))
        else:
            # This must be a value. Set it.
            cur_tree_item.set_data(STATUS_COL, cur_config)
            return

        blacklisted_keys = []

        if ('source_distance' in keys and
                cur_config['source_distance']['value'] == np.inf):
            # Hide the source distance if it is infinite, as the infinite
            # value does not get displayed correctly by Qt
            # (maybe we need to register it as a custom type?)
            blacklisted_keys.append('source_distance')

        for key in keys:
            if key in blacklisted_keys:
                continue
            elif key == 'value':
                name = cur_tree_item.data(KEY_COL)
                data = cur_config[key]
                path = self.path_to_value(cur_tree_item, VALUE_COL)

                chi_path = ['oscillation_stage', 'chi', 'value']
                if path == chi_path:
                    data = np.degrees(data).item()
                elif (name == 'tilt' and
                      HexrdConfig().rotation_matrix_euler() is not None):
                    data = [np.degrees(rad).item() for rad in cur_config[key]]
                self.set_value(key, data, cur_tree_item)
                continue
            elif key == 'status':
                tree_item = cur_tree_item
            else:
                tree_item = self.add_tree_item(key, None, REFINABLE,
                                               cur_tree_item)
            if tree_item is not None:
                self.recursive_add_tree_items(cur_config[key], tree_item)

    def update_parent_status(self, parent):
        children = parent.child_items
        for child in children:
            if child.child_count() > 0:
                self.update_parent_status(child)
            if child.data(STATUS_COL):
                parent.set_data(STATUS_COL, FIXED)

    def path_to_value(self, tree_item, column):
        path = ['value'] if column == VALUE_COL else ['status']
        cur_tree_item = tree_item
        while True:
            text = cur_tree_item.data(KEY_COL)
            if is_int(text):
                path.append(int(text))
            else:
                path.insert(0, text)
            cur_tree_item = cur_tree_item.parent_item
            if cur_tree_item is self.root_item:
                break

        return path

    def set_value(self, key, cur_config, cur_tree_item):
        if isinstance(cur_config, list):
            children = cur_tree_item.child_items
            for child in children:
                value = cur_config[child.data(KEY_COL)]
                child.set_data(VALUE_COL, value)
        else:
            cur_tree_item.set_data(VALUE_COL, cur_config)
        return


class CheckBoxDelegate(QStyledItemDelegate):

    def __init__(self, parent=None):
        super(CheckBoxDelegate, self).__init__(parent)

    def createEditor(self, parent, option, index):
        check = QCheckBox(parent)

        # Only indicate the status has changed on user interaction
        check.clicked.connect(self.statusChanged)

        return check

    def statusChanged(self):
        self.commitData.emit(self.sender())

    def setModelData(self, check, model, index):
        item = self.parent().model().get_item(index)
        if item.child_count() > 0:
            self.setChildData(item, int(check.isChecked()))
        model.setData(index, int(check.isChecked()), Qt.DisplayRole)
        self.updateModel(index)

    def setChildData(self, parent, value):
        children = parent.child_items
        for child in children:
            child.set_data(STATUS_COL, value)
            if child.child_count() == 0:
                path = self.parent().model().path_to_value(child, STATUS_COL)
                self.parent().model().cfg.set_instrument_config_val(path,
                                                                    value)
            else:
                self.setChildData(child, value)

    def updateModel(self, index):
        end = self.parent().model().index(
            -1, STATUS_COL, self.parent().model().parent(index))
        self.parent().model().dataChanged.emit(index, end)


class CalTreeView(QTreeView):

    def __init__(self, parent=None):
        super(CalTreeView, self).__init__(parent)
        self.setModel(CalTreeItemModel(self))
        self.setItemDelegateForColumn(
            VALUE_COL, ValueColumnDelegate(self))
        self.setItemDelegateForColumn(
            STATUS_COL, CheckBoxDelegate(self))

        self.expand_all_rows()

        self.resizeColumnToContents(KEY_COL)
        self.resizeColumnToContents(VALUE_COL)
        self.resizeColumnToContents(STATUS_COL)

        self.header().resizeSection(KEY_COL, 180)
        self.header().resizeSection(VALUE_COL, 170)

        self.setup_connections()

    def setup_connections(self):
        self.collapsed.connect(self.update_collapsed_status)
        self.expanded.connect(self.update_collapsed_status)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        item = self.model().get_item(index)
        children = item.child_count()

        if index.column() == KEY_COL and children:
            menu = QMenu(self)
            collapse = menu.addAction('Collapse All')
            expand = menu.addAction('Expand All')
            check = None
            uncheck = None
            if children:
                menu.addSeparator()
                check = menu.addAction('Check All')
                uncheck = menu.addAction('Uncheck All')
            action = menu.exec(QCursor.pos())

            if action == collapse:
                self.collapse_selection(item, index)
            elif action == expand:
                self.expand_selection(item, index)
            elif action == check:
                self.itemDelegateForColumn(STATUS_COL).setChildData(
                    item, True)
                self.itemDelegateForColumn(STATUS_COL).updateModel(index)
            elif action == uncheck:
                self.itemDelegateForColumn(STATUS_COL).setChildData(
                    item, False)
                self.itemDelegateForColumn(STATUS_COL).updateModel(index)

    def rebuild_tree(self):
        # We rebuild it from scratch every time it is shown in case
        # the number of detectors have changed.
        self.model().rebuild_tree()
        self.expand_all_rows()

    def expand_all_rows(self):
        self.blockSignals(True)
        # It is *significantly* faster to recursively expand
        # all rows using Qt's function and then to collapse as
        # needed afterward.
        self.expandRecursively(QModelIndex())
        self.fix_row_states()
        self.blockSignals(False)

    def fix_row_states(self, parent=QModelIndex()):
        # Recursively fix all row states
        # This includes opening persistent editors and collapsing any
        # needed rows.
        # We performed an "expandRecursively()" earlier, as we typically
        # have everything expanded, and then we only collapse what was
        # specifically requested to be collapsed.
        collapsed_state = HexrdConfig().collapsed_state
        for i in range(self.model().rowCount(parent)):
            index = self.model().index(i, KEY_COL, parent)
            item = self.model().get_item(index)
            path = self.model().path_to_value(item, KEY_COL)

            # Force open the editor for the panel buffer values
            if item.data(KEY_COL) == constants.BUFFER_KEY:
                self.openPersistentEditor(self.model().index(i, VALUE_COL,
                                          parent))

            if collapsed_state and path in collapsed_state:
                self.collapse(index)

            self.display_status_checkbox(i, parent)

            self.fix_row_states(index)

    def expand_selection(self, parent, index):
        for child in range(parent.child_count()):
            self.expand_selection(
                parent.child_items[child],
                self.model().index(child, KEY_COL, index))
        self.expand(index)

    def collapse_selection(self, parent, index):
        for child in range(parent.child_count()):
            self.collapse_selection(
                parent.child_items[child],
                self.model().index(child, KEY_COL, index))
        self.collapse(index)

    def update_collapsed_status(self, index):
        item = self.model().get_item(index)
        path = self.model().path_to_value(item, KEY_COL)

        HexrdConfig().update_collapsed_state(path)

    # Display status checkbox for the row if the requirements are met
    def display_status_checkbox(self, row, parent=QModelIndex()):

        index = self.model().index(row, KEY_COL, parent)
        item = self.model().get_item(index)

        # If it has children, return
        if item.child_count() != 0:
            return

        # If the data is a string, return
        if isinstance(item.data(VALUE_COL), str):
            return

        # If the key is blacklisted, return
        blacklisted_keys = ['saturation_level', 'buffer', 'source_distance']
        if item.data(KEY_COL) in blacklisted_keys:
            return

        # If one of the parents of the item is blacklisted, return
        blacklisted_parents = ['pixels']
        parent_item = item.parent_item
        while parent_item is not None:
            if parent_item.data(KEY_COL) in blacklisted_parents:
                return

            parent_item = parent_item.parent_item

        # Show the checkbox
        editor_idx = self.model().index(row, STATUS_COL, parent)
        self.openPersistentEditor(editor_idx)
