from PySide6.QtCore import Signal, QModelIndex, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QItemEditorFactory, QMenu, QStyledItemDelegate,
    QVBoxLayout
)

from hexrdgui.scientificspinbox import ScientificDoubleSpinBox
from hexrdgui.tree_views.base_dict_tree_item_model import (
    BaseDictTreeItemModel, BaseTreeItemModel, BaseDictTreeView
)
from hexrdgui.tree_views.tree_item import TreeItem

# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL


class MultiColumnDictTreeItemModel(BaseDictTreeItemModel):

    UNEDITABLE_COLUMN_INDICES = []

    def __init__(self, dictionary, columns, parent=None):
        super().__init__(dictionary, parent)

        self.column_labels = list(columns.keys())
        self.column_keys = list(columns.values())
        self.uneditable_paths = []

        self.root_item = TreeItem(['Key'] + self.column_labels)
        self.rebuild_tree()

    def data(self, index, role):
        value = super().data(index, role)

        if isinstance(value, bool) and role == Qt.DisplayRole:
            # If it's a bool, we want to display a checkbox via
            # a persistent editor, rather than the default display.
            return

        return value

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super().flags(index)

        # Make sure the editable flag is removed. We'll add it later
        # after some checks.
        flags = flags & ~Qt.ItemIsEditable

        column = index.column()
        item = self.get_item(index)
        if column != KEY_COL and item.data(column) is not None:
            # All columns after the first that aren't None are editable,
            # unless explicitly disabled.
            editable = True
            if self.has_uneditable_paths:
                # Need to check if it is uneditable
                path = tuple(self.path_to_item(item) + [column])
                if path in self.uneditable_paths:
                    editable = False

            if column in self.UNEDITABLE_COLUMN_INDICES:
                editable = False

            if editable:
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

    def has_uneditable_paths(self) -> bool:
        return bool(self.uneditable_paths)


class MultiColumnDictTreeView(BaseDictTreeView):

    dict_modified = Signal(QModelIndex)

    def __init__(self, dictionary, columns, parent=None,
                 model_class=MultiColumnDictTreeItemModel):
        super().__init__(parent)

        # Set this to the needed check/uncheck index to allow for context
        # menu actions "Check All" and "Uncheck All"
        self.check_selection_index = None

        # These are tree view paths to editors that should be disabled
        # Each item in this list is a path tuple (which includes the
        # column at the end), like so: ('beam', 'XRS1', 'energy', 1)
        self.disabled_editor_paths = []

        self.setModel(model_class(dictionary, columns, parent=self))

        self.resizeColumnToContents(0)
        self.header().resizeSection(0, 200)
        for i in range(1, len(columns) + 1):
            self.resizeColumnToContents(i)
            self.header().resizeSection(i, 150)
            self.setItemDelegateForColumn(i, ColumnDelegate(self))

        self.open_persistent_editors()
        self.expand_rows()
        self.setup_connections()

    def contextMenuEvent(self, event):
        actions = {}

        index = self.indexAt(event.pos())
        item = self.model().get_item(index)
        children = item.child_items

        # Convenience booleans
        key_col_with_children = index.column() == KEY_COL and children
        check_index_set = self.check_selection_index is not None

        menu = QMenu(self)

        # Helper functions
        def add_actions(d: dict):
            actions.update({menu.addAction(k): v for k, v in d.items()})

        def add_separator():
            if not actions:
                return
            menu.addSeparator()

        # Context menu methods
        def collapse_selection():
            self.collapse_selection(index)

        def expand_selection():
            self.expand_selection(index)

        def check_selection():
            self.set_data_on_children(item, self.check_selection_index, True)

        def uncheck_selection():
            self.set_data_on_children(item, self.check_selection_index, False)

        # Action logic
        if key_col_with_children:
            add_actions({
                'Collapse All': collapse_selection,
                'Expand All': expand_selection,
            })

        if key_col_with_children and check_index_set:
            add_separator()
            add_actions({
                'Check All': check_selection,
                'Uncheck All': uncheck_selection,
            })

        if not actions:
            # No context menu
            return

        # Open up the context menu
        action_chosen = menu.exec(QCursor.pos())

        if action_chosen is None:
            # No action chosen
            return

        # Run the function for the action that was chosen
        actions[action_chosen]()

    def expand_selection(self, index):
        model = self.model()
        item = model.get_item(index)
        for i in range(item.child_count()):
            self.expand_selection(model.index(i, KEY_COL, index))
        self.expand(index)

    def collapse_selection(self, index):
        model = self.model()
        item = model.get_item(index)
        for i in range(item.child_count()):
            self.collapse_selection(model.index(i, KEY_COL, index))
        self.collapse(index)

    def set_data_on_children(self, parent, column, value):
        for child in parent.child_items:
            if child.data(column) is not None:
                # None would imply that column is not supposed to have data
                index = self.model().createIndex(child.row(), column, child)
                self.model().setData(index, value)
                self.model().dataChanged.emit(index, index)

            self.set_data_on_children(child, column, value)

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
        self.model().dict_modified.connect(self.on_dict_modified)

    def on_dict_modified(self, index: QModelIndex):
        self.dict_modified.emit(index)

    def reset_gui(self):
        # Save the vertical scroll bar position if we can
        sb = self.verticalScrollBar()
        prev_pos = sb.value()

        # Reset the gui now
        self.rebuild_tree()
        self.open_persistent_editors()
        self.expand_rows()

        def restore_vertical_bar():
            # Restore the vertical scroll bar position
            sb.setValue(prev_pos)

        # Do this in the next iteration of the event loop, because
        # it may require the GUI to finish updating.
        QTimer.singleShot(0, restore_vertical_bar)

    @property
    def has_disabled_editors(self) -> bool:
        return bool(self.disabled_editor_paths)

    def editor_is_disabled(self, path: list[str] | tuple[str]):
        return tuple(path) in self.disabled_editor_paths


class MultiColumnDictTreeViewDialog(QDialog):

    dict_modified = Signal(QModelIndex)

    def __init__(self, dictionary, columns, parent=None):
        super().__init__(parent)

        self.setLayout(QVBoxLayout(self))

        self.tree_view = MultiColumnDictTreeView(dictionary, columns,
                                                 parent=self)
        self.layout().addWidget(self.tree_view)

        self.resize(500, 500)

        self.setup_connections()

    def setup_connections(self):
        self.tree_view.dict_modified.connect(self.dict_modified.emit)


class ColumnDelegate(QStyledItemDelegate):
    def __init__(self, parent: MultiColumnDictTreeView):
        super().__init__(parent)

        editor_factory = ColumnEditorFactory(self, parent)
        self.setItemEditorFactory(editor_factory)

    @property
    def tree_view(self) -> MultiColumnDictTreeView:
        return self.parent()

    @property
    def model(self) -> MultiColumnDictTreeItemModel:
        return self.tree_view.model()

    def state_changed(self):
        self.commitData.emit(self.sender())

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if self.tree_view.has_disabled_editors:
            item = self.model.get_item(index)
            path = self.model.path_to_item(item) + [index.column()]
            if self.tree_view.editor_is_disabled(path):
                editor.setEnabled(False)

                if isinstance(editor, QCheckBox):
                    # For some reason, checkboxes are not being grayed out
                    # automatically, so we must gray it out here.
                    editor.setStyleSheet(
                        'QCheckBox::indicator {background-color: gray}'
                    )

        return editor


class ColumnEditorFactory(QItemEditorFactory):
    def __init__(self, delegate, parent=None):
        super().__init__(self, parent)
        self.delegate = delegate

    def createEditor(self, user_type, parent):
        # Normally in Qt, we'd use QVariant (like QVariant::Double) to compare
        # with the user_type integer. However, QVariant is not available in
        # PySide6, making us use roundabout methods to get the integer like
        # below.
        def utype(w):
            return w.staticMetaObject.userProperty().userType()

        bool_type = utype(QCheckBox)
        float_type = utype(ScientificDoubleSpinBox)
        if user_type == bool_type:
            cb = QCheckBox(parent)
            # Force an update when the check state changes
            # Only indicate the status has changed on user interaction
            cb.clicked.connect(self.delegate.state_changed)
            return cb
        if user_type == float_type:
            return ScientificDoubleSpinBox(parent)

        return super().createEditor(user_type, parent)


if __name__ == '__main__':
    import json
    import sys

    from PySide6.QtWidgets import QApplication

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
    app.exec()
