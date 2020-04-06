import copy
import math
import numpy as np

from PySide2.QtCore import QItemSelectionModel, QObject, Qt
from PySide2.QtWidgets import QMenu, QMessageBox, QTableWidgetItem

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.material_editor_widget import MaterialEditorWidget
from hexrd.ui.overlay_style_picker import OverlayStylePicker
from hexrd.ui.ui_loader import UiLoader


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
        self.ui.materials_combo.currentIndexChanged.connect(
            self.update_enable_states)
        self.ui.materials_combo.currentIndexChanged.connect(self.update_table)
        self.ui.materials_combo.lineEdit().textEdited.connect(
            self.modify_material_name)

        self.material_editor_widget.material_modified.connect(self.update_table)

        self.ui.materials_table.selectionModel().selectionChanged.connect(
            self.update_ring_selection)

        self.ui.show_overlays.toggled.connect(HexrdConfig()._set_show_overlays)
        self.ui.enable_width.toggled.connect(
            HexrdConfig().set_tth_width_enabled)
        self.ui.tth_width.valueChanged.connect(
            lambda v: HexrdConfig().set_active_material_tth_width(
                np.radians(v)))

        self.ui.limit_active.toggled.connect(
            HexrdConfig().set_limit_active_rings)
        self.ui.max_tth.valueChanged.connect(self.on_max_tth_changed)
        self.ui.min_d_spacing.valueChanged.connect(
            self.on_min_d_spacing_changed)

        self.ui.edit_style_button.pressed.connect(self.edit_overlay_style)
        self.ui.hide_all.pressed.connect(self.hide_all_materials)

        self.ui.material_visible.toggled.connect(
            self.material_visibility_toggled)

        HexrdConfig().new_plane_data.connect(self.update_gui_from_config)

        self.ui.enable_width.toggled.connect(self.update_enable_states)
        self.ui.limit_active.toggled.connect(self.update_enable_states)
        self.ui.limit_active.toggled.connect(self.update_material_limits)
        self.ui.limit_active.toggled.connect(self.update_table)

    def update_enable_states(self):
        enable_width = self.ui.enable_width.isChecked()
        self.ui.tth_width.setEnabled(enable_width)

        limit_active = self.ui.limit_active.isChecked()
        self.ui.max_tth.setEnabled(limit_active)
        self.ui.min_d_spacing.setEnabled(limit_active)
        self.ui.min_d_spacing_label.setEnabled(limit_active)
        self.ui.max_tth_label.setEnabled(limit_active)

    def on_max_tth_changed(self):
        max_tth = math.radians(self.ui.max_tth.value())
        wavelength = HexrdConfig().beam_wavelength

        w = self.ui.min_d_spacing
        block_signals = w.blockSignals(True)
        try:
            # Bragg's law
            max_bragg = max_tth / 2.0
            d = wavelength / (2.0 * math.sin(max_bragg))
            w.setValue(d)
        finally:
            w.blockSignals(block_signals)

        # Update the config
        HexrdConfig().active_material_tth_max = max_tth
        self.update_table()

    def on_min_d_spacing_changed(self):
        min_d = self.ui.min_d_spacing.value()
        wavelength = HexrdConfig().beam_wavelength

        w = self.ui.max_tth
        block_signals = w.blockSignals(True)
        try:
            # Bragg's law
            theta = math.degrees(math.asin(wavelength / 2.0 / min_d))
            w.setValue(theta * 2.0)
        finally:
            w.blockSignals(block_signals)

        # Update the config
        HexrdConfig().active_material_tth_max = math.radians(theta * 2.0)
        self.update_table()

    def update_gui_from_config(self):
        block_list = [
            self.material_editor_widget,
            self.ui.materials_combo,
            self.ui.show_overlays,
            self.ui.enable_width,
            self.ui.tth_width,
            self.ui.material_visible,
            self.ui.min_d_spacing,
            self.ui.max_tth,
            self.ui.limit_active
        ]

        block_signals = []
        for item in block_list:
            block_signals.append(item.blockSignals(True))

        try:
            current_items = sorted([self.ui.materials_combo.itemText(x) for x in
                range(self.ui.materials_combo.count())])
            materials_keys = sorted(list(HexrdConfig().materials.keys()))

            # If the materials in the config have changed, re-build the list
            if current_items != materials_keys:
                self.ui.materials_combo.clear()
                self.ui.materials_combo.addItems(materials_keys)

            self.material_editor_widget.material = HexrdConfig().active_material
            self.ui.materials_combo.setCurrentIndex(
                materials_keys.index(HexrdConfig().active_material_name))
            self.ui.show_overlays.setChecked(HexrdConfig().show_overlays)
            self.ui.enable_width.setChecked(HexrdConfig().tth_width_enabled)

            width = HexrdConfig().active_material_tth_width
            width = width if width else HexrdConfig().backup_tth_width
            self.ui.tth_width.setValue(np.degrees(width))

            self.ui.material_visible.setChecked(
                HexrdConfig().material_is_visible(self.current_material()))
            self.ui.limit_active.setChecked(HexrdConfig().limit_active_rings)
        finally:
            for b, item in zip(block_signals, block_list):
                item.blockSignals(b)

        self.update_material_limits()
        self.update_table()
        self.update_enable_states()

    def update_material_limits(self):
        max_tth = HexrdConfig().active_material_tth_max
        if max_tth is None:
            # Display the backup if it is None
            max_tth = HexrdConfig().backup_tth_max

        max_bragg = max_tth / 2.0

        # Bragg's law
        min_d_spacing = HexrdConfig().beam_wavelength / (
            2.0 * math.sin(max_bragg))

        block_list = [
            self.ui.min_d_spacing,
            self.ui.max_tth
        ]
        block_signals = [item.blockSignals(True) for item in block_list]
        try:
            self.ui.max_tth.setValue(math.degrees(max_tth))
            self.ui.min_d_spacing.setValue(min_d_spacing)
        finally:
            for b, item in zip(block_signals, block_list):
                item.blockSignals(b)

    def update_table(self):
        material = HexrdConfig().active_material

        block_list = [
            self.ui.materials_table,
            self.ui.materials_table.selectionModel()
        ]
        previously_blocked = [w.blockSignals(True) for w in block_list]
        try:
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

            self.ui.materials_table.clearContents()
            self.ui.materials_table.setRowCount(len(hkls))
            for i, hkl in enumerate(hkls):
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
            for block, w in zip(previously_blocked, block_list):
                w.blockSignals(block)

        self.update_table_selections()

    def update_table_selections(self):
        # This updates the table selections based on the exclusions
        material = HexrdConfig().active_material
        selection_model = self.ui.materials_table.selectionModel()
        block = selection_model.blockSignals(True)
        try:
            selection_model.clear()
            plane_data = material.planeData
            for i, exclude in enumerate(plane_data.exclusions):
                if exclude:
                    continue

                # Add the row to the selections
                model_index = selection_model.model().index(i, 0)
                command = QItemSelectionModel.Select | QItemSelectionModel.Rows
                selection_model.select(model_index, command)
        finally:
            selection_model.blockSignals(block)

    def update_ring_selection(self):
        # This updates the exclusions based upon the table selections
        plane_data = HexrdConfig().active_material.planeData
        selection_model = self.ui.materials_table.selectionModel()
        selected_rows = [x.row() for x in selection_model.selectedRows()]

        indices = range(len(plane_data.exclusions))
        exclusions = [i not in selected_rows for i in indices]
        plane_data.exclusions = exclusions
        HexrdConfig().ring_config_changed.emit()

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

        old_name = HexrdConfig().active_material_name
        HexrdConfig().rename_material(old_name, new_name)
        self.update_gui_from_config()

    def edit_overlay_style(self):
        material_name = self.current_material()

        # The overlay style picker will modify the HexrdConfig() itself
        picker = OverlayStylePicker(material_name, self.ui)
        picker.ui.exec_()

    def material_visibility_toggled(self):
        visible = self.ui.material_visible.isChecked()
        name = self.current_material()
        HexrdConfig().set_material_visibility(name, visible)

    def hide_all_materials(self):
        # This clears the list
        HexrdConfig().visible_material_names = []
