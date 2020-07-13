import os

from PySide2.QtCore import QObject
from PySide2.QtWidgets import QFileDialog

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.ui_loader import UiLoader


class ImportDataPanel(QObject):

    def __init__(self, parent=None):
        super(ImportDataPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('import_data_panel.ui', parent)

        self.setup_connections()
    
    def setup_connections(self):
        self.ui.load.clicked.connect(self.load_images)
    
    def load_images(self):
        caption = HexrdConfig().images_dirtion = 'Select file(s)'
        selected_files, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, caption, dir=HexrdConfig().images_dir)
        if selected_files:
            HexrdConfig().set_images_dir(selected_files[0])

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_files[0])[1]
            if (ImageFileManager().is_hdf5(ext) and not
                    ImageFileManager().path_exists(selected_files[0])):

                ImageFileManager().path_prompt(selected_files[0])

            selected_files = [[x] for x in selected_files]
            ImageLoadManager().read_data(
                selected_files, parent=self.ui)
