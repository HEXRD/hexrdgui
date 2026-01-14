import numpy as np

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from hexrdgui.indexing.utils import write_grains_txt


class GrainsTableModel(QAbstractTableModel):
    """Model for viewing grains"""

    grains_table_modified = Signal()

    def __init__(self, grains_table, excluded_columns=None, parent=None):
        super().__init__(parent)
        self.full_grains_table = grains_table
        self.full_headers = [
            'grain ID',
            'completeness',
            'chi^2',
            'exp_map_c[0]',
            'exp_map_c[1]',
            'exp_map_c[2]',
            't_vec_c[0]',
            't_vec_c[1]',
            't_vec_c[2]',
            'inv(V_s)[0,0]',
            'inv(V_s)[1,1]',
            'inv(V_s)[2,2]',
            'inv(V_s)[1,2]*sqrt(2)',
            'inv(V_s)[0,2]*sqrt(2)',
            'inv(V_s)[0,2]*sqrt(2)',
            'ln(V_s)[0,0]',
            'ln(V_s)[1,1]',
            'ln(V_s)[2,2]',
            'ln(V_s)[1,2]',
            'ln(V_s)[0,2]',
            'ln(V_s)[0,1]',
        ]

        self.excluded_columns = excluded_columns if excluded_columns else []

        self.regenerate_grains_table()

    def regenerate_grains_table(self):
        self.grains_table = self.full_grains_table[:, self.included_columns]
        self.headers = [self.full_headers[x] for x in self.included_columns]

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

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

        return super().headerData(section, orientation, role)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0

        return len(self.grains_table)

    def removeRows(self, row, count, parent):
        while count > 0:
            self.full_grains_table = np.delete(self.full_grains_table, row, axis=0)
            count -= 1

        self.regenerate_grains_table()

        return True

    # Custom methods

    def delete_grains(self, grain_ids):
        any_modified = False
        for grain_id in grain_ids:
            to_delete = np.where(self.full_grains_table[:, 0] == grain_id)[0]
            if to_delete.size == 0:
                continue

            self.remove_rows(to_delete)
            any_modified = True

        if any_modified:
            self.renumber_grains()
            self.grains_table_modified.emit()

    def renumber_grains(self):
        sorted_indices = np.argsort(self.full_grains_table[:, 0])
        print(f'Renumbering grains from 0 to {len(sorted_indices) - 1}...')

        for i, ind in enumerate(sorted_indices):
            self.full_grains_table[ind, 0] = i

        self.regenerate_grains_table()

    def remove_rows(self, rows):
        for row in rows:
            self.beginRemoveRows(QModelIndex(), row, row)
            self.removeRow(row)
            self.endRemoveRows()

    @property
    def included_columns(self):
        return [
            i for i in range(len(self.full_headers)) if i not in self.excluded_columns
        ]

    def save(self, path):
        write_grains_txt(self.full_grains_table, path)
        print('Wrote', path)
