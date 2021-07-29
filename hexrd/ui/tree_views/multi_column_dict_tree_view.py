import numpy as np

from PySide2.QtCore import Signal, QModelIndex, Qt
from PySide2.QtWidgets import (
    QCheckBox, QDialog, QItemEditorFactory, QStyledItemDelegate, QVBoxLayout
)

from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox
from hexrd.ui.tree_views.base_dict_tree_item_model import (
    BaseDictTreeItemModel, BaseTreeItemModel, BaseDictTreeView
)
from hexrd.ui.tree_views.tree_item import TreeItem

# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL


class MultiColumnDictTreeItemModel(BaseDictTreeItemModel):

    def __init__(self, dictionary, columns, parent=None):
        super().__init__(dictionary, parent)

        self.column_labels = list(columns.keys())
        self.column_keys = list(columns.values())

        self.root_item = TreeItem(['Key'] + self.column_labels)
        self.rebuild_tree()

    def data(self, index, role):
        value = super().data(index, role)

        if isinstance(value, bool) and role == Qt.DisplayRole:
            # If it's a bool, we want to display a checkbox via
            # a persistent editor, rather than the default display.
            return

        if isinstance(value, np.generic):
            # Get a native python type for display. Otherwise,
            # it won't display anything..
            value = value.item()

        return value

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super().flags(index)

        column = index.column()
        item = self.get_item(index)
        if column != KEY_COL and item.data(column) is not None:
            # All columns after the first that isn't set to None is editable
            flags = flags | Qt.ItemIsEditable

        return flags

    def rebuild_tree(self):
        # Rebuild the tree from scratch
        self.clear()
        for key in self.config:
            data = [key] + [None] * len(self.column_keys)
            tree_item = self.add_tree_item(data, self.root_item)
            self.recursive_add_tree_items(self.config[key], tree_item)

    def recursive_add_tree_items(self, cur_config, cur_tree_item):
        def add_columns():
            for col, key in enumerate(self.column_keys, KEY_COL + 1):
                if key not in cur_config:
                    continue

                cur_tree_item.set_data(col, cur_config[key])

        def non_column_keys():
            keys = list(cur_config.keys())
            return [x for x in keys if x not in self.column_keys]

        if isinstance(cur_config, dict):
            add_columns()
            keys = non_column_keys()
        elif isinstance(cur_config, list):
            keys = range(len(cur_config))
        else:
            return

        for key in keys:
            path = self.path_to_item(cur_tree_item) + [key]
            if path in self.blacklisted_paths or str(key).startswith('_'):
                continue

            data = [key] + [None] * len(self.column_keys)
            tree_item = self.add_tree_item(data, cur_tree_item)
            self.recursive_add_tree_items(cur_config[key], tree_item)

    def path_to_value(self, tree_item, column):
        return self.path_to_item(tree_item) + [self.column_keys[column - 1]]


class MultiColumnDictTreeView(BaseDictTreeView):

    dict_modified = Signal()

    def __init__(self, dictionary, columns, parent=None):
        super().__init__(parent)

        self.setModel(MultiColumnDictTreeItemModel(dictionary, columns,
                                                   parent=self))

        self.resizeColumnToContents(0)
        self.header().resizeSection(0, 200)
        for i in range(1, len(columns) + 1):
            self.resizeColumnToContents(i)
            self.header().resizeSection(i, 150)
            self.setItemDelegateForColumn(i, ColumnDelegate(self))

        self.open_persistent_editors()
        self.expand_rows()
        self.setup_connections()

    def open_persistent_editors(self, parent=QModelIndex()):
        # If the data type is one of these, open the persistent editor
        persistent_editor_data_types = (
            bool,
        )

        rows = self.model().rowCount(parent)
        cols = self.model().columnCount(parent)

        for i in range(rows):
            key_index = self.model().index(i, KEY_COL, parent)
            item = self.model().get_item(key_index)
            for j in range(cols):
                data = item.data(j)
                if isinstance(data, persistent_editor_data_types):
                    data_index = self.model().index(i, j, parent)
                    self.openPersistentEditor(data_index)

            if item.child_count() != 0:
                self.open_persistent_editors(key_index)

    def setup_connections(self):
        self.model().dict_modified.connect(self.dict_modified.emit)

    def reset_gui(self):
        self.rebuild_tree()
        self.open_persistent_editors()
        self.expand_rows()


class MultiColumnDictTreeViewDialog(QDialog):

    dict_modified = Signal()

    def __init__(self, dictionary, columns, parent=None):
        super().__init__(parent)

        self.setLayout(QVBoxLayout(self))

        self.tree_view = MultiColumnDictTreeView(dictionary, columns, self)
        self.layout().addWidget(self.tree_view)

        self.resize(500, 500)

        self.setup_connections()

    def setup_connections(self):
        self.tree_view.dict_modified.connect(self.dict_modified.emit)


class ColumnDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

        editor_factory = ColumnEditorFactory(self, parent)
        self.setItemEditorFactory(editor_factory)

    def state_changed(self):
        self.commitData.emit(self.sender())


class ColumnEditorFactory(QItemEditorFactory):
    def __init__(self, delegate, parent=None):
        super().__init__(self, parent)
        self.delegate = delegate

    def createEditor(self, user_type, parent):
        # Normally in Qt, we'd use QVariant (like QVariant::Double) to compare
        # with the user_type integer. However, QVariant is not available in
        # PySide2, making us use roundabout methods to get the integer like
        # below.
        def utype(w):
            return w.staticMetaObject.userProperty().userType()

        bool_type = utype(QCheckBox)
        float_type = utype(ScientificDoubleSpinBox)
        if user_type == bool_type:
            cb = QCheckBox(parent)
            # Force an update when the check state changes
            cb.toggled.connect(self.delegate.state_changed)
            return cb
        if user_type == float_type:
            return ScientificDoubleSpinBox(parent)

        return super().createEditor(user_type, parent)


if __name__ == '__main__':
    import json
    import sys

    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    columns = {
        'Value': '_value',
        'Status': '_status',
        'Constrained': '_constrained',
    }

    config = {
        'root_key1': {
            '_status': True,
            'child_key1': {
                '_value': 3,
                '_status': False,
                '_constrained': True,
            }
        },
        'root_key2': {
            '_value': 4.2,
            '_status': False,
            '_constrained': True,
        },
        'root_key3': {
            'child_key2': {
                'child_key3': {
                    '_value': 92,
                    '_status': True,
                    '_constrained': False,
                },
            },
            'child_key4': {
                '_value': 8.4,
                '_status': True,
                '_constrained': True,
            },
        }
    }

    dialog = MultiColumnDictTreeViewDialog(config, columns)

    dialog.dict_modified.connect(lambda: print(json.dumps(config, indent=4)))

    dialog.finished.connect(app.quit)
    dialog.show()
    app.exec_()
