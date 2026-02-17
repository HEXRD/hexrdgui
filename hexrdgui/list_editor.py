from PySide6.QtCore import QItemSelectionModel, QObject, Signal
from PySide6.QtWidgets import QDialog, QTableWidgetItem, QVBoxLayout, QWidget

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals, unique_name
from typing import Any, Sequence


class ListEditor(QObject):
    """A string list editor that doesn't allow duplicates"""

    # Indicates the items were re-arranged
    items_rearranged = Signal()

    # Indicates that some items were deleted
    # Provides a list of names that were deleted.
    items_deleted = Signal(list)

    # Indicates that an item was renamed.
    # Provides an old item name and it's new name.
    item_renamed = Signal(str, str)

    # Indicates that some items were copied.
    # Provides a list of items that were copied, and a list of new
    # names they correspond to, in order.
    items_copied = Signal(list, list)

    # Indicates that a default item was added to the end.
    # Provides the name of the new item.
    item_added = Signal(str)

    def __init__(self, items: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.ui = UiLoader().load_file('list_editor.ui', parent)

        # I have no idea why, but for *this* specific UI file, the table's
        # selection model's model starts out in an invalid state.
        # I haven't seen it be invalid for other uses of QTableWidget. But
        # if we call `self.ui.table.selectionModel().model()`, which we
        # must do in some functions, we get the following error:
        #     RuntimeError: Internal C++ object
        #     (PySide6.QtCore.QAbstractTableModel) already deleted.

        # I tried resetting all QTableWidget settings to default in the ui
        # file, but the model still starts out in an invalid state! So I
        # have no idea why it is happening.
        # But one fix I found is that if we set the table's selection model
        # on the table (which you'd think wouldn't change anything), the
        # model on the selection model gets fixed. So we are doing that.
        # FIXME: see if we can figure out why this is an issue.
        self.ui.table.setSelectionModel(self.selection_model)

        # Make sure there are no duplicates in the items
        items = list(dict.fromkeys(items))

        self._items = items
        self._prev_selected_items: list[Any] = []

        self.update_table()

        self.setup_connections()

    def setup_connections(self) -> None:
        self.selection_model.selectionChanged.connect(self.selection_changed)

        self.ui.up.clicked.connect(self.up)
        self.ui.down.clicked.connect(self.down)
        self.ui.delete_.clicked.connect(self.delete)
        self.ui.copy.clicked.connect(self.copy)
        self.ui.add.clicked.connect(self.add)

        self.ui.table.itemChanged.connect(self.item_edited)

    @property
    def selection_model(self) -> Any:
        return self.ui.table.selectionModel()

    @property
    def selected_rows(self) -> list[int]:
        return sorted([x.row() for x in self.selection_model.selectedRows()])

    @property
    def items(self) -> list[str]:
        return self._items

    @items.setter
    def items(self, items: list[str]) -> None:
        if self._items == items:
            return

        # Make sure there are no duplicates in the items
        items = list(dict.fromkeys(items))

        self._items = items
        self.update_table()

    @property
    def selected_items(self) -> list[str]:
        return [self.items[x] for x in self.selected_rows]

    @property
    def num_items(self) -> int:
        return len(self.items)

    def clear_selection(self) -> None:
        self.selection_model.clearSelection()

    def select_row(self, i: int) -> None:
        model_index = self.selection_model.model().index(i, 0)
        command = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        self.selection_model.select(model_index, command)

    def selection_changed(self) -> None:
        self.update_enable_states()

    def update_enable_states(self) -> None:
        selected_rows = self.selected_rows
        num_selected = len(selected_rows)

        top_selected = 0 in selected_rows
        bottom_selected = self.num_items - 1 in selected_rows
        one_selected = num_selected == 1
        any_selected = num_selected > 0
        all_selected = num_selected == self.num_items

        self.ui.up.setEnabled(one_selected and not top_selected)
        self.ui.down.setEnabled(one_selected and not bottom_selected)
        self.ui.copy.setEnabled(any_selected)
        self.ui.delete_.setEnabled(any_selected and not all_selected)

    def update_prev_selected_items(self) -> None:
        self._prev_selected_items = self.selected_items

    def up(self) -> None:
        i = self.selected_rows[0]
        self.swap(i, i - 1)

    def down(self) -> None:
        i = self.selected_rows[0]
        self.swap(i, i + 1)

    def delete(self) -> None:
        self.update_prev_selected_items()
        selected_rows = self.selected_rows

        deleted: list[Any] = []
        for i in selected_rows:
            deleted.append(self.items.pop(i - len(deleted)))

        new_selection = min(selected_rows[-1] - len(deleted) + 1, self.num_items - 1)

        self.update_table()
        self.select_row(new_selection)

        self.items_deleted.emit(deleted)

    def copy(self) -> None:
        self.update_prev_selected_items()

        old_items = [self.items[x] for x in self.selected_rows]

        new_items: list[Any] = []
        for name in old_items:
            new_name = unique_name(self.items + new_items, name)
            new_items.append(new_name)

        self.items += new_items
        self.update_table()

        self.items_copied.emit(old_items, new_items)

    def add(self) -> None:
        new_name = unique_name(self.items, 'new')
        self.items += [new_name]
        self.update_table()

        # Select the new item
        self.clear_selection()
        self.select_row(len(self.items) - 1)

        self.item_added.emit(new_name)

    def item_edited(self, item: QTableWidgetItem) -> None:
        row = item.row()

        old_name = self.items[row]
        new_name = item.text()

        if new_name in self.items:
            # Make sure it is not a duplicate. If it is, then revert it.
            new_name = old_name

        self.items[row] = new_name
        self.update_prev_selected_items()
        self.update_table()

        if new_name != old_name:
            self.item_renamed.emit(old_name, new_name)

    def swap(self, i: int, j: int) -> None:
        self.update_prev_selected_items()
        items = self.items
        items[i], items[j] = items[j], items[i]
        self.update_table()

        self.items_rearranged.emit()

    def update_table(self) -> None:
        table = self.ui.table

        with block_signals(table, self.selection_model):
            table.clearContents()

            table.setRowCount(self.num_items)
            for i, item in enumerate(self.items):
                table.setItem(i, 0, QTableWidgetItem(item))

            for item in self._prev_selected_items:
                if item in self.items:
                    self.select_row(self.items.index(item))


class ListEditorDialog(QDialog):
    def __init__(self, items: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        self.editor = ListEditor(items, self)
        layout.addWidget(self.editor.ui)

        self.setWindowTitle('List Editor')

        UiLoader().install_dialog_enter_key_filters(self)

    @property
    def items(self) -> list[str]:
        return self.editor.items


if __name__ == '__main__':
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    items = [
        'a',
        'b',
        'c',
        'd',
        'e',
    ]
    dialog = ListEditorDialog(items)

    def dialog_finished() -> None:
        print(f'Final items: {dialog.items}')

    def items_rearranged() -> None:
        print(f'Items re-arranged: {dialog.items}')

    def items_deleted(items: list[str]) -> None:
        print(f'Items deleted: {items=}')

    def items_copied(old_names: Sequence[str], new_names: Sequence[str]) -> None:
        print(f'Items copied: {old_names=} => {new_names=}')

    def item_renamed(old_name: str, new_name: str) -> None:
        print(f'Item renamed: {old_name} => {new_name}')

    editor = dialog.editor
    editor.items_rearranged.connect(items_rearranged)
    editor.items_deleted.connect(items_deleted)
    editor.items_copied.connect(items_copied)
    editor.item_renamed.connect(item_renamed)

    dialog.finished.connect(dialog_finished)
    dialog.finished.connect(app.quit)
    dialog.show()
    app.exec()
