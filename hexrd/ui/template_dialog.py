import os
import numpy as np

from matplotlib import cm
import matplotlib.pyplot as plt
import matplotlib.colors

from PySide2.QtCore import QObject
from PySide2.QtWidgets import QFileDialog, QMessageBox

import hexrd.ui.constants
from hexrd.ui.ui_loader import UiLoader

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.interactive_template import InteractiveTemplate

LESS_THAN = 0
GREATER_THAN = 1
NOT_EQUAL_TO = 2
EQUAL_TO = 3

class TemplateDialog(QObject):

    def __init__(self, parent=None):
        super(TemplateDialog, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('template_dialog.ui', parent)
        self.it = []
        self.masks = []

        self.color_map_editor = ColorMapEditor(self.ui.image_tab_widget,
                                               self.ui)
        self.ui.select_image_group.layout().addWidget(self.color_map_editor.ui)

        self.setup_connections()
        self.list_detectors()

    def setup_connections(self):
        self.ui.load_image.clicked.connect(self.open_image_files)
        self.ui.dialog_buttons.rejected.connect(self.warn_before_close)
        self.ui.dialog_buttons.accepted.connect(self.save)
        self.ui.template_menu.currentIndexChanged.connect(self.load_template)
        self.ui.add_mask.clicked.connect(self.add_mask)
        self.ui.threshold_select.toggled.connect(self.set_threshold)
        self.ui.threshold_select.toggled.connect(self.ui.comparator.setEnabled)

        self.ui.image_tab_widget.template_update_needed.connect(self.update_image)
        ImageLoadManager().template_update_needed.connect(self.update_image)
        ImageLoadManager().new_images_loaded.connect(
            self.color_map_editor.update_bounds)
        ImageLoadManager().new_images_loaded.connect(
            self.color_map_editor.reset_range)

    def list_detectors(self):
        self.ui.detectors.clear()
        self.ui.detectors.addItems(HexrdConfig().get_detector_names())
        det = HexrdConfig().get_detector(self.ui.detectors.currentText())
        self.pixel_size = det['pixels']['size']['value']

    def exec_(self):
        return self.ui.exec_()

    def open_image_files(self):
        images_dir = HexrdConfig().images_dir
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, dir=images_dir)

        if selected_file:
            HexrdConfig().set_images_dir(selected_file)

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_file)[1]
            if (ImageFileManager().is_hdf5(ext) and not
                    ImageFileManager().path_exists(selected_file)):

                ImageFileManager().path_prompt(selected_file)

            ImageLoadManager().read_data([[selected_file]], parent=self.ui, template=True)
            self.images_loaded(os.path.split(selected_file)[1])

    def images_loaded(self, file_name):
        val = HexrdConfig().current_images_dict().values()
        self.img = list(val)[0]
        self.ui.file_name.setText(file_name)
        self.ui.template_menu.setEnabled(True)

    def warn_before_close(self):
        ret = QMessageBox.warning(
                self.ui, 'HEXRD',
                'All changes will be lost. Do you want to quit anyway?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.ui.reject()

    def update_image(self):
        # If there are no images loaded, skip the request
        if not HexrdConfig().has_images():
            return
        self.ui.image_tab_widget.load_images(template=True)
        self.ui.image_tab_widget.image_canvases[0].draw()

    def load_template(self, idx):
        self.ui.template_menu.setDisabled(bool(idx))
        if idx == 0:
            return
        else:
            selection = self.ui.template_menu.currentText()
            self.current_template = InteractiveTemplate(self.img, self.ui.image_tab_widget)
            self.current_template.create_shape(selection, self.pixel_size)
            self.it.append(self.current_template)
            self.ui.image_tab_widget.add_template(self.current_template.get_shape())
            self.ui.image_tab_widget.image_canvases[0].draw()

    def set_threshold(self, checked):
          self.ui.threshold.setEnabled(checked)

    def add_mask(self):
        if self.ui.threshold_select.isChecked():
            self.create_threshold_mask(
                self.ui.threshold.value(),
                self.ui.comparator.currentIndex())
        else:
            self.current_template.create_mask()
            self.masks.append(self.current_template.get_mask())
            self.current_template.disconnect()
        self.reset_settings()

    def create_threshold_mask(self, val, comparator):
        if comparator == LESS_THAN:
            self.masks.append(self.img > val)
        elif comparator == GREATER_THAN:
            self.masks.append(self.img < val)
        elif comparator == NOT_EQUAL_TO:
            self.masks.append(self.img != val)
        elif comparator == EQUAL_TO:
            self.masks.append(self.img == val)

    def reset_settings(self):
        self.ui.blockSignals(True)
        self.ui.template_menu.setCurrentIndex(0)
        self.ui.threshold_select.setChecked(False)
        self.ui.comparator.setCurrentIndex(0)
        self.ui.threshold.setValue(0.00)
        self.ui.blockSignals(False)

    def save(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Mask', HexrdConfig().working_dir,
            'NPZ files (*.npz)')
        result = self.masks[0]
        for mask in self.masks[1:]:
            result = np.logical_and(result, mask)
        # print('list: ', result.tolist(False))
        # lst = result.tolist()
        # print('result: ', result)
        np.savez(selected_file, result)
