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

    def columnCount(self, parent=QModelIndex()):
        return 3

    def data(self, model_index, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None

        row = model_index.row()
        if row < 0 or row >= len(self.tth_tolerances):
            return None

        table = [self.tth_tolerances, self.eta_tolerances, self.omega_tolerances]
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

    def update_from_config(self, config):
        # This method should generally be called *before* the instance is assigned to
        # a view, but just in case, we emit the internal signals to notify views.
        self.beginResetModel()

        del self.tth_tolerances[:]
        del self.eta_tolerances[:]
        del self.omega_tolerances[:]

        self.tth_tolerances = config.get('tth')
        self.eta_tolerances = config.get('eta')
        self.omega_tolerances = config.get('omega')

        self.endResetModel()
