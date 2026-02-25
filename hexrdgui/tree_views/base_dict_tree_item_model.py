from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from typing import Any

from PySide6.QtCore import (
    QAbstractItemModel,
    QItemSelection,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QContextMenuEvent, QCursor
from PySide6.QtWidgets import QAbstractItemView, QMenu, QMessageBox, QTreeView, QWidget

from hexrdgui.tree_views.base_tree_item_model import BaseTreeItemModel
from hexrdgui.tree_views.tree_item import TreeItem


# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL


class BaseDictTreeItemModel(BaseTreeItemModel):

    dict_modified = Signal(QModelIndex)

    def __init__(
        self,
        dictionary: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        # These can be modified anytime
        self.lists_resizable = True
        self._blacklisted_paths: list[list[str | int]] = []
        self.disabled_paths: list[tuple[str | int, ...]] = []
        self.editable = True

        self.config = dictionary

    def path_to_value(
        self,
        tree_item: TreeItem,
        column: int,
    ) -> list[str | int]:
        # Subclasses must implement this
        raise NotImplementedError

    def recursive_add_tree_items(
        self,
        cur_config: Any,
        cur_tree_item: TreeItem,
    ) -> None:
        # Subclasses must implement this
        raise NotImplementedError

    def config_path(self, path: list[str | int]) -> Any:
        # Return any nested path from the config for viewing/editing
        config: Any = self.config
        for entry in path:
            config = config[entry]

        return config

    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        item = self.get_item(index)

        # If they are identical, don't do anything
        if value == item.data(index.column()):
            return True

        path = self.path_to_value(item, index.column())
        if index.column() != KEY_COL:
            old_value = self.config_val(path)

            # As a validation step, ensure that the new value can be
            # converted to the old value's type
            try:
                value = type(old_value)(value)
            except ValueError:
                msg = (
                    f'Could not convert {value} to type ' f'{type(old_value).__name__}'
                )
                QMessageBox.warning(None, 'HEXRD', msg)
                return False

        item.set_data(index.column(), value)

        self.set_config_val(path, value)
        self.dict_modified.emit(index)

        return True

    def removeRows(
        self,
        row: int,
        count: int,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> bool:
        item = self.get_item(parent)
        for _ in range(count):
            if row >= len(item.child_items):
                return False

            # First, remove the value from the config
            path = self.path_to_item(item.child_items[row])
            self.del_config_val(path)

            # Next, remove the value from the tree item
            item.child_items.pop(row)

            parent_val = self.config_val(path[:-1])
            if isinstance(parent_val, (tuple, list)):
                # If the parent was a tuple or list, re-number the keys
                # (this assumes the keys are the indices)
                self.renumber_list_keys(item)

        return True

    def insertRows(
        self,
        row: int,
        count: int,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> bool:
        # This will not add data to the items. The data must be
        # added in a separate function.
        parent_item = self.get_item(parent)
        for _ in range(count):
            item = TreeItem([0] * self.columnCount(parent))
            item.parent_item = parent_item
            parent_item.child_items.insert(row, item)

        return True

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag(0)

        flags = super().flags(index)
        item = self.get_item(index)

        if self.has_disabled_paths:
            path = self.path_to_item(item)
            if self.is_disabled_path(path):
                flags = flags & ~Qt.ItemFlag.ItemIsEnabled
                return flags

        # Items are selectable if they have no children
        # and none of the data values in the row are `None`.
        is_selectable = all(
            (
                item.child_count() == 0,
                not any(x is None for x in item.data_list),
            )
        )
        if is_selectable:
            flags = flags | Qt.ItemFlag.ItemIsSelectable
        else:
            flags = flags & ~Qt.ItemFlag.ItemIsSelectable

        is_editable = all(
            (
                index.column() != KEY_COL,
                item.child_count() == 0,
                self.editable,
            )
        )

        if is_editable:
            # All columns after the first with no children are editable
            flags = flags | Qt.ItemFlag.ItemIsEditable

        return flags

    def create_index(
        self,
        path: list[str | int],
        column: int = 0,
    ) -> QModelIndex:
        # Create an index, given a path

        def recurse(
            item: TreeItem,
            cur_path: list[str | int],
        ) -> QModelIndex | None:
            for i, child_item in enumerate(item.child_items):
                if child_item.data(KEY_COL) == cur_path[0]:
                    if len(cur_path) == 1:
                        return self.createIndex(
                            child_item.row(),
                            column,
                            child_item,
                        )
                    else:
                        return recurse(child_item, cur_path[1:])

            return None

        return recurse(self.root_item, path)  # type: ignore[return-value]

    def remove_items(self, items: list[TreeItem]) -> None:
        for item in items:
            row = item.row()
            parent = item.parent_item
            assert parent is not None
            index = self.createIndex(parent.row(), 0, parent)
            self.beginRemoveRows(index, row, row)
            self.removeRow(row, index)
            self.endRemoveRows()

    def insert_items(
        self,
        items: list[TreeItem],
        parent_item: TreeItem,
        position: int,
    ) -> None:
        parent_path = self.path_to_item(parent_item)
        if not isinstance(self.config_val(parent_path), list):
            # Inserting items is only supported for list
            raise NotImplementedError(type(self.config_val(parent_path)))

        num_items = len(items)
        end_position = position + num_items - 1
        parent_index = self.createIndex(parent_item.row(), 0, parent_item)
        self.beginInsertRows(parent_index, position, end_position)
        self.insertRows(position, num_items, parent_index)
        self.endInsertRows()

        # Set the data for these items
        for i, item in enumerate(items, position):
            # Over-write the added tree items with the provided items
            parent_item.child_items[i] = item
            item.parent_item = parent_item

        data_list = [item.data_list[1:] for item in parent_item.child_items]
        self.set_config_val(parent_path, data_list)

        # Renumber the list keys. This will also flag that the data
        # has been changed.
        self.renumber_list_keys(parent_item)

    def rebuild_tree(self) -> None:
        # Rebuild the tree from scratch
        self.clear()
        self.recursive_add_tree_items(self.config, self.root_item)

    def path_to_item(
        self,
        tree_item: TreeItem,
    ) -> list[str | int]:
        path: list[str | int] = []
        cur_tree_item: TreeItem | None = tree_item
        while cur_tree_item is not self.root_item:
            assert cur_tree_item is not None
            text = cur_tree_item.data(KEY_COL)
            path.insert(0, text)
            cur_tree_item = cur_tree_item.parent_item

        return path

    def config_val(self, path: list[str | int]) -> Any:
        """This obtains a dict value from a path list"""
        cur_val: Any = self.config
        try:
            for val in path:
                cur_val = cur_val[val]
        except KeyError:
            msg = f'Path: {path}\n' f'was not found in dict: {self.config}'
            raise Exception(msg)

        return cur_val

    def set_config_val(
        self,
        path: list[str | int],
        value: Any,
    ) -> None:
        """This sets a value from a path list"""
        cur_val: Any = self.config
        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            cur_val[path[-1]] = value
        except KeyError:
            msg = f'Path: {path}\n' f'was not found in dict: {self.config}'
            raise Exception(msg)

    def del_config_val(
        self,
        path: list[str | int],
    ) -> None:
        """Delete a config value from a path"""
        cur_val: Any = self.config
        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            del cur_val[path[-1]]
        except KeyError:
            msg = f'Path: {path}\n' f'was not found in dict: {self.config}'
            raise Exception(msg)

    def renumber_list_keys(self, item: TreeItem) -> None:
        # This should be called after a list item was deleted to renumber
        # the sibling items' keys.
        for child_item in item.child_items:
            child_item.set_data(0, child_item.row())
            index = self.createIndex(child_item.row(), 0, child_item)
            self.dataChanged.emit(index, index)

    @property
    def blacklisted_paths(self) -> list[list[str | int]]:
        return self._blacklisted_paths

    @blacklisted_paths.setter
    def blacklisted_paths(
        self,
        v: list[Sequence[str | int]],
    ) -> None:
        # Make sure it is a list of lists, so we can do things like
        # "x in self.blacklisted_paths", where x is a list.
        self._blacklisted_paths = [list(x) for x in v]
        self.rebuild_tree()

    @property
    def has_disabled_paths(self) -> bool:
        return bool(self.disabled_paths)

    def is_disabled_path(
        self,
        path: list[str | int] | tuple[str | int, ...],
    ) -> bool:
        path = tuple(path)
        for disabled_path in self.disabled_paths:
            if path[: len(disabled_path)] == disabled_path:
                return True

        return False


class BaseDictTreeView(QTreeView):

    selection_changed = Signal(QItemSelection, QItemSelection)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._combo_keys: Any = []

    def model(self) -> BaseDictTreeItemModel:
        return super().model()  # type: ignore[return-value]

    def setModel(
        self,
        model: QAbstractItemModel | None,
    ) -> None:
        # Override to add a connection
        super().setModel(model)
        if selection_model := self.selectionModel():
            selection_model.selectionChanged.connect(self.selection_changed)

    def rebuild_tree(self) -> None:
        self.model().rebuild_tree()

    def expand_rows(
        self,
        parent: QModelIndex = QModelIndex(),
        rows: list[int] | None = None,
    ) -> None:
        if rows is None:
            # Perform expandRecursively(), as it is *significantly* faster.
            self.expandRecursively(parent)
            return

        # If there are certain rows selected for expansion, we have to do
        # it ourselves.

        # Recursively expands rows
        row_count = self.model().rowCount(parent)
        for i in rows:
            if i >= row_count:
                continue

            index = self.model().index(i, KEY_COL, parent)
            if self.model().hasChildren(index):
                self.expand(index)
                self.expand_rows(index)

    def collapse_disabled_paths(self) -> None:
        model = self.model()
        for path in model.disabled_paths:
            index = model.create_index(list(path))
            self.collapse(index)

    @property
    def lists_resizable(self) -> bool:
        return self.model().lists_resizable

    @lists_resizable.setter
    def lists_resizable(self, v: bool) -> None:
        self.model().lists_resizable = v

    @property
    def blacklisted_paths(self) -> list[list[str | int]]:
        return self.model().blacklisted_paths

    @blacklisted_paths.setter
    def blacklisted_paths(
        self,
        v: list[Sequence[str | int]],
    ) -> None:
        self.model().blacklisted_paths = v
        self.expand_rows()

    @property
    def combo_keys(self) -> Any:
        return self._combo_keys

    @combo_keys.setter
    def combo_keys(self, v: Any) -> None:
        """Should have the following structure:
        {
            ('path', 'to', 'parent'): {
                'option1': option1_defaults,
                'option2': option2_defaults,
            }
        }
        """

        self._combo_keys = v
        self.rebuild_tree()
        self.expand_rows()

    @property
    def editable(self) -> bool:
        return self.model().editable

    @editable.setter
    def editable(self, v: bool) -> None:
        self.model().editable = v

    @property
    def selection_mode(
        self,
    ) -> QTreeView.SelectionMode:
        return self.selectionMode()

    @selection_mode.setter
    def selection_mode(
        self,
        v: QTreeView.SelectionMode,
    ) -> None:
        self.setSelectionMode(v)

    def set_single_selection_mode(self) -> None:
        self.selection_mode = QAbstractItemView.SelectionMode.SingleSelection

    def set_multi_selection_mode(self) -> None:
        self.selection_mode = QAbstractItemView.SelectionMode.MultiSelection

    def set_extended_selection_mode(self) -> None:
        self.selection_mode = QAbstractItemView.SelectionMode.ExtendedSelection

    @property
    def selected_rows(self) -> list[QModelIndex]:
        return self.selectionModel().selectedRows()

    @property
    def selected_items(self) -> list[TreeItem]:
        return [self.model().get_item(x) for x in self.selected_rows]

    def clear_selection(self) -> None:
        self.selectionModel().clearSelection()

    def contextMenuEvent(
        self,
        event: QContextMenuEvent,
    ) -> None:
        # Generate the actions
        actions = {}

        index = self.indexAt(event.pos())
        model = self.model()
        item = model.get_item(index)
        path = tuple(model.path_to_value(item, index.column()))
        parent_element = model.config_val(list(path[:-1])) if path else None
        menu = QMenu(self)

        # Helper functions
        def add_actions(d: dict) -> None:
            actions.update({menu.addAction(k): v for k, v in d.items()})

        def add_separator() -> None:
            if not actions:
                return
            menu.addSeparator()

        def rebuild_gui() -> None:
            self.rebuild_tree()
            self.expand_rows()

        # Callbacks for different actions
        def insert_list_item() -> None:
            assert parent_element is not None
            value_type = type(parent_element[0]) if parent_element else int
            parent_element.insert(path[-1], value_type(0))
            rebuild_gui()

        def remove_list_item() -> None:
            assert parent_element is not None
            parent_element.pop(path[-1])
            rebuild_gui()

        def change_combo_item(
            old: str | int,
            new: str | int,
            value: Any,
        ) -> None:
            assert parent_element is not None
            del parent_element[old]
            parent_element[new] = value
            rebuild_gui()

        # Add any actions that need to be added
        if isinstance(path[-1], int) and self.lists_resizable:
            assert parent_element is not None
            # The item right-clicked is part of a list
            new_actions = {
                'Insert Item': insert_list_item,
            }

            # Don't let the user remove the last item from the list,
            # or they may get stuck with an invalid config.
            if len(parent_element) > 1:
                new_actions['Remove Item'] = remove_list_item

            add_separator()
            add_actions(new_actions)

        # "path" must be a tuple for this to work
        if path[:-1] in self.combo_keys:
            options = self.combo_keys[path[:-1]]
            old_key = path[-1]
            if old_key in options:
                new_actions = {}
                for name, default in options.items():
                    if name == old_key:
                        continue

                    label = f'Change to {name}'
                    func = partial(change_combo_item, old_key, name, default)
                    new_actions[label] = func

                add_separator()
                add_actions(new_actions)

        if not actions:
            # No context menu
            return super().contextMenuEvent(event)

        # Open up the context menu
        action_chosen = menu.exec(QCursor.pos())

        if action_chosen is None:
            # No action chosen
            return super().contextMenuEvent(event)

        # Run the function for the action that was chosen
        actions[action_chosen]()

        return super().contextMenuEvent(event)
