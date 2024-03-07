from contextlib import contextmanager
import csv
from io import StringIO
import math

import numpy as np

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMenu, QTableWidgetItem

from hexrd.material.crystallography import hklToStr

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.reflections_selection_helper import ReflectionsSelectionHelper
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals, exclusions_off, tth_max_off
from hexrdgui.utils.dialog import add_help_url


class COLUMNS:
    ID = 0
    HKL = 1
    D_SPACING = 2
    TTH = 3
    SF = 4
    HEDM_INTENSITY = 5
    POWDER_INTENSITY = 6
    MULTIPLICITY = 7


class ReflectionsTable:

    def __init__(self, material, title_prefix='', parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('reflections_table.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        add_help_url(self.ui.button_box,
                     'configuration/materials/#reflections-table')

        self.title_prefix = title_prefix
        self._material = material
        self.selection_helper = ReflectionsSelectionHelper(self.material,
                                                           self.ui)

        # If we are modifying the exclusions, skip updating the table, because
        # if we update the table during selection, it messes up something with
        # the selection on Qt's side.
        self._modifying_exclusions = False

        self.setup_connections()

        self.update_material_name()
        self.populate_relative_scale_options()
        self.update_table(only_if_visible=False)

    def setup_connections(self):
        self.ui.table.selectionModel().selectionChanged.connect(
            self.update_selections)
        self.ui.table.customContextMenuRequested.connect(
            self.on_table_context_menu_requested)

        HexrdConfig().materials_removed.connect(self.on_materials_removed)
        HexrdConfig().material_renamed.connect(self.on_material_renamed)
        HexrdConfig().materials_dict_modified.connect(
            self.on_materials_dict_modified)
        HexrdConfig().active_material_modified.connect(
            self.active_material_modified)
        HexrdConfig().update_reflections_tables.connect(
            self.update_table_if_name_matches)

        self.ui.relative_scale_material.currentIndexChanged.connect(
            self.on_relative_scale_material_changed)

        self.ui.show_selection_helper.clicked.connect(
            self.show_selection_helper)

        self.selection_helper.apply_clicked.connect(
            self.on_selection_helper_apply)

    def on_table_context_menu_requested(self, pos):
        # This is the item that was right-clicked
        item = self.ui.table.itemAt(pos)  # noqa

        menu = QMenu(self.ui)
        actions = {}

        # Helper functions
        def add_actions(d: dict):
            actions.update({menu.addAction(k): v for k, v in d.items()})

        add_actions({'Copy to Clipboard': self.copy_selected_to_clipboard})

        action_chosen = menu.exec(QCursor.pos())

        if action_chosen is None:
            return

        # Run the function for the action that was chosen
        actions[action_chosen]()

    def copy_selected_to_clipboard(self):
        table = self.ui.table
        clipboard = QApplication.instance().clipboard()

        with StringIO() as string_io:
            writer = csv.writer(string_io)

            # Write the headers
            headers = [table.horizontalHeaderItem(j).text()
                       for j in range(table.columnCount())]
            writer.writerow(headers)

            # Write the rows
            for i in sorted(self.selected_rows):
                row = []
                for j in range(table.columnCount()):
                    item = table.item(i, j)
                    text = item.text() if item is not None else ''
                    row.append(text)

                writer.writerow(row)

            # Copy it to the clipboard
            clipboard.setText(string_io.getvalue())

    def populate_relative_scale_options(self):
        old_setting = self.relative_scale_material_name
        if not old_setting:
            old_setting = self.material.name

        old_setting_found = False

        w = self.ui.relative_scale_material
        with block_signals(w):
            w.clear()
            names = list(HexrdConfig().materials)
            w.addItems(names)

            if old_setting in names:
                w.setCurrentText(old_setting)
                old_setting_found = True

        if not old_setting_found:
            # Default to the current material and trigger an update
            w.setCurrentText(self.material.name)

    def on_relative_scale_material_changed(self):
        # For now, just update the whole table
        self.update_table()

    def on_materials_dict_modified(self):
        # Re-populate the relative scale settings
        self.populate_relative_scale_options()

    @property
    def material(self):
        return self._material

    @material.setter
    def material(self, m):
        if m is self._material:
            return

        self._material = m
        self.update_material_name()
        # Change the relative scale material name to match the
        # new material's name.
        self.relative_scale_material_name = self.material.name
        self.update_selection_helper_material()
        self.update_table()

    @property
    def relative_scale_material(self):
        return HexrdConfig().material(self.relative_scale_material_name)

    @property
    def relative_scale_material_name(self):
        return self.ui.relative_scale_material.currentText()

    @relative_scale_material_name.setter
    def relative_scale_material_name(self, v):
        self.ui.relative_scale_material.setCurrentText(v)

    def show(self):
        self.update_table(only_if_visible=False)
        self.ui.show()

    def hide(self):
        self.ui.hide()
        self.hide_selection_helper()

    def on_materials_removed(self):
        # If our material isn't the active material, and it was removed,
        # hide it. If it is the active material, it will be changed elsewhere.
        if HexrdConfig().active_material is self.material:
            return

        if self.material.name not in HexrdConfig().materials:
            self.hide()

    def on_material_renamed(self, old_name, new_name):
        if self.relative_scale_material_name == old_name:
            # Need to update the combo box text
            cb = self.ui.relative_scale_material
            cb.setItemText(cb.currentIndex(), new_name)

        self.update_material_name()

    def update_material_name(self):
        self.ui.setWindowTitle(f'{self.title_prefix}{self.material.name}')
        self.update_selection_helper_material_name()

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

        # Indicate that we are modifying exclusions so the table will not
        # update
        self._modifying_exclusions = True
        try:
            HexrdConfig().overlay_config_changed.emit()
        finally:
            self._modifying_exclusions = False

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
        with block_signals(selection_model):
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
            # In case the relative material was deleted, update this
            self.populate_relative_scale_options()
            self.update_table()

    def update_table(self, only_if_visible=True):
        if self._modifying_exclusions:
            # Don't update the table if we are modifying the exclusions
            return

        if only_if_visible and not self.ui.isVisible():
            # If it is not visible, don't bother updating the table.
            return

        material = self.material
        table = self.ui.table

        block_list = [
            table,
            table.selectionModel()
        ]

        with block_signals(*block_list):
            plane_data = material.planeData

            # For the table, we will turn off exclusions so that all
            # rows are displayed, even the excluded ones. The user
            # picks the exclusions by selecting the rows.
            with exclusions_off(plane_data):
                with tth_max_off(plane_data):
                    hkls = plane_data.getHKLs(asStr=True)
                    d_spacings = plane_data.getPlaneSpacings()
                    tth = plane_data.getTTh()
                    powder_intensity = plane_data.powder_intensity
                    hedm_intensity = plane_data.hedm_intensity
                    multiplicity = plane_data.getMultiplicity()

                    # Since structure factors use arbitrary scaling, re-scale
                    # them to a range that's easier on the eyes.
                    sf = self.rescaled_structure_factor

            # Grab the hkl ids
            hkl_ids = [-1] * len(hkls)
            for hkl_data in plane_data.hklDataList:
                try:
                    idx = hkls.index(hklToStr(hkl_data['hkl']))
                except ValueError:
                    continue
                else:
                    hkl_ids[idx] = hkl_data['hklID']

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

                    table_item = FloatTableItem(hedm_intensity[i])
                    table.setItem(i, COLUMNS.HEDM_INTENSITY, table_item)

                    table_item = FloatTableItem(powder_intensity[i])
                    table.setItem(i, COLUMNS.POWDER_INTENSITY, table_item)

                    table_item = IntTableItem(multiplicity[i])
                    table.setItem(i, COLUMNS.MULTIPLICITY, table_item)

                    # Set the selectability for the entire row
                    selectable = True
                    if plane_data.tThMax is not None:
                        selectable = tth[i] <= plane_data.tThMax

                    self.set_row_selectable(i, selectable)

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

    def set_row_selectable(self, i, selectable):
        table = self.ui.table
        for j in range(table.columnCount()):
            item = table.item(i, j)
            flags = item.flags()
            if selectable:
                flags |= Qt.ItemIsSelectable | Qt.ItemIsEnabled
            else:
                flags &= ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled

            item.setFlags(flags)

    @property
    def rescaled_structure_factor(self):
        # Rescale structure factors according to the current relative
        # material.

        def get_sfact(pd):
            # pd is a PlaneData object
            with exclusions_off(pd):
                with tth_max_off(pd):
                    return pd.structFact

        this_pd = self.material.planeData
        compare_material = self.relative_scale_material
        if compare_material is None:
            # This shouldn't happen, but in case it does, reset the relative
            # scale material to the current material.
            self.relative_scale_material_name = self.material.name
            compare_material = self.material

        compare_pd = compare_material.planeData

        sf = get_sfact(this_pd)
        if len(sf) == 0:
            return sf

        if this_pd is compare_pd:
            compare_sf = sf
        else:
            compare_sf = get_sfact(compare_pd)

        # Rescale the other structure factor to be between 0 and 100
        return ((sf - compare_sf.min()) /
                (compare_sf.max() - compare_sf.min()) * 100)

    def update_selection_helper_material(self):
        self.selection_helper.material = self.material

    def update_selection_helper_material_name(self):
        self.selection_helper.update_material_name()

    def show_selection_helper(self):
        self.selection_helper.show()

    def hide_selection_helper(self):
        self.selection_helper.hide()

    def on_selection_helper_apply(self):
        d = self.selection_helper
        min_sfac = d.min_sfac
        max_sfac = d.max_sfac

        exclusions = np.zeros_like(self.exclusions, dtype=bool)

        if min_sfac is not None or max_sfac is not None:
            sf = self.rescaled_structure_factor
            if min_sfac:
                exclusions[sf < min_sfac] = True
            if max_sfac:
                exclusions[sf > max_sfac] = True

        self.exclusions = exclusions
        # update_selected_rows() would be better here, but it doesn't always
        # update unless we update the whole table.
        self.update_table()


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
