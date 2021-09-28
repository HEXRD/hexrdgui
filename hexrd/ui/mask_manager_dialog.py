from hexrd.ui.create_polar_mask import rebuild_polar_masks
from hexrd.ui.create_raw_mask import rebuild_raw_masks
import os
import numpy as np
import h5py

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import (
    QCheckBox, QFileDialog, QMenu, QMessageBox, QPushButton, QTableWidgetItem)
from PySide2.QtGui import QCursor

from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict
from hexrd.utils.compatibility import h5py_read_string

from hexrd.ui.utils import block_signals, unique_name
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.constants import ViewType


class MaskManagerDialog(QObject):

    # Emitted when masks are removed or visibility is toggled
    update_masks = Signal()

    def __init__(self, parent=None):
        super(MaskManagerDialog, self).__init__(parent)
        self.parent = parent

        loader = UiLoader()
        self.ui = loader.load_file('mask_manager_dialog.ui', parent)
        self.create_masks_list()
        self.threshold = False
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
            self.threshold = True
            self.masks['threshold'] = (
                'threshold', HexrdConfig().threshold_mask)
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
        elif not self.threshold:
            name = unique_name(self.masks, 'threshold')
            self.masks[name] = ('threshold', HexrdConfig().threshold_mask)
            HexrdConfig().visible_masks.append(name)
            self.threshold = True
        self.setup_table()

    def setup_connections(self):
        self.ui.masks_table.cellDoubleClicked.connect(self.get_old_name)
        self.ui.masks_table.cellChanged.connect(self.update_mask_name)
        self.ui.masks_table.customContextMenuRequested.connect(
            self.context_menu_event)
        self.ui.export_masks.clicked.connect(self.write_all_masks)
        self.ui.import_masks.clicked.connect(self.import_masks)
        HexrdConfig().mode_threshold_mask_changed.connect(
            self.update_masks_list)
        HexrdConfig().detectors_changed.connect(self.clear_masks)

        HexrdConfig().save_state.connect(self.save_state)
        HexrdConfig().load_state.connect(self.load_state)

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

                # Connect manager to raw image mode tab settings
                # for threshold mask
                mtype, _ = self.masks[key]
                if mtype == 'threshold':
                    self.setup_threshold_connections(cb, i, key)

    def setup_threshold_connections(self, checkbox, row, name):
        HexrdConfig().mode_threshold_mask_changed.connect(checkbox.setChecked)
        checkbox.toggled.connect(self.threshold_toggled)
        self.ui.masks_table.cellWidget(row, 2).clicked.connect(
            lambda row=row, name=name: self.remove_mask(row, name))


    def image_mode_changed(self, mode):
        self.image_mode = mode

    def threshold_toggled(self, v):
        HexrdConfig().set_threshold_mask_status(v, set_by_mgr=True)

    def toggle_visibility(self, checked, name):
        if checked and name not in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.append(name)
        elif not checked and name in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.remove(name)

        if self.image_mode == ViewType.polar:
            HexrdConfig().polar_masks_changed.emit()
        elif self.image_mode == ViewType.raw:
            HexrdConfig().raw_masks_changed.emit()

    def reset_threshold(self):
        self.threshold = False
        HexrdConfig().set_threshold_comparison(0)
        HexrdConfig().set_threshold_value(0.0)
        HexrdConfig().set_threshold_mask(None)
        HexrdConfig().set_threshold_mask_status(False)

    def remove_mask(self, row, name):
        mtype, _ = self.masks[name]

        del self.masks[name]
        if name in HexrdConfig().visible_masks:
            HexrdConfig().visible_masks.remove(name)
        HexrdConfig().raw_mask_coords.pop(name, None)
        HexrdConfig().masks.pop(name, None)
        if mtype == 'threshold':
            self.reset_threshold()

        self.ui.masks_table.removeRow(row)
        self.setup_table()

        if self.image_mode == ViewType.polar:
            HexrdConfig().polar_masks_changed.emit()
        elif self.image_mode == ViewType.raw:
            HexrdConfig().raw_masks_changed.emit()

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

        self.old_name = None
        self.setup_table()

    def context_menu_event(self, event):
        index = self.ui.masks_table.indexAt(event)
        if index.row() >= 0:
            menu = QMenu(self.ui.masks_table)
            export = menu.addAction('Export Mask')
            action = menu.exec_(QCursor.pos())
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
        if 'masks' in h5py_group:
            self.load_masks(h5py_group['masks'])

    def write_all_masks(self, h5py_group=None):
        d = {'_visible': HexrdConfig().visible_masks}
        for name, data in HexrdConfig().raw_mask_coords.items():
            for i, (det, mask) in enumerate(data):
                parent = d.setdefault(det, {})
                parent.setdefault(name, {})[str(i)] = mask
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

        if self.image_mode == ViewType.raw:
            rebuild_raw_masks()
            HexrdConfig().raw_masks_changed.emit()
        elif self.image_mode == ViewType.polar:
            rebuild_polar_masks()
            HexrdConfig().polar_masks_changed.emit()

        self.update_masks_list('raw')
