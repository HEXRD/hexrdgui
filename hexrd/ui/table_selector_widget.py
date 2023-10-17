import numpy as np

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem, QVBoxLayout
)

from hexrd.ui.ui_loader import UiLoader


class TableSelectorWidget(QTableWidget):

    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.data = None

        self.setup_connections()

    def setup_connections(self):
        self.selectionModel().selectionChanged.connect(
            lambda: self.selection_changed.emit())

    @property
    def selected_rows(self):
        return [x.row() for x in self.selectionModel().selectedRows()]

    @property
    def selected_columns(self):
        return [x.column() for x in self.selectionModel().selectedColumns()]

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, data):
        if hasattr(self, '_data') and np.array_equal(self.data, data):
            return

        self._data = data
        self.update_contents()

    def update_contents(self):
        self.clearContents()
        data = self.data
        if data is None:
            return

        num_rows, num_cols = self.data.shape
        self.setRowCount(num_rows)
        self.setColumnCount(num_cols)

        for i in range(num_rows):
            for j in range(num_cols):
                x = data[i][j]
                item = QTableWidgetItem(str(x))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setTextAlignment(Qt.AlignHCenter)
                self.setItem(i, j, item)

        self.resizeColumnsToContents()
        self.resizeRowsToContents()

    @property
    def horizontal_headers(self):
        num_cols = self.columnCount()
        return [self.horizontalHeaderItem(i).text() for i in range(num_cols)]

    @horizontal_headers.setter
    def horizontal_headers(self, v):
        if len(v) != self.columnCount():
            raise Exception(f'{len(v)=} does not match {self.columnCount()=}!')

        self.setHorizontalHeaderLabels(v)

    @property
    def vertical_headers(self):
        num_rows = self.rowCount()
        return [self.verticalHeaderItem(i).text() for i in range(num_rows)]

    @vertical_headers.setter
    def vertical_headers(self, v):
        if len(v) != self.rowCount():
            raise Exception(f'{len(v)=} does not match {self.rowCount()=}!')

        self.setVerticalHeaderLabels(v)


class TableSelectorDialog(QDialog):

    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        self.table = TableSelectorWidget(self)
        layout.addWidget(self.table)

        self.set_options()

        buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        self.button_box = QDialogButtonBox(buttons, self)
        layout.addWidget(self.button_box)

        # Disable ok by default
        self.enable_ok(False)

        UiLoader().install_dialog_enter_key_filters(self)

        self.setup_connections()

    def setup_connections(self):
        self.table.selection_changed.connect(self.on_selection_changed)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def set_options(self):
        pass

    def on_selection_changed(self):
        self.selection_changed.emit()

    def enable_ok(self, b):
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        ok_button.setEnabled(b)

    @property
    def selected_rows(self):
        return self.table.selected_rows

    @property
    def selected_columns(self):
        return self.table.selected_columns


class TableRowSelectorDialog(TableSelectorDialog):
    def set_options(self):
        super().set_options()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)

    def on_selection_changed(self):
        super().on_selection_changed()
        enable_ok = len(self.table.selected_rows) > 0
        self.enable_ok(enable_ok)


class TableSingleRowSelectorDialog(TableRowSelectorDialog):
    def set_options(self):
        super().set_options()
        self.table.setSelectionMode(QTableWidget.SingleSelection)

    @property
    def selected_row(self):
        if not self.selected_rows:
            return None

        return self.selected_rows[0]


if __name__ == '__main__':
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    data = np.arange(12).reshape((4, 3))
    dialog = TableSingleRowSelectorDialog()
    dialog.table.data = data
    dialog.table.horizontal_headers = ['a', 'b', 'c']

    def selected_rows():
        print(f'Selected rows: {dialog.selected_rows}')

    dialog.selection_changed.connect(selected_rows)
    dialog.finished.connect(selected_rows)
    dialog.finished.connect(app.quit)
    dialog.show()
    app.exec()
