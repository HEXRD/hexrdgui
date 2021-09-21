from hexrd.ui.create_polar_mask import rebuild_polar_masks
from hexrd.ui.create_raw_mask import convert_polar_to_raw, rebuild_raw_masks
import os
import numpy as np
import h5py

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import (
    QCheckBox, QFileDialog, QMenu, QMessageBox, QPushButton, QTableWidgetItem)
from PySide2.QtGui import QCursor

from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict

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
        polar_data = HexrdConfig().polar_masks_line_data
        raw_data = HexrdConfig().raw_masks_line_data

        for key, val in polar_data.items():
            if not any(np.array_equal(m, val) for m in self.masks.values()):
                self.masks[key] = ('polar', val)
        for key, val in raw_data.items():
            if not any(np.array_equal(m, val) for m in self.masks.values()):
                self.masks[key] = val
        if HexrdConfig().threshold_mask_status:
            self.threshold = True
            self.masks['threshold'] = (
                'threshold', HexrdConfig().threshold_mask)
        HexrdConfig().visible_masks = list(self.masks.keys())

    def update_masks_list(self, mask_type):
        if mask_type == 'polar':
            if not HexrdConfig().polar_masks_line_data:
                return
            for name, data in HexrdConfig().polar_masks_line_data.items():
                vals = self.masks.values()
                if any(np.array_equal(val, m) for val, (_, m) in zip(data, vals)):
                    continue
                self.masks[name] = (mask_type, data)
        elif mask_type == 'raw':
            if not HexrdConfig().raw_masks_line_data:
                return
            for name, value in HexrdConfig().raw_masks_line_data.items():
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
        self.ui.export_masks.clicked.connect(self.export_visible_masks)
        self.ui.import_masks.clicked.connect(self.import_masks)
        HexrdConfig().mode_threshold_mask_changed.connect(
            self.update_masks_list)
        HexrdConfig().detectors_changed.connect(self.clear_masks)

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
        HexrdConfig().polar_masks_line_data.pop(name, None)
        HexrdConfig().polar_masks.pop(name, None)
        HexrdConfig().raw_masks_line_data.pop(name, None)
        HexrdConfig().raw_masks.pop(name, None)
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
            if self.old_name in HexrdConfig().polar_masks_line_data.keys():
                value = HexrdConfig().polar_masks_line_data.pop(self.old_name)
                HexrdConfig().polar_masks[new_name] = value
            elif self.old_name in HexrdConfig().raw_masks_line_data.keys():
                value = HexrdConfig().raw_masks_line_data.pop(self.old_name)
                HexrdConfig().raw_masks[new_name] = value

            if self.old_name in HexrdConfig().polar_masks.keys():
                value = HexrdConfig().polar_masks.pop(self.old_name)
                HexrdConfig().polar_masks[new_name] = value
            if self.old_name in HexrdConfig().raw_masks.keys():
                value = HexrdConfig().raw_masks.pop(self.old_name)
                HexrdConfig().raw_masks[new_name] = value

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
                self.convert_polar_to_raw()
                selection = self.ui.masks_table.item(index.row(), 0).text()
                det, data = HexrdConfig().raw_masks_line_data[selection]
                self.export_masks({det: {selection: data}})

    def export_masks(self, data):
        selected_file, _ = QFileDialog.getSaveFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            # write to hdf5
            with h5py.File(selected_file, 'w') as f:
                masks_group = f.create_group('masks')
                unwrap_dict_to_h5(masks_group, data, asattr=False)

    def export_visible_masks(self):
        self.convert_polar_to_raw()
        d = {}
        for name in HexrdConfig().visible_masks:
            data = HexrdConfig().raw_masks_line_data[name]
            for det, mask in data:
                d.setdefault(det, {})[name] = mask
        self.export_masks(d)

    def clear_masks(self):
        HexrdConfig().polar_masks.clear()
        HexrdConfig().raw_masks.clear()
        HexrdConfig().visible_masks.clear()
        self.masks.clear()
        self.setup_table()

    def convert_polar_to_raw(self):
        for name, data in HexrdConfig().polar_masks_line_data.items():
            line_data = convert_polar_to_raw(data)
            HexrdConfig().raw_masks_line_data[name] = line_data

    def import_masks(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            # Unwrap the h5 file to a dict
            masks_dict = {}
            with h5py.File(selected_file, 'r') as f:
                unwrap_h5_to_dict(f, masks_dict)

            raw_line_data = HexrdConfig().raw_masks_line_data
            mask_data = masks_dict['masks']
            for det, data in mask_data.items():
                if det not in HexrdConfig().detector_names:
                    msg = (
                        f'Detectors must match.\n'
                        f'Current detectors: {HexrdConfig().detector_names}.\n'
                        f'Detectors found in masks: {list(mask_data.keys())}')
                    QMessageBox.warning(self.ui, 'HEXRD', msg)
                    return
                for name, mask in data.items():
                    raw_line_data.setdefault(name, []).append((det, mask))

            if self.image_mode == ViewType.raw:
                rebuild_raw_masks()
            elif self.image_mode == ViewType.polar:
                rebuild_polar_masks()

            self.update_masks_list('raw')
