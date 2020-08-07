import copy
import numpy as np

from PySide2.QtCore import QObject, Signal, Qt
from PySide2.QtWidgets import (
    QCheckBox, QHBoxLayout, QPushButton, QTableWidgetItem, QWidget)
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class MaskManagerDialog(QObject):

    # Emitted when masks are removed or visibility is toggled
    update_masks = Signal()

    def __init__(self, parent=None):
        super(MaskManagerDialog, self).__init__(parent)
        self.parent = parent

        loader = UiLoader()
        self.ui = loader.load_file('mask_manager_dialog.ui', parent)
        self.create_masks_list()
        self.threshold_name = ''

        self.setup_connections()

    def show(self):
        self.setup_table()
        self.ui.show()

    def create_masks_list(self):
        self.masks = {}
        for v, i in enumerate(HexrdConfig().polar_masks_line_data):
            if not any(np.array_equal(m, v) for m in self.masks.values()):
                self.masks['mask_' + str(i)] = copy.copy(v)
        if HexrdConfig().threshold_mask_status:
            self.threshold_name = 'threshold'
            self.masks['threshold'] = HexrdConfig().threshold_mask
        self.visible = copy.copy(self.masks)

    def update_masks_list(self):
        # Check if new mask is threshold
        if not self.threshold_name and HexrdConfig().threshold_mask_status:
            self.masks['threshold'] = HexrdConfig().threshold_mask
            self.visible['threshold'] = HexrdConfig().threshold_mask
            self.threshold_name = 'threshold'
        else:
            data = HexrdConfig().polar_masks_line_data
            if not data:
                return
            if any(np.array_equal(data[-1], m) for m in self.masks.values()):
                return

            self.masks['mask_' + str(len(data) - 1)] = data[-1]
            self.visible['mask_' + str(len(data) - 1)] = data[-1]
        self.setup_table()

    def setup_connections(self):
        self.ui.masks_table.cellDoubleClicked.connect(self.get_old_name)
        self.ui.masks_table.cellChanged.connect(self.update_mask_name)
        HexrdConfig().threshold_mask_changed.connect(self.update_masks_list)

    def setup_table(self, status=True):
        self.ui.masks_table.setRowCount(0)
        for i, key in enumerate(self.masks.keys()):
            # Add label
            self.ui.masks_table.insertRow(i)
            self.ui.masks_table.setItem(i, 0, QTableWidgetItem(key))

            # Add checkbox to toggle visibility
            cb = QCheckBox()
            status = key in self.visible.keys()
            cb.setChecked(status)
            cb.setStyleSheet('margin-left:50%; margin-right:50%;')
            cb.toggled.connect(self.toggle_visibility)
            self.ui.masks_table.setCellWidget(i, 1, cb)

            # Add push button to remove mask
            pb = QPushButton('Remove Mask')
            pb.clicked.connect(self.remove_mask)
            self.ui.masks_table.setCellWidget(i, 2, pb)

            # Connect manager to raw image mode tab settings
            # for threshold mask
            if key == self.threshold_name:
                self.setup_threshold_connections(cb, pb)

    def setup_threshold_connections(self, checkbox, pushbutton):
        HexrdConfig().threshold_mask_changed.connect(checkbox.setChecked)
        checkbox.toggled.connect(HexrdConfig().set_threshold_mask_status)

    def toggle_visibility(self, checked):
        name = self.threshold_name
        if self.ui.masks_table.currentRow() > 0:
            row = self.ui.masks_table.currentRow()
            name = self.ui.masks_table.item(row, 0).text()
        if checked and name and name not in self.visible.keys():
            # TODO: does this need to be a copy of masks[name]?
            self.visible[name] = self.masks[name]
        elif not checked and name in self.visible.keys():
            del self.visible[name]
        HexrdConfig().polar_masks_line_data = (
            [v for k, v in self.visible.items() if k != self.threshold_name])
        self.update_masks.emit()

    def reset_threshold(self):
        self.threshold_name = ''
        HexrdConfig().set_threshold_comparison(0)
        HexrdConfig().set_threshold_value(0.0)
        HexrdConfig().set_threshold_mask(None)
        HexrdConfig().set_threshold_mask_status(False)

    def remove_mask(self):
        item = self.ui.masks_table.item(self.ui.masks_table.currentRow(), 0)
        del self.masks[item.text()]
        if item.text() in self.visible.keys():
            del self.visible[item.text()]

        if item.text() == self.threshold_name:
            self.reset_threshold()
        HexrdConfig().polar_masks_line_data = (
            [i for j, i in enumerate(self.masks.values()) if j not in self.hidden])
        self.update_masks.emit()
        self.ui.masks_table.removeRow(self.ui.masks_table.currentRow())

    def get_old_name(self, row, column):
        if column != 0:
            return

        self.old_name = self.ui.masks_table.item(row, 0).text()

    def update_mask_name(self, row, column):
        if not hasattr(self, 'old_name') or self.old_name is None:
            return

        new_name = self.ui.masks_table.item(row, 0).text()
        if self.old_name != new_name:
            if new_name in self.masks.keys():
                self.ui.masks_table.item(row, 0).setText(self.old_name)
                return

            self.masks[new_name] = self.masks.pop(self.old_name)
            if self.old_name in self.visible.keys():
                self.visible[new_name] = self.visible.pop(self.old_name)
        if self.old_name == self.threshold_name:
            self.threshold_name = new_name
        self.old_name = None
