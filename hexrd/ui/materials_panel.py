import copy
import math

from PySide2.QtCore import QObject, Qt
from PySide2.QtWidgets import QMenu, QMessageBox, QTableWidgetItem

from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.material_editor_widget import MaterialEditorWidget
from hexrd.ui.hexrd_config import HexrdConfig


class MaterialsPanel(QObject):

    def __init__(self, parent=None):
        super(MaterialsPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('materials_panel.ui', parent)

        m = HexrdConfig().active_material
        self.material_editor_widget = MaterialEditorWidget(m, self.ui)

        self.ui.layout().insertWidget(2, self.material_editor_widget.ui)

        self.add_tool_button_actions()

        self.setup_connections()

        self.update_gui_from_config()

    def add_tool_button_actions(self):
        b = self.ui.materials_tool_button

        m = QMenu(b)
        self.tool_button_menu = m

        self.add_material_action = m.addAction('Add material')
        self.delete_material_action = m.addAction('Delete material')

        b.setMenu(m)

    def setup_connections(self):
        self.add_material_action.triggered.connect(self.add_material)
        self.delete_material_action.triggered.connect(
            self.remove_current_material)
        self.ui.materials_combo.currentIndexChanged.connect(
            self.set_active_material)
        self.ui.materials_combo.currentIndexChanged.connect(self.update_table)
        self.ui.materials_combo.lineEdit().textEdited.connect(
            self.modify_material_name)

        self.material_editor_widget.material_modified.connect(self.update_table)

        self.ui.materials_table.selectionModel().selectionChanged.connect(
            self.update_ring_selection)

        self.ui.show_rings.toggled.connect(HexrdConfig()._set_show_rings)
        self.ui.show_ranges.toggled.connect(
            HexrdConfig()._set_show_ring_ranges)
        self.ui.tth_ranges.valueChanged.connect(HexrdConfig()._set_ring_ranges)

        HexrdConfig().new_plane_data.connect(self.update_gui_from_config)

    def update_gui_from_config(self):
        block_list = [
            self.ui.materials_combo,
            self.ui.show_rings,
            self.ui.show_ranges,
            self.ui.tth_ranges
        ]

        block_signals = []
        for item in block_list:
            block_signals.append(item.blockSignals(True))

        try:
            self.ui.materials_combo.clear()
            materials = list(HexrdConfig().materials.keys())
            for mat in materials:
                self.ui.materials_combo.addItem(mat)

            self.ui.materials_combo.setCurrentText(
                HexrdConfig().active_material_name())

            self.ui.show_rings.setChecked(HexrdConfig().show_rings)
            self.ui.show_ranges.setChecked(HexrdConfig().show_ring_ranges)
            self.ui.tth_ranges.setValue(HexrdConfig().ring_ranges)
        finally:
            for b, item in zip(block_signals, block_list):
                item.blockSignals(b)

        self.update_table()

    def update_table(self):
        text = self.current_material()
        material = HexrdConfig().material(text)
        if not material:
            raise Exception('Material not found in configuration: ' + material)

        block = self.ui.materials_table.blockSignals(True)
        try:
            plane_data = material.planeData
            self.ui.materials_table.clearContents()
            self.ui.materials_table.setRowCount(plane_data.nHKLs)
            d_spacings = plane_data.getPlaneSpacings()
            tth = plane_data.getTTh()

            for i, hkl in enumerate(plane_data.getHKLs(asStr=True)):
                table_item = QTableWidgetItem(hkl)
                table_item.setTextAlignment(Qt.AlignCenter)
                self.ui.materials_table.setItem(i, 0, table_item)

                table_item = QTableWidgetItem('%.2f' % d_spacings[i])
                table_item.setTextAlignment(Qt.AlignCenter)
                self.ui.materials_table.setItem(i, 1, table_item)

                table_item = QTableWidgetItem('%.2f' % math.degrees(tth[i]))
                table_item.setTextAlignment(Qt.AlignCenter)
                self.ui.materials_table.setItem(i, 2, table_item)
        finally:
            self.ui.materials_table.blockSignals(block)

    def update_ring_selection(self):
        selection_model = self.ui.materials_table.selectionModel()
        selected_rows = [x.row() for x in selection_model.selectedRows()]
        HexrdConfig().selected_rings = selected_rows

    def set_active_material(self):
        HexrdConfig().active_material = self.current_material()
        self.material_editor_widget.material = HexrdConfig().active_material

    def current_material(self):
        return self.ui.materials_combo.currentText()

    def add_material(self):
        # Copy all of the active material properties to the dialog
        new_mat = copy.deepcopy(HexrdConfig().active_material)

        # Get a unique name
        base_name = 'new_material'
        names = HexrdConfig().materials.keys()
        for i in range(1, 10000):
            new_name = base_name + '_' + str(i)
            if new_name not in names:
                new_mat.name = new_name
                break

        HexrdConfig().add_material(new_name, new_mat)
        HexrdConfig().active_material = new_name
        self.material_editor_widget.material = new_mat
        self.update_gui_from_config()

    def remove_current_material(self):
        # Don't allow the user to remove all of the materials
        if len(HexrdConfig().materials.keys()) == 1:
            msg = 'Cannot remove all materials. Add another first.'
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        name = self.current_material()
        HexrdConfig().remove_material(name)
        self.material_editor_widget.material = HexrdConfig().active_material
        self.update_gui_from_config()

    def modify_material_name(self, new_name):
        names = HexrdConfig().materials.keys()

        if new_name in names:
            # Just ignore it
            return

        old_name = HexrdConfig().active_material_name()
        HexrdConfig().rename_material(old_name, new_name)
        self.update_gui_from_config()
