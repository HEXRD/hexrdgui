from collections import Counter  # To compare two lists' contents
import re
import os
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QTableWidgetItem, QComboBox
from hexrdgui.constants import TRANSFORM_OPTIONS

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader


class LoadImagesDialog:

    def __init__(self, image_files, manual_assign=False, parent=None):
        self.setup_vars(image_files)

        loader = UiLoader()
        self.ui = loader.load_file('load_images_dialog.ui', parent)
        self.manual_assign = manual_assign
        self.using_roi = HexrdConfig().instrument_has_roi
        self.orignal_file_names = [f for i in image_files for f in i]

        self.setup_connections()
        self.setup_state()
        self.setup_table()
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
        dets = HexrdConfig().detector_names
        multiple = max(len(self.image_files) // len(dets), 1)
        self.detectors = [det for det in dets for i in range(multiple)]

    def setup_connections(self):
        self.ui.regex_combo.currentIndexChanged.connect(self.update_table)
        self.ui.regex_line_edit.textChanged.connect(self.update_combo_state)
        self.ui.regex_line_edit.textChanged.connect(self.update_table)

    def exec(self):
        # Loop until canceled or validation succeeds
        while True:
            if self.ui.exec():
                # Perform some validation before returning
                results = self.results()
                matches = [Path(v).name for f in results.values() for v in f]
                image_files = [Path(f).name for f in self.image_files]
                if Counter(results.keys()) != Counter(self.detectors):
                    msg = 'Detectors do not match the current detectors'
                    QMessageBox.warning(self.ui, 'HEXRD', msg)
                    continue
                elif not self.using_roi and (Counter(matches) != Counter(image_files)):
                    msg = 'Image files do not match the selected files'
                    QMessageBox.warning(self.ui, 'HEXRD', msg)
                    continue
                return True
            else:
                return False

    def setup_state(self):
        if 'trans' not in HexrdConfig().load_panel_state:
            num_dets = len(HexrdConfig().detector_names)
            HexrdConfig().load_panel_state = {'trans': [0 for x in range(num_dets)]}

    def setup_roi_table(self, table):
        # This use case is less common. For ROI configs images are re-used for
        # multiple detectors. Image names are toggled to match the detector for
        # that row.
        table.setRowCount(len(self.detectors))
        for i in range(table.rowCount()):
            d = QTableWidgetItem(self.detectors[i])
            table.setItem(i, 0, d)

            trans_cb = QComboBox()
            trans_cb.addItems(TRANSFORM_OPTIONS)
            idx = 0
            if 'trans' in HexrdConfig().load_panel_state:
                idx = HexrdConfig().load_panel_state['trans'][i]
            trans_cb.setCurrentIndex(idx)
            table.setCellWidget(i, 1, trans_cb)
            table.cellWidget(i, 1).currentTextChanged.connect(
                lambda v, i=i: self.selection_changed(v, i)
            )

            img_cb = QComboBox()
            img_cb.addItems(list(set(self.image_files)))
            table.setCellWidget(i, 2, img_cb)
            table.cellWidget(i, 2).currentTextChanged.connect(
                lambda v, i=i: self.selection_changed(v, i)
            )

    def setup_standard_table(self, table):
        # The typical use case. This supports one or more images per detector.
        # The detector names are toggled to match the image for that row.
        table.setRowCount(len(self.image_files))
        imgs_per_det = len(self.image_files) / len(HexrdConfig().detector_names)
        for i in range(table.rowCount()):
            if self.manual_assign:
                det_cb = QComboBox()
                det_cb.addItems(sorted(list(set(self.detectors))))
                table.setCellWidget(i, 0, det_cb)
                table.cellWidget(i, 0).currentTextChanged.connect(
                    lambda v, i=i: self.selection_changed(v, i)
                )
            else:
                d = QTableWidgetItem(self.detectors[i])
                table.setItem(i, 0, d)

            trans_cb = QComboBox()
            trans_cb.addItems(TRANSFORM_OPTIONS)
            idx = 0
            if 'trans' in HexrdConfig().load_panel_state:
                det = int(i / imgs_per_det)
                idx = HexrdConfig().load_panel_state['trans'][det]
            trans_cb.setCurrentIndex(idx)
            table.setCellWidget(i, 1, trans_cb)
            table.cellWidget(i, 1).currentTextChanged.connect(
                lambda v, i=i: self.selection_changed(v, i)
            )

            f = QTableWidgetItem(Path(self.image_files[i]).name)
            table.setItem(i, 2, f)

    def setup_table(self):
        table = self.ui.match_detectors_table
        table.clearContents()
        if self.using_roi:
            self.setup_roi_table(table)
        else:
            self.setup_standard_table(table)
        table.resizeColumnsToContents()

    def update_combo_state(self):
        enable = len(self.ui.regex_line_edit.text()) == 0
        self.ui.regex_combo.setEnabled(enable)

    def update_table(self):
        table = self.ui.match_detectors_table
        results = self.results()
        detectors = results.keys()
        image_files = [v for f in results.values() for v in f]
        cur_regex = self.current_regex()

        try:
            image_files.sort(key=lambda s: _re_res(cur_regex, s))
        except Exception:
            # The user is probably in the middle of typing...
            pass

        for i in range(len(detectors)):
            if self.manual_assign and len(image_files) < len(detectors):
                img_cb = QComboBox()
                img_cb.addItems(list(set(image_files)))
                table.setCellWidget(i, 2, img_cb)
                table.cellWidget(i, 2).currentTextChanged.connect(
                    lambda v, i=i: self.selection_changed(v, i)
                )
            else:
                f = QTableWidgetItem(Path(image_files[i]).name)
                table.setItem(i, 2, f)

    def results(self):
        table = self.ui.match_detectors_table
        results = {}
        for i in range(table.rowCount()):
            if isinstance(table.item(i, 0), QTableWidgetItem):
                detector = table.item(i, 0).text()
            else:
                detector = table.cellWidget(i, 0).currentText()
            results.setdefault(detector, [])

            if isinstance(table.item(i, 2), QTableWidgetItem):
                fp = table.item(i, 2).text()
            else:
                fp = table.cellWidget(i, 2).currentText()
            fp = [f for f in self.orignal_file_names if fp in f][0]
            results[detector].append(fp)

            idx = table.cellWidget(i, 1).currentIndex()
            det_idx = i
            if not self.using_roi:
                imgs_per_det = len(self.image_files) / len(self.detectors)
                det_idx = int(i / imgs_per_det)
            HexrdConfig().load_panel_state['trans'][det_idx] = idx

        return results

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
