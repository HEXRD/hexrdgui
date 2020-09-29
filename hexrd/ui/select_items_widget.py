import copy

from PySide2.QtCore import QObject, Qt, Signal
from PySide2.QtWidgets import QCheckBox, QHBoxLayout, QTableWidgetItem, QWidget

from hexrd.ui.ui_loader import UiLoader


COLUMNS = {
    'name': 0,
    'checkbox': 1
}


class SelectItemsWidget(QObject):

    selection_changed = Signal()

    def __init__(self, items, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('select_items_widget.ui', parent)

        self.checkboxes = []

        # The items should be a list of tuples of length two, like
        # (name, selected).
        self.items = items

    @property
    def items(self):
        return self._items

    @items.setter
    def items(self, v):
        self._items = copy.deepcopy(v)
        self.update_table()

    def create_table_widget(self, w):
        # These are required to center the widget...
        tw = QWidget(self.ui.table)
        layout = QHBoxLayout(tw)
        layout.addWidget(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return tw

    def create_label(self, v):
        w = QTableWidgetItem(v)
        w.setTextAlignment(Qt.AlignCenter)
        return w

    def create_checkbox(self, v):
        cb = QCheckBox(self.ui.table)
        cb.setChecked(v)
        cb.toggled.connect(self.checkbox_toggled)
        self.checkboxes.append(cb)
        return self.create_table_widget(cb)

    def clear_table(self):
        self.checkboxes.clear()
        self.ui.table.clearContents()

    def update_table(self):
        self.clear_table()
        self.ui.table.setRowCount(len(self.items))
        for i, (name, checked) in enumerate(self.items):
            w = self.create_label(name)
            self.ui.table.setItem(i, COLUMNS['name'], w)

            w = self.create_checkbox(checked)
            self.ui.table.setCellWidget(i, COLUMNS['checkbox'], w)

        self.ui.table.resizeColumnsToContents()

    def checkbox_toggled(self):
        # Go through and update the items
        for i, (item, cb) in enumerate(zip(self.items, self.checkboxes)):
            self.items[i] = (item[0], cb.isChecked())

        self.selection_changed.emit()

    @property
    def selected_items(self):
        return [x[0] for x in self.items if x[1] is True]
