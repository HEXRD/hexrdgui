from PySide2.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide2.QtWidgets import QMessageBox, QTreeView, QMenu, QCheckBox, QStyledItemDelegate
from PySide2.QtGui import QCursor

from hexrd.ui.hexrd_config import HexrdConfig


class TreeItem:
    # A simple TreeItem class to be used with QTreeView...

    def __init__(self, data_list, parent_item=None):
        self.data_list = data_list
        self.parent_item = parent_item
        self.child_items = []
        if self.parent_item:
            # Add itself automatically to its parent's children...
            self.parent_item.append_child(self)

    def append_child(self, child):
        self.child_items.append(child)

    def child(self, row):
        if row < 0 or row >= len(self.child_items):
            return None

        return self.child_items[row]

    def child_count(self):
        return len(self.child_items)

    def clear_children(self):
        self.child_items.clear()

    def column_count(self):
        return len(self.data_list)

    def data(self, column):
        if column < 0 or column >= len(self.data_list):
            return None
        return self.data_list[column]

    def set_data(self, column, val):
        if column < 0 or column >= len(self.data_list):
            return
        self.data_list[column] = val

    def row(self):
        if self.parent_item:
            return self.parent_item.child_items.index(self)
        return 0


# Global constants
REFINED = 0
FIXED = 1

KEY_COL = 0
VALUE_COL = 1
STATUS_COL = 2

class CalTreeItemModel(QAbstractItemModel):

    """Emitted when data has changed in tree view"""
    tree_data_changed = Signal()

    def __init__(self, parent=None):
        super(CalTreeItemModel, self).__init__(parent)
        self.root_item = TreeItem(['key', 'value', 'fixed'])
        self.cfg = HexrdConfig()
        self.rebuild_tree()

    def columnCount(self, parent):
        return self.root_item.column_count()

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

        if index.column() == VALUE_COL:
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
        self.tree_data_changed.emit()

        if item.child_count() == 0:
            self.cfg.set_instrument_config_val(path, value)

        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super(CalTreeItemModel, self).flags(index)

        item = self.get_item(index)
        if ((index.column() == VALUE_COL and item.child_count() == 0)
            or index.column() == STATUS_COL):
            # The second and third columns with no children are editable
            flags = flags | Qt.ItemIsEditable

        return flags

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.root_item.data(section)

        return None

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_item = self.get_item(parent)
        child_item = parent_item.child(row)
        if not child_item:
            return QModelIndex()

        return self.createIndex(row, column, child_item)

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        child_item = self.get_item(index)
        parent_item = child_item.parent_item
        if not parent_item or parent_item is self.root_item:
            return QModelIndex()

        return self.createIndex(parent_item.row(), KEY_COL, parent_item)

    def rowCount(self, parent=QModelIndex()):
        parent_item = self.get_item(parent)
        return parent_item.child_count()

    def get_item(self, index):
        # If the index is valid and the internal pointer is valid,
        # return the item. Otherwise, return the root item.
        if index.isValid():
            item = index.internalPointer()
            if item:
                return item

        return self.root_item

    def clear(self):
        # Remove all of the root item children. That clears it.
        root = self.root_item
        self.beginRemoveRows(QModelIndex(), KEY_COL, root.child_count() - 1)
        root.clear_children()
        self.endRemoveRows()

    def rebuild_tree(self):
        # Rebuild the tree from scratch
        self.clear()
        for key in self.cfg.internal_instrument_config.keys():
            tree_item = self.add_tree_item(key, None, REFINED, self.root_item)
            self.recursive_add_tree_items(self.cfg.internal_instrument_config[key],
                                          tree_item)
            self.update_parent_status(tree_item)

    def add_tree_item(self, key, value, status, parent):
        data = [key, value, status]
        tree_item = TreeItem(data, parent)
        return tree_item

    def set_value(self, key, cur_config, cur_tree_item):
        if isinstance(cur_config, list):
            children = cur_tree_item.child_items
            for child in children:
                value = cur_config[child.data(KEY_COL)]
                child.set_data(VALUE_COL, value)
        else:
            cur_tree_item.set_data(VALUE_COL, cur_config)
        return

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
                tree_item = self.add_tree_item(key, None, REFINED, cur_tree_item)
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
                path = self.parent().model().get_path_from_root(child, STATUS_COL)
                self.parent().model().cfg.set_instrument_config_val(path, value)
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
            STATUS_COL, CheckBoxDelegate(self))
        self.expand_rows()
        self.resizeColumnToContents(KEY_COL)
        self.resizeColumnToContents(VALUE_COL)
        self.resizeColumnToContents(STATUS_COL)

        self.header().resizeSection(KEY_COL, 200)
        self.header().resizeSection(VALUE_COL, 200)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        item = self.model().get_item(index)
        children = item.child_count()

        if index.column() == KEY_COL:
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
                self.collapseAll()
            elif action == expand:
                self.expandAll()
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
        self.expand_rows()

    def expand_rows(self, parent=QModelIndex()):
        # Recursively expands all rows
        for i in range(self.model().rowCount(parent)):
            index = self.model().index(i, KEY_COL, parent)
            editor_idx = self.model().index(i, STATUS_COL, parent)

            item = self.model().get_item(index)
            self.expand(index)

            if item.child_count() == 0 and not isinstance(item.data(VALUE_COL), str):
                self.openPersistentEditor(editor_idx)

            self.expand_rows(index)


def _is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False
