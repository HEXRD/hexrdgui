from PySide2.QtCore import QObject, QModelIndex, Qt
from PySide2.QtWidgets import (
    QCheckBox, QMenu, QMessageBox, QStyledItemDelegate, QTreeView
)
from PySide2.QtGui import QCursor

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.tree_views.base_tree_item_model import BaseTreeItemModel
from hexrd.ui.tree_views.tree_item import TreeItem
from hexrd.ui.tree_views.value_column_delegate import ValueColumnDelegate


# Global constants
REFINED = 0
FIXED = 1

KEY_COL = BaseTreeItemModel.KEY_COL
VALUE_COL = BaseTreeItemModel.VALUE_COL
STATUS_COL = VALUE_COL + 1


class CalTreeItemModel(BaseTreeItemModel):

    def __init__(self, parent=None):
        super(CalTreeItemModel, self).__init__(parent)
        self.root_item = TreeItem(['key', 'value', 'fixed'])
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
        return value

    def setData(self, index, value, role):
        item = self.get_item(index)
        path = self.get_path_from_root(item, index.column())

        # If they are identical, don't do anything
        if value == item.data(index.column()):
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
        if ((index.column() == VALUE_COL and item.child_count() == 0) or
                index.column() == STATUS_COL):
            # The second and third columns with no children are editable
            flags = flags | Qt.ItemIsEditable

        return flags

    def add_tree_item(self, key, value, status, parent):
        data = [key, value, status]
        tree_item = TreeItem(data, parent)
        return tree_item

    def rebuild_tree(self):
        # Rebuild the tree from scratch
        self.clear()
        for key in self.cfg.internal_instrument_config.keys():
            tree_item = self.add_tree_item(key, None, REFINED, self.root_item)
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

        for key in keys:
            if key == 'value':
                self.set_value(key, cur_config[key], cur_tree_item)
                continue
            elif key == 'status':
                tree_item = cur_tree_item
            else:
                tree_item = self.add_tree_item(key, None, REFINED,
                                               cur_tree_item)
            self.recursive_add_tree_items(cur_config[key], tree_item)

    def update_parent_status(self, parent):
        children = parent.child_items
        for child in children:
            if child.child_count() > 0:
                self.update_parent_status(child)
            if child.data(STATUS_COL):
                parent.set_data(STATUS_COL, FIXED)

    def get_path_from_root(self, tree_item, column):
        path = ['value'] if column == VALUE_COL else ['status']
        cur_tree_item = tree_item
        while True:
            text = cur_tree_item.data(KEY_COL)
            if _is_int(text):
                path.append(int(text))
            else:
                path.insert(0, text)
            cur_tree_item = cur_tree_item.parent_item
            if cur_tree_item is self.root_item:
                break

        return path


class CheckBoxDelegate(QStyledItemDelegate):

    def __init__(self, parent=None):
        super(CheckBoxDelegate, self).__init__(parent)

    def createEditor(self, parent, option, index):
        check = QCheckBox(parent)

        check.toggled.connect(self.statusChanged)

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
                path = self.parent().model().get_path_from_root(child,
                                                                STATUS_COL)
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

        self.blockSignals(True)
        self.expand_rows()
        self.blockSignals(False)

        self.resizeColumnToContents(KEY_COL)
        self.resizeColumnToContents(VALUE_COL)
        self.resizeColumnToContents(STATUS_COL)

        self.header().resizeSection(KEY_COL, 200)
        self.header().resizeSection(VALUE_COL, 200)

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
            action = menu.exec_(QCursor.pos())

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

        self.blockSignals(True)
        self.expand_rows()
        self.blockSignals(False)

    def expand_rows(self, parent=QModelIndex()):
        # Recursively expands all rows
        for i in range(self.model().rowCount(parent)):
            index = self.model().index(i, KEY_COL, parent)
            item = self.model().get_item(index)
            path = self.model().get_path_from_root(item, KEY_COL)

            # Force open the editor for the panel buffer values
            if item.data(KEY_COL) == constants.BUFFER_KEY:
                self.openPersistentEditor(self.model().index(i, VALUE_COL,
                                          parent))

            if (HexrdConfig().collapsed_state is None
                    or path not in HexrdConfig().collapsed_state):
                self.expand(index)

            self.display_status_checkbox(i, parent)

            self.expand_rows(index)

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
        path = self.model().get_path_from_root(item, KEY_COL)

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
        blacklisted_keys = ['saturation_level', 'buffer']
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


def _is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False
