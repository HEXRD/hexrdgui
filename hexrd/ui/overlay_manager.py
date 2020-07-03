from PySide2.QtCore import Qt, QItemSelectionModel, QSignalBlocker
from PySide2.QtWidgets import QCheckBox, QHBoxLayout, QTableWidgetItem, QWidget

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlay_editor import OverlayEditor
from hexrd.ui.ui_loader import UiLoader


COLUMNS = {
    'material': 0,
    'type': 1,
    'visible': 2
}


class OverlayManager:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('overlay_manager.ui', parent)
        self.check_boxes = []
        self.setup_connections()

    def setup_connections(self):
        self.ui.table.selectionModel().selectionChanged.connect(
            self.update_enable_states)
        self.ui.add_button.pressed.connect(self.add)
        self.ui.edit_button.pressed.connect(self.edit)
        self.ui.remove_button.pressed.connect(self.remove)

    def show(self):
        if not hasattr(self, 'already_shown'):
            self.already_shown = True
            self.move_dialog_to_left()

        self.update_table()
        self.ui.show()

    @staticmethod
    def format_type(type):
        types = {
            'powder': 'Powder',
            'laue': 'Laue',
            'mono_rotation_series': 'Mono Rotation Series'
        }

        if type not in types:
            raise Exception(f'Unknown type: {type}')

        return types[type]

    def update_table(self):
        block_list = [
            self.ui.table,
            self.ui.table.selectionModel()
        ]
        blockers = [QSignalBlocker(x) for x in block_list]  # noqa: F841

        prev_selected = self.selected_row

        overlays = HexrdConfig().overlays
        self.check_boxes.clear()
        self.ui.table.clearContents()
        self.ui.table.setRowCount(len(overlays))
        for i, overlay in enumerate(overlays):
            table_item = QTableWidgetItem(overlay['material'])
            table_item.setTextAlignment(Qt.AlignCenter)
            self.ui.table.setItem(i, COLUMNS['material'], table_item)

            table_item = QTableWidgetItem(self.format_type(overlay['type']))
            table_item.setTextAlignment(Qt.AlignCenter)
            self.ui.table.setItem(i, COLUMNS['type'], table_item)

            cb = QCheckBox(self.ui.table)
            cb.setChecked(overlay['visible'])
            cb.toggled.connect(self.update_config_visibilities)
            self.check_boxes.append(cb)

            # This is required to center the checkbox...
            w = QWidget(self.ui.table)
            layout = QHBoxLayout(w)
            layout.addWidget(cb)
            layout.setAlignment(Qt.AlignCenter)
            layout.setContentsMargins(0, 0, 0, 0)
            self.ui.table.setCellWidget(i, COLUMNS['visible'], w)

        if prev_selected is not None:
            select_row = (prev_selected if prev_selected < len(overlays)
                          else len(overlays) - 1)
            self.select_row(select_row)

        self.update_enable_states()

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

    def update_enable_states(self):
        row_selected = self.selected_row is not None
        self.ui.edit_button.setEnabled(row_selected)
        self.ui.remove_button.setEnabled(row_selected)

    def update_config_visibilities(self):
        for i in range(self.ui.table.rowCount()):
            w = self.check_boxes[i]
            HexrdConfig().overlays[i]['visible'] = w.isChecked()

        HexrdConfig().overlay_config_changed.emit()

    @property
    def active_material_name(self):
        return HexrdConfig().active_material_name

    def add(self):
        HexrdConfig().append_overlay(self.active_material_name, 'powder')
        self.update_table()
        self.select_row(len(HexrdConfig().overlays) - 1)

    def close_overlay_editor(self):
        if hasattr(self, '_overlay_editor'):
            self._overlay_editor.ui.reject()
            del self._overlay_editor

    def edit(self):
        overlay = HexrdConfig().overlays[self.selected_row]

        self.close_overlay_editor()
        self._overlay_editor = OverlayEditor(overlay)
        self._overlay_editor.update_manager_gui.connect(self.update_table)
        self._overlay_editor.show()

    def remove(self):
        self.close_overlay_editor()
        HexrdConfig().overlays.pop(self.selected_row)
        HexrdConfig().overlay_config_changed.emit()
        self.update_table()

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
