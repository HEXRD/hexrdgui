from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt

from hexrdgui.tree_views.tree_item import TreeItem

KEY_COL = 0


class BaseTreeItemModel(QAbstractItemModel):

    KEY_COL = KEY_COL

    def columnCount(self, parent):
        return self.root_item.column_count()

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.root_item.data(section)

        return None

    def data(self, index, role):
        if not index.isValid():
            return

        if role not in (Qt.DisplayRole, Qt.EditRole):
            return

        item = self.get_item(index)
        return item.data(index.column())

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

        # We need to do begin/endResetModel() rather than begin/endRemoveRows()
        # because it was buggy when we were using the row version before.
        # I think the issue was that some parts of the item model were not
        # being notified that the data was modified (maybe a dataChanged() was
        # needed). However, since we are deleting everything, it is simpler
        # to just do a full ResetModel().
        self.beginResetModel()
        root.clear_children()
        self.endResetModel()

    def add_tree_item(self, data, parent):
        return TreeItem(data, parent)
