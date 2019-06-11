import math

from PySide2.QtCore import QObject, Qt
from PySide2.QtWidgets import QMenu, QTableWidgetItem

from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.add_material_dialog import AddMaterialDialog

class MaterialsPanel(QObject):

    def __init__(self, config, parent=None):
        super(MaterialsPanel, self).__init__(parent)

        self.config = config

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

    def update_table(self):
        text = self.ui.materials_combo.currentText().lower()
        material = self.config.get_material(text)
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

    def set_active_material(self):
        text = self.ui.materials_combo.currentText().lower()
        self.config.set_active_material(text)
