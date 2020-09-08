import os
import numpy as np

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QFileDialog, QMessageBox

from skimage.transform import rotate

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
        self.canvas = parent.image_tab_widget.image_canvases[0]

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
        self.ui.button_box.accepted.connect(self.finalize)
        self.ui.button_box.rejected.connect(self.clear)
        self.ui.save.clicked.connect(self.save_file)
        self.ui.complete.clicked.connect(self.completed)

    def enable_widgets(self, *widgets, enabled):
        for w in widgets:
            w.setEnabled(enabled)

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
                self.enable_widgets(self.ui.detector_label, self.ui.detectors,
                                    enabled=True)

    def get_instrument_detectors(self, instrument):
        self.mod = resource_loader.import_dynamic_module(
            'hexrd.ui.resources.templates.' + instrument)
        contents = resource_loader.module_contents(self.mod)
        dets = ['None']
        for content in contents:
            if not content.startswith('__'):
                dets.append(content.split('.')[0])
        return dets

    def load_instrument_config(self, name):
        fname = 'default_' + name.lower() + '_config.yml'
        with resource_loader.resource_path(
                hexrd.ui.resources.calibration, fname) as f:
            for overlay in HexrdConfig().overlays:
                overlay['visible'] = False
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
            if (ImageFileManager().is_hdf(ext) and not
                    ImageFileManager().path_exists(selected_file)):
                path_selected = ImageFileManager().path_prompt(selected_file)
                if not path_selected:
                    return

            if hasattr(self, 'prev_extent'):
                self.canvas.axes_images[0].set_extent(self.prev_extent)
            ImageLoadManager().read_data(files, parent=self.ui)

            file_names = [os.path.split(f[0])[1] for f in files]
            self.ui.files_label.setText(', '.join(file_names))
            self.enable_widgets(self.ui.outline, self.ui.add_template,
                                self.ui.transforms, self.ui.add_transform,
                                enabled=True)
            self.enable_widgets(self.parent().action_show_toolbar,
                                self.ui.save, enabled=False)
            self.parent().action_show_toolbar.setChecked(False)

    def add_transform(self):
        ilm = ImageLoadManager()
        state = HexrdConfig().load_panel_state
        ilm.set_state({ 'trans': [self.ui.transforms.currentIndex()] })
        ilm.begin_processing(postprocess=True)
        self.ui.transforms.setCurrentIndex(0)
        if self.it:
            self.it.update_image(HexrdConfig().image('default', 0))

    def add_template(self):
        det = self.ui.detectors.currentText()
        self.it = InteractiveTemplate(
            HexrdConfig().image('default', 0), self.parent())
        self.it.create_shape(module=self.mod, file_name=det + '.txt')
        self.enable_widgets(self.ui.trans, self.ui.rotate, self.ui.button_box,
                            self.ui.complete, enabled=True)
        self.enable_widgets(self.ui.detectors, self.ui.add_template,
                            self.ui.load, enabled=False)
        self.ui.trans.setChecked(True)

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

    def finalize(self):
        if self.ui.trans.isChecked():
            self.it.disconnect_translate()
        else:
            self.it.disconnect_rotate()
        self.crop_and_mask()
        self.completed_detectors.append(self.ui.detectors.currentText())
        self.enable_widgets(self.ui.detectors, self.ui.load, self.ui.complete,
                            self.ui.completed_dets, self.ui.save,
                            self.ui.finalize, enabled=True)
        self.enable_widgets(self.ui.trans, self.ui.rotate, self.ui.button_box,
                            self.ui.add_template, enabled=False)
        self.ui.completed_dets.setText(', '.join(
            set(self.completed_detectors)))

    def crop_and_mask(self):
        if self.it.rotation:
            self.it.update_image(rotate(self.it.img, self.it.rotation))
            self.it.rotate_template(self.it.get_shape().xy, -(self.it.rotation))
        self.it.update_image(self.it.get_mask())
        img = self.it.crop()
        bounds = self.it.bounds()
        ImageLoadManager().read_data([[img]], parent=self.ui)
        det = self.ui.detectors.currentText()
        self.edited_images[det] = {
            'img': img,
            'height': img.shape[0],
            'width': img.shape[1],
            'transform': transform
        }
        self.canvas.raw_axes[0].autoscale(True)
        self.prev_extent = self.canvas.axes_images[0].get_extent()
        self.canvas.axes_images[0].set_extent(
            (bounds[2], bounds[3], bounds[0], bounds[1]))
        self.it.redraw()
        self.clear_boundry()

    def clear(self):
        self.clear_boundry()
        self.enable_widgets(self.ui.detectors, self.ui.load,
                            self.ui.add_template, enabled=True)
        self.enable_widgets(self.ui.trans, self.ui.rotate, self.ui.button_box,
                            self.ui.save, self.ui.complete, enabled=False)

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
            self.finalize()

    def reset_panel(self):
        self.clear_boundry()
        self.ui.instruments.setCurrentIndex(3)
        self.ui.detectors.setCurrentIndex(0)
        self.ui.files_label.setText('')
        self.ui.completed_dets.setText('')
        self.enable_widgets(self.ui.detectors, self.ui.data, self.ui.outline,
                            self.ui.finalize, enabled=False)
        self.completed_detectors = []

    def completed(self):
        self.check_for_unsaved_changes()

        files = []
        for key, val in self.edited_images.items():
            HexrdConfig().add_detector(key, 'default')
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'pixels', 'columns', 'value'],
                int(val['width']))
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'pixels', 'rows', 'value'],
                int(val['height']))
            files.append([val['img']])
        HexrdConfig().remove_detector('default')
        ilm = ImageLoadManager()
        ilm.read_data(files, parent=self.ui)
        self.new_config_loaded.emit()

        self.reset_panel()
        self.parent().action_show_toolbar.setEnabled(True)
        self.parent().action_show_toolbar.setChecked(True)
