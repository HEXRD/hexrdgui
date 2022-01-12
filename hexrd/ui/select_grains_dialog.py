import os

import numpy as np

from PySide2.QtCore import Signal, QItemSelectionModel, QObject, Qt
from PySide2.QtWidgets import QDialogButtonBox, QFileDialog, QMessageBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.grains_table_model import GrainsTableModel
from hexrd.ui.ui_loader import UiLoader


class SelectGrainsDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, num_requested_grains=1, parent=None):
        super().__init__(parent)
        self.ignore_errors = False

        loader = UiLoader()
        self.ui = loader.load_file('select_grains_dialog.ui', parent)

        self.num_requested_grains = num_requested_grains

        if num_requested_grains >= 1:
            suffix = 's' if num_requested_grains > 1 else ''
            title = f'Please select {num_requested_grains} grain{suffix}'
            self.ui.setWindowTitle(title)

        # Hide the tab bar. It gets selected by changes to the combo box.
        self.ui.tab_widget.tabBar().hide()

        # pull_spots is not allowed with this grains table view
        self.ui.table_view.pull_spots_allowed = False

        self.setup_methods()
        self.update_gui()

        self.ignore_errors = True
        try:
            self.update_grains_table()
        finally:
            self.ignore_errors = False

        self.setup_connections()

    def setup_connections(self):
        self.ui.select_file_button.pressed.connect(self.select_file)
        self.ui.file_name.editingFinished.connect(self.file_name_changed)
        self.ui.method.currentIndexChanged.connect(self.method_index_changed)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)
        self.ui.table_view.selection_changed.connect(self.update_enable_states)

    def show(self):
        return self.ui.show()

    @property
    def find_orientations_grains_table(self):
        return HexrdConfig().find_orientations_grains_table

    @property
    def fit_grains_grains_table(self):
        return HexrdConfig().fit_grains_grains_table

    def setup_methods(self):
        fo_grains_table = self.find_orientations_grains_table
        fg_grains_table = self.fit_grains_grains_table
        methods_and_enable = {
            'fit_grains_output': fg_grains_table is not None,
            'find_orientations_output': fo_grains_table is not None,
            'file': True,
        }

        methods = list(methods_and_enable.keys())
        self.ui.method.addItems([name_to_label(x) for x in methods])

        # FIXME: it'd be nice to eventually put this QComboBox
        # item disabling in a utility function.
        model = self.ui.method.model()
        for i, method in enumerate(methods):
            enabled = methods_and_enable[method]
            if enabled:
                # Already enabled...
                continue

            item = model.item(i)
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)

        # Set the combo box to the first enabled entry
        for i, method in enumerate(methods):
            enabled = methods_and_enable[method]
            if enabled:
                self.ui.method.setCurrentIndex(i)
                break

    def exec_(self):
        return self.ui.exec_()

    def on_accepted(self):
        self.update_config()
        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

    def select_file(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'grains.out', HexrdConfig().working_dir,
            'Grains.out files (*.out)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            self.file_name = selected_file

    @property
    def file_name(self):
        return self.ui.file_name.text()

    @file_name.setter
    def file_name(self, v):
        self.ui.file_name.setText(v)
        self.file_name_changed()

    def file_name_changed(self):
        file_name = self.file_name
        if not file_name:
            self.grains_table = None
            return

        # Try to load the file
        try:
            self.grains_table = np.loadtxt(file_name, ndmin=2)
        except Exception as e:
            if not self.ignore_errors:
                msg = f'Failed to load "{file_name}". Error was:\n\n{e}'
                QMessageBox.critical(self.ui, 'HEXRD', msg)
            self.grains_table = None

    def load_fo_grains_table(self):
        self.grains_table = self.find_orientations_grains_table

    def load_fg_grains_table(self):
        self.grains_table = self.fit_grains_grains_table

    @property
    def grains_table(self):
        return self.ui.table_view.grains_table

    @grains_table.setter
    def grains_table(self, v):
        # We make a new GrainsTableModel each time for now to save
        # dev time, since the model wasn't designed to be mutable.
        # FIXME: in the future, make GrainsTableModel grains mutable,
        # and then just set the grains table on it, rather than
        # creating a new one every time.
        view = self.ui.table_view
        if v is None:
            view.data_model = None
            self.update_enable_states()
            return

        kwargs = {
            'grains_table': v,
            'excluded_columns': list(range(9, 15)),
            'parent': view,
        }
        view.data_model = GrainsTableModel(**kwargs)

        # If the number of rows is equal to the number of requested grains,
        # select all rows automatically for convenience.
        if len(v) == self.num_requested_grains:
            selection_model = view.selectionModel()
            command = QItemSelectionModel.Select | QItemSelectionModel.Rows
            for i in range(len(v)):
                model_index = selection_model.model().index(i, 0)
                selection_model.select(model_index, command)

    def update_grains_table(self):
        functions = {
            'find_orientations_output': self.load_fo_grains_table,
            'fit_grains_output': self.load_fg_grains_table,
            'file': self.file_name_changed,
        }
        if self.method_name not in functions:
            raise NotImplementedError(self.method_name)

        functions[self.method_name]()

    @property
    def selected_grain(self):
        if self.num_requested_grains != 1:
            msg = 'selected_grain() called, but one grain was not requested!'
            raise Exception(msg)

        if self.num_selected_grains == 1:
            return self.selected_grains[0]

    @property
    def selected_grains(self):
        grains = self.ui.table_view.selected_grains
        if grains is None:
            return []

        return grains

    @property
    def num_selected_grains(self):
        return len(self.selected_grains)

    def update_gui(self):
        indexing_config = HexrdConfig().indexing_config
        key = '_loaded_crystal_params_file'
        self.file_name = indexing_config.get(key, '')

        self.update_method_tab()
        self.update_enable_states()

    def update_config(self):
        indexing_config = HexrdConfig().indexing_config
        indexing_config['_loaded_crystal_params_file'] = self.file_name

    def update_enable_states(self):
        button_box = self.ui.button_box
        ok_button = button_box.button(QDialogButtonBox.Ok)
        if ok_button:
            enable = self.num_selected_grains == self.num_requested_grains
            ok_button.setEnabled(enable)

    @property
    def method_name(self):
        return label_to_name(self.ui.method.currentText())

    @method_name.setter
    def method_name(self, v):
        self.ui.method.setCurrentText(name_to_label(v))

    def method_index_changed(self):
        self.update_method_tab()
        self.update_grains_table()

    def update_method_tab(self):
        # Take advantage of the naming scheme...
        method_tab = getattr(self.ui, self.method_name + '_tab')
        self.ui.tab_widget.setCurrentWidget(method_tab)

        visible = self.method_name == 'file'
        self.ui.tab_widget.setVisible(visible)


def name_to_label(s):
    return ' '.join(x.capitalize() for x in s.split('_'))


def label_to_name(s):
    return '_'.join(x.lower() for x in s.split())
