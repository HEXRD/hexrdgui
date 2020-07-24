import os
import numpy as np

from PySide2.QtCore import QObject
from PySide2.QtWidgets import QFileDialog

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.interactive_template import InteractiveTemplate
from hexrd.ui import resource_loader
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
        self.ui.add_template.clicked.connect(self.add_template)
        self.ui.trans.clicked.connect(self.setup_translate)
        self.ui.rotate.clicked.connect(self.setup_rotate)
        self.ui.button_box.accepted.connect(self.crop_and_mask)
        self.ui.button_box.rejected.connect(self.clear)
        self.ui.save.clicked.connect(self.save_file)

    def instrument_selected(self, idx):
        instruments = ['TARDIS', 'PXRDIP', 'BBXRD']
        det_list = self.get_instrument_detectors(instruments[idx])
        self.ui.detectors.clear()
        self.ui.detectors.insertItems(0, det_list)
        self.ui.detector_label.setEnabled(True)
        self.ui.detectors.setEnabled(True)

    def get_instrument_detectors(self, instrument):
        self.mod = resource_loader.import_dynamic_module(
            'hexrd.ui.resources.templates.' + instrument)
        contents = resource_loader.module_contents(self.mod)
        dets = ['None']
        for content in contents:
            if isinstance(content, str) and not content.startswith('__'):
                dets.append(content.split('.')[0])
        return dets

    def load_instrument_config(self, name):
        fname = 'default_' + name.lower() + '_config.yml'
        with resource_loader.resource_path(
                hexrd.ui.resources.calibration, fname) as f:
            HexrdConfig().load_instrument_config(f)

    def detector_selected(self, selected):
        self.ui.data.setEnabled(selected)
        self.ui.instruments.setDisabled(selected)

    def load_images(self):
        caption = HexrdConfig().images_dirtion = 'Select file(s)'
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, caption, dir=HexrdConfig().images_dir)
        if selected_file:
            HexrdConfig().set_images_dir(selected_file)

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_file)[1]
            if (ImageFileManager().is_hdf5(ext) and not
                    ImageFileManager().path_exists(selected_file)):
                ImageFileManager().path_prompt(selected_file)

            selected_files = [[selected_file]]
            ImageLoadManager().read_data(
                selected_files, parent=self.ui)

            files = [os.path.split(f[0])[1] for f in selected_files]
            self.ui.files_label.setText(','.join(files))
            self.ui.outline.setEnabled(True)
            self.ui.detectors.setDisabled(True)
            self.ui.load.setDisabled(True)

    def add_template(self):
        det = self.ui.detectors.currentText()
        self.it = InteractiveTemplate(
            HexrdConfig().image('detector', 0), self.parent())
        self.it.create_shape(module=self.mod, file_name=det + '.txt')
        self.ui.add_template.setDisabled(True)
        self.ui.trans.setEnabled(True)
        self.ui.rotate.setEnabled(True)
        self.ui.button_box.setEnabled(True)
        self.ui.save.setEnabled(True)

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

    def crop_and_mask(self):
        if self.ui.trans.isChecked():
            self.it.disconnect_translate()
        else:
            self.it.disconnect_rotate()
        img = self.it.get_mask()
        bounds = np.array([int(val) for val in self.it.crop()]).reshape(2, 2)
        self.finalize(img, bounds)
        self.ui.trans.setDisabled(True)
        self.ui.rotate.setDisabled(True)
        self.ui.button_box.setDisabled(True)
        self.ui.add_template.setDisabled(True)
        self.ui.detectors.setEnabled(True)
        self.ui.load.setEnabled(True)

    def finalize(self, img, bounds):
        ImageLoadManager().read_data([[img]], parent=self.ui)
        ilm = ImageLoadManager()
        ilm.set_state({'rect': [bounds]})
        ilm.begin_processing()
        det = self.ui.detectors.currentText()
        self.it.redraw()
        self.clear_boundry()

    def clear(self):
        self.clear_boundry()
        self.ui.detectors.setEnabled(True)
        self.ui.load.setEnabled(True)
        self.ui.add_template.setEnabled(True)
        self.ui.trans.setDisabled(True)
        self.ui.rotate.setDisabled(True)
        self.ui.button_box.setDisabled(True)
        self.ui.save.setDisabled(True)

    def save_file(self):
        self.parent().action_save_imageseries.trigger()
