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
        self.ui.template_menu.currentIndexChanged.connect(self.load_template)
        self.ui.add_mask.clicked.connect(self.add_mask)

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
        self.ui.add_mask.setEnabled(True)

    def update_image(self):
        # If there are no images loaded, skip the request
        if not HexrdConfig().has_images():
            return
        self.ui.image_tab_widget.load_images(template=True)
        self.ui.image_tab_widget.image_canvases[0].draw()

    def load_template(self, idx):
        if idx == 0:
            return
        else:
            selection = self.ui.template_menu.currentText()
            self.current_template = InteractiveTemplate(self.img, self.ui.image_tab_widget)
            self.current_template.create_shape(selection, self.pixel_size)
            self.it.append(self.current_template)
            self.ui.image_tab_widget.add_template(self.current_template.get_shape())
            self.ui.image_tab_widget.image_canvases[0].draw()

    def add_mask(self):
        self.current_shape.create_mask()
        self.masks.append(self.current_shape.get_mask())
        result = None
        for mask in self.masks:
            if result is None:
                result = mask
            else:
                result = np.logical_and(result, mask)
        master_mask = np.ma.masked_where(result, self.img)
        axis = self.ui.image_tab_widget.image_canvases[0].raw_axes[0]
        self.ui.image_tab_widget.image_canvases[0].axes_images.append(
            axis.imshow(master_mask, cmap=plt.cm.binary, alpha=1.0))
        self.ui.image_tab_widget.image_canvases[0].draw()
        self.reset_settings()

    def reset_settings(self):
        self.ui.blockSignals(True)
        self.ui.template_menu.setCurrentIndex(0)
        self.ui.threshold_select.setChecked(False)
        self.ui.comparator.setCurrentIndex(0)
        self.ui.threshold.setValue(0.00)
        self.ui.blockSignals(False)
