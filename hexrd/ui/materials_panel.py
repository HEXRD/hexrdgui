import math

from PySide2.QtCore import QObject, Qt
from PySide2.QtWidgets import QMenu, QTableWidgetItem

from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.add_material_dialog import AddMaterialDialog
from hexrd.ui.hexrd_config import HexrdConfig

class MaterialsPanel(QObject):

    def __init__(self, parent=None):
        super(MaterialsPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('materials_panel.ui', parent)
        self.add_material_dialog = AddMaterialDialog(self.ui)

        self.add_tool_button_actions()

        self.setup_connections()

        self.update_table()

    def add_tool_button_actions(self):
        b = self.ui.materials_tool_button

        m = QMenu(b)
        self.tool_button_menu = m

        self.add_material_action = m.addAction('Add material')
        self.modify_material_action = m.addAction('Modify material')
        self.delete_material_action = m.addAction('Delete material')

        b.setMenu(m)

    def setup_connections(self):
        self.add_material_action.triggered.connect(
            self.add_material_dialog.show)
        self.ui.materials_combo.currentIndexChanged.connect(
            self.update_table)
        self.ui.materials_combo.currentIndexChanged.connect(
            self.set_active_material)

        self.ui.materials_table.selectionModel().selectionChanged.connect(
            self.update_ring_selection)

        self.ui.show_rings.toggled.connect(HexrdConfig().set_show_rings)
        self.ui.show_ranges.toggled.connect(HexrdConfig().set_show_ring_ranges)
        self.ui.tth_ranges.valueChanged.connect(HexrdConfig().set_ring_ranges)

    def update_table(self):
        text = self.ui.materials_combo.currentText().lower()
        material = HexrdConfig().material(text)
        if not material:
            raise Exception('Material not found in configuration: ' + material)

        plane_data = material.planeData
        self.ui.materials_table.clearContents()
        self.ui.materials_table.setRowCount(plane_data.nHKLs)

        d_spacings = plane_data.getPlaneSpacings()
        tth = plane_data.getTTh()

        for i, hkl in enumerate(plane_data.getHKLs()):
            hkl = str(hkl).replace(' ', '').replace('[', '(').replace(']', ')')
            table_item = QTableWidgetItem(hkl)
            table_item.setTextAlignment(Qt.AlignCenter)
            self.ui.materials_table.setItem(i, 0, table_item)

            table_item = QTableWidgetItem('%.2f' % d_spacings[i])
            table_item.setTextAlignment(Qt.AlignCenter)
            self.ui.materials_table.setItem(i, 1, table_item)

            table_item = QTableWidgetItem('%.2f' % math.degrees(tth[i]))
            table_item.setTextAlignment(Qt.AlignCenter)
            self.ui.materials_table.setItem(i, 2, table_item)

    def update_ring_selection(self):
        selection_model = self.ui.materials_table.selectionModel()
        selected_rows = [x.row() for x in selection_model.selectedRows()]
        HexrdConfig().set_selected_rings(selected_rows)

    def set_active_material(self):
        text = self.ui.materials_combo.currentText().lower()
        HexrdConfig().set_active_material(text)
