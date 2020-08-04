import copy
import numpy as np

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QCheckBox, QPushButton, QTableWidgetItem

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
            if not data or data[-1] in self.masks.values():
                return
            self.masks['mask_' + str(len(data) - 1)] = data[-1]
            self.visible['mask_' + str(len(data) - 1)] = data[-1]
        self.setup_table()

    def setup_table(self, status=True):
        self.ui.masks_table.setRowCount(0)
        for i, key in enumerate(self.masks.keys()):
            # Add label
            self.ui.masks_table.insertRow(i)
            mask_name = QTableWidgetItem('mask_' + str(i))
            self.ui.masks_table.setItem(i, 0, mask_name)
            cb = QCheckBox()
            cb.setChecked(True)
            self.ui.masks_table.setCellWidget(i, 1, cb)
            cb.toggled.connect(self.toggle_visibility)
            pb = QPushButton('Remove Mask')
            pb.clicked.connect(self.remove_mask)
            self.ui.masks_table.setCellWidget(i, 2, pb)

    def toggle_visibility(self, checked):
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

    def remove_mask(self):
        return
