from PySide2.QtCore import QAbstractItemModel, QModelIndex, Qt

from hexrd.ui.tree_views.tree_item import TreeItem

KEY_COL = 0
VALUE_COL = 1


class BaseTreeItemModel(QAbstractItemModel):

    KEY_COL = KEY_COL
    VALUE_COL = VALUE_COL

    def columnCount(self, parent):
        return self.root_item.column_count()

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

    def add_tree_item(self, key, value, parent):
        data = [key, value]
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
