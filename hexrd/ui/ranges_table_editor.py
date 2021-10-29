import copy
import numpy as np

from PySide2.QtCore import QItemSelectionModel, QObject, QSignalBlocker, Signal
from PySide2.QtWidgets import QSizePolicy

from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox
from hexrd.ui.ui_loader import UiLoader


class RangesTableEditor(QObject):

    data_modified = Signal()

    def __init__(self, data=None, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('ranges_table_editor.ui', parent)

        self._data = data
        self._suffix = '°'
        self.data_to_gui_func = np.degrees
        self.gui_to_data_func = np.radians
        self._min = -360.0
        self._max = 360.0

        self.spin_boxes = []

        self.setup_connections()
        self.update_enable_states()
        self.update_table()

    def setup_connections(self):
        self.ui.add.pressed.connect(self.add_row)
        self.ui.remove.pressed.connect(self.remove_row)

        self.ui.table.selectionModel().selectionChanged.connect(
            self.update_enable_states)

    def update_enable_states(self):
        enable_remove = self.num_rows > 1 and self.selected_row is not None
        self.ui.remove.setEnabled(enable_remove)

    @property
    def data(self):
        return copy.deepcopy(self._data)

    @data.setter
    def data(self, v):
        self._data = copy.deepcopy(v)
        self.update_table()

    @property
    def suffix(self):
        return self._suffix

    @suffix.setter
    def suffix(self, v):
        self._suffix = v
        self.update_table()

    @property
    def min(self):
        return self._min

    @min.setter
    def min(self, v):
        self._min = v
        self.update_table()

    @property
    def max(self):
        return self._max

    @max.setter
    def max(self, v):
        self._max = v
        self.update_table()

    @property
    def num_rows(self):
        return self.ui.table.rowCount()

    def select_row(self, i):
        if i is None or i >= self.ui.table.rowCount():
            # Out of range. Don't do anything.
            return

        # Select the row
        selection_model = self.ui.table.selectionModel()
        selection_model.clearSelection()

        model_index = selection_model.model().index(i, 0)
        command = QItemSelectionModel.Select | QItemSelectionModel.Rows
        selection_model.select(model_index, command)

    @property
    def selected_row(self):
        selected = self.ui.table.selectionModel().selectedRows()
        return selected[0].row() if selected else None

    def add_row(self):
        if not self._data:
            # We are assuming there must always be data in this widget
            return

        # Copy the last row
        self._data.append(copy.deepcopy(self._data[-1]))
        self.update_table()
        self.data_modified.emit()

    def remove_row(self):
        selected_row = self.selected_row
        if selected_row is None:
            return

        del self._data[selected_row]
        self.update_table()
        self.data_modified.emit()

    def create_double_spin_box(self, v):
        sb = ScientificDoubleSpinBox(self.ui.table)
        sb.setKeyboardTracking(False)
        sb.setSuffix(self.suffix)
        sb.setMinimum(self.min)
        sb.setMaximum(self.max)
        sb.setValue(v)
        sb.valueChanged.connect(self.update_data)

        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sb.setSizePolicy(size_policy)

        self.spin_boxes.append(sb)
        return sb

    def clear_table(self):
        self.spin_boxes.clear()
        self.ui.table.clearContents()

    def update_table(self):
        self.clear_table()
        if self._data is None:
            return

        block_list = [
            self.ui.table,
            self.ui.table.selectionModel()
        ]
        blockers = [QSignalBlocker(x) for x in block_list]  # noqa: F841

        prev_selected = self.selected_row

        self.ui.table.setRowCount(len(self._data))
        for i, entry in enumerate(self._data):
            for j, datum in enumerate(entry):
                if self.data_to_gui_func is not None:
                    datum = self.data_to_gui_func(datum)
                w = self.create_double_spin_box(datum)
                self.ui.table.setCellWidget(i, j, w)

        if prev_selected is not None:
            select_row = (prev_selected if prev_selected < len(self._data)
                          else len(self._data) - 1)
            self.select_row(select_row)

        # Just in case the selection actually changed...
        self.update_enable_states()

    def table_data(self, row, column):
        val = self.ui.table.cellWidget(row, column).value()
        if self.gui_to_data_func is not None:
            return self.gui_to_data_func(val)
        return val

    def update_data(self):
        for i in range(self.ui.table.rowCount()):
            for j in range(self.ui.table.columnCount()):
                self._data[i][j] = self.table_data(i, j)

        self.data_modified.emit()

    def set_title(self, title):
        self.ui.main_label.setText(title)
