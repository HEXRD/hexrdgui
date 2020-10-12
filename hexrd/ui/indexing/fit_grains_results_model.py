import os

import numpy as np

from PySide2.QtCore import QAbstractTableModel, QModelIndex, Qt


class FitGrainsResultsModel(QAbstractTableModel):
    """Model for grain-fitting results

    """

    def __init__(self, grains_table, parent=None):
        super().__init__(parent)
        self.grains_table = grains_table
        self.headers = [
            'grain ID', 'completeness', 'chi^2',
            'exp_map_c[0]', 'exp_map_c[1]', 'exp_map_c[2]',
            't_vec_c[0]', 't_vec_c[1]', 't_vec_c[2]',
            'inv(V_s)[0,0]', 'inv(V_s)[1,1]', 'inv(V_s)[2,2]',
            'inv(V_s)[1,2]*sqrt(2)',
            'inv(V_s)[0,2]*sqrt(2)',
            'inv(V_s)[0,2]*sqrt(2)',
            'ln(V_s)[0,0]', 'ln(V_s)[1,1]', 'ln(V_s)[2,2]',
            'ln(V_s)[1,2]', 'ln(V_s)[0,2]', 'ln(V_s)[0,1]'
        ]

    # Override methods:

    def columnCount(self, parent=QModelIndex()):
        return 21

    def data(self, model_index, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None

        # Presume that row and column are valid
        row = model_index.row()
        column = model_index.column()
        value = self.grains_table[row][column].item()
        return value

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        # (else)
        return super().headerData(section, orientation, role)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.grains_table)

    # Custom methods

    def save(self, path):
        with open(path, 'w') as fp:
            header_items = self.headers.copy()
            header_items[0] = f'# {self.headers[0]}'

            # Formatting logic is copied from instrument GrainDataWriter
            delim = '  '
            header = delim.join(
                [delim.join(
                    np.tile('{:<12}', 3)
                    ).format(*header_items[:3]), delim.join(
                        np.tile('{:<23}', len(header_items) - 3)
                    ).format(*header_items[3:])]
            )
            fp.write(header)
            fp.write('\n')

            for row in self.grains_table:
                res = row.tolist()
                res[0] = int(res[0])
                output_str = delim.join(
                    [delim.join(
                        ['{:<12d}', '{:<12f}', '{:<12e}']
                    ).format(*res[:3]), delim.join(
                        np.tile('{:<23.16e}', len(res) - 3)
                    ).format(*res[3:])]
                )
                fp.write(output_str)
                fp.write('\n')

            print('Wrote', path)
