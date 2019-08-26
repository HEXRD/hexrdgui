import os
import fabio

from hexrd import imageseries

from PySide2.QtGui import QCursor
from PySide2.QtCore import QObject, Qt, QPersistentModelIndex, QThreadPool
from PySide2.QtWidgets import QTableWidgetItem, QFileDialog, QMenu, QMessageBox

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.cal_progress_dialog import CalProgressDialog
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.ui_loader import UiLoader

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

        self.ims = HexrdConfig().imageseries_dict
        self.parent_dir = HexrdConfig().images_dir
        self.files = []
        self.dark_file = None
        self.trans = {'agg': 0, 'trans': 0, 'dark': 0}
        self.idx = 0

        self.setup_gui()
        self.setup_connections()

    def setup_gui(self):
        self.ui.img_directory.setText(os.path.dirname(self.parent_dir))
        self.ui.dark_file.setText(
            '(Using ' + str(self.ui.darkMode.currentText()) + ')')
        self.detectors_changed()
        self.ui.file_options.resizeColumnsToContents()

    def setup_connections(self):
        self.ui.image_folder.clicked.connect(self.select_folder)
        self.ui.image_files.clicked.connect(self.select_images)
        self.ui.selectDark.clicked.connect(self.select_dark_img)
        self.ui.read.clicked.connect(self.read_data)

        self.ui.darkMode.currentIndexChanged.connect(self.dark_mode_changed)
        self.ui.detector.currentIndexChanged.connect(self.create_table)
        self.ui.aggregation.currentIndexChanged.connect(self.agg_changed)
        self.ui.transform.currentIndexChanged.connect(self.trans_changed)

        self.ui.file_options.customContextMenuRequested.connect(
            self.contextMenuEvent)
        self.ui.file_options.cellChanged.connect(self.omega_data_changed)
        HexrdConfig().detectors_changed.connect(self.detectors_changed)

    def dark_mode_changed(self):
        self.trans['dark'] = self.ui.darkMode.currentIndex()

        if self.trans['dark'] == 4:
            self.ui.selectDark.setEnabled(True)
            self.ui.dark_file.setText(self.dark_file)
            self.ui.read.setEnabled(
                self.dark_file is not None and len(self.files))
        else:
            self.ui.selectDark.setEnabled(False)
            self.ui.dark_file.setText(
                '(Using ' + str(self.ui.darkMode.currentText()) + ')')
            self.ui.read.setEnabled(len(self.files))

    def detectors_changed(self):
        self.ui.detector.clear()
        self.ui.detector.addItems(HexrdConfig().get_detector_names())

    def agg_changed(self):
        self.trans['agg'] = self.ui.aggregation.currentIndex()

    def trans_changed(self):
        self.trans['trans'] = self.ui.transform.currentIndex()

    def dir_changed(self):
        self.ui.img_directory.setText(os.path.dirname(self.parent_dir))

    def select_folder(self):
        # This expects to define the root image folder.
        images_dir = HexrdConfig().images_dir
        caption = HexrdConfig().images_dirtion = 'Select directory for images'
        new_dir = QFileDialog.getExistingDirectory(
            self.ui, caption, dir=self.parent_dir)

        # Only update if a new directory is selected
        if new_dir and new_dir != self.parent_dir:
            HexrdConfig().set_images_dir(new_dir)
            self.parent_dir = new_dir
            self.dir_changed()

    def select_dark_img(self):
        # This takes one image to use for dark subtraction.
        caption = HexrdConfig().images_dirtion = 'Select image file'
        selected_file, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, caption, dir=self.parent_dir)

        if selected_file:
            self.dark_file = selected_file[0]
            self.dark_mode_changed()
            self.ui.read.setEnabled(len(selected_file))

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
