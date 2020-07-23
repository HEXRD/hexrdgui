import os

from PySide2.QtCore import QObject
from PySide2.QtWidgets import QFileDialog

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.interactive_template import InteractiveTemplate
from hexrd.ui.ui_loader import UiLoader


class ImportDataPanel(QObject):

    def __init__(self, parent=None):
        super(ImportDataPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('import_data_panel.ui', parent)
        self.it = None

        self.setup_connections()
    
    def setup_connections(self):
        self.ui.instruments.currentIndexChanged.connect(
            self.instrument_selected)
        self.ui.detectors.currentIndexChanged.connect(self.detector_selected)
        self.ui.load.clicked.connect(self.load_images)
        self.ui.trans.clicked.connect(self.setup_translate)
        self.ui.rotate.clicked.connect(self.setup_rotate)

    def instrument_selected(self, idx):
        TARDIS = ['None', 'IP2', 'IP3', 'IP4']
        PXRDIP = ['None']
        BBXRD = ['None']
        dets = [TARDIS, PXRDIP, BBXRD]

        self.ui.detectors.clear()
        self.ui.detectors.insertItems(0, dets[idx])
        self.ui.detector_label.setEnabled(True)
        self.ui.detectors.setEnabled(True)
        self.clear_boundry()

    def detector_selected(self, selected):
        self.ui.trans.setEnabled(selected)
        self.ui.rotate.setEnabled(selected)
        self.ui.button_box.setEnabled(selected)
        if selected > 0:
            instr = self.ui.instruments.currentText()
            det = self.ui.detectors.currentText()
            if self.it is not None:
                self.clear_boundry()
            self.it = InteractiveTemplate(
                HexrdConfig().image(det, 0), self.parent())
            self.it.create_shape(file_name=instr+'_'+det)
        else:
            self.clear_boundry()

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

            files = [os.path.split(f[0])[1] for f in selected_files]
            self.ui.files_label.setText(','.join(files))
            self.ui.instruments.setEnabled(True)
            self.ui.instrument_label.setEnabled(True)

    def setup_translate(self):
        if self.it is not None:
            self.it.disconnect_rotate()
            self.it.connect_translate()

    def setup_rotate(self):
        if self.it is not None:
            self.it.disconnect_translate()
            self.it.connect_rotate()

    def clear_boundry(self):
        if self.it is None:
            return
        self.it.clear()
        self.it = None
