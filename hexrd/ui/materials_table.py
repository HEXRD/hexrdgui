from contextlib import contextmanager
import math

import numpy as np

from PySide2.QtCore import Qt, QItemSelectionModel, QSignalBlocker
from PySide2.QtWidgets import QTableWidgetItem

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import exclusions_off


class COLUMNS:
    HKL = 0
    D_SPACING = 1
    TTH = 2
    SF = 3
    MULTIPLICITY = 4


class MaterialsTable:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('materials_table.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)
        self.setup_connections()

    def setup_connections(self):
        self.ui.table.selectionModel().selectionChanged.connect(
            self.update_selections)

    def show(self):
        if not hasattr(self, 'already_shown'):
            self.already_shown = True
            self.move_dialog_to_left()

        self.ui.show()

    def update_material_name(self):
        self.ui.setWindowTitle(HexrdConfig().active_material_name)

    def update_selections(self):
        # This updates the exclusions based upon the selected rows
        self.selections = self.map_rows_to_selections(self.selected_rows)

    def update_selected_rows(self):
        # This updates the selected rows based on the exclusions
        self.selected_rows = self.map_selections_to_rows(self.selections)

    @property
    def exclusions(self):
        return HexrdConfig().active_material.planeData.exclusions

    @exclusions.setter
    def exclusions(self, exclusions):
        if np.array_equal(exclusions, self.exclusions):
            return

        HexrdConfig().active_material.planeData.exclusions = exclusions
        HexrdConfig().flag_overlay_updates_for_active_material()
        HexrdConfig().overlay_config_changed.emit()

    @property
    def selections(self):
        return [i for i, x in enumerate(self.exclusions) if not x]

    @selections.setter
    def selections(self, selections):
        if sorted(selections) == sorted(self.selections):
            return

        indices = range(len(self.exclusions))
        self.exclusions = [i not in selections for i in indices]

    @property
    def selected_rows(self):
        selection_model = self.ui.table.selectionModel()
        return [x.row() for x in selection_model.selectedRows()]

    @selected_rows.setter
    def selected_rows(self, rows):
        selection_model = self.ui.table.selectionModel()
        blocker = QSignalBlocker(selection_model)  # noqa: F841
        selection_model.clear()

        command = QItemSelectionModel.Select | QItemSelectionModel.Rows
        for i in rows:
            model_index = selection_model.model().index(i, 0)
            selection_model.select(model_index, command)

    def update_table(self):
        material = HexrdConfig().active_material
        table = self.ui.table

        block_list = [
            table,
            table.selectionModel()
        ]
        blockers = [QSignalBlocker(x) for x in block_list]  # noqa: F841

        plane_data = material.planeData

        # For the table, we will turn off exclusions so that all
        # rows are displayed, even the excluded ones. The user
        # picks the exclusions by selecting the rows.
        with exclusions_off(plane_data):
            hkls = plane_data.getHKLs(asStr=True)
            d_spacings = plane_data.getPlaneSpacings()
            tth = plane_data.getTTh()
            sf = plane_data.structFact
            multiplicity = plane_data.getMultiplicity()

        self.update_hkl_index_maps(hkls)

        table.clearContents()
        table.setRowCount(len(hkls))

        # We have to disable sorting while adding items, or else Qt
        # will automatically move some rows in the middle of setItem().
        # After sorting is enabled again, Qt sorts the table.
        with sorting_disabled(table):
            for i, hkl in enumerate(hkls):
                table_item = HklTableItem(hkl)
                table.setItem(i, COLUMNS.HKL, table_item)

                table_item = FloatTableItem(d_spacings[i])
                table.setItem(i, COLUMNS.D_SPACING, table_item)

                table_item = FloatTableItem(math.degrees(tth[i]))
                table.setItem(i, COLUMNS.TTH, table_item)

                table_item = FloatTableItem(sf[i])
                table.setItem(i, COLUMNS.SF, table_item)

                table_item = IntTableItem(multiplicity[i])
                table.setItem(i, COLUMNS.MULTIPLICITY, table_item)

        self.update_selected_rows()
        self.update_material_name()

    def update_hkl_index_maps(self, hkls):
        self.hkl_to_index_map = {x: i for i, x in enumerate(hkls)}
        self.index_to_hkl_map = {i: x for i, x in enumerate(hkls)}

    def map_rows_to_selections(self, rows):
        table = self.ui.table
        selected_hkls = [table.item(i, COLUMNS.HKL).text() for i in rows]
        return [self.hkl_to_index_map[x] for x in selected_hkls]

    def map_selections_to_rows(self, selections):
        selected_hkls = [self.index_to_hkl_map[x] for x in selections]
        table = self.ui.table
        rows = []
        for i in range(table.rowCount()):
            if table.item(i, COLUMNS.HKL).text() in selected_hkls:
                rows.append(i)

        return rows

    def move_dialog_to_left(self):
        # This moves the dialog to the left border of the parent
        parent = self.ui.parent()
        if not parent:
            return

        ph = parent.geometry().height()
        px = parent.geometry().x()
        py = parent.geometry().y()
        dw = self.ui.width()
        dh = self.ui.height()
        self.ui.setGeometry(px, py + (ph - dh) / 2.0, dw, dh)


class HklTableItem(QTableWidgetItem):
    """Subclass so we can sort by HKLs instead of strings"""
    def __init__(self, data):
        super().__init__(data)
        self.setTextAlignment(Qt.AlignCenter)

    @property
    def sort_value(self):
        return tuple(map(int, self.text().split()))

    def __lt__(self, other):
        return self.sort_value < other.sort_value


class FloatTableItem(QTableWidgetItem):
    """Subclass so we can sort as floats instead of strings"""
    DATA_ROLE = Qt.UserRole

    def __init__(self, data):
        super().__init__(f'{data:.2f}')
        self.setTextAlignment(Qt.AlignCenter)
        self.setData(self.DATA_ROLE, data)

    @property
    def sort_value(self):
        return self.data(self.DATA_ROLE)

    def __lt__(self, other):
        return self.sort_value < other.sort_value


class IntTableItem(QTableWidgetItem):
    """Subclass so we can sort as ints instead of strings"""
    DATA_ROLE = Qt.UserRole

    def __init__(self, data):
        super().__init__(f'{data}')
        self.setTextAlignment(Qt.AlignCenter)
        self.setData(self.DATA_ROLE, data)

    @property
    def sort_value(self):
        return self.data(self.DATA_ROLE)

    def __lt__(self, other):
        return self.sort_value < other.sort_value


@contextmanager
def sorting_disabled(table):
    prev = table.isSortingEnabled()
    table.setSortingEnabled(False)
    try:
        yield
    finally:
        table.setSortingEnabled(prev)
