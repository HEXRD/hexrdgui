from __future__ import annotations

from collections.abc import Sequence
from typing import Any, overload

from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from hexrdgui.tree_views.tree_item import TreeItem

KEY_COL = 0


class BaseTreeItemModel(QAbstractItemModel):

    KEY_COL = KEY_COL

    # Subclasses must define root_item
    root_item: TreeItem

    def columnCount(
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return self.root_item.column_count()

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return self.root_item.data(section)

        return None

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return

        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return

        item = self.get_item(index)
        return item.data(index.column())

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_item = self.get_item(parent)
        child_item = parent_item.child(row)
        if not child_item:
            return QModelIndex()

        return self.createIndex(row, column, child_item)

    @overload
    def parent(self) -> QObject: ...
    @overload
    def parent(self, index: QModelIndex | QPersistentModelIndex) -> QModelIndex: ...
    def parent(
        self, index: QModelIndex | QPersistentModelIndex | None = None
    ) -> QObject | QModelIndex:
        if index is None:
            return super().parent()

        if not index.isValid():
            return QModelIndex()

        child_item = self.get_item(index)
        parent_item = child_item.parent_item
        if not parent_item or parent_item is self.root_item:
            return QModelIndex()

        return self.createIndex(parent_item.row(), KEY_COL, parent_item)

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        parent_item = self.get_item(parent)
        return parent_item.child_count()

    def get_item(self, index: QModelIndex | QPersistentModelIndex) -> TreeItem:
        # If the index is valid and the internal pointer is valid,
        # return the item. Otherwise, return the root item.
        if index.isValid():
            item = index.internalPointer()
            if item:
                return item

        return self.root_item

    def clear(self) -> None:
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

    def add_tree_item(
        self,
        data: Sequence[object],
        parent: TreeItem,
    ) -> TreeItem:
        return TreeItem(data, parent)
