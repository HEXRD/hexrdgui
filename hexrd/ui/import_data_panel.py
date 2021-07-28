import os
import yaml
import tempfile
import copy
import h5py
from pathlib import Path

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QColorDialog, QFileDialog, QMessageBox
from PySide2.QtGui import QColor

from hexrd import resources as hexrd_resources
from hexrd.instrument import HEDMInstrument
from hexrd.rotations import (
    angleAxisOfRotMat, make_rmat_euler, angles_from_rmat_zxz)

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.interactive_template import InteractiveTemplate
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui import resource_loader
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.constants import (
    UI_TRANS_INDEX_ROTATE_90, UI_TRANS_INDEX_FLIP_HORIZONTALLY, YAML_EXTS)
import hexrd.ui.resources.calibration

from hexrd.ui.utils import convert_tilt_convention, instr_to_internal_dict
from hexrd.ui.create_hedm_instrument import create_hedm_instrument

class ImportDataPanel(QObject):

    # Emitted when new config is loaded
    new_config_loaded = Signal()

    cancel_workflow = Signal()

    enforce_raw_mode = Signal(bool)

    def __init__(self, cmap=None, parent=None):
        super(ImportDataPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('import_data_panel.ui', parent)
        self.it = None
        self.instrument = None
        self.edited_images = {}
        self.completed_detectors = []
        self.canvas = parent.image_tab_widget.image_canvases[0]
        self.detector_defaults = {}
        self.cmap = cmap
        self.detectors = []
        self.defaults = {}
        self.import_in_progress = False

        self.set_default_color()
        self.setup_connections()

    def setup_connections(self):
        self.ui.instruments.currentIndexChanged.connect(
            self.instrument_selected)
        self.ui.load.clicked.connect(self.load_images)
        self.ui.detectors.currentIndexChanged.connect(self.detector_selected)
        self.ui.add_template.clicked.connect(self.add_template)
        self.ui.trans.clicked.connect(self.setup_translate)
        self.ui.rotate.clicked.connect(self.setup_rotate)
        self.ui.add_transform.clicked.connect(self.add_transform)
        self.ui.button_box.accepted.connect(self.crop_and_mask)
        self.ui.button_box.rejected.connect(self.clear)
        self.ui.complete.clicked.connect(self.completed)
        self.ui.bb_height.valueChanged.connect(self.update_bbox_height)
        self.ui.bb_width.valueChanged.connect(self.update_bbox_width)
        self.ui.line_style.currentIndexChanged.connect(
            self.update_template_style)
        self.ui.line_color.clicked.connect(self.pick_line_color)
        self.ui.line_size.valueChanged.connect(self.update_template_style)
        self.ui.cancel.clicked.connect(self.reset_panel)
        self.ui.cancel.clicked.connect(self.cancel_workflow.emit)
        self.ui.select_config.toggled.connect(self.update_config_selection)
        self.ui.default_config.toggled.connect(self.update_config_load)
        self.ui.load_config.clicked.connect(self.load_config)

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
        not_default = (self.ui.current_config.isChecked()
                       or not self.ui.default_config.isChecked())
        if self.config_file and not_default:
            if os.path.splitext(self.config_file)[1] in YAML_EXTS:
                with open(self.config_file, 'r') as f:
                    self.defaults = yaml.load(f, Loader=yaml.FullLoader)
            else:
                try:
                    with h5py.File(self.config_file, 'r') as f:
                        instr = HEDMInstrument(f)
                        self.defaults = instr_to_internal_dict(
                            instr, convert_tilts=False)
                except Exception as e:
                    msg = (
                        f'ERROR - Could not read file: \n {e} \n'
                        f'File must be HDF5 or YAML.')
                    QMessageBox.warning(None, 'HEXRD', msg)
                    return False
        else:
            fname = f'{self.instrument.lower()}_reference_config.yml'
            text = resource_loader.load_resource(hexrd_resources, fname)
            self.defaults = yaml.load(text, Loader=yaml.FullLoader)
        self.detector_defaults['default_config'] = self.defaults
        self.set_detector_options()
        return True

    def set_detector_options(self):
        for det, vals in self.defaults['detectors'].items():
            self.detector_defaults[det] = vals['transform']
            self.detectors.append(det)

        det_list = list(self.detectors)
        self.ui.detectors.clear()
        self.ui.detectors.addItems(det_list)

    def load_config(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Configuration', HexrdConfig().working_dir,
            'HEXRD files (*.hexrd *.yml)')
        self.config_file = selected_file if selected_file else None
        self.ui.config_file_label.setText(os.path.basename(self.config_file))
        self.ui.config_file_label.setToolTip(self.config_file)

    def instrument_selected(self, idx):
        self.detectors.clear()
        self.detector_defaults.clear()
        instruments = {1: 'TARDIS', 2: 'PXRDIP'}
        self.instrument = instruments.get(idx, None)

        if self.instrument is None:
            self.import_in_progress = False
            self.enforce_raw_mode.emit(False)
            self.ui.detectors.setCurrentIndex(0)
            self.enable_widgets(self.ui.file_selection, self.ui.transform_img,
                                enabled=False)
            self.parent().action_show_toolbar.setChecked(True)
        else:
            self.import_in_progress = True
            self.enforce_raw_mode.emit(True)
            self.load_instrument_config()
            self.enable_widgets(self.ui.raw_image, self.ui.config,
                                self.ui.file_selection, enabled=True)
            self.parent().action_show_toolbar.setChecked(False)
            self.ui.config_file_label.setToolTip(
                'Defaults to currently loaded configuration')

    def set_convention(self):
        new_conv = {'axes_order': 'zxz', 'extrinsic': False}
        HexrdConfig().set_euler_angle_convention(new_conv)

    def update_config_selection(self, checked):
        self.ui.default_config.setEnabled(checked)
        if not checked:
            self.enable_widgets(self.ui.load_config, self.ui.config_file_label,
                                enabled=False)
        elif not self.ui.default_config.isChecked():
            self.enable_widgets(self.ui.load_config, self.ui.config_file_label,
                                enabled=True)

    def update_config_load(self, checked):
        self.enable_widgets(self.ui.load_config, self.ui.config_file_label,
                            enabled=not checked)

    def load_instrument_config(self):
        temp = tempfile.NamedTemporaryFile(delete=False, suffix='.hexrd')
        self.config_file = temp.name
        HexrdConfig().save_instrument_config(self.config_file)
        fname = f'default_{self.instrument.lower()}_config.yml'
        with resource_loader.resource_path(
                hexrd.ui.resources.calibration, fname) as f:
            for overlay in HexrdConfig().overlays:
                overlay['visible'] = False
            HexrdConfig().load_instrument_config(f, import_raw=True)

    def config_loaded_from_menu(self):
        if not self.import_in_progress:
            return
        self.load_instrument_config()

    def detector_selected(self, selected):
        self.ui.instrument.setDisabled(selected)
        self.detector = self.ui.detectors.currentText()

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
        if self.instrument == 'PXRDIP':
            HexrdConfig().load_panel_state['trans'] = (
                [UI_TRANS_INDEX_FLIP_HORIZONTALLY])

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

            if self.ui.instrument.isEnabled():
                # Only set the instrument config once
                success = self.get_instrument_defaults()
                if not success:
                    return

            ImageLoadManager().read_data(files, parent=self.ui)
            self.cmap.block_updates(False)
            self.it = InteractiveTemplate(self.parent())

            file_names = [os.path.split(f[0])[1] for f in files]
            self.ui.files_label.setText(', '.join(file_names))
            self.enable_widgets(self.ui.transform_img, self.ui.association,
                                self.ui.finalize, enabled=True)
            self.enable_widgets(self.ui.data, enabled=False)

    def add_transform(self):
        # Prevent color map reset on transform
        self.cmap.block_updates(True)
        self.it.toggle_boundaries(show=False)
        ilm = ImageLoadManager()
        ilm.set_state({'trans': [self.ui.transforms.currentIndex()]})
        ilm.begin_processing(postprocess=True)
        self.cmap.block_updates(False)

        self.ui.transforms.setCurrentIndex(0)

        img = HexrdConfig().image('default', 0)
        if self.detector in self.edited_images.keys():
            # This transform is being done post-processing
            self.edited_images[self.detector]['img'] = img
            self.edited_images[self.detector]['height'] = img.shape[0]
            self.edited_images[self.detector]['width'] = img.shape[1]

        self.it.toggle_boundaries(show=True)
        if self.it.shape is not None:
            self.it.update_image(img)

    def display_bounds(self):
        self.ui.bb_height.blockSignals(True)
        self.ui.bb_width.blockSignals(True)

        y0, y1, x0, x1 = self.it.bounds
        self.ui.bb_width.setMaximum(self.it.img.shape[1])
        self.ui.bb_height.setMaximum(self.it.img.shape[0])

        self.ui.bb_width.setValue(x1)
        self.ui.bb_height.setValue(y1)

        self.ui.bb_height.blockSignals(False)
        self.ui.bb_width.blockSignals(False)

    def add_template(self):
        self.it.create_shape(
            module=hexrd_resources,
            file_name=f'{self.instrument}_{self.detector}_bnd.txt',
            det=self.detector,
            instr=self.instrument)
        self.it.update_image(HexrdConfig().image('default', 0))
        self.update_template_style()

        self.display_bounds()
        self.enable_widgets(self.ui.outline_position,
                            self.ui.outline_appearance, enabled=True)
        self.enable_widgets(self.ui.association, self.ui.file_selection,
                            enabled=False)
        if self.ui.instruments.currentText() != 'TARDIS':
            self.ui.bbox.setEnabled(True)
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
        if self.it.shape is not None:
            self.it.disconnect()
            self.it.connect_translate()

    def setup_rotate(self):
        if self.it.shape is not None:
            self.it.disconnect()
            self.it.connect_rotate()

    def clear_boundry(self):
        if self.it.shape is None:
            return
        self.it.clear()

    def save_boundary_position(self):
        position = {'coords': self.it.template.xy, 'angle': self.it.rotation}
        HexrdConfig().set_boundary_position(
            self.instrument, self.detector, position)
        if self.it.shape:
            self.it.save_boundary(self.outline_color)

    def crop_and_mask(self):
        self.save_boundary_position()
        self.finalize()
        self.completed_detectors.append(self.detector)
        self.enable_widgets(self.ui.association, self.ui.file_selection,
                            self.ui.transform_img, self.ui.complete,
                            enabled=True)
        self.enable_widgets(self.ui.outline_appearance,
                            self.ui.outline_position, enabled=False)
        self.ui.completed_dets.setText(
            ', '.join(set(self.completed_detectors)))

    def finalize(self):
        detectors = self.detector_defaults['default_config'].get(
            'detectors', {})
        det = detectors.setdefault(self.detector, {})
        width = det.setdefault('pixels', {}).get('columns', 0)
        height = det.setdefault('pixels', {}).get('rows', 0)

        if self.instrument == 'PXRDIP':
            # Boundary is currently rotated 90 degrees
            width, height = height, width
        self.it.cropped_image(height, width)

        img, panel_buffer = self.it.masked_image

        self.edited_images[self.detector] = {
            'img': img,
            'tilt': self.it.rotation,
            'panel_buffer': panel_buffer,
        }

        self.it.completed()

    def clear(self):
        self.clear_boundry()
        self.enable_widgets(self.ui.association, self.ui.transform_img,
                            self.ui.file_selection, enabled=True)
        self.enable_widgets(self.ui.outline_position,
                            self.ui.outline_appearance, enabled=False)

    def check_for_unsaved_changes(self):
        if self.it.shape is None and self.detector in self.completed_detectors:
            return
        msg = ('The currently selected detector has changes that have not been'
               + ' accepted. Keep changes?')
        response = QMessageBox.question(
            self.ui, 'HEXRD', msg, (QMessageBox.Cancel | QMessageBox.Save))
        if response == QMessageBox.Save:
            self.crop_and_mask()

    def reset_panel(self):
        self.enforce_raw_mode.emit(False)
        self.clear_boundry()
        self.ui.instruments.setCurrentIndex(0)
        self.ui.detectors.setCurrentIndex(0)
        self.ui.files_label.setText('')
        self.ui.completed_dets.setText('')
        self.edited_images.clear()
        self.enable_widgets(self.ui.association, self.ui.raw_image,
                            self.ui.transform_img, self.ui.outline_appearance,
                            self.ui.outline_position, self.ui.finalize,
                            self.ui.default_config, self.ui.load_config,
                            self.ui.config_file_label, self.ui.config,
                            enabled=False)
        self.enable_widgets(self.ui.data, self.ui.file_selection, enabled=True)
        select_config = self.ui.select_config.isChecked()
        self.ui.default_config.setEnabled(select_config)
        not_default = select_config and not self.ui.default_config.isChecked()
        self.ui.load_config.setEnabled(not_default)
        self.ui.config_file_label.setEnabled(not_default)
        self.ui.config_file_label.setText('No File Selected')
        self.ui.config_file_label.setToolTip(
            'Defaults to currently loaded configuration')
        self.completed_detectors = []
        self.defaults.clear()
        self.config_file = None
        self.import_in_progress = False

    def completed(self):
        self.import_in_progress = False
        self.cmap.block_updates(True)
        self.check_for_unsaved_changes()

        files = []
        detectors = self.detector_defaults['default_config'].setdefault(
            'detectors', {})
        not_set = [d for d in detectors if d not in self.completed_detectors]
        for det in not_set:
            del(self.detector_defaults['default_config']['detectors'][det])

        instr = HEDMInstrument(
            instrument_config=self.detector_defaults['default_config'])
        for det in self.completed_detectors:
            panel = instr.detectors[det]
            # first need the zxz Euler angles from the panel rotation matrix.
            *zx, z = angles_from_rmat_zxz(panel.rmat)
            # convert updated zxz angles to rmat
            tilts = [*zx, (z + float(self.edited_images[det]['tilt']))]
            rmat_updated = make_rmat_euler(tilts, 'zxz', extrinsic=False)
            # convert to angle-axis parameters
            rang, raxs = angleAxisOfRotMat(rmat_updated)
            # update tilt property on panel
            panel.tilt = rang * raxs.flatten()
            panel.panel_buffer = self.edited_images[det]['panel_buffer']
            files.append([self.edited_images[det]['img']])

        temp = tempfile.NamedTemporaryFile(delete=False, suffix='.hexrd')
        try:
            instr.write_config(temp.name, style='hdf5')
            HexrdConfig().load_instrument_config(temp.name)
        finally:
            temp.close()
            Path(temp.name).unlink()

        self.set_convention()
        if self.instrument == 'PXRDIP':
            HexrdConfig().load_panel_state['trans'] = (
                [UI_TRANS_INDEX_ROTATE_90] * len(self.detectors))
        ImageLoadManager().read_data(files, parent=self.ui)

        self.reset_panel()
        self.parent().action_show_toolbar.setEnabled(True)
        self.parent().action_show_toolbar.setChecked(True)
        self.cmap.block_updates(False)
