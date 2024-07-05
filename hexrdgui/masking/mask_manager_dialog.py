import math
import os
import numpy as np
import h5py

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QMenu,
    QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QColorDialog
)
from PySide6.QtGui import QCursor, QColor


from hexrdgui.utils import block_signals
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType, MaskStatus
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url

import matplotlib.pyplot as plt


class MaskManagerDialog(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        loader = UiLoader()
        self.ui = loader.load_file('mask_manager_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        add_help_url(self.ui.button_box,
                     'configuration/masking/#managing-masks')

        self.setup_connections()

    def show(self):
        self.update_table()
        self.ui.show()

    def setup_connections(self):
        self.ui.masks_table.cellChanged.connect(self.update_mask_name)
        self.ui.masks_table.customContextMenuRequested.connect(
            self.context_menu_event)
        self.ui.export_masks.clicked.connect(MaskManager().write_all_masks)
        self.ui.import_masks.clicked.connect(self.import_masks)
        self.ui.panel_buffer.clicked.connect(self.masks_to_panel_buffer)
        self.ui.view_masks.clicked.connect(self.show_masks)
        self.ui.hide_all_masks.clicked.connect(self.hide_all_masks)
        self.ui.show_all_masks.clicked.connect(self.show_all_masks)
        MaskManager().mask_mgr_dialog_update.connect(self.update_table)
        self.ui.hide_all_boundaries.clicked.connect(self.hide_all_boundaries)
        self.ui.show_all_boundaries.clicked.connect(self.show_all_boundaries)
        MaskManager().mask_mgr_dialog_update.connect(self.update_table)
        MaskManager().export_masks_to_file.connect(self.export_masks_to_file)
        self.ui.border_color.clicked.connect(self.set_boundary_color)

    def update_table(self):
        with block_signals(self.ui.masks_table):
            self.ui.masks_table.setRowCount(0)
            for i, key in enumerate(MaskManager().mask_names):
                # Add label
                self.ui.masks_table.insertRow(i)
                self.ui.masks_table.setItem(i, 0, QTableWidgetItem(key))

                # Add combo box to select mask presentation
                mask_type = MaskManager().masks[key].type
                presentation_combo = QComboBox()
                presentation_combo.addItem('None')
                presentation_combo.addItem('Visible')
                idx = MaskStatus.none
                if key in MaskManager().visible_masks:
                    idx = MaskStatus.visible
                if (mask_type == MaskType.region or
                        mask_type == MaskType.polygon or
                        mask_type == MaskType.pinhole):
                    presentation_combo.addItem('Boundary Only')
                    presentation_combo.addItem('Visible + Boundary')
                    if key in MaskManager().visible_boundaries:
                        idx += MaskStatus.boundary
                presentation_combo.setCurrentIndex(idx)
                self.ui.masks_table.setCellWidget(i, 1, presentation_combo)
                presentation_combo.currentIndexChanged.connect(
                    lambda i, k=key: self.change_mask_presentation(i, k))

                # Add push button to remove mask
                pb = QPushButton('Remove Mask')
                self.ui.masks_table.setCellWidget(i, 2, pb)
                pb.clicked.connect(lambda i=i, k=key: self.remove_mask(i, k))

    def change_mask_presentation(self, index, name):
        match index:
            case MaskStatus.visible:
                MaskManager().update_mask_visibility(name, True)
                MaskManager().update_border_visibility(name, False)
            case MaskStatus.boundary:
                MaskManager().update_mask_visibility(name, False)
                MaskManager().update_border_visibility(name, True)
            case MaskStatus.all:
                MaskManager().update_mask_visibility(name, True)
                MaskManager().update_border_visibility(name, True)
            case _:
                MaskManager().update_mask_visibility(name, False)
                MaskManager().update_border_visibility(name, False)
        MaskManager().masks_changed()

    def remove_mask(self, row, name):
        MaskManager().remove_mask(name)
        self.ui.masks_table.removeRow(row)
        self.update_table()
        MaskManager().masks_changed()

    def update_mask_name(self, row):
        old_name = MaskManager().mask_names[row]
        new_name = self.ui.masks_table.item(row, 0).text()
        if old_name != new_name:
            if new_name in MaskManager().mask_names:
                self.ui.masks_table.item(row, 0).setText(old_name)
                return
            MaskManager().update_name(old_name, new_name)

        self.update_table()

    def context_menu_event(self, event):
        index = self.ui.masks_table.indexAt(event)
        if index.row() >= 0:
            menu = QMenu(self.ui.masks_table)
            export = menu.addAction('Export Mask')
            action = menu.exec(QCursor.pos())
            if action == export:
                selection = self.ui.masks_table.item(index.row(), 0).text()
                MaskManager().write_single_mask(selection)

    def export_masks_to_file(self, data):
        output_file, _ = QFileDialog.getSaveFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not output_file:
            return

        HexrdConfig().working_dir = os.path.dirname(output_file)
        # write to hdf5
        with h5py.File(output_file, 'w') as f:
            h5py_group = f.create_group('masks')
            MaskManager().write_masks_to_group(data, h5py_group)

    def import_masks(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Import Masks', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            return

        HexrdConfig().working_dir = os.path.dirname(selected_file)

        with h5py.File(selected_file, 'r') as f:
            MaskManager().load_masks(f['masks'])

    def masks_to_panel_buffer(self):
        show_dialog = False
        selection = 'Replace buffer'
        for det in HexrdConfig().detectors.values():
            buff_val = det.get('buffer', {}).get('value', None)
            if isinstance(buff_val, np.ndarray) and buff_val.ndim == 2:
                show_dialog = True
                break

        if show_dialog:
            dialog = QDialog(self.ui)
            layout = QVBoxLayout()
            dialog.setLayout(layout)

            options = QComboBox(dialog)
            options.addItem('Replace buffer')
            options.addItem('Logical AND with buffer')
            options.addItem('Logical OR with buffer')
            layout.addWidget(options)

            buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            button_box = QDialogButtonBox(buttons, dialog)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)

            if not dialog.exec():
                # canceled
                return

            selection = options.currentText()

        MaskManager().masks_to_panel_buffer(selection)
        msg = 'Masks set as panel buffers.'
        QMessageBox.information(self.parent, 'HEXRD', msg)

    def show_masks(self):
        num_dets = len(HexrdConfig().detector_names)
        cols = 2 if num_dets > 1 else 1
        rows = math.ceil(num_dets / cols)

        fig = plt.figure()
        fig.canvas.manager.set_window_title('User Created Masks')
        for i, det in enumerate(HexrdConfig().detector_names):
            axis = fig.add_subplot(rows, cols, i + 1)
            axis.set_title(det)
            axis.imshow(HexrdConfig().raw_masks_dict[det])
        fig.canvas.draw_idle()
        fig.show()

    def update_presentation_selector(self):
        with block_signals(self.ui.masks_table):
            for i, key in enumerate(MaskManager().mask_names):
                cb = self.ui.masks_table.cellWidget(i, 1)
                idx = MaskStatus.none
                if key in MaskManager().visible_masks:
                    idx += MaskStatus.visible
                if key in MaskManager().visible_boundaries:
                    idx += MaskStatus.boundary
                with block_signals(cb):
                    cb.setCurrentIndex(idx)

    def hide_all_masks(self):
        for name in MaskManager().mask_names:
            MaskManager().update_mask_visibility(name, False)
        self.update_presentation_selector()
        MaskManager().masks_changed()

    def show_all_masks(self):
        for name in MaskManager().mask_names:
            MaskManager().update_mask_visibility(name, True)
        self.update_presentation_selector()
        MaskManager().masks_changed()

    def hide_all_boundaries(self):
        for name in MaskManager().mask_names:
            MaskManager().update_border_visibility(name, False)
        self.update_presentation_selector()
        MaskManager().masks_changed()

    def show_all_boundaries(self):
        for name in MaskManager().mask_names:
            MaskManager().update_border_visibility(name, True)
        self.update_presentation_selector()
        MaskManager().masks_changed()

    def set_boundary_color(self):
        dialog = QColorDialog(QColor(MaskManager().boundary_color), self.ui)
        if dialog.exec():
            MaskManager().boundary_color = dialog.selectedColor().name()
            MaskManager().masks_changed()
