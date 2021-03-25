from functools import partial

from PySide2.QtCore import QModelIndex, Qt
from PySide2.QtGui import QCursor
from PySide2.QtWidgets import (
    QDialog, QMenu, QMessageBox, QTreeView, QVBoxLayout
)

from hexrd.ui.tree_views.base_tree_item_model import BaseTreeItemModel
from hexrd.ui.tree_views.tree_item import TreeItem
from hexrd.ui.tree_views.value_column_delegate import ValueColumnDelegate


# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL
VALUE_COL = BaseTreeItemModel.VALUE_COL


class DictTreeItemModel(BaseTreeItemModel):

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)

        # These can be modified anytime
        self.lists_resizable = True
        self._blacklisted_paths = []

        self.root_item = TreeItem(['key', 'value'])
        self.config = dictionary
        self.rebuild_tree()

    def data(self, index, role):
        if not index.isValid():
            return

        if role != Qt.DisplayRole and role != Qt.EditRole:
            return

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
                msg = (f'Could not convert {value} to type '
                       f'{type(old_value).__name__}')
                QMessageBox.warning(None, 'HEXRD', msg)
                return False

        item.set_data(index.column(), value)

        if item.child_count() == 0:
            self.set_config_val(path, value)

        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super().flags(index)

        item = self.get_item(index)
        if index.column() == VALUE_COL and item.child_count() == 0:
            # The second column with no children is editable
            flags = flags | Qt.ItemIsEditable

        return flags

    def rebuild_tree(self):
        # Rebuild the tree from scratch
        self.clear()
        for key in self.config:
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
            path = self.get_path_from_root(cur_tree_item, 0) + [key]
            if path in self.blacklisted_paths or str(key).startswith('_'):
                continue

            tree_item = self.add_tree_item(key, None, cur_tree_item)
            self.recursive_add_tree_items(cur_config[key], tree_item)

    def get_path_from_root(self, tree_item, column):
        path = []
        cur_tree_item = tree_item
        while True:
            text = cur_tree_item.data(KEY_COL)
            text = int(text) if _is_int(text) else text
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

    @property
    def blacklisted_paths(self):
        return self._blacklisted_paths

    @blacklisted_paths.setter
    def blacklisted_paths(self, v):
        # Make sure it is a list of lists, so we can do things like
        # "x in self.blacklisted_paths", where x is a list.
        self._blacklisted_paths = [list(x) for x in v]
        self.rebuild_tree()


class DictTreeView(QTreeView):

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)

        self._combo_keys = []

        self.setModel(DictTreeItemModel(dictionary, parent=self))
        self.setItemDelegateForColumn(
            VALUE_COL, ValueColumnDelegate(self))

        self.resizeColumnToContents(KEY_COL)
        self.resizeColumnToContents(VALUE_COL)

        self.header().resizeSection(KEY_COL, 200)
        self.header().resizeSection(VALUE_COL, 200)

        self.expand_rows()

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

    def contextMenuEvent(self, event):
        # Generate the actions
        actions = {}

        index = self.indexAt(event.pos())
        model = self.model()
        item = model.get_item(index)
        path = tuple(model.get_path_from_root(item, index.column()))
        parent_element = model.get_config_val(path[:-1]) if path else None
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


class DictTreeViewDialog(QDialog):

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)

        self.setLayout(QVBoxLayout(self))

        self.dict_tree_view = DictTreeView(dictionary, self)
        self.layout().addWidget(self.dict_tree_view)

        self.resize(500, 500)


def _is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False
