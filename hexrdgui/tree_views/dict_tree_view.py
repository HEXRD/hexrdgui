from PySide6.QtWidgets import QDialog, QVBoxLayout

from hexrdgui.tree_views.base_dict_tree_item_model import (
    BaseTreeItemModel, BaseDictTreeItemModel, BaseDictTreeView
)
from hexrdgui.tree_views.tree_item import TreeItem
from hexrdgui.tree_views.value_column_delegate import ValueColumnDelegate


# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL
VALUE_COL = KEY_COL + 1


class DictTreeItemModel(BaseDictTreeItemModel):

    def __init__(self, dictionary, parent=None):
        super().__init__(dictionary, parent)

        self.root_item = TreeItem(['key', 'value'])
        self.rebuild_tree()

    def recursive_add_tree_items(self, cur_config, cur_tree_item):
        if isinstance(cur_config, dict):
            keys = cur_config.keys()
        elif isinstance(cur_config, list):
            keys = range(len(cur_config))
        else:
            # This must be a value.
            cur_tree_item.set_data(VALUE_COL, cur_config)
            return

        for key in keys:
            path = self.path_to_value(cur_tree_item, 0) + [key]
            if path in self.blacklisted_paths or str(key).startswith('_'):
                continue

            data = [key, None]
            tree_item = self.add_tree_item(data, cur_tree_item)
            self.recursive_add_tree_items(cur_config[key], tree_item)

    def path_to_value(self, tree_item, column):
        return self.path_to_item(tree_item)


class DictTreeView(BaseDictTreeView):

    def __init__(self, dictionary, model=DictTreeItemModel, parent=None):
        super().__init__(parent)

        self.setModel(model(dictionary, parent=self))
        self.setItemDelegateForColumn(
            VALUE_COL, ValueColumnDelegate(self))

        self.resizeColumnToContents(KEY_COL)
        self.resizeColumnToContents(VALUE_COL)

        self.header().resizeSection(KEY_COL, 200)
        self.header().resizeSection(VALUE_COL, 200)


class DictTreeViewDialog(QDialog):

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)

        self.setLayout(QVBoxLayout(self))

        self.tree_view = DictTreeView(dictionary, parent=self)
        self.layout().addWidget(self.tree_view)

        self.resize(500, 500)

    def expand_rows(self):
        return self.tree_view.expand_rows()

    @property
    def editable(self):
        return self.tree_view.editable

    @editable.setter
    def editable(self, v):
        self.tree_view.editable = v

    def set_single_selection_mode(self):
        self.tree_view.set_single_selection_mode()

    def set_multi_selection_mode(self):
        self.tree_view.set_multi_selection_mode()

    def set_extended_selection_mode(self):
        self.tree_view.set_extended_selection_mode()

    @property
    def selected_items(self):
        return self.tree_view.selected_items
