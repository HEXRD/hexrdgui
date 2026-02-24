from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import QWidget


class FitGrainsToleranceModel(QAbstractTableModel):
    """Model for grain-fitting tolerances

    Organizes one column for each tolerance type (tth, eta, omega)
    """

    data_modified = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tth_tolerances: list[float] = []
        self.eta_tolerances: list[float] = []
        self.omega_tolerances: list[float] = []

    # Override methods:

    def columnCount(
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 3

    def data(
        self,
        model_index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return

        row, column = model_index.row(), model_index.column()
        if row < 0 or row >= len(self.tth_tolerances):
            return

        if column < 0 or column >= len(self.data_columns):
            return

        # Note that conventional [row][col] is reversed here
        return self.data_columns[column][row]

    def setData(
        self,
        model_index: QModelIndex | QPersistentModelIndex,
        value: float,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        # This should always be a float
        try:
            value = float(value)
        except ValueError:
            return False

        row, column = model_index.row(), model_index.column()
        # Note that conventional [row][col] is reversed here
        self.data_columns[column][row] = value

        self.data_modified.emit()
        return True

    def flags(self, model_index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        # All items are editable
        return super().flags(model_index) | Qt.ItemFlag.ItemIsEditable

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            headers = ['tth', 'eta', 'omega']
            return headers[section]
        # (else)
        return super().headerData(section, orientation, role)

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        if parent.isValid():
            return 0
        return len(self.tth_tolerances)

    # Custom methods:

    @property
    def data_columns(
        self,
    ) -> tuple[list[float], list[float], list[float]]:
        return (
            self.tth_tolerances,
            self.eta_tolerances,
            self.omega_tolerances,
        )

    def add_row(self) -> None:
        new_row = self.rowCount()
        self.beginInsertRows(QModelIndex(), new_row, new_row)
        self.tth_tolerances.append(0.0)
        self.eta_tolerances.append(0.0)
        self.omega_tolerances.append(0.0)
        self.endInsertRows()
        self.data_modified.emit()

    def delete_rows(self, rows: list[int]) -> None:
        first = rows[0]
        last = rows[-1]
        self.beginRemoveRows(QModelIndex(), first, last)
        for row in range(last, first - 1, -1):
            del self.tth_tolerances[row]
            del self.eta_tolerances[row]
            del self.omega_tolerances[row]
        self.endRemoveRows()
        self.data_modified.emit()

    def move_rows(self, rows: list[int], delta: int) -> None:
        """Move rows in the table

        @param delta: number of rows to move
        """
        first = rows[0]
        last = rows[-1]
        destination = first + delta
        # Qt's destination depends on the direction of the move
        offset = 1 if delta > 0 else 0
        self.beginMoveRows(
            QModelIndex(), first, last, QModelIndex(), destination + offset
        )
        for data in self.data_columns:
            moving_section = data[first : last + 1]
            remaining_list = data[:first] + data[last + 1 :]
            first_section = remaining_list[:destination]
            last_section = remaining_list[destination:]
            data[:] = first_section + moving_section + last_section
        self.endMoveRows()
        self.data_modified.emit()

    def copy_to_config(self, config: dict[str, Any]) -> None:
        config['tolerance'] = {
            'tth': self.tth_tolerances,
            'eta': self.eta_tolerances,
            'omega': self.omega_tolerances,
        }

    def update_from_config(self, config: dict[str, Any]) -> None:
        # This method should generally be called *before* the instance
        # is assigned to a view, but just in case, we emit the internal
        # signals to notify views.
        self.beginResetModel()

        self.tth_tolerances = config.get('tth', [])
        self.eta_tolerances = config.get('eta', [])
        self.omega_tolerances = config.get('omega', [])

        self.endResetModel()

        self.data_modified.emit()
