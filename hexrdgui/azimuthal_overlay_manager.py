from __future__ import annotations

import random
from typing import Any

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QTableWidgetItem,
    QWidget,
)
from hexrdgui import utils

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.azimuthal_overlay_editor import AzimuthalOverlayEditor
from hexrdgui.azimuthal_overlay_style_picker import AzimuthalOverlayStylePicker
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals

import numpy as np

COLUMNS = {
    'name': 0,
    'material': 1,
    'visible': 2,
}


class AzimuthalOverlayManager:

    def __init__(self, parent: QWidget | None = None) -> None:
        loader = UiLoader()
        self.ui = loader.load_file('azimuthal_overlay_manager.ui', parent)

        self.overlay_editor = AzimuthalOverlayEditor(self.ui)
        self.ui.overlay_editor_layout.addWidget(self.overlay_editor.ui)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.WindowType.Tool)

        self.material_combos: list[QComboBox] = []
        self.visibility_boxes: list[QCheckBox] = []

        self.setup_connections()

    def setup_connections(self) -> None:
        self.ui.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.ui.table.itemChanged.connect(self.table_item_changed)
        self.ui.add_button.pressed.connect(self.add)
        self.ui.remove_button.pressed.connect(self.remove)
        self.ui.edit_style_button.pressed.connect(self.edit_style)
        self.ui.show_legend.toggled.connect(self.show_legend)
        self.ui.show_legend.setChecked(HexrdConfig().show_azimuthal_legend)
        self.ui.save_plot.clicked.connect(
            HexrdConfig().azimuthal_plot_save_requested.emit
        )
        HexrdConfig().materials_added.connect(self.update_table)
        HexrdConfig().material_renamed.connect(self.on_material_renamed)
        HexrdConfig().materials_removed.connect(self.update_table)

        HexrdConfig().state_loaded.connect(self.update_table)
        HexrdConfig().material_modified.connect(self.on_material_modified)

    def show(self) -> None:
        self.update_table()
        self.ui.show()

    def on_material_renamed(self, old_name: str, new_name: str) -> None:
        self.update_table()

    def create_materials_combo(self, v: str) -> QWidget:
        materials = list(HexrdConfig().materials.keys())

        if v not in materials:
            raise Exception(f'Unknown material: {v}')

        cb = QComboBox(self.ui.table)
        size_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        cb.setSizePolicy(size_policy)
        for mat in materials:
            cb.addItem(mat, mat)

        cb.setCurrentIndex(materials.index(v))
        cb.currentIndexChanged.connect(self.update_config_materials)
        self.material_combos.append(cb)
        return self.create_table_widget(cb)

    def create_visibility_checkbox(self, v: bool) -> QWidget:
        cb = QCheckBox(self.ui.table)
        cb.setChecked(v)
        cb.toggled.connect(self.update_visibilities)
        self.visibility_boxes.append(cb)
        return self.create_table_widget(cb)

    def create_table_widget(self, w: QWidget) -> QWidget:
        # These are required to center the widget...
        tw = QWidget(self.ui.table)
        layout = QHBoxLayout(tw)
        layout.addWidget(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return tw

    def clear_table(self) -> None:
        self.material_combos.clear()
        self.visibility_boxes.clear()
        self.ui.table.clearContents()

    def update_table(self) -> None:
        block_list = [self.ui.table, self.ui.table.selectionModel()]

        with block_signals(*block_list):
            prev_selected = self.selected_row

            self.clear_table()
            self.ui.table.setRowCount(len(self.overlays))
            for i, overlay in enumerate(self.overlays):
                w = QTableWidgetItem(overlay['name'])
                self.ui.table.setItem(i, COLUMNS['name'], w)

                w = self.create_materials_combo(overlay['material'])  # type: ignore[assignment]
                self.ui.table.setCellWidget(i, COLUMNS['material'], w)

                w = self.create_visibility_checkbox(overlay['visible'])  # type: ignore[assignment]
                self.ui.table.setCellWidget(i, COLUMNS['visible'], w)

            if prev_selected is not None:
                select_row = (
                    prev_selected
                    if prev_selected < len(self.overlays)
                    else len(self.overlays) - 1
                )
                self.select_row(select_row)

            self.ui.table.resizeColumnsToContents()

            # The last section isn't always stretching automatically, even
            # though we have setStretchLastSection(True) set.
            # Force it to stretch manually.
            last_column = max(v for v in COLUMNS.values())
            self.ui.table.horizontalHeader().setSectionResizeMode(
                last_column, QHeaderView.ResizeMode.Stretch
            )

            # Just in case the selection actually changed...
            self.selection_changed()

    def select_row(self, i: int | None) -> None:
        if i is None or i >= self.ui.table.rowCount():
            # Out of range. Don't do anything.
            return

        # Select the row
        selection_model = self.ui.table.selectionModel()
        selection_model.clearSelection()

        model_index = selection_model.model().index(i, 0)
        command = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        selection_model.select(model_index, command)

    @property
    def overlays(self) -> list[dict[str, Any]]:
        return HexrdConfig().azimuthal_overlays

    @property
    def selected_row(self) -> int | None:
        selected = self.ui.table.selectionModel().selectedRows()
        return selected[0].row() if selected else None

    def selection_changed(self) -> None:
        self.update_enable_states()
        self.update_overlay_editor()

    def update_enable_states(self) -> None:
        row_selected = self.selected_row is not None
        self.ui.remove_button.setEnabled(row_selected)
        self.ui.edit_style_button.setEnabled(row_selected)
        self.overlay_editor.enable_inputs(row_selected)

    def update_overlay_editor(self) -> None:
        if self.selected_row is not None:
            overlay = self.overlays[self.selected_row]
            self.overlay_editor.selected_overlay = overlay
        else:
            self.overlay_editor.selected_overlay = None

    def update_config_materials(self) -> None:
        any_changed = False
        for i in range(self.ui.table.rowCount()):
            w = self.material_combos[i]
            overlay = self.overlays[i]
            if overlay['material'] != w.currentData():
                new_name = self.create_unique_name(w.currentData())
                if overlay['material'] in overlay['name']:
                    overlay['name'] = new_name
                overlay['material'] = w.currentData()
                any_changed = True

        if any_changed:
            # In case the material was renamed
            self.update_table()
            HexrdConfig().azimuthal_options_modified.emit()

    def update_visibilities(self) -> None:
        for i in range(self.ui.table.rowCount()):
            w = self.visibility_boxes[i]
            self.overlays[i]['visible'] = w.isChecked()
        HexrdConfig().azimuthal_options_modified.emit()

    @property
    def active_material_name(self) -> str | None:
        return HexrdConfig().active_material_name

    @property
    def active_overlay(self) -> dict[str, Any] | None:
        i = self.selected_row
        if i is None or i >= len(self.overlays):
            return None

        return self.overlays[i]

    def table_item_changed(self, item: QTableWidgetItem) -> None:
        col = item.column()
        if col == COLUMNS['name']:
            return self.overlay_name_edited(item)
        else:
            raise Exception(f'Item editing not implemented for column: {col}')

    def overlay_name_edited(self, item: QTableWidgetItem) -> None:
        row = item.row()
        new_name = item.text()
        modified_overlay = self.overlays[row]
        old_name = modified_overlay['name']

        # If the name matches any other overlay names, revert back so that
        # we can keep unique names.
        for overlay in self.overlays:
            if new_name == overlay['name']:
                # This name already exists. Revert changes.
                item.setText(old_name)
                return

        modified_overlay['name'] = new_name
        self.overlay_editor.update_name_label(new_name)

    def create_unique_name(self, name: str | None = None) -> str:
        if name is None:
            name = self.active_material_name or ''
        existing_names = [o['name'] for o in self.overlays]
        return utils.unique_name(existing_names, name)

    def add_azimuthal_overlay(self) -> None:
        tth: np.ndarray
        sum: np.ndarray
        data = HexrdConfig().last_unscaled_azimuthal_integral_data
        assert data is not None
        tth, sum = data
        data = {
            'name': self.create_unique_name(),
            'material': self.active_material_name,
            'visible': True,
            'fwhm': 2.0,
            'scale': np.max(sum) / 100,
            'color': f'#{random.randint(0, 0xFFFFFF):06x}',
            'opacity': 0.3,
        }
        self.overlays.append(data)

    def add(self) -> None:
        self.add_azimuthal_overlay()
        self.update_table()
        self.select_row(len(self.overlays) - 1)
        HexrdConfig().azimuthal_options_modified.emit()

    def remove(self) -> None:
        if self.selected_row is None:
            return
        self.overlays.pop(self.selected_row)
        self.update_table()
        HexrdConfig().azimuthal_options_modified.emit()

    def edit_style(self) -> None:
        self._style_picker = AzimuthalOverlayStylePicker(self.active_overlay, self.ui)
        self._style_picker.exec()

    def show_legend(self, value: bool) -> None:
        HexrdConfig().show_azimuthal_legend = value
        HexrdConfig().azimuthal_options_modified.emit()

    def on_material_modified(self, material_name: str) -> None:
        update_needed = False
        for overlay in self.overlays:
            if overlay['material'] == material_name:
                update_needed = True
                break

        if update_needed:
            HexrdConfig().azimuthal_options_modified.emit()
