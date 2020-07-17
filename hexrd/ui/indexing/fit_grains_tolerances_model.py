from PySide2.QtCore import QAbstractTableModel, QModelIndex, Qt


class FitGrainsToleranceModel(QAbstractTableModel):
    """Model for grain-fitting tolerances

    Organizes one column for each tolerance type (tth, eta, omega)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tth_tolerances = list()
        self.eta_tolerances = list()
        self.omega_tolerances = list()

    # Override methods:

    def columnCount(self, parent=QModelIndex()):
        return 3

    def data(self, model_index, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None

        row = model_index.row()
        if row < 0 or row >= len(self.tth_tolerances):
            return None

        table = [self.tth_tolerances,
                 self.eta_tolerances, self.omega_tolerances]
        column = model_index.column()
        if column < 0 or column >= len(table):
            return None

        # Note that conventional [row][col] is reversed here
        element = table[column][row]

        return element

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            headers = ['tth', 'eta', 'omega']
            return headers[section]
        # (else)
        return super().headerData(section, orientation, role)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.tth_tolerances)

    # Custom methods:

    def add_row(self):
        new_row = self.rowCount()
        self.beginInsertRows(QModelIndex(), new_row, new_row)
        self.tth_tolerances.append(0.0)
        self.eta_tolerances.append(0.0)
        self.omega_tolerances.append(0.0)
        self.endInsertRows()

    def delete_rows(self, rows):
        first = rows[0]
        last = rows[-1]
        self.beginRemoveRows(QModelIndex(), first, last)
        for row in range(last, first-1, -1):
            del self.tth_tolerances[row]
            del self.eta_tolerances[row]
            del self.omega_tolerances[row]
        self.endRemoveRows()

    def move_rows(self, rows, delta):
        """Move rows in the table

        @param delta: number of rows to move
        """
        first = rows[0]
        last = rows[-1]
        sourceIndex = QModelIndex()
        destinationIndex = QModelIndex()
        destination = first + delta
        # Qt's destination depends on the direction of the move
        offset = 1 if delta > 0 else 0
        self.beginMoveRows(sourceIndex, first, last,
                           sourceIndex, destination + offset)
        table = [self.tth_tolerances,
                 self.eta_tolerances, self.omega_tolerances]
        for i in range(len(table)):
            data = table[i]
            moving_section = data[first:last+1]
            remaining_list = data[:first] + data[last+1:]
            first_section = remaining_list[:destination]
            last_section = remaining_list[destination:]
            table[i] = first_section + moving_section + last_section
        self.tth_tolerances, self.eta_tolerances, self.omega_tolerances = table
        self.endMoveRows()

    def update_from_config(self, config):
        # This method should generally be called *before* the instance
        # is assigned to a view, but just in case, we emit the internal
        # signals to notify views.
        self.beginResetModel()

        del self.tth_tolerances[:]
        del self.eta_tolerances[:]
        del self.omega_tolerances[:]

        self.tth_tolerances = config.get('tth')
        self.eta_tolerances = config.get('eta')
        self.omega_tolerances = config.get('omega')

        self.endResetModel()
