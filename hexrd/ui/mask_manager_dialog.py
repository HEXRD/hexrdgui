import copy
import math
from hexrd.ui.create_polar_mask import rebuild_polar_masks
from hexrd.ui.create_raw_mask import rebuild_raw_masks
import os
import numpy as np
import h5py

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QMenu,
    QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout
)
from PySide6.QtGui import QCursor

from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict
from hexrd.utils.compatibility import h5py_read_string

from hexrd.ui.utils import block_signals, unique_name
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.constants import ViewType

import matplotlib.pyplot as plt


class MaskManagerDialog(QObject):

    # Emitted when masks are removed or visibility is toggled
    update_masks = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        loader = UiLoader()
        self.ui = loader.load_file('mask_manager_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)
        self.create_masks_list()
        self.threshold = None
        self.image_mode = ViewType.raw

        self.setup_connections()

    def show(self):
        self.setup_table()
        self.ui.show()

    def create_masks_list(self):
        self.masks = {}
        raw_data = HexrdConfig().raw_mask_coords

        for key, val in raw_data.items():
            if not any(np.array_equal(m, val) for m in self.masks.values()):
                self.masks[key] = val
        if HexrdConfig().threshold_mask_status:
            self.threshold = 'threshold'
            self.masks['threshold'] = (
                'threshold', HexrdConfig().threshold_masks)
        HexrdConfig().visible_masks = list(self.masks.keys())

    def update_masks_list(self, mask_type):
        if mask_type == 'raw' or mask_type == 'polar':
            if not HexrdConfig().raw_mask_coords:
                return
            for name, value in HexrdConfig().raw_mask_coords.items():
                det, val = value[0]
                vals = self.masks.values()
                if any(np.array_equal(val, m) for _, m in vals):
                    continue
                self.masks[name] = (det, val)
        elif mask_type == 'threshold':
            if self.threshold is None and HexrdConfig().threshold_mask_status:
                name = unique_name(self.masks, 'threshold')
                self.masks[name] = ('threshold', HexrdConfig().threshold_masks)
                HexrdConfig().visible_masks.append(name)
                self.threshold = name
                self.toggle_visibility(True, self.threshold)
            elif self.threshold and not HexrdConfig().threshold_masks:
                items = self.ui.masks_table.findItems(
                    self.threshold, Qt.MatchExactly)
                if items:
                    self.remove_mask(items[0].row(), self.threshold)
        self.setup_table()

    def setup_connections(self):
        self.ui.masks_table.cellDoubleClicked.connect(self.get_old_name)
        self.ui.masks_table.cellChanged.connect(self.update_mask_name)
        self.ui.masks_table.customContextMenuRequested.connect(
            self.context_menu_event)
        self.ui.export_masks.clicked.connect(self.write_all_masks)
        self.ui.import_masks.clicked.connect(self.import_masks)
        self.ui.panel_buffer.clicked.connect(self.masks_to_panel_buffer)
        self.ui.view_masks.clicked.connect(self.show_masks)
        self.ui.hide_all_masks.clicked.connect(self.hide_all_masks)
        self.ui.show_all_masks.clicked.connect(self.show_all_masks)

        HexrdConfig().threshold_mask_changed.connect(
            self.update_masks_list)
        HexrdConfig().detectors_changed.connect(self.clear_masks)
        HexrdConfig().save_state.connect(self.save_state)
        HexrdConfig().load_state.connect(self.load_state)
        HexrdConfig().state_loaded.connect(self.rebuild_masks)

    def setup_table(self, status=True):
        with block_signals(self.ui.masks_table):
            self.ui.masks_table.setRowCount(0)
            for i, key in enumerate(self.masks.keys()):
                # Add label
                self.ui.masks_table.insertRow(i)
                self.ui.masks_table.setItem(i, 0, QTableWidgetItem(key))

                # Add checkbox to toggle visibility
                cb = QCheckBox()
                status = key in HexrdConfig().visible_masks
                cb.setChecked(status)
                cb.setStyleSheet('margin-left:50%; margin-right:50%;')
                self.ui.masks_table.setCellWidget(i, 1, cb)
                cb.toggled.connect(
                    lambda c, k=key: self.toggle_visibility(c, k))

                # Add push button to remove mask
                pb = QPushButton('Remove Mask')
                self.ui.masks_table.setCellWidget(i, 2, pb)
                pb.clicked.connect(lambda i=i, k=key: self.remove_mask(i, k))

    def image_mode_changed(self, mode):
        self.image_mode = mode

    def masks_changed(self):
        if self.image_mode in (ViewType.polar, ViewType.stereo):
            HexrdConfig().polar_masks_changed.emit()
        elif self.image_mode == ViewType.raw:
            HexrdConfig().raw_masks_changed.emit()

    def toggle_visibility(self, checked, name):
        if checked and name not in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.append(name)
        elif not checked and name in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.remove(name)

        if name == self.threshold:
            HexrdConfig().threshold_mask_status = checked

        self.masks_changed()

    def reset_threshold(self):
        self.threshold = None
        HexrdConfig().threshold_values = []
        HexrdConfig().threshold_masks = {
            d: None for d in HexrdConfig().detector_names }
        HexrdConfig().mgr_threshold_mask_changed.emit()

    def remove_mask(self, row, name):
        mtype, _ = self.masks.get(name, (None, None))
        if mtype is None:
            return

        del self.masks[name]
        if name in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.remove(name)
        HexrdConfig().raw_mask_coords.pop(name, None)
        HexrdConfig().masks.pop(name, None)
        if mtype == 'threshold':
            self.reset_threshold()

        self.ui.masks_table.removeRow(row)
        self.setup_table()

        self.masks_changed()

    def get_old_name(self, row, column):
        if column != 0:
            return

        self.old_name = self.ui.masks_table.item(row, 0).text()

    def update_mask_name(self, row):
        if not hasattr(self, 'old_name') or self.old_name is None:
            return

        new_name = self.ui.masks_table.item(row, 0).text()
        if self.old_name != new_name:
            if new_name in self.masks.keys():
                self.ui.masks_table.item(row, 0).setText(self.old_name)
                return

            self.masks[new_name] = self.masks.pop(self.old_name)
            if self.old_name in HexrdConfig().raw_mask_coords.keys():
                value = HexrdConfig().raw_mask_coords.pop(self.old_name)
                HexrdConfig().raw_mask_coords[new_name] = value

            if self.old_name in HexrdConfig().masks.keys():
                value = HexrdConfig().masks.pop(self.old_name)
                HexrdConfig().masks[new_name] = value

            if self.old_name in HexrdConfig().visible_masks:
                HexrdConfig().visible_masks.append(new_name)
                HexrdConfig().visible_masks.remove(self.old_name)

            if self.old_name == self.threshold:
                self.threshold = new_name

        self.old_name = None
        self.setup_table()

    def context_menu_event(self, event):
        index = self.ui.masks_table.indexAt(event)
        if index.row() >= 0:
            menu = QMenu(self.ui.masks_table)
            export = menu.addAction('Export Mask')
            action = menu.exec(QCursor.pos())
            if action == export:
                selection = self.ui.masks_table.item(index.row(), 0).text()
                data = HexrdConfig().raw_mask_coords[selection]
                d = {'_visible': []}
                if selection in HexrdConfig().visible_masks:
                    d['_visible'] = [selection]
                for i, (det, mask) in enumerate(data):
                    parent = d.setdefault(det, {})
                    parent.setdefault(selection, {})[str(i)] = mask
                self.export_masks_to_file(d)

    def save_state(self, h5py_group):
        if 'masks' not in h5py_group:
            h5py_group.create_group('masks')

        self.write_all_masks(h5py_group['masks'])

    def load_state(self, h5py_group):
        self.clear_masks()
        self.reset_threshold()
        if 'masks' in h5py_group:
            self.load_masks(h5py_group['masks'])

    def write_all_masks(self, h5py_group=None):
        d = {'_visible': HexrdConfig().visible_masks}
        for name, data in HexrdConfig().raw_mask_coords.items():
            for i, (det, mask) in enumerate(data):
                parent = d.setdefault(det, {})
                parent.setdefault(name, {})[str(i)] = mask
        if self.threshold:
            d['threshold'] = copy.deepcopy(HexrdConfig()._threshold_data)
        if h5py_group:
            self.write_masks_to_group(d, h5py_group)
        else:
            self.export_masks_to_file(d)

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
            self.write_masks_to_group(data, h5py_group)

    def write_masks_to_group(self, data, h5py_group):
        unwrap_dict_to_h5(h5py_group, data, asattr=False)

    def clear_masks(self):
        HexrdConfig().masks.clear()
        HexrdConfig().visible_masks.clear()
        HexrdConfig().raw_mask_coords.clear()
        self.masks.clear()
        self.setup_table()

    def import_masks(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if not selected_file:
            return

        HexrdConfig().working_dir = os.path.dirname(selected_file)
        # Unwrap the h5 file to a dict
        masks_dict = {}
        with h5py.File(selected_file, 'r') as f:
            unwrap_h5_to_dict(f, masks_dict)
        self.load_masks(masks_dict['masks'])

    def load_masks(self, h5py_group):
        raw_line_data = HexrdConfig().raw_mask_coords
        for key, data in h5py_group.items():
            if key == '_visible':
                # Convert strings into actual python strings
                HexrdConfig().visible_masks = list(h5py_read_string(data))
            elif key == 'threshold':
                HexrdConfig().threshold_values = data['values'][()].tolist()
                threshold_masks = {}
                for det, mask in data['masks'].items():
                    threshold_masks[det] = mask[()]
                HexrdConfig().threshold_masks = threshold_masks
            else:
                if key not in HexrdConfig().detector_names:
                    msg = (
                        f'Detectors must match.\n'
                        f'Current detectors: {HexrdConfig().detector_names}.\n'
                        f'Detectors found in masks: {list(h5py_group.keys())}')
                    QMessageBox.warning(self.ui, 'HEXRD', msg)
                    return
                for name, masks in data.items():
                    for mask in masks.values():
                        # Load the numpy array from the hdf5 file
                        mask = mask[()]
                        raw_line_data.setdefault(name, []).append((key, mask))

        if not HexrdConfig().loading_state:
            # We're importing masks directly,
            # don't wait for the state loaded signal
            self.rebuild_masks()

    def rebuild_masks(self):
        if self.image_mode == ViewType.raw:
            rebuild_raw_masks()
        elif self.image_mode in (ViewType.polar, ViewType.stereo):
            rebuild_polar_masks()

        self.masks_changed()

        self.update_masks_list('raw')
        self.update_masks_list('threshold')

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

        # Set the visible masks as the panel buffer(s)
        # We must ensure that we are using raw masks
        for det, mask in HexrdConfig().raw_masks_dict.items():
            detector_config = HexrdConfig().detector(det)
            buffer_default = {'status': 0}
            buffer = detector_config.setdefault('buffer', buffer_default)
            buffer_value = detector_config['buffer'].get('value', None)
            if isinstance(buffer_value, np.ndarray) and buff_val.ndim == 2:
                if selection == 'Logical AND with buffer':
                    mask = np.logical_and(mask, buffer_value)
                elif selection == 'Logical OR with buffer':
                    mask = np.logical_or(mask, buffer_value)
            buffer['value'] = mask
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

    def update_visibility_checkboxes(self):
        with block_signals(self.ui.masks_table):
            for i, key in enumerate(self.masks.keys()):
                cb = self.ui.masks_table.cellWidget(i, 1)
                status = key in HexrdConfig().visible_masks
                cb.setChecked(status)
        self.masks_changed()

    def hide_all_masks(self):
        HexrdConfig().visible_masks.clear()
        self.update_visibility_checkboxes()

    def show_all_masks(self):
        HexrdConfig().visible_masks = list(self.masks.keys())
        self.update_visibility_checkboxes()
