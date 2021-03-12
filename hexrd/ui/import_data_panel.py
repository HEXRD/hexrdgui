import os
import yaml

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QColorDialog, QFileDialog, QMessageBox
from PySide2.QtGui import QColor

from hexrd import resources as hexrd_resources

from hexrd.ui.utils import convert_tilt_convention
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.interactive_template import InteractiveTemplate
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui import resource_loader
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.constants import UI_TRANS_INDEX_ROTATE_90

import hexrd.ui.resources.calibration


class ImportDataPanel(QObject):

    # Emitted when new config is loaded
    new_config_loaded = Signal()

    def __init__(self, cmap=None, parent=None):
        super(ImportDataPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('import_data_panel.ui', parent)
        self.it = None
        self.edited_images = {}
        self.completed_detectors = []
        self.canvas = parent.image_tab_widget.image_canvases[0]
        self.detector_defaults = {}
        self.cmap = cmap

        self.set_default_color()
        self.setup_connections()

    def setup_connections(self):
        self.ui.instruments.currentTextChanged.connect(
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
        self.ui.bb_height.valueChanged.connect(self.update_bbox_height)
        self.ui.bb_width.valueChanged.connect(self.update_bbox_width)
        self.ui.line_style.currentIndexChanged.connect(
            self.update_template_style)
        self.ui.line_color.clicked.connect(self.pick_line_color)
        self.ui.line_size.valueChanged.connect(self.update_template_style)

    def enable_widgets(self, *widgets, enabled):
        for w in widgets:
            w.setEnabled(enabled)

    def set_default_color(self):
        self.outline_color = '#00ffff'
        self.ui.line_color.setText(self.outline_color)
        self.ui.line_color.setStyleSheet(
            'QPushButton {background-color: cyan}')

    def get_instrument_defaults(self):
        self.detector_defaults.clear()
        fname = f'{self.instrument.lower()}_ref_config.yml'
        try:
            text = resource_loader.load_resource(hexrd_resources, fname)
        except Exception:
            fname = f'{self.instrument.lower()}_reference_config.yml'
            text = resource_loader.load_resource(hexrd_resources, fname)
        defaults = yaml.load(text, Loader=yaml.FullLoader)
        for det, vals in defaults['detectors'].items():
            self.detector_defaults[det] = vals['transform']

    def instrument_selected(self, instrument):
        self.detector_defaults.clear()
        self.instrument = instrument

        if self.instrument is None:
            self.ui.detectors.setCurrentIndex(0)
            self.ui.detectors.setDisabled(True)
        else:
            self.get_instrument_defaults()
            self.set_convention()
            det_list = list(self.detector_defaults.keys())
            det_list.insert(0, '(None)')
            self.load_instrument_config()
            self.ui.detectors.clear()
            self.ui.detectors.insertItems(0, det_list)
            self.enable_widgets(self.ui.detector_label, self.ui.detectors,
                                enabled=True)

    def set_convention(self):
        new_conv = {'axes_order': 'zxz', 'extrinsic': False}
        HexrdConfig().set_euler_angle_convention(new_conv)

    def load_instrument_config(self):
        fname = f'default_{self.instrument.lower()}_config.yml'
        with resource_loader.resource_path(
                hexrd.ui.resources.calibration, fname) as f:
            for overlay in HexrdConfig().overlays:
                overlay['visible'] = False
            HexrdConfig().load_instrument_config(f)

    def set_detector_defaults(self, det):
        if det not in self.detector_defaults.keys():
            return

        for key, value in self.detector_defaults[det].items():
            HexrdConfig().set_instrument_config_val(
                ['detectors', det, 'transform', key, 'value'], value)
        eac = {'axes_order': 'zxz', 'extrinsic': False}
        convert_tilt_convention(HexrdConfig().config['instrument'], None, eac)
        self.detector_defaults[det]['tilt'] = (
            HexrdConfig().get_instrument_config_val(
                ['detectors', det, 'transform', 'tilt', 'value']))
        self.new_config_loaded.emit()

    def detector_selected(self, selected):
        self.ui.data.setEnabled(selected)
        self.ui.instruments.setDisabled(selected)
        if selected:
            self.detector = self.ui.detectors.currentText()
            old_det = HexrdConfig().detector_names[0]

            self.cmap.block_updates(True)
            HexrdConfig().rename_detector(old_det, self.detector)
            self.cmap.block_updates(False)

            self.set_detector_defaults(self.detector)

    def update_bbox_height(self, val):
        y0, y1, *x = self.it.bounds
        h = y1 - y0
        scale = 1 - ((h - val) / h)
        self.it.scale_template(sy=scale)

    def update_bbox_width(self, val):
        *y, x0, x1 = self.it.bounds
        w = x1 - x0
        scale = 1 - ((w - val) / w)
        self.it.scale_template(sx=scale)

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

            if not self.canvas.raw_axes[0].get_autoscale_on():
                self.canvas.raw_axes[0].set_autoscale_on(True)

            if self.completed_detectors:
                # Only reset the color map range for first detector processed
                self.cmap.block_updates(True)
            ImageLoadManager().read_data(files, parent=self.ui)
            self.cmap.block_updates(False)

            file_names = [os.path.split(f[0])[1] for f in files]
            self.ui.files_label.setText(', '.join(file_names))
            self.enable_widgets(self.ui.outline, self.ui.add_template,
                                self.ui.transforms, self.ui.add_transform,
                                enabled=True)
            self.enable_widgets(self.parent().action_show_toolbar,
                                self.ui.save, enabled=False)
            self.parent().action_show_toolbar.setChecked(False)

    def add_transform(self):
        # Prevent color map reset on transform
        self.cmap.block_updates(True)
        ilm = ImageLoadManager()
        ilm.set_state({'trans': [self.ui.transforms.currentIndex()]})
        ilm.begin_processing(postprocess=True)
        self.cmap.block_updates(False)

        self.ui.transforms.setCurrentIndex(0)

        img = HexrdConfig().image(self.detector, 0)
        if self.detector in self.edited_images.keys():
            # This transform is being done post-processing
            self.edited_images[self.detector]['img'] = img
            self.edited_images[self.detector]['height'] = img.shape[0]
            self.edited_images[self.detector]['width'] = img.shape[1]

        if self.it:
            self.it.update_image(img)

    def display_bounds(self):
        self.ui.bb_height.blockSignals(True)
        self.ui.bb_width.blockSignals(True)

        y0, y1, x0, x1 = self.it.bounds
        self.ui.bb_width.setMaximum(x1 - x0)
        self.ui.bb_height.setMaximum(y1 - y0)

        self.ui.bb_width.setValue(x1)
        self.ui.bb_height.setValue(y1)

        self.ui.bb_height.blockSignals(False)
        self.ui.bb_width.blockSignals(False)

    def add_template(self):
        self.it = InteractiveTemplate(
            HexrdConfig().image(self.detector, 0), self.parent())
        self.it.create_shape(
            module=hexrd_resources,
            file_name=f'{self.instrument}_{self.detector}_bnd.txt',
            det=self.detector)
        self.update_template_style()
        if self.instrument == 'PXRDIP':
            self.it.rotate_shape(angle=90)

        self.display_bounds()
        self.enable_widgets(self.ui.trans, self.ui.rotate, self.ui.button_box,
                            self.ui.complete, self.ui.line_color,
                            self.ui.line_style, self.ui.line_size,
                            self.ui.color_label, self.ui.size_label,
                            self.ui.style_label, enabled=True)
        self.enable_widgets(self.ui.detectors, self.ui.add_template,
                            self.ui.load, self.ui.transforms,
                            self.ui.add_transform, enabled=False)
        if self.ui.instruments.currentText() != 'TARDIS':
            self.enable_widgets(self.ui.height_label, self.ui.bb_height,
                                self.ui.bb_width, self.ui.width_label,
                                self.ui.bb_label, enabled=True)
        self.ui.trans.setChecked(True)

    def update_template_style(self):
        ls = self.ui.line_style.currentText()
        lw = self.ui.line_size.value()
        self.it.update_style(ls, lw, self.outline_color)

    def pick_line_color(self):
        sender = self.sender()
        color = sender.text()

        dialog = QColorDialog(QColor(color), self.ui)
        if dialog.exec_():
            sender.setText(dialog.selectedColor().name())
            lc = self.ui.line_color
            lc.setStyleSheet('QPushButton {background-color: %s}' % lc.text())
            self.outline_color = dialog.selectedColor().name()
            self.update_template_style()

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
        self.finalize()
        self.completed_detectors.append(self.detector)
        self.enable_widgets(self.ui.detectors, self.ui.load, self.ui.complete,
                            self.ui.completed_dets, self.ui.save,
                            self.ui.finalize, self.ui.transforms,
                            self.ui.add_transform, enabled=True)
        self.enable_widgets(self.ui.trans, self.ui.rotate, self.ui.button_box,
                            self.ui.add_template, self.ui.bb_label,
                            self.ui.bb_height, self.ui.height_label,
                            self.ui.bb_width, self.ui.width_label,
                            self.ui.line_color, self.ui.line_style,
                            self.ui.line_size, self.ui.color_label,
                            self.ui.size_label, self.ui.style_label,
                            enabled=False)
        self.ui.completed_dets.setText(', '.join(
            set(self.completed_detectors)))

    def finalize(self):
        self.it.cropped_image
        img = self.it.masked_image

        ilm = ImageLoadManager()
        self.cmap.block_updates(True)
        # Do not re-apply transform if selected in load file dialog
        HexrdConfig().load_panel_state.clear()
        ilm.read_data([[img]], parent=self.ui)
        if self.instrument == 'PXRDIP':
            ilm.set_state({'trans': [UI_TRANS_INDEX_ROTATE_90]})
            ilm.begin_processing(postprocess=True)
            img = HexrdConfig().image(self.detector, 0)
        self.cmap.block_updates(False)

        self.edited_images[self.detector] = {
            'img': img,
            'height': img.shape[0],
            'width': img.shape[1],
            'tilt': self.it.rotation
        }
        self.clear_boundry()

    def clear(self):
        self.clear_boundry()
        self.enable_widgets(self.ui.detectors, self.ui.load,
                            self.ui.add_template, self.ui.transforms,
                            self.ui.add_transform, enabled=True)
        self.enable_widgets(self.ui.trans, self.ui.rotate, self.ui.button_box,
                            self.ui.save, self.ui.complete, enabled=False)

    def save_file(self):
        self.parent().action_save_imageseries.trigger()

    def check_for_unsaved_changes(self):
        if self.it is None and self.detector in self.completed_detectors:
            return
        msg = ('The currently selected detector has changes that have not been'
               + ' accepted. Keep changes?')
        response = QMessageBox.question(
            self.ui, 'HEXRD', msg, (QMessageBox.Cancel | QMessageBox.Save))
        if response == QMessageBox.Save:
            self.crop_and_mask()

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
        self.cmap.block_updates(True)
        self.check_for_unsaved_changes()

        files = []
        HexrdConfig().rename_detector(self.detector, 'default')
        for key, val in self.edited_images.items():
            HexrdConfig().add_detector(key, 'default')
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'pixels', 'columns', 'value'],
                int(val['width']))
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'pixels', 'rows', 'value'],
                int(val['height']))
            *zx, z = self.detector_defaults[key]['tilt']
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'transform', 'tilt', 'value'],
                [*zx, (z + float(val['tilt']))])
            translation = self.detector_defaults[key]['translation']
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'transform', 'translation', 'value'],
                translation)
            files.append([val['img']])
        HexrdConfig().remove_detector('default')
        self.new_config_loaded.emit()

        ImageLoadManager().read_data(files, parent=self.ui)

        self.reset_panel()
        self.parent().action_show_toolbar.setEnabled(True)
        self.parent().action_show_toolbar.setChecked(True)
        self.cmap.block_updates(False)
