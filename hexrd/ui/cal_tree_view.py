from PySide2.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide2.QtWidgets import QMessageBox, QTreeView

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


class CalTreeItemModel(QAbstractItemModel):

    def __init__(self, parent=None):
        super(CalTreeItemModel, self).__init__(parent)
        self.root_item = TreeItem(['key', 'value'])
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
        return item.data(index.column())

    def setData(self, index, value, role):
        item = self.get_item(index)

        # If they are identical, don't do anything
        if value == item.data(1):
            return True

        path = self.get_path_from_root(item)
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

        self.cfg.set_instrument_config_val(path, value)
        item.set_data(1, value)
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super(CalTreeItemModel, self).flags(index)

        item = self.get_item(index)
        if index.column() == 1 and item.child_count() == 0:
            # The second column with no children is editable
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

        return self.createIndex(parent_item.row(), 0, parent_item)

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
        self.beginRemoveRows(QModelIndex(), 0, root.child_count() - 1)
        root.clear_children()
        self.endRemoveRows()

    def rebuild_tree(self):
        # Rebuild the tree from scratch
        self.clear()
        for key in self.cfg.instrument_config.keys():
            tree_item = self.add_tree_item(key, None, self.root_item)
            self.recursive_add_tree_items(self.cfg.instrument_config[key],
                                          tree_item)

    def add_tree_item(self, key, value, parent):
        data = [key, value]
        tree_item = TreeItem(data, parent)
        return tree_item

    def recursive_add_tree_items(self, cur_config, cur_tree_item):
        if isinstance(cur_config, dict):
            keys = cur_config.keys()
        elif isinstance(cur_config, list):
            keys = range(len(cur_config))
        else:
            # This must be a value. Set it.
            cur_tree_item.set_data(1, str(cur_config))
            return

        for key in keys:
            tree_item = self.add_tree_item(key, None, cur_tree_item)
            self.recursive_add_tree_items(cur_config[key], tree_item)

    def get_path_from_root(self, tree_item):
        path = []
        cur_tree_item = tree_item
        while True:
            text = cur_tree_item.data(0)
            if _is_int(text):
                text = int(text)

            path.insert(0, text)
            cur_tree_item = cur_tree_item.parent_item
            if cur_tree_item is self.root_item:
                break

        return path


class CalTreeView(QTreeView):

    def __init__(self, parent=None):
        super(CalTreeView, self).__init__(parent)
        self.setModel(CalTreeItemModel(self))
        self.expand_rows()

        self.header().resizeSection(0, 200)
        self.header().resizeSection(1, 200)

    def rebuild_tree(self):
        # We rebuild it from scratch every time it is shown in case
        # the number of detectors have changed.
        self.model().rebuild_tree()
        self.expand_rows()

    def expand_rows(self, parent=QModelIndex()):
        # Recursively expands all rows except for the detectors
        for i in range(self.model().rowCount(parent)):
            index = self.model().index(i, 0, parent)

            # Don't expand detectors
            item = self.model().get_item(index)
            parent_item = item.parent_item
            if parent_item and parent_item.data(0) != 'detectors':
                self.expand(index)

            self.expand_rows(index)


def _is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False
