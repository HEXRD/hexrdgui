from PySide2.QtCore import Qt, QPersistentModelIndex
from PySide2.QtWidgets import (
    QDialog, QTableWidgetItem, QFileDialog, QMessageBox
)

from hexrd import imageseries

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class WedgeEditor(QDialog):

    def __init__(self, parent=None):
        super(WedgeEditor, self).__init__(parent)

        self.tabs = []
        self.index = 0
        self.row = 0
        self.steps = []
        self.changed = []
        self.name = None
        self.table = None
        self.omw = None

        self.ui = UiLoader().load_file(
            'wedges_dialog.ui', self.parent())
        self.button_box = self.ui.button_box
        self.save = self.ui.save
        self.tab_widget = self.ui.tab_widget

        self.create_tabs()
        self.load_metadata()
        self.current_changed(0)

        self.setup_connections()

        self.ui.show()

    def create_tabs(self):
        self.tab_widget.clear()
        for key in HexrdConfig().imageseries_dict:
            tab_ui = UiLoader().load_file('wedge_form.ui', self.parent())
            self.tab_widget.addTab(tab_ui, key)
            self.setup_tab_connections(tab_ui)
            self.tabs.append(tab_ui)
            self.steps.append(len(HexrdConfig().imageseries(key)))
            self.changed.append(False)
            tab_ui.steps.setText(str(len(HexrdConfig().imageseries(key))))

    def load_metadata(self):
        idx = 0
        for detector in HexrdConfig().imageseries_dict.keys():
            self.current_changed(idx)
            data = HexrdConfig().imageseries(detector).metadata
            if 'omega' not in data:
                return

            for i in range(len(data['omega'])):
                self.create_row(False, data['omega'][i])
            idx += 1

    def setup_connections(self):
        self.save.clicked.connect(self.save_omega)
        self.save.clicked.connect(self.ui.accept)
        self.button_box.accepted.connect(self.add_omega_data)
        self.tab_widget.currentChanged.connect(self.current_changed)

    def setup_tab_connections(self, ui):
        ui.add_new_wedge.clicked.connect(self.create_row)
        ui.remove_wedge.clicked.connect(self.delete_wedge)

    def create_row(self, new_wedge=True, values=None):
        if new_wedge:
            if not self.steps:
                return

            if not self.tabs[self.index].start_angle.text():
                return

            if not self.tabs[self.index].end_angle.text():
                return

        self.table.blockSignals(True)

        self.changed[self.index] = True

        self.table.setRowCount(self.row + 1)
        for i in range(self.table.columnCount()):
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignHCenter)
            self.table.setItem(self.row, i, item)

        if new_wedge:
            self.table.item(self.row, 0).setText(
                self.tabs[self.index].start_angle.text())
            self.table.item(self.row, 1).setText(
                self.tabs[self.index].end_angle.text())
            self.table.item(self.row, 2).setText(
                self.tabs[self.index].steps.text())
        else:
            self.table.item(self.row, 0).setText(
                str(values[0]))
            self.table.item(self.row, 1).setText(
                str(values[1]))
            self.table.item(self.row, 2).setText(
                str(1))

        self.row += 1
        self.reset_inputs()

        self.table.blockSignals(False)

    def reset_inputs(self):
        self.tabs[self.index].start_angle.clear()
        self.tabs[self.index].end_angle.clear()
        self.steps[self.index] -= int(self.tabs[self.index].steps.text())
        self.tabs[self.index].steps.setText(str(self.steps[self.index]))

        self.tabs[self.index].start_angle.setFocus()

    def current_changed(self, idx):
        self.name = self.tab_widget.tabText(idx)
        self.index = idx
        self.table = self.tabs[idx].angles_table
        self.row = self.table.rowCount()

    def delete_wedge(self):
        indices = []
        for index in self.table.selectedIndexes():
            if index.column() == 0:
                indices.append(QPersistentModelIndex(index))

        for idx in indices:
            row = idx.row()
            if row >= 0:
                self.steps[self.index] += int(self.table.item(row, 2).text())
                self.table.removeRow(row)
                self.tabs[self.index].steps.setText(
                    str(self.steps[self.index]))
                self.row -= 1

    def add_omega_data(self, name=None):
        try:
            for i in range(len(self.tabs)):
                if self.changed[self.index]:
                    self.current_changed(i)
                    tot_frames = len(HexrdConfig().imageseries(self.name))
                    omw = imageseries.omega.OmegaWedges(tot_frames)
                    for j in range(self.table.rowCount()):
                        omw.addwedge(
                            float(self.table.item(j, 0).text()),
                            float(self.table.item(j, 1).text()),
                            int(self.table.item(j, 2).text()))

                    if self.table.rowCount():
                        HexrdConfig().imageseries(
                            self.name).metadata['omega'] = omw.omegas
                    else:
                        HexrdConfig().imageseries(
                            self.name).metadata['omega'] = []

                    if self.name == name:
                        self.omw = omw

        except imageseries.omega.OmegaSeriesError as error:
            msg = ('ERROR: \n' + str(error) + '\nThe angles for ' +
                    self.name + ' will not be saved.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

    def save_omega(self, omw):
        self.add_omega_data(self.name)

        if self.omw is None:
            msg = ('ERROR: No angles to export.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self, 'Save Omega', HexrdConfig().working_dir,
            'NUMPY files (*.npy)')

        self.omw.save_omegas(selected_file)
