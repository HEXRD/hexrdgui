import math

from PySide2.QtCore import Qt, QItemSelectionModel, QSignalBlocker
from PySide2.QtWidgets import QTableWidgetItem

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class MaterialsTable:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('materials_table.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)
        self.setup_connections()

    def setup_connections(self):
        self.ui.table.selectionModel().selectionChanged.connect(
            self.update_ring_selections)

    def show(self):
        if not hasattr(self, 'already_shown'):
            self.already_shown = True
            self.move_dialog_to_left()

        self.ui.show()

    def update_material_name(self):
        self.ui.setWindowTitle(HexrdConfig().active_material_name)

    def update_ring_selections(self):
        # This updates the exclusions based upon the table selections
        plane_data = HexrdConfig().active_material.planeData
        selection_model = self.ui.table.selectionModel()
        selected_rows = [x.row() for x in selection_model.selectedRows()]

        indices = range(len(plane_data.exclusions))
        exclusions = [i not in selected_rows for i in indices]
        plane_data.exclusions = exclusions
        HexrdConfig().overlay_config_changed.emit()

    def update_table_selections(self):
        # This updates the table selections based on the exclusions
        material = HexrdConfig().active_material
        selection_model = self.ui.table.selectionModel()
        blocker = QSignalBlocker(selection_model)  # noqa: F841

        selection_model.clear()
        plane_data = material.planeData
        for i, exclude in enumerate(plane_data.exclusions):
            if exclude:
                continue

            # Add the row to the selections
            model_index = selection_model.model().index(i, 0)
            command = QItemSelectionModel.Select | QItemSelectionModel.Rows
            selection_model.select(model_index, command)

    def update_table(self):
        material = HexrdConfig().active_material

        block_list = [
            self.ui.table,
            self.ui.table.selectionModel()
        ]
        blockers = [QSignalBlocker(x) for x in block_list]  # noqa: F841

        plane_data = material.planeData

        # For the table, we will turn off exclusions so that all
        # rows are displayed, even the excluded ones. The user
        # picks the exclusions by selecting the rows.
        previous_exclusions = plane_data.exclusions
        plane_data.exclusions = [False] * len(plane_data.exclusions)

        hkls = plane_data.getHKLs(asStr=True)
        d_spacings = plane_data.getPlaneSpacings()
        tth = plane_data.getTTh()

        # Restore the previous exclusions
        plane_data.exclusions = previous_exclusions

        self.ui.table.clearContents()
        self.ui.table.setRowCount(len(hkls))
        for i, hkl in enumerate(hkls):
            table_item = QTableWidgetItem(hkl)
            table_item.setTextAlignment(Qt.AlignCenter)
            self.ui.table.setItem(i, 0, table_item)

            table_item = QTableWidgetItem('%.2f' % d_spacings[i])
            table_item.setTextAlignment(Qt.AlignCenter)
            self.ui.table.setItem(i, 1, table_item)

            table_item = QTableWidgetItem('%.2f' % math.degrees(tth[i]))
            table_item.setTextAlignment(Qt.AlignCenter)
            self.ui.table.setItem(i, 2, table_item)

        self.update_table_selections()
        self.update_material_name()

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
