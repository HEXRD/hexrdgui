import os

import numpy as np

from PySide2.QtCore import QObject, QSignalBlocker, Signal
from PySide2.QtWidgets import QFileDialog, QMessageBox

from hexrd.ui import enter_key_filter
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.indexing.utils import generate_grains_table


class FitGrainsSelectDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, indexing_runner=None, parent=None):
        super().__init__(parent)

        self.indexing_runner = indexing_runner
        self.grains_table = None

        loader = UiLoader()
        self.ui = loader.load_file('fit_grains_select_dialog.ui', parent)
        self.ui.setWindowTitle('Select Grains to Fit')
        self.ui.installEventFilter(enter_key_filter)

        # Hide the tab bar. It gets selected by changes to the combo box.
        self.ui.tab_widget.tabBar().hide()

        self.update_valid_methods()

        self.setup_connections()

    def setup_connections(self):
        self.ui.select_estimate_file_button.pressed.connect(
            self.select_estimate_file)
        self.ui.select_orientations_file_button.pressed.connect(
            self.select_orientations_file)
        self.ui.method.currentIndexChanged.connect(self.update_method_tab)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def show(self):
        self.ui.show()

    def on_accepted(self):
        # Validate
        if self.method in self.file_methods and not self.file_name:
            msg = 'Please select a file'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            self.show()
            return

        self.set_grains_table()
        self.accepted.emit()

    def set_grains_table(self):
        if self.method == 'indexing':
            # Get the grains table off the indexing runner
            self.grains_table = self.indexing_runner.grains_table
        elif self.method == 'estimate':
            # It is a grains.out file
            self.grains_table = np.loadtxt(self.file_name)
        elif self.method == 'orientations':
            # It is an accepted_orientations*.dat file
            qbar = np.loadtxt(self.file_name, ndmin=2).T
            self.grains_table = generate_grains_table(qbar)
        else:
            raise Exception(f'Unknown method: {self.method}')

    def on_rejected(self):
        self.rejected.emit()

    def select_estimate_file(self):
        self.select_file('Load grains.out file', 'grains.out files (*.out)')

    def select_orientations_file(self):
        self.select_file('Load orientations file',
                         'Accepted orientations files (*.dat)')

    def select_file(self, title, filters):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, title, HexrdConfig().working_dir, filters)

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            self.file_name = selected_file

    @property
    def file_methods(self):
        # Methods that use a file name...
        return ('estimate', 'orientations')

    @property
    def all_methods(self):
        return ('indexing',) + self.file_methods

    @property
    def file_name(self):
        self.assert_file_method()
        widget = getattr(self.ui, f'{self.method}_file_name')
        return widget.text()

    @file_name.setter
    def file_name(self, v):
        self.assert_file_method()
        widget = getattr(self.ui, f'{self.method}_file_name')
        widget.setText(v)

    def assert_file_method(self):
        if self.method not in self.file_methods:
            raise Exception(f'{self.method} is not a file method')

    @property
    def method(self):
        return self.ui.method.currentText().lower()

    @method.setter
    def method(self, v):
        v = v.capitalize()
        ind = self.ui.method.findText(v)
        if ind == -1:
            raise Exception(f'Invalid method name: {v}')

        self.ui.method.setCurrentIndex(ind)

    def update_method_tab(self):
        # Take advantage of the naming scheme...
        method_tab = getattr(self.ui, f'{self.method}_tab')
        self.ui.tab_widget.setCurrentWidget(method_tab)

    def update_valid_methods(self):
        valid_methods = list(self.all_methods)

        if getattr(self.indexing_runner, 'grains_table', None) is None:
            valid_methods.remove('indexing')

        widget = self.ui.method
        blocker = QSignalBlocker(widget)  # noqa: F841
        widget.clear()
        widget.addItems([x.capitalize() for x in valid_methods])

        # In case the current widget changed...
        self.update_method_tab()
