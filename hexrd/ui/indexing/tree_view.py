from PySide2.QtCore import QModelIndex, Qt
from PySide2.QtWidgets import QMessageBox, QTreeView

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.tree_views.base_tree_item_model import BaseTreeItemModel
from hexrd.ui.tree_views.tree_item import TreeItem
from hexrd.ui.tree_views.value_column_delegate import ValueColumnDelegate


# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL
VALUE_COL = BaseTreeItemModel.VALUE_COL


class IndexingTreeItemModel(BaseTreeItemModel):

    def __init__(self, parent=None):
        super(IndexingTreeItemModel, self).__init__(parent)
        self.root_item = TreeItem(['key', 'value'])
        self.config = HexrdConfig().indexing_config
        self.rebuild_tree()

    def data(self, index, role):
        if not index.isValid():
            return None

        if role != Qt.DisplayRole and role != Qt.EditRole:
            return None

        item = self.get_item(index)
        return item.data(index.column())

    def setData(self, index, value, role):
        item = self.get_item(index)
        path = self.get_path_from_root(item, index.column())

        # If they are identical, don't do anything
        if value == item.data(index.column()):
            return True

        if index.column() == VALUE_COL:
            old_value = self.get_config_val(path)

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
            self.set_config_val(path, value)

        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super(IndexingTreeItemModel, self).flags(index)

        item = self.get_item(index)
        if index.column() == VALUE_COL and item.child_count() == 0:
            # The second column with no children is editable
            flags = flags | Qt.ItemIsEditable

        return flags

    def rebuild_tree(self):
        # Rebuild the tree from scratch
        self.clear()
        for key in self.config.keys():
            tree_item = self.add_tree_item(key, None, self.root_item)
            self.recursive_add_tree_items(self.config[key], tree_item)

    def recursive_add_tree_items(self, cur_config, cur_tree_item):
        if isinstance(cur_config, dict):
            keys = cur_config.keys()
        elif isinstance(cur_config, list):
            keys = range(len(cur_config))
        else:
            # This must be a value. Set it.
            cur_tree_item.set_data(VALUE_COL, cur_config)
            return

        for key in keys:
            tree_item = self.add_tree_item(key, None, cur_tree_item)
            self.recursive_add_tree_items(cur_config[key], tree_item)

    def get_path_from_root(self, tree_item, column):
        path = []
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

    def get_config_val(self, path):
        """This obtains a dict value from a path list"""
        cur_val = self.config
        try:
            for val in path:
                cur_val = cur_val[val]
        except KeyError:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.config))
            raise Exception(msg)

        return cur_val

    def set_config_val(self, path, value):
        """This sets a value from a path list"""
        cur_val = self.config
        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            cur_val[path[-1]] = value
        except KeyError:
            msg = ('Path: ' + str(path) + '\nwas not found in dict: ' +
                   str(self.config))
            raise Exception(msg)


class IndexingTreeView(QTreeView):

    def __init__(self, parent=None):
        super(IndexingTreeView, self).__init__(parent)
        self.setModel(IndexingTreeItemModel(self))
        self.setItemDelegateForColumn(
            VALUE_COL, ValueColumnDelegate(self))

        self.resizeColumnToContents(KEY_COL)
        self.resizeColumnToContents(VALUE_COL)

        self.header().resizeSection(KEY_COL, 200)
        self.header().resizeSection(VALUE_COL, 200)

        self.expand_rows()

        self.setup_connections()

    def setup_connections(self):
        pass

    def rebuild_tree(self):
        self.model().rebuild_tree()

    def expand_rows(self, parent=QModelIndex()):
        # Recursively expands all rows
        for i in range(self.model().rowCount(parent)):
            index = self.model().index(i, KEY_COL, parent)
            self.expand(index)
            self.expand_rows(index)


def _is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False
