import os
import numpy as np

from matplotlib import cm
import matplotlib.pyplot as plt
import matplotlib.colors

from PySide2.QtCore import QObject
from PySide2.QtWidgets import QFileDialog, QMessageBox

import hexrd.ui.constants
from hexrd.ui.ui_loader import UiLoader

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

        self.load_cmaps()

        self.setup_connections()

    def setup_connections(self):
        self.ui.load_image.clicked.connect(self.open_image_files)
        self.ui.template_menu.currentIndexChanged.connect(self.load_template)

        self.ui.image_tab_widget.template_update_needed.connect(self.update_image)
        ImageLoadManager().template_update_needed.connect(self.update_image)
        ImageLoadManager().new_images_loaded.connect(
            self.color_map_editor.update_bounds)
        ImageLoadManager().new_images_loaded.connect(
            self.color_map_editor.reset_range)

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

    def update_image(self, clear_canvases=False):
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
            self.current_shape = InteractiveTemplate(self.img, self.ui.image_tab_widget, selection)
            self.it.append(self.current_shape)
            self.ui.image_tab_widget.add_template(self.current_shape.get_shape())
