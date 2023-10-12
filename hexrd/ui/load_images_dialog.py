from collections import Counter  # To compare two lists' contents
import re
import os

from PySide6.QtWidgets import QMessageBox, QTableWidgetItem, QComboBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class LoadImagesDialog:

    def __init__(self, image_files, manual_assign=False, parent=None):
        self.setup_vars(image_files)

        loader = UiLoader()
        self.ui = loader.load_file('load_images_dialog.ui', parent)

        self.setup_connections()
        self.setup_state()
        self.setup_table(manual_assign)
        self.update_table()

    def setup_vars(self, image_files):
        # Flatten out the array of selected images
        self.image_files = []
        for imgs in image_files:
            for img in imgs:
                self.image_files.append(os.path.basename(img))
        # Create a list of detectors to match the number of files
        # This is neccessary to check validity of file/detector association
        # when the association is set manually
        multiple = int(len(self.image_files)/len(HexrdConfig().detector_names))
        dets = HexrdConfig().detector_names
        self.detectors = [det for det in dets for i in range(multiple)]

    def setup_connections(self):
        self.ui.regex_combo.currentIndexChanged.connect(self.update_table)
        self.ui.regex_line_edit.textChanged.connect(self.update_combo_state)
        self.ui.regex_line_edit.textChanged.connect(self.update_table)

    def exec_(self):
        # Loop until canceled or validation succeeds
        while True:
            if self.ui.exec_():
                # Perform some validation before returning
                detectors, image_files = self.results()
                if Counter(detectors) != Counter(self.detectors):
                    msg = 'Detectors do not match the current detectors'
                    QMessageBox.warning(self.ui, 'HEXRD', msg)
                    continue
                elif Counter(image_files) != Counter(self.image_files):
                    msg = 'Image files do not match the selected files'
                    QMessageBox.warning(self.ui, 'HEXRD', msg)
                    continue
                return True
            else:
                return False

    def setup_state(self):
        if 'trans' not in HexrdConfig().load_panel_state:
            num_dets = len(HexrdConfig().detector_names)
            HexrdConfig().load_panel_state = {
                'trans': [0 for x in range(num_dets)]}

    def setup_table(self, manual_assign):
        table = self.ui.match_detectors_table
        table.clearContents()
        table.setRowCount(len(self.image_files))
        imgs_per_det = len(self.image_files)/len(HexrdConfig().detector_names)
        for i in range(len(self.image_files)):
            if manual_assign:
                det_cb = QComboBox()
                det_cb.addItems(list(set(self.detectors)))
                table.setCellWidget(i, 0, det_cb)
                table.cellWidget(i, 0).currentTextChanged.connect(
                    lambda v, i=i: self.selection_changed(v, i))
            else:
                d = QTableWidgetItem(self.detectors[i])
                table.setItem(i, 0, d)

            trans_cb = QComboBox()
            options = ["None",
                       "Mirror about Vertical",
                       "Mirror about Horizontal",
                       "Transpose",
                       "Rotate 90°",
                       "Rotate 180°",
                       "Rotate 270°"]
            trans_cb.addItems(options)
            idx = 0
            if 'trans' in HexrdConfig().load_panel_state:
                det = int(i/imgs_per_det)
                idx = HexrdConfig().load_panel_state['trans'][det]
            trans_cb.setCurrentIndex(idx)
            table.setCellWidget(i, 1, trans_cb)
            table.cellWidget(i, 1).currentTextChanged.connect(
                lambda v, i=i: self.selection_changed(v, i))

            f = QTableWidgetItem(self.image_files[i])
            table.setItem(i, 2, f)
        table.resizeColumnsToContents()

    def update_combo_state(self):
        enable = len(self.ui.regex_line_edit.text()) == 0
        self.ui.regex_combo.setEnabled(enable)

    def update_table(self):
        table = self.ui.match_detectors_table
        detectors, image_files = self.results()
        cur_regex = self.current_regex()

        try:
            image_files.sort(key=lambda s: _re_res(cur_regex, s))
        except Exception:
            # The user is probably in the middle of typing...
            pass

        for i in range(len(detectors)):
            f = QTableWidgetItem(image_files[i])
            table.setItem(i, 2, f)

    def results(self):
        table = self.ui.match_detectors_table
        detectors = []
        image_files = []
        for i in range(table.rowCount()):
            try:
                detectors.append(table.cellWidget(i, 0).currentText())
            except Exception:
                detectors.append(table.item(i, 0).text())
            image_files.append(table.item(i, 2).text())
            idx = table.cellWidget(i, 1).currentIndex()
            imgs_per_det = (
                len(self.image_files)/len(HexrdConfig().detector_names))
            HexrdConfig().load_panel_state['trans'][int(i/imgs_per_det)] = idx

        return detectors, image_files

    def current_regex(self):
        if self.ui.regex_line_edit.text():
            return self.ui.regex_line_edit.text()

        return self.ui.regex_combo.currentText()

    def selection_changed(self, val, row):
        table = self.ui.match_detectors_table
        if val in self.detectors:
            for i in range(table.rowCount()):
                if i != row and table.cellWidget(i, 0).currentText() == val:
                    trans = table.cellWidget(i, 1).currentText()
                    table.cellWidget(row, 1).setCurrentText(trans)
                    break
        else:
            try:
                det = table.cellWidget(row, 0).currentText()
            except Exception:
                det = table.item(row, 0).text()
            for i in range(table.rowCount()):
                if i != row and table.item(i, 0).text() == det:
                    table.cellWidget(i, 1).setCurrentText(val)


def _re_res(pat, s):
    r = re.search(pat, s)
    return r.group(0) if r else '&'
