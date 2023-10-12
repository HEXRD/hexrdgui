#!/usr/bin/env python

import io

import h5py
import numpy as np

from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

from hexrd.instrument import unwrap_h5_to_dict
import hexrd.resources
from hexrd.utils.decorators import memoize

from hexrd.ui.resource_loader import load_resource
from hexrd.ui.tree_views.dict_tree_view import DictTreeViewDialog
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils.dialog import add_help_url


class XRayEnergySelectionDialog(DictTreeViewDialog):

    def __init__(self, parent=None):
        # Load the data
        self.load_xray_dict()
        super().__init__(self.xray_dict, parent)

        self.selected_energy = None
        self.editable = False
        self.set_extended_selection_mode()

        # Set the headers
        root_item = self.tree_view.model().root_item
        root_item.set_data(0, 'Key')
        root_item.set_data(1, 'Energy (eV)')

        # Resize the key column
        self.tree_view.setColumnWidth(0, 250)

        # Set the tooltip
        tooltip = 'Select an energy, or multiple energies to average'
        self.tree_view.setToolTip(tooltip)

        self.setWindowTitle('X-Ray Energy Selection')

        # Add the dialog buttons
        buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        button_box = QDialogButtonBox(buttons, self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        add_help_url(button_box, 'configuration/instrument/#x-ray-energy-selection')
        self.layout().addWidget(button_box)

        UiLoader().install_dialog_enter_key_filters(self)

    def load_xray_dict(self):
        self.xray_dict = _load_xray_dict()

    def accept(self):
        items = self.selected_items
        names = [self.generate_item_name(x) for x in items]
        values = [x.data(1) for x in items]

        if len(values) == 0:
            msg = 'No values selected'
            QMessageBox.critical(self, 'HEXRD', msg)
            return

        if np.isnan(values).any():
            msg = 'Selected energy is NaN'
            QMessageBox.critical(self, 'HEXRD', msg)
            return

        if len(values) == 1:
            self.selected_energy = values[0]
            super().accept()
            return

        mean = np.mean(values)

        msg = 'Selected entries:\n\n'
        for n, v in zip(names, values):
            msg += f'{n: <30}: {v:>10.2f}\n'

        msg += f'\nProduces mean energy: {mean:.2f} eV\n\n'
        msg += 'Accept?'

        response = QMessageBox.question(self, 'HEXRD', msg)
        if response == QMessageBox.No:
            return

        self.selected_energy = mean
        super().accept()

    @staticmethod
    def generate_item_name(item, delimiter='.'):
        name = item.data(0)
        while item.parent_item:
            item = item.parent_item
            if item.data(0) == 'key':
                # Assume this is the root item, and break
                break

            name = f'{item.data(0)}{delimiter}{name}'

        return name


@memoize(maxsize=1)
def _load_xray_dict():
    # Load the data from the file
    filename = 'characteristic_xray_energies.h5'
    h5_data = load_resource(hexrd.resources, filename, binary=True)
    io_data = io.BytesIO(h5_data)

    # Unwrap the h5 file to a dict
    xray_dict = {}
    with h5py.File(io_data, 'r') as f:
        unwrap_h5_to_dict(f, xray_dict)

    # Sort the keys in the dict
    def sort(x):
        return int(x) if x.isdigit() else 0

    sorted_keys = sorted(xray_dict.keys(), key=sort)
    return {k: xray_dict[k] for k in sorted_keys}


if __name__ == '__main__':
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    dialog = XRayEnergySelectionDialog()

    def finished():
        print(f'Selected value was: {dialog.selected_energy}')
        app.exit()

    dialog.accepted.connect(finished)
    dialog.show()
    app.exec_()
