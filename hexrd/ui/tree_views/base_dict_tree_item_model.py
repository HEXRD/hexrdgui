from functools import partial

from PySide2.QtCore import QItemSelection, QModelIndex, Qt, Signal
from PySide2.QtGui import QCursor
from PySide2.QtWidgets import QMenu, QMessageBox, QTreeView

from hexrd.ui.tree_views.base_tree_item_model import BaseTreeItemModel
from hexrd.ui.tree_views.tree_item import TreeItem
from hexrd.ui.utils import is_int


# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL


class BaseDictTreeItemModel(BaseTreeItemModel):

    dict_modified = Signal()

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)

        # These can be modified anytime
        self.lists_resizable = True
        self._blacklisted_paths = []
        self.editable = True

        self.config = dictionary

    def setData(self, index, value, role=Qt.EditRole):
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
                msg = (f'Could not convert {value} to type '
                       f'{type(old_value).__name__}')
                QMessageBox.warning(None, 'HEXRD', msg)
                return False

        item.set_data(index.column(), value)

        self.set_config_val(path, value)
        self.dict_modified.emit()

        return True

    def removeRows(self, row, count, parent):
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

    def insertRows(self, row, count, parent):
        # This will not add data to the items. The data must be
        # added in a separate function.
        parent_item = self.get_item(parent)
        for _ in range(count):
            item = TreeItem([0] * self.columnCount(parent))
            item.parent_item = parent_item
            parent_item.child_items.insert(row, item)

        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super().flags(index)
        item = self.get_item(index)

        # Items are selectable if they have no children
        # and none of the data values in the row are `None`.
        is_selectable = all((
            item.child_count() == 0,
            not any(x is None for x in item.data_list),
        ))
        if is_selectable:
            flags = flags | Qt.ItemIsSelectable
        else:
            flags = flags & ~Qt.ItemIsSelectable

        is_editable = all((
            index.column() != KEY_COL,
            item.child_count() == 0,
            self.editable,
        ))

        if is_editable:
            # All columns after the first with no children are editable
            flags = flags | Qt.ItemIsEditable

        return flags

    def remove_items(self, items):
        for item in items:
            row = item.row()
            parent = item.parent_item
            index = self.createIndex(parent.row(), 0, parent)
            self.beginRemoveRows(index, row, row)
            self.removeRow(row, index)
            self.endRemoveRows()

    def insert_items(self, items, parent_item, position):
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

    def rebuild_tree(self):
        # Rebuild the tree from scratch
        self.clear()
        self.recursive_add_tree_items(self.config, self.root_item)

    def path_to_item(self, tree_item):
        path = []
        cur_tree_item = tree_item
        while cur_tree_item is not self.root_item:
            text = cur_tree_item.data(KEY_COL)
            text = int(text) if is_int(text) else text
            path.insert(0, text)
            cur_tree_item = cur_tree_item.parent_item

        return path

    def config_val(self, path):
        """This obtains a dict value from a path list"""
        cur_val = self.config
        try:
            for val in path:
                cur_val = cur_val[val]
        except KeyError:
            msg = f'Path: {path}\nwas not found in dict: {self.config}'
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
            msg = f'Path: {path}\nwas not found in dict: {self.config}'
            raise Exception(msg)

    def del_config_val(self, path):
        """Delete a config value from a path"""
        cur_val = self.config
        try:
            for val in path[:-1]:
                cur_val = cur_val[val]

            del cur_val[path[-1]]
        except KeyError:
            msg = f'Path: {path}\nwas not found in dict: {self.config}'
            raise Exception(msg)

    def renumber_list_keys(self, item):
        # This should be called after a list item was deleted to renumber
        # the sibling items' keys.
        for child_item in item.child_items:
            child_item.set_data(0, child_item.row())
            index = self.createIndex(child_item.row(), 0, child_item)
            self.dataChanged.emit(index, index)

    @property
    def blacklisted_paths(self):
        return self._blacklisted_paths

    @blacklisted_paths.setter
    def blacklisted_paths(self, v):
        # Make sure it is a list of lists, so we can do things like
        # "x in self.blacklisted_paths", where x is a list.
        self._blacklisted_paths = [list(x) for x in v]
        self.rebuild_tree()


class BaseDictTreeView(QTreeView):

    selection_changed = Signal(QItemSelection, QItemSelection)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._combo_keys = []

    def setModel(self, model):
        # Override to add a connection
        super().setModel(model)
        if selection_model := self.selectionModel():
            selection_model.selectionChanged.connect(self.selection_changed)

    def rebuild_tree(self):
        self.model().rebuild_tree()

    def expand_rows(self, parent=QModelIndex()):
        # Recursively expands all rows
        for i in range(self.model().rowCount(parent)):
            index = self.model().index(i, KEY_COL, parent)
            self.expand(index)
            self.expand_rows(index)

    @property
    def lists_resizable(self):
        return self.model().lists_resizable

    @property
    def blacklisted_paths(self):
        return self.model().blacklisted_paths

    @blacklisted_paths.setter
    def blacklisted_paths(self, v):
        self.model().blacklisted_paths = v
        self.expand_rows()

    @property
    def combo_keys(self):
        return self._combo_keys

    @combo_keys.setter
    def combo_keys(self, v):
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
    def editable(self):
        return self.model().editable

    @editable.setter
    def editable(self, v):
        self.model().editable = v

    @property
    def selection_mode(self):
        return self.selectionMode()

    @selection_mode.setter
    def selection_mode(self, v):
        self.setSelectionMode(v)

    def set_single_selection_mode(self):
        self.selection_mode = QTreeView.SingleSelection

    def set_multi_selection_mode(self):
        self.selection_mode = QTreeView.MultiSelection

    def set_extended_selection_mode(self):
        self.selection_mode = QTreeView.ExtendedSelection

    @property
    def selected_rows(self):
        return self.selectionModel().selectedRows()

    @property
    def selected_items(self):
        return [self.model().get_item(x) for x in self.selected_rows]

    def contextMenuEvent(self, event):
        # Generate the actions
        actions = {}

        index = self.indexAt(event.pos())
        model = self.model()
        item = model.get_item(index)
        path = tuple(model.path_to_value(item, index.column()))
        parent_element = model.config_val(path[:-1]) if path else None
        menu = QMenu(self)

        # Helper functions
        def add_actions(d: dict):
            actions.update({menu.addAction(k): v for k, v in d.items()})

        def add_separator():
            if not actions:
                return
            menu.addSeparator()

        def rebuild_gui():
            self.rebuild_tree()
            self.expand_rows()

        # Callbacks for different actions
        def insert_list_item():
            value_type = type(parent_element[0]) if parent_element else int
            parent_element.insert(path[-1], value_type(0))
            rebuild_gui()

        def remove_list_item():
            parent_element.pop(path[-1])
            rebuild_gui()

        def change_combo_item(old, new, value):
            del parent_element[old]
            parent_element[new] = value
            rebuild_gui()

        # Add any actions that need to be added
        if isinstance(path[-1], int) and self.lists_resizable:
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
        action_chosen = menu.exec_(QCursor.pos())

        if action_chosen is None:
            # No action chosen
            return super().contextMenuEvent(event)

        # Run the function for the action that was chosen
        actions[action_chosen]()

        return super().contextMenuEvent(event)
