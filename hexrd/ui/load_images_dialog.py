from collections import Counter # To compare two lists' contents
import re

from PySide2.QtWidgets import QMessageBox, QTableWidgetItem

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader

class LoadImagesDialog:

    def __init__(self, image_files, parent=None):
        self.detectors = HexrdConfig().get_detector_names()
        self.image_files = image_files

        loader = UiLoader()
        self.ui = loader.load_file('load_images_dialog.ui', parent)

        self.setup_connections()

        self.setup_table()
        self.update_table()

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

    def setup_table(self):
        table = self.ui.match_detectors_table
        table.clearContents()
        table.setRowCount(len(self.detectors))
        for i in range(len(self.detectors)):
            d = QTableWidgetItem(self.detectors[i])
            table.setItem(i, 0, d)

            f = QTableWidgetItem(self.image_files[i])
            table.setItem(i, 1, f)

    def update_combo_state(self):
        enable = len(self.ui.regex_line_edit.text()) == 0
        self.ui.regex_combo.setEnabled(enable)

    def update_table(self):
        table = self.ui.match_detectors_table
        detectors, image_files = self.results()
        cur_regex = self.current_regex()

        try:
            detectors.sort(key=lambda s: _re_res(cur_regex, s))
            image_files.sort(key=lambda s: _re_res(cur_regex, s))
        except Exception as e:
            # The user is probably in the middle of typing...
            pass

        for i in range(len(detectors)):
            d = QTableWidgetItem(detectors[i])
            table.setItem(i, 0, d)

            f = QTableWidgetItem(image_files[i])
            table.setItem(i, 1, f)

    def results(self):
        table = self.ui.match_detectors_table
        detectors = []
        image_files = []
        for i in range(table.rowCount()):
            detectors.append(table.item(i, 0).text())
            image_files.append(table.item(i, 1).text())

        return detectors, image_files

    def current_regex(self):
        if self.ui.regex_line_edit.text():
            return self.ui.regex_line_edit.text()

        return self.ui.regex_combo.currentText()

def _re_res(pat, s):
    r = re.search(pat, s)
    return r.group(0) if r else '&'
