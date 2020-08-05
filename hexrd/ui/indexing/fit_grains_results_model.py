from PySide2.QtCore import QAbstractTableModel, QModelIndex, Qt


class FitGrainsResultsModel(QAbstractTableModel):
    """Model for grain-fitting results

    """

    def __init__(self, fit_grains_results, parent=None):
        super().__init__(parent)
        self.fit_grains_results = fit_grains_results
        self.headers = (
            'grain ID', 'completeness', 'chi^2',
            'exp_map_c[0]', 'exp_map_c[1]', 'exp_map_c[2]',
            't_vec_c[0]', 't_vec_c[1]', 't_vec_c[2]',
            'inv(V_s)[0,0]', 'inv(V_s)[1,1]', 'inv(V_s)[2,2]',
            'inv(V_s)[1,2]*sqrt(2)',
            'inv(V_s)[0,2]*sqrt(2)',
            'inv(V_s)[0,2]*sqrt(2)',
            'ln(V_s)[0,0]', 'ln(V_s)[1,1]', 'ln(V_s)[2,2]',
            'ln(V_s)[1,2]', 'ln(V_s)[0,2]', 'ln(V_s)[0,1]'
        )

    # Override methods:

    def columnCount(self, parent=QModelIndex()):
        return 21

    def data(self, model_index, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None

        # Presume that row and column are valid
        row = model_index.row()
        column = model_index.column()
        value = self.fit_grains_results[row][column].item()
        return value

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        # (else)
        return super().headerData(section, orientation, role)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.fit_grains_results)


if __name__ == '__main__':
    import sys
    import numpy as np
    from PySide2.QtWidgets import QApplication, QTableView, QVBoxLayout

    # User specifies grains.out file
    if (len(sys.argv) < 2):
        print()
        print('Load grains.out file and display as table')
        print('Usage: python fit_grains_resuls_model.py  <path-to-grains.out>')
        print()
        sys.exit(-1)

    # print(sys.argv)
    app = QApplication(sys.argv)

    data = np.loadtxt(sys.argv[1])
    # print(data)

    model = FitGrainsResultsModel(data)
    view = QTableView()
    view.verticalHeader().hide()
    view.setModel(model)
    view.resizeColumnToContents(0)
    view.resize(960, 320)

    view.show()
    app.exec_()
