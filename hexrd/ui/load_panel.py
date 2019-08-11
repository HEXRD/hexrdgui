from PySide2.QtCore import QObject, Qt
from PySide2.QtWidgets import QMenu, QMessageBox, QTableWidgetItem, QFileDialog

from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.hexrd_config import HexrdConfig

"""
    This panel is in charge of loading file(s) for the experiment. It is built
    up in a few steps, and defines how they should be loaded, transformed, and
    attempts to apply intelligent templates to avoid manual entry of everything.
    The final act is to click load data and bring the data set in.
"""
class LoadPanel(QObject):

    def __init__(self, parent=None):
        super(LoadPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('load_panel.ui', parent)

        self.setup_connections()

    def setup_connections(self):
        self.ui.image_folder.clicked.connect(self.select_folder)
        self.ui.image_files.clicked.connect(self.select_images)
        self.ui.read.clicked.connect(self.read_data)

    def select_folder(self):
        # This expects to define the root image folder.
        images_dir = HexrdConfig().images_dir
        caption = HexrdConfig().images_dirtion = 'Select directory for images'
        dir = QFileDialog.getExistingDirectory(self.ui, caption, dir=images_dir)

    def select_images(self):
        # This takes one or more images for a single detector.
        images_dir = HexrdConfig().images_dir
        caption = HexrdConfig().images_dirtion = 'Select image file(s)'
        selected_files, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, caption, dir=images_dir)

    def read_data(self):
        # When this is pressed we need to check that all data is set, and then
        # read in a complete set of data for all detectors.
        print("Read all the data!")
