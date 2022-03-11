from PySide2.QtCore import Qt, QItemSelectionModel, QSignalBlocker
from PySide2.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QSizePolicy, QTableWidgetItem, QWidget
)

from hexrd.ui.constants import OverlayType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlay_editor import OverlayEditor
from hexrd.ui.overlay_style_picker import OverlayStylePicker
from hexrd.ui.ui_loader import UiLoader


COLUMNS = {
    'name': 0,
    'material': 1,
    'type': 2,
    'visible': 3,
}


class OverlayManager:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('overlay_manager.ui', parent)

        self.overlay_editor = OverlayEditor(self.ui)
        self.ui.overlay_editor_layout.addWidget(self.overlay_editor.ui)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.material_combos = []
        self.type_combos = []
        self.visibility_boxes = []

        self.setup_connections()

    def setup_connections(self):
        self.ui.table.selectionModel().selectionChanged.connect(
            self.selection_changed)
        self.ui.table.itemChanged.connect(self.table_item_changed)
        self.ui.add_button.pressed.connect(self.add)
        self.ui.remove_button.pressed.connect(self.remove)
        self.ui.edit_style_button.pressed.connect(self.edit_style)
        HexrdConfig().update_overlay_editor.connect(self.update_overlay_editor)
        HexrdConfig().material_renamed.connect(self.update_table)
        HexrdConfig().materials_removed.connect(self.update_table)

        HexrdConfig().state_loaded.connect(self.update_table)

    def show(self):
        self.update_table()
        self.ui.show()

    @staticmethod
    def format_type(type):
        types = {
            OverlayType.powder: 'Powder',
            OverlayType.laue: 'Laue',
            OverlayType.rotation_series: 'Rotation Series',
        }

        if type not in types:
            raise Exception(f'Unknown type: {type}')

        return types[type]

    def create_materials_combo(self, v):
        materials = list(HexrdConfig().materials.keys())

        if v not in materials:
            raise Exception(f'Unknown material: {v}')

        cb = QComboBox(self.ui.table)
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cb.setSizePolicy(size_policy)
        for mat in materials:
            cb.addItem(mat, mat)

        cb.setCurrentIndex(materials.index(v))
        cb.currentIndexChanged.connect(self.update_config_materials)
        self.material_combos.append(cb)
        return self.create_table_widget(cb)

    def create_type_combo(self, v):
        types = list(OverlayType)
        if v not in types:
            raise Exception(f'Unknown type: {v}')

        cb = QComboBox(self.ui.table)
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cb.setSizePolicy(size_policy)
        for type in types:
            cb.addItem(self.format_type(type), type.value)

        cb.setCurrentIndex(types.index(v))
        cb.currentIndexChanged.connect(self.update_config_types)
        self.type_combos.append(cb)
        return self.create_table_widget(cb)

    def create_visibility_checkbox(self, v):
        cb = QCheckBox(self.ui.table)
        cb.setChecked(v)
        cb.toggled.connect(self.update_config_visibilities)
        self.visibility_boxes.append(cb)
        return self.create_table_widget(cb)

    def create_table_widget(self, w):
        # These are required to center the widget...
        tw = QWidget(self.ui.table)
        layout = QHBoxLayout(tw)
        layout.addWidget(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return tw

    def clear_table(self):
        self.material_combos.clear()
        self.type_combos.clear()
        self.visibility_boxes.clear()
        self.ui.table.clearContents()

    def update_table(self):
        block_list = [
            self.ui.table,
            self.ui.table.selectionModel()
        ]
        blockers = [QSignalBlocker(x) for x in block_list]  # noqa: F841

        prev_selected = self.selected_row

        overlays = HexrdConfig().overlays
        self.clear_table()
        self.ui.table.setRowCount(len(overlays))
        for i, overlay in enumerate(overlays):
            w = QTableWidgetItem(overlay.name)
            self.ui.table.setItem(i, COLUMNS['name'], w)

            w = self.create_materials_combo(overlay.material_name)
            self.ui.table.setCellWidget(i, COLUMNS['material'], w)

            w = self.create_type_combo(overlay.type)
            self.ui.table.setCellWidget(i, COLUMNS['type'], w)

            w = self.create_visibility_checkbox(overlay.visible)
            self.ui.table.setCellWidget(i, COLUMNS['visible'], w)

        if prev_selected is not None:
            select_row = (prev_selected if prev_selected < len(overlays)
                          else len(overlays) - 1)
            self.select_row(select_row)

        self.ui.table.resizeColumnsToContents()
        # Just in case the selection actually changed...
        self.selection_changed()

    def select_row(self, i):
        if i is None or i >= self.ui.table.rowCount():
            # Out of range. Don't do anything.
            return

        # Select the row
        selection_model = self.ui.table.selectionModel()
        selection_model.clearSelection()

        model_index = selection_model.model().index(i, 0)
        command = QItemSelectionModel.Select | QItemSelectionModel.Rows
        selection_model.select(model_index, command)

    @property
    def selected_row(self):
        selected = self.ui.table.selectionModel().selectedRows()
        return selected[0].row() if selected else None

    def selection_changed(self):
        self.update_enable_states()
        self.update_overlay_editor()

    def update_enable_states(self):
        row_selected = self.selected_row is not None
        self.ui.remove_button.setEnabled(row_selected)
        self.ui.edit_style_button.setEnabled(row_selected)

    def update_overlay_editor(self):
        self.overlay_editor.overlay = self.active_overlay

    def update_config_materials(self):
        for i in range(self.ui.table.rowCount()):
            w = self.material_combos[i]
            overlay = HexrdConfig().overlays[i]
            if overlay.material_name != w.currentData():
                overlay.material_name = w.currentData()

                # In case the active widget depends on material settings
                self.overlay_editor.update_active_widget_gui()

        HexrdConfig().update_visible_material_energies()
        HexrdConfig().overlay_config_changed.emit()

    def update_config_types(self):
        for i in range(self.ui.table.rowCount()):
            w = self.type_combos[i]
            # This won't do anything if the type already matches
            HexrdConfig().change_overlay_type(i, OverlayType(w.currentData()))

        HexrdConfig().overlay_config_changed.emit()
        self.update_overlay_editor()

    def update_config_visibilities(self):
        for i in range(self.ui.table.rowCount()):
            w = self.visibility_boxes[i]
            HexrdConfig().overlays[i].visible = w.isChecked()

        HexrdConfig().update_visible_material_energies()
        HexrdConfig().overlay_config_changed.emit()

    @property
    def active_material_name(self):
        return HexrdConfig().active_material_name

    @property
    def active_overlay(self):
        i = self.selected_row
        return HexrdConfig().overlays[i] if i is not None else None

    def update_refinement_options(self):
        self.overlay_editor.update_refinement_options()

    def table_item_changed(self, item):
        col = item.column()
        if col == COLUMNS['name']:
            return self.overlay_name_edited(item)
        else:
            raise Exception(f'Item editing not implemented for column: {col}')

    def overlay_name_edited(self, item):
        row = item.row()
        new_name = item.text()
        modified_overlay = HexrdConfig().overlays[row]
        old_name = modified_overlay.name

        # If the name matches any other overlay names, revert back so that
        # we can keep unique names.
        for overlay in HexrdConfig().overlays:
            if new_name == overlay.name:
                # This name already exists. Revert changes.
                item.setText(old_name)
                return

        modified_overlay.name = new_name

    def add(self):
        HexrdConfig().append_overlay(self.active_material_name,
                                     OverlayType.powder)
        self.update_table()
        self.select_row(len(HexrdConfig().overlays) - 1)

    def remove(self):
        HexrdConfig().overlays.pop(self.selected_row)
        HexrdConfig().overlay_config_changed.emit()
        self.update_table()

    def edit_style(self):
        self._style_picker = OverlayStylePicker(self.active_overlay, self.ui)
        self._style_picker.exec_()
