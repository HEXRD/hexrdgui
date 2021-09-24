from contextlib import contextmanager
import math

import numpy as np

from PySide2.QtCore import Qt, QItemSelectionModel, QSignalBlocker
from PySide2.QtWidgets import QTableWidgetItem

from hexrd.crystallography import hklToStr

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import exclusions_off


class COLUMNS:
    ID = 0
    HKL = 1
    D_SPACING = 2
    TTH = 3
    SF = 4
    POWDER_INTENSITY = 5
    MULTIPLICITY = 6


class ReflectionsTable:

    def __init__(self, material, title_prefix='', parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('reflections_table.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)
        self.setup_connections()

        self.title_prefix = title_prefix
        self._material = material
        self.update_material_name()
        self.update_table()

    def setup_connections(self):
        self.ui.table.selectionModel().selectionChanged.connect(
            self.update_selections)

        HexrdConfig().active_material_modified.connect(
            self.active_material_modified)
        HexrdConfig().material_renamed.connect(self.update_material_name)
        HexrdConfig().update_reflections_tables.connect(
            self.update_table_if_name_matches)

    @property
    def material(self):
        return self._material

    @material.setter
    def material(self, m):
        if m is self._material:
            return

        self._material = m
        self.update_material_name()
        self.update_table()

    def show(self):
        self.ui.show()

    def update_material_name(self):
        self.ui.setWindowTitle(f'{self.title_prefix}{self.material.name}')

    def update_selections(self):
        # This updates the exclusions based upon the selected rows
        self.selections = self.map_rows_to_selections(self.selected_rows)

    def update_selected_rows(self):
        # This updates the selected rows based on the exclusions
        self.selected_rows = self.map_selections_to_rows(self.selections)

    @property
    def exclusions(self):
        return self.material.planeData.exclusions

    @exclusions.setter
    def exclusions(self, exclusions):
        if np.array_equal(exclusions, self.exclusions):
            return

        self.material.planeData.exclusions = exclusions
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)
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

    def active_material_modified(self):
        if HexrdConfig().active_material is self.material:
            self.update_table()

    def update_table_if_name_matches(self, name):
        if self.material.name == name:
            self.update_table()

    def update_table(self):
        material = self.material
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
            powder_intensity = plane_data.powder_intensity
            multiplicity = plane_data.getMultiplicity()

        # Grab the hkl ids
        hkl_ids = [-1] * len(hkls)
        for hkl_data in plane_data.hklDataList:
            try:
                idx = hkls.index(hklToStr(hkl_data['hkl']))
            except ValueError:
                continue
            else:
                hkl_ids[idx] = hkl_data['hklID']

        # Since structure factors use arbitrary scaling, re-scale them
        # to a range that's easier on the eyes.
        rescale_structure_factors(sf)

        self.update_hkl_index_maps(hkls)

        table.clearContents()
        table.setRowCount(len(hkls))

        # We have to disable sorting while adding items, or else Qt
        # will automatically move some rows in the middle of setItem().
        # After sorting is enabled again, Qt sorts the table.
        with sorting_disabled(table):
            for i, hkl in enumerate(hkls):
                table_item = IntTableItem(hkl_ids[i])
                table.setItem(i, COLUMNS.ID, table_item)

                table_item = HklTableItem(hkl)
                table.setItem(i, COLUMNS.HKL, table_item)

                table_item = FloatTableItem(d_spacings[i])
                table.setItem(i, COLUMNS.D_SPACING, table_item)

                table_item = FloatTableItem(math.degrees(tth[i]))
                table.setItem(i, COLUMNS.TTH, table_item)

                table_item = FloatTableItem(sf[i])
                table.setItem(i, COLUMNS.SF, table_item)

                table_item = FloatTableItem(powder_intensity[i])
                table.setItem(i, COLUMNS.POWDER_INTENSITY, table_item)

                table_item = IntTableItem(multiplicity[i])
                table.setItem(i, COLUMNS.MULTIPLICITY, table_item)

        table.resizeColumnsToContents()

        self.update_selected_rows()
        self.update_material_name()

    def update_hkl_index_maps(self, hkls):
        self.hkl_to_index_map = {x: i for i, x in enumerate(hkls)}
        self.index_to_hkl_map = {i: x for i, x in enumerate(hkls)}

    def map_rows_to_selections(self, rows):
        table = self.ui.table
        selected_hkls = [table.item(i, COLUMNS.HKL).text() for i in rows]

        ret = []
        for x in selected_hkls:
            if x not in self.hkl_to_index_map:
                continue

            ret.append(self.hkl_to_index_map[x])

        return ret

    def map_selections_to_rows(self, selections):
        selected_hkls = []
        for x in selections:
            if x not in self.index_to_hkl_map:
                continue

            selected_hkls.append(self.index_to_hkl_map[x])

        table = self.ui.table
        rows = []
        for i in range(table.rowCount()):
            if table.item(i, COLUMNS.HKL).text() in selected_hkls:
                rows.append(i)

        return rows


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


def rescale_structure_factors(sf):
    if len(sf) == 0:
        return

    # Rescale the structure factors to be between 0 and 100
    sf[:] = np.interp(sf, (sf.min(), sf.max()), (0, 100))
