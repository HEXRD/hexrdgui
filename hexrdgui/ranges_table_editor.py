import copy
from typing import Any, Callable
import numpy as np

from PySide6.QtCore import QItemSelectionModel, QObject, Signal
from PySide6.QtWidgets import QSizePolicy, QWidget

from hexrdgui.scientificspinbox import ScientificDoubleSpinBox
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class RangesTableEditor(QObject):

    data_modified = Signal()

    def __init__(self, data: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('ranges_table_editor.ui', parent)

        self._data: Any = self._validate_data(data)
        self._suffix: str = '°'
        self.data_to_gui_func: Callable[[Any], Any] | None = np.degrees
        self.gui_to_data_func: Callable[[Any], Any] | None = np.radians
        self._min: float = -360.0
        self._max: float = 360.0

        self.spin_boxes: list[ScientificDoubleSpinBox] = []

        self.setup_connections()
        self.update_enable_states()
        self.update_table()

    def setup_connections(self) -> None:
        self.ui.add.pressed.connect(self.add_row)
        self.ui.remove.pressed.connect(self.remove_row)

        self.ui.table.selectionModel().selectionChanged.connect(
            self.update_enable_states
        )

    def update_enable_states(self) -> None:
        enable_remove = self.num_rows > 1 and self.selected_row is not None
        self.ui.remove.setEnabled(enable_remove)

    @property
    def data(self) -> Any:
        return copy.deepcopy(self._data)

    @data.setter
    def data(self, v: Any) -> None:
        self._data = self._validate_data(v)
        self.update_table()

    @staticmethod
    def _validate_data(v: Any) -> Any:
        if isinstance(v, np.ndarray):
            return v.tolist()
        else:
            return copy.deepcopy(v)

    @property
    def suffix(self) -> str:
        return self._suffix

    @suffix.setter
    def suffix(self, v: str) -> None:
        self._suffix = v
        self.update_table()

    @property
    def min(self) -> float:
        return self._min

    @min.setter
    def min(self, v: float) -> None:
        self._min = v
        self.update_table()

    @property
    def max(self) -> float:
        return self._max

    @max.setter
    def max(self, v: float) -> None:
        self._max = v
        self.update_table()

    @property
    def num_rows(self) -> int:
        return self.ui.table.rowCount()

    def select_row(self, i: int) -> None:
        if i is None or i >= self.ui.table.rowCount():
            # Out of range. Don't do anything.
            return

        # Select the row
        selection_model = self.ui.table.selectionModel()
        selection_model.clearSelection()

        model_index = selection_model.model().index(i, 0)
        command = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        selection_model.select(model_index, command)

    @property
    def selected_row(self) -> int | None:
        selected = self.ui.table.selectionModel().selectedRows()
        return selected[0].row() if selected else None

    def add_row(self) -> None:
        if not self._data:
            # We are assuming there must always be data in this widget
            return

        # Copy the last row
        self._data.append(copy.deepcopy(self._data[-1]))
        self.update_table()
        self.data_modified.emit()

    def remove_row(self) -> None:
        selected_row = self.selected_row
        if selected_row is None:
            return

        del self._data[selected_row]
        self.update_table()
        self.data_modified.emit()

    def create_double_spin_box(self, v: float) -> ScientificDoubleSpinBox:
        sb = ScientificDoubleSpinBox(self.ui.table)
        sb.setKeyboardTracking(False)
        sb.setSuffix(self.suffix)
        sb.setMinimum(self.min)
        sb.setMaximum(self.max)
        sb.setValue(v)
        sb.valueChanged.connect(self.update_data)

        size_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        sb.setSizePolicy(size_policy)

        self.spin_boxes.append(sb)
        return sb

    def clear_table(self) -> None:
        self.spin_boxes.clear()
        self.ui.table.clearContents()

    def update_table(self) -> None:
        self.clear_table()
        if self._data is None:
            return

        block_list = [self.ui.table, self.ui.table.selectionModel()]

        with block_signals(*block_list):

            prev_selected = self.selected_row

            self.ui.table.setRowCount(len(self._data))
            for i, entry in enumerate(self._data):
                for j, datum in enumerate(entry):
                    if self.data_to_gui_func is not None:
                        datum = self.data_to_gui_func(datum)
                    w = self.create_double_spin_box(datum)
                    self.ui.table.setCellWidget(i, j, w)

            if prev_selected is not None:
                select_row = (
                    prev_selected
                    if prev_selected < len(self._data)
                    else len(self._data) - 1
                )
                self.select_row(select_row)

            # Just in case the selection actually changed...
            self.update_enable_states()

    def table_data(self, row: int, column: int) -> Any:
        val = self.ui.table.cellWidget(row, column).value()
        if self.gui_to_data_func is not None:
            return self.gui_to_data_func(val)
        return val

    def update_data(self) -> None:
        for i in range(self.ui.table.rowCount()):
            for j in range(self.ui.table.columnCount()):
                self._data[i][j] = self.table_data(i, j)

        self.data_modified.emit()

    def set_title(self, title: str) -> None:
        self.ui.main_label.setText(title)
