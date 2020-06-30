import os
import numpy as np

from matplotlib import cm
import matplotlib.colors

from PySide2.QtCore import QObject
from PySide2.QtWidgets import QFileDialog, QMessageBox

import hexrd.ui.constants
from hexrd.ui.ui_loader import UiLoader

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager


class TemplateDialog(QObject):

    def __init__(self, parent=None):
        super(TemplateDialog, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('template_dialog.ui', parent)

        self.load_cmaps()

        self.setup_connections()

    def setup_connections(self):
        self.ui.load_image.clicked.connect(self.open_image_files)

        self.ui.color_map.currentIndexChanged.connect(self.update_cmap)
        self.ui.log_scale.toggled.connect(self.update_norm)

        self.ui.image_tab_widget.dialog_update_needed.connect(self.update_image)
        ImageLoadManager().dialog_update_needed.connect(self.update_image)
        ImageLoadManager().new_images_loaded.connect(self.percentile_range)

    def exec_(self):
        return self.ui.exec_()

    def load_cmaps(self):
        cmaps = sorted(i[:-2] for i in dir(cm) if i.endswith('_r'))
        self.ui.color_map.addItems(cmaps)

        # Set the combobox to be the default
        self.ui.color_map.setCurrentText(hexrd.ui.constants.DEFAULT_CMAP)

    def update_cmap(self):
        # Get the Colormap object from the name
        cmap = cm.get_cmap(self.ui.color_map.currentText())
        self.ui.image_tab_widget.set_cmap(cmap)

    def update_norm(self):
        min, max = self.bounds

        if self.ui.log_scale.isChecked():
            # The min cannot be 0 here, or this will raise an exception
            min = 1.e-8 if min < 1.e-8 else min
            norm = matplotlib.colors.LogNorm(vmin=min, vmax=max)
        else:
            norm = matplotlib.colors.Normalize(vmin=min, vmax=max)

        self.ui.image_tab_widget.set_norm(norm)

    def percentile_range(self, low=69.0, high=99.9):
        d = HexrdConfig().current_images_dict()
        l = min([np.percentile(d[key], low) for key in d.keys()])
        h = min([np.percentile(d[key], high) for key in d.keys()])

        if h - l < 5:
            h = l + 5

        self.bounds = l, h

    def open_image_files(self):
        # Get the most recent images dir
        images_dir = HexrdConfig().images_dir
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, dir=images_dir)

        if selected_file:
            # Save the chosen dir
            HexrdConfig().set_images_dir(selected_file)

            # If it is a hdf5 file allow the user to select the path
            file_name, ext = os.path.splitext(selected_file)
            if (ImageFileManager().is_hdf5(ext) and not
                    ImageFileManager().path_exists(selected_file)):

                ImageFileManager().path_prompt(selected_file)

            ImageLoadManager().read_data(selected_file, parent=self.ui, dialog=True)
            self.images_loaded(file_name)

    def images_loaded(self, file_name):
        self.ui.file_name.setText(file_name)
        self.ui.log_scale.setEnabled(True)
        self.ui.color_map.setEnabled(True)

    def update_image(self, clear_canvases=False):
        # If there are no images loaded, skip the request
        if not HexrdConfig().has_images():
            return
        self.ui.image_tab_widget.load_images(dialog=True)
