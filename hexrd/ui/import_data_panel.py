import os
import numpy as np

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QFileDialog, QMessageBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.interactive_template import InteractiveTemplate
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui import resource_loader
from hexrd.ui.ui_loader import UiLoader

import hexrd.ui.resources.calibration


class ImportDataPanel(QObject):

    # Emitted when new config is loaded
    new_config_loaded = Signal()

    def __init__(self, parent=None):
        super(ImportDataPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('import_data_panel.ui', parent)
        self.it = None
        self.edited_images = {}
        self.completed_detectors = []

        self.setup_connections()

    def setup_connections(self):
        self.ui.instruments.currentIndexChanged.connect(
            self.instrument_selected)
        self.ui.detectors.currentIndexChanged.connect(self.detector_selected)
        self.ui.load.clicked.connect(self.load_images)
        self.ui.add_template.clicked.connect(self.add_template)
        self.ui.trans.clicked.connect(self.setup_translate)
        self.ui.rotate.clicked.connect(self.setup_rotate)
        self.ui.add_transform.clicked.connect(self.add_transform)
        self.ui.button_box.accepted.connect(self.crop_and_mask)
        self.ui.button_box.rejected.connect(self.clear)
        self.ui.save.clicked.connect(self.save_file)
        self.ui.complete.clicked.connect(self.completed)

    def instrument_selected(self, idx):
        if idx == 3:
            self.ui.detectors.setCurrentIndex(0)
            self.ui.detectors.setDisabled(True)
        else:
            instruments = ['TARDIS', 'PXRDIP', 'BBXRD']
            det_list = self.get_instrument_detectors(instruments[idx])
            if len(det_list) > 1:
                self.load_instrument_config(instruments[idx])
                self.new_config_loaded.emit()
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

            files, manual = ImageLoadManager().load_images([selected_file])
            dialog = LoadImagesDialog(files, manual, self.ui.parent())
            if not dialog.exec_():
                return

            # If it is a hdf5 file allow the user to select the path
            ext = os.path.splitext(selected_file)[1]
            if (ImageFileManager().is_hdf5(ext) and not
                    ImageFileManager().path_exists(selected_file)):
                ImageFileManager().path_prompt(selected_file)

            ImageLoadManager().read_data(files, parent=self.ui)

            file_names = [os.path.split(f[0])[1] for f in files]
            self.ui.files_label.setText(', '.join(file_names))
            self.ui.outline.setEnabled(True)
            self.ui.add_template.setEnabled(True)
            self.ui.save.setDisabled(True)
            self.ui.transforms.setEnabled(True)
            self.ui.add_transform.setEnabled(True)
            self.parent().action_show_toolbar.setChecked(False)
            self.parent().action_show_toolbar.setDisabled(True)

    def add_transform(self):
        ilm = ImageLoadManager()
        state = HexrdConfig().load_panel_state
        ilm.set_state({ 'trans': [self.ui.transforms.currentIndex()] })
        ilm.begin_processing(postprocess=True)
        self.ui.transforms.setCurrentIndex(0)

    def add_template(self):
        det = self.ui.detectors.currentText()
        self.it = InteractiveTemplate(
            HexrdConfig().image('default', 0), self.parent())
        self.it.create_shape(module=self.mod, file_name=det + '.txt')
        self.ui.add_template.setDisabled(True)
        self.ui.trans.setEnabled(True)
        self.ui.trans.setChecked(True)
        self.ui.rotate.setEnabled(True)
        self.ui.button_box.setEnabled(True)
        self.ui.detectors.setDisabled(True)
        self.ui.load.setDisabled(True)
        self.ui.complete.setEnabled(True)

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
        self.completed_detectors.append(self.ui.detectors.currentText())
        self.ui.trans.setDisabled(True)
        self.ui.rotate.setDisabled(True)
        self.ui.button_box.setDisabled(True)
        self.ui.add_template.setDisabled(True)
        self.ui.detectors.setEnabled(True)
        self.ui.load.setEnabled(True)
        self.ui.completed_dets.setText(', '.join(
            set(self.completed_detectors)))
        self.ui.completed_dets.setEnabled(True)
        self.ui.finalize.setEnabled(True)
        self.ui.complete.setEnabled(True)
        self.ui.save.setEnabled(True)

    def finalize(self, img, bounds):
        ImageLoadManager().read_data([[img]], parent=self.ui)
        ilm = ImageLoadManager()
        ilm.set_state({'rect': [bounds]})
        ilm.begin_processing()
        det = self.ui.detectors.currentText()
        self.edited_images[det] = {
            'img': img,
            'rect': bounds,
            'height': np.abs(bounds[0][0]-bounds[0][1]),
            'width': np.abs(bounds[1][0]-bounds[1][1])
        }
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
        self.ui.complete.setDisabled(True)

    def save_file(self):
        self.parent().action_save_imageseries.trigger()

    def check_for_unsaved_changes(self):
        curr_det = self.ui.detectors.currentText()
        if self.it is None and curr_det in self.completed_detectors:
            return
        msg = ('The currently selected detector has changes that have not been'
               + ' accepted. Keep changes?')
        response = QMessageBox.question(
            self.ui, 'HEXRD', msg, (QMessageBox.Cancel | QMessageBox.Save))
        if response == QMessageBox.Save:
            self.crop_and_mask()

    def reset_panel(self):
        self.clear_boundry()
        self.ui.detectors.setCurrentIndex(0)
        self.ui.detectors.setDisabled(True)
        self.ui.files_label.setText('')
        self.ui.data.setDisabled(True)
        self.ui.outline.setDisabled(True)
        self.ui.completed_dets.setText('')
        self.ui.finalize.setDisabled(True)
        self.completed_detectors = []

    def completed(self):
        self.check_for_unsaved_changes()

        state = {'rect': []}
        files = []
        for key, val in self.edited_images.items():
            HexrdConfig().add_detector(key, 'default')
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'pixels', 'columns', 'value'],
                int(val['width']))
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'pixels', 'rows', 'value'],
                int(val['height']))
            state['rect'].append(val['rect'])
            files.append([val['img']])
        HexrdConfig().remove_detector('default')
        ilm = ImageLoadManager()
        ilm.read_data(files, parent=self.ui)
        ilm.set_state(state)
        ilm.begin_processing()
        self.new_config_loaded.emit()

        self.reset_panel()
        self.parent().action_show_toolbar.setEnabled(True)
        self.parent().action_show_toolbar.setChecked(True)
