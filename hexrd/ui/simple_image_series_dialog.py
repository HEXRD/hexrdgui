import copy
import yaml
import numpy as np
from pathlib import Path

from PySide2.QtGui import QCursor
from PySide2.QtCore import QObject, Qt, QPersistentModelIndex, QDir, Signal
from PySide2.QtWidgets import QTableWidgetItem, QFileDialog, QMenu, QMessageBox

from hexrd.ui.constants import (
    MAXIMUM_OMEGA_RANGE, UI_DARK_INDEX_FILE, UI_DARK_INDEX_NONE,
    UI_AGG_INDEX_NONE, UI_TRANS_INDEX_NONE, YAML_EXTS)
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.load_images_dialog import LoadImagesDialog
from hexrd.ui.ui_loader import UiLoader

"""
    This panel is in charge of loading file(s) for the experiment. It is built
    up in a few steps, and defines how they should be loaded, transformed, and
    attempts to apply intelligent templates to avoid manual entry of everything.
    The final act is to click load data and bring the data set in.
"""


class SimpleImageSeriesDialog(QObject):

    # Emitted when images are loaded
    images_loaded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('simple_image_series_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.update_config_variables()

        self.files = []
        self.omega_min = []
        self.omega_max = []
        self.idx = 0
        self.ext = ''
        self.frame_data = None
        self.progress_dialog = None
        self.current_progress_step = 0
        self.progress_macro_steps = 0
        self.update_allowed = False

        self.setup_gui()
        self.detectors_changed()
        self.setup_connections()

    # Setup GUI

    def setup_gui(self):
        self.setup_processing_options()

        self.ui.all_detectors.setChecked(self.state.get('apply_to_all', False))
        self.ui.aggregation.setCurrentIndex(self.state['agg'])
        self.ui.transform.setCurrentIndex(
            self.state['trans'][self.ui.detector.currentIndex()])
        self.ui.dark_mode.setCurrentIndex(
            self.state['dark'][self.ui.detector.currentIndex()])
        self.dark_files = self.state['dark_files']
        self.ui.reverse_frames.setChecked(
            self.state.get('frames_reversed', False))

        self.dark_mode_changed()
        if not self.parent_dir:
            self.ui.img_directory.setText('No directory set')
        else:
            directory = self.parent_dir
            if Path(directory).is_file():
                directory = str(Path(directory).parent)
            self.ui.img_directory.setText(directory)

        self.ui.file_options.resizeColumnsToContents()

    def setup_connections(self):
        HexrdConfig().detectors_changed.connect(self.config_changed)
        HexrdConfig().load_panel_state_reset.connect(self.config_changed)

        self.ui.image_folder.clicked.connect(self.select_folder)
        self.ui.image_files.clicked.connect(self.select_images)
        self.ui.select_dark.clicked.connect(self.select_dark_img)
        self.ui.read.clicked.connect(self.read_data)

        self.ui.dark_mode.currentIndexChanged.connect(self.dark_mode_changed)
        self.ui.detector.currentIndexChanged.connect(self.switch_detector)
        self.ui.aggregation.currentIndexChanged.connect(self.agg_changed)
        self.ui.transform.currentIndexChanged.connect(self.trans_changed)
        self.ui.all_detectors.toggled.connect(self.apply_to_all_changed)

        self.ui.file_options.customContextMenuRequested.connect(
            self.contextMenuEvent)
        self.ui.file_options.cellChanged.connect(self.omega_data_changed)
        self.ui.file_options.cellChanged.connect(self.enable_aggregations)
        self.ui.update_image_data.clicked.connect(self.update_image_data)
        self.ui.reverse_frames.toggled.connect(self.reverse_frames)

        self.ui.button_box.accepted.connect(self.accept_dialog)
        self.ui.button_box.rejected.connect(self.close_widget)
        self.ui.dockLocationChanged.connect(self.location_changed)

        HexrdConfig().state_loaded.connect(self.state_loaded)

    def setup_processing_options(self):
        self.state = HexrdConfig().load_panel_state
        self.num_dets = len(HexrdConfig().detector_names)
        self.state.setdefault('agg', UI_AGG_INDEX_NONE)
        self.state.setdefault(
            'trans', [UI_TRANS_INDEX_NONE for x in range(self.num_dets)])
        self.state.setdefault(
            'dark', [UI_DARK_INDEX_NONE for x in range(self.num_dets)])
        self.state.setdefault(
            'dark_files', [None for x in range(self.num_dets)])

    def state_loaded(self):
        self.update_config_variables()
        self.setup_gui()

    def update_config_variables(self):
        self.ims = HexrdConfig().imageseries_dict
        self.parent_dir = HexrdConfig().images_dir
        self.state = HexrdConfig().load_panel_state

    # Handle GUI changes

    def dark_mode_changed(self):
        self.state['dark'][self.idx] = self.ui.dark_mode.currentIndex()

        if self.state['dark'][self.idx] == UI_DARK_INDEX_FILE:
            self.ui.select_dark.setEnabled(True)
            if self.dark_files[self.idx]:
                self.ui.dark_file.setText(self.dark_files[self.idx])
            else:
                self.ui.dark_file.setText('(No File Selected)')
            self.enable_read()
        else:
            self.ui.select_dark.setEnabled(False)
            self.ui.dark_file.setText(
                '(Using ' + str(self.ui.dark_mode.currentText()) + ')')
            self.enable_read()
            self.state['dark_files'][self.idx] = None
        self.enable_read()

    def detectors_changed(self):
        self.ui.detector.clear()
        self.dets = HexrdConfig().detector_names
        self.ui.detector.addItems(HexrdConfig().detector_names)

    def agg_changed(self):
        self.state['agg'] = self.ui.aggregation.currentIndex()
        if self.ui.aggregation.currentIndex() == UI_AGG_INDEX_NONE:
            HexrdConfig().reset_unagg_imgs()
        self.enable_read()

    def trans_changed(self):
        self.state['trans'][self.idx] = self.ui.transform.currentIndex()
        self.enable_read()

    def dir_changed(self):
        new_dir = str(Path(self.files[0][0]).parent)
        HexrdConfig().set_images_dir(new_dir)
        self.parent_dir = new_dir
        self.ui.img_directory.setText(str(Path(self.parent_dir).parent))

    def config_changed(self):
        self.setup_gui()
        self.detectors_changed()
        self.ui.file_options.setRowCount(0)
        self.reset_data()
        self.enable_read()

    def switch_detector(self):
        self.idx = self.ui.detector.currentIndex()
        if not self.ui.all_detectors.isChecked():
            self.ui.transform.setCurrentIndex(self.state['trans'][self.idx])
            if self.ui.dark_mode.isEnabled():
                self.ui.dark_mode.setCurrentIndex(self.state['dark'][self.idx])
        self.dark_mode_changed()
        self.create_table()

    def apply_to_all_changed(self, checked):
        HexrdConfig().load_panel_state['apply_to_all'] = checked
        if not checked:
            self.switch_detector()
        elif self.state['dark'][self.idx] == UI_DARK_INDEX_FILE:
            self.select_dark_img(self.dark_files[self.idx])
        self.enable_read()

    def select_folder(self, new_dir=None):
        # This expects to define the root image folder.
        if not new_dir:
            caption = HexrdConfig().images_dirtion = 'Select directory for images'
            new_dir = QFileDialog.getExistingDirectory(
                self.ui, caption, dir=self.parent_dir)

        # Only update if a new directory is selected
        if new_dir and new_dir != HexrdConfig().images_dir:
            self.ui.image_files.setEnabled(True)
            HexrdConfig().set_images_dir(new_dir)
            self.parent_dir = new_dir
            self.dir_changed()

    def select_dark_img(self, selected_file=False):
        if not selected_file:
            # This takes one image to use for dark subtraction.
            caption = HexrdConfig().images_dirtion = 'Select image file'
            selected_file, selected_filter = QFileDialog.getOpenFileName(
                self.ui, caption, dir=self.parent_dir)

        if selected_file:
            if self.ui.all_detectors.isChecked():
                files = ImageLoadManager().match_files([selected_file])
                if files and all(len(f) for f in files):
                    files.sort()
                    for i, f in enumerate(files):
                        self.dark_files[i] = files[i][0]
                        self.state['dark_files'][i] = files[i][0]
                else:
                    self.dark_files = [selected_file] * self.num_dets
                    self.state['dark_files'] = [selected_file] * self.num_dets
                    msg = (
                        f'Unable to match files - using the same dark file'
                        f'for each detector.\nIf this is incorrect please '
                        f'de-select \"Apply Selections to All Detectors\" and '
                        f'select the dark file manually for each detector.')
                    QMessageBox.warning(self.ui, 'HEXRD', msg)
            else:
                self.dark_files[self.idx] = selected_file
                self.state['dark_files'][self.idx] = selected_file

            self.dark_mode_changed()
            self.enable_read()

    def select_images(self):
        # This takes one or more images for a single detector.
        caption = HexrdConfig().images_dirtion = 'Select image file(s)'
        selected_files, _ = QFileDialog.getOpenFileNames(
            self.ui, caption, dir=self.parent_dir)

        if selected_files:
            self.update_allowed = False
            self.reset_data()
            self.load_image_data(selected_files)
            self.create_table()
            self.setup_gui()
            self.enable_read()

    def reset_data(self):
        self.empty_frames = 0
        self.total_frames = []
        self.omega_min = []
        self.omega_max = []
        self.nsteps = []
        self.files = []
        self.frame_data = None

    def clear_from_stack_dialog(self):
        self.reset_data()
        self.ui.file_options.setRowCount(0)
        self.enable_read()

    def enable_aggregations(self, row, column):
        if not (column == 1 or column == 2):
            return

        enable = True
        total_frames = np.sum(self.total_frames) / len(self.dets)
        if total_frames - self.empty_frames < 2:
            enable = False
        self.ui.aggregation.setEnabled(enable)
        for i in [1, 2, 3]:
            self.ui.dark_mode.model().item(i).setEnabled(enable)

        if not enable:
            # Update dark mode settings
            if self.ui.dark_mode.currentIndex() != UI_DARK_INDEX_FILE:
                num_dets = len(HexrdConfig().detector_names)
                self.state['dark'] = (
                    [UI_DARK_INDEX_NONE for x in range(num_dets)])
                self.ui.dark_mode.setCurrentIndex(UI_DARK_INDEX_NONE)
            # Update aggregation settings
            self.state['agg'] = UI_AGG_INDEX_NONE
            self.ui.aggregation.setCurrentIndex(0)

    def load_image_data(self, selected_files):
        self.ext = Path(selected_files[0]).suffix
        has_omega = False

        # Select the path if the file(s) are HDF5
        if (ImageFileManager().is_hdf(self.ext) and not
                ImageFileManager().path_exists(selected_files[0])):
            if ImageFileManager().path_prompt(selected_files[0]) is None:
                return

        tmp_ims = []
        for img in selected_files:
            if self.ext not in YAML_EXTS:
                tmp_ims.append(ImageFileManager().open_file(img))

        self.find_images(selected_files)

        if not self.files:
            return

        if self.ext in YAML_EXTS:
            for yf in self.yml_files[0]:
                ims = ImageFileManager().open_file(yf)
                self.total_frames.append(len(ims) if len(ims) > 0 else 1)

            for f in self.files[0]:
                with open(f, 'r') as raw_file:
                    data = yaml.safe_load(raw_file)
                if 'ostart' in data['meta'] or 'omega' in data['meta']:
                    self.get_yaml_omega_data(data)
                else:
                    self.omega_min = [0] * len(self.yml_files[0])
                    self.omega_max = [0.25] * len(self.yml_files[0])
                self.nsteps = [self.total_frames[0]] * len(self.yml_files[0])
                options = data.get('options', {})
                self.empty_frames = 0
                if isinstance(options, dict):
                    empty = options.get('empty-frames', 0)
                    self.empty_frames = empty
                    self.total_frames = [f-empty for f in self.total_frames]
        else:
            for ims in tmp_ims:
                has_omega = 'omega' in ims.metadata
                self.total_frames.append(len(ims) if len(ims) > 0 else 1)
                if has_omega:
                    self.get_omega_data(ims)
                else:
                    self.omega_min.append(0)
                    self.omega_max.append(0.25)
                self.nsteps.append(len(ims))

    def get_omega_data(self, ims):
        minimum = ims.metadata['omega'][0][0]
        maximum = ims.metadata['omega'][-1][1]

        self.omega_min.append(minimum)
        self.omega_max.append(maximum)

    def get_yaml_omega_data(self, data):
        if 'ostart' in data['meta']:
            self.omega_min.append(data['meta']['ostart'])
            self.omega_max.append(data['meta']['ostop'])
        else:
            if isinstance(data['meta']['omega'], str):
                words = data['meta']['omega'].split()
                fname = Path(self.parent_dir, words[-1])
                nparray = np.load(fname)
            else:
                nparray = data['meta']['omega']

            for idx, vals in enumerate(nparray):
                self.omega_min.append(vals[0])
                self.omega_max.append(vals[1])

    def find_images(self, fnames):
        self.files, manual = ImageLoadManager().load_images(fnames)

        if len(self.files) % len(HexrdConfig().detector_names) != 0:
            msg = ('Please select at least one file for each detector.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            self.files = []
            return

        if manual:
            dialog = LoadImagesDialog(self.files, manual, self.ui.parent())
            if not dialog.exec_():
                self.reset_data()
                return

            detector_names, files = dialog.results()
            image_files = [img for f in self.files for img in f]
            # Make sure files are matched to selected detector
            self.files = [[] for det in HexrdConfig().detector_names]
            for d, f in zip(detector_names, image_files):
                pos = HexrdConfig().detector_names.index(d)
                self.files[pos].append(f)

        self.dir_changed()

        if self.files and self.ext in YAML_EXTS:
            self.get_yml_files()

    def get_yml_files(self):
        self.yml_files = []
        for det in self.files:
            files = []
            for f in det:
                with open(f, 'r') as yml_file:
                    data = yaml.safe_load(yml_file)['image-files']
                raw_images = data['files'].split()
                for raw_image in raw_images:
                    path = Path(self.parent_dir, data['directory'])
                    files.extend([str(p) for p in path.glob(raw_image)])
            self.yml_files.append(files)

    def enable_read(self):
        files = self.yml_files if self.ext in YAML_EXTS else self.files
        enabled = len(files) > 0
        if len(files) and all(len(f) for f in files):
            if (self.state['dark'][self.idx] == UI_DARK_INDEX_FILE
                    and self.dark_files[self.idx] is None):
                enabled = False
        self.ui.read.setEnabled(enabled)

    # Handle table setup and changes

    def create_table(self):
        # Create the table if files have successfully been selected
        if not len(self.files):
            return

        if self.ext in YAML_EXTS:
            table_files = self.yml_files
        else:
            table_files = self.files

        self.ui.file_options.setRowCount(
            len(table_files[self.idx]))

        # Create the rows
        for row in range(self.ui.file_options.rowCount()):
            for column in range(self.ui.file_options.columnCount()):
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignCenter)
                self.ui.file_options.setItem(row, column, item)

        self.ui.file_options.blockSignals(True)
        # Populate the rows
        for i in range(self.ui.file_options.rowCount()):
            curr = table_files[self.idx][i]
            self.ui.file_options.item(i, 0).setText(Path(curr).name)
            self.ui.file_options.item(i, 1).setText(str(self.empty_frames))
            self.ui.file_options.item(i, 2).setText(str(self.total_frames[i]))
            self.ui.file_options.item(i, 3).setText(str(self.omega_min[i]))
            self.ui.file_options.item(i, 4).setText(str(self.omega_max[i]))
            self.ui.file_options.item(i, 5).setText(str(self.nsteps[i]))

            # Set tooltips
            self.ui.file_options.item(i, 0).setToolTip(Path(curr).name)
            self.ui.file_options.item(i, 3).setToolTip('Start must be set')
            self.ui.file_options.item(i, 4).setToolTip('Stop must be set')
            self.ui.file_options.item(i, 5).setToolTip('Number of steps')

            # Don't allow editing of file name or total frames
            self.ui.file_options.item(i, 0).setFlags(Qt.ItemIsEnabled)
            self.ui.file_options.item(i, 2).setFlags(Qt.ItemIsEnabled)
            self.ui.file_options.item(i, 5).setFlags(Qt.ItemIsEnabled)
            # If raw data offset can only be changed in YAML file
            if self.ext in YAML_EXTS:
                self.ui.file_options.item(i, 1).setFlags(Qt.ItemIsEnabled)

        self.ui.file_options.blockSignals(False)
        self.ui.file_options.resizeColumnsToContents()
        self.ui.file_options.sortByColumn(0, Qt.AscendingOrder)

    def contextMenuEvent(self, event):
        # Allow user to delete selected file(s)
        menu = QMenu(self.ui)
        remove = menu.addAction('Remove Selected Files')
        action = menu.exec_(QCursor.pos())

        # Re-selects the current row if context menu is called on disabled cell
        i = self.ui.file_options.indexAt(event)
        self.ui.file_options.selectRow(i.row())

        indices = []
        if action == remove:
            for index in self.ui.file_options.selectedIndexes():
                indices.append(QPersistentModelIndex(index))

            for idx in indices:
                self.ui.file_options.removeRow(idx.row())

            if self.ui.file_options.rowCount():
                for i in range(len(self.files)):
                    self.files[i] = []
                for row in range(self.ui.file_options.rowCount()):
                    f = self.ui.file_options.item(row, 0).text()
            else:
                self.files = []
        self.enable_read()

    def omega_data_changed(self, row, column):
        # Update the values for equivalent files when the data is changed
        self.ui.file_options.blockSignals(True)

        curr_val = self.ui.file_options.item(row, column).text()
        total_frames = self.total_frames[row] - self.empty_frames
        if curr_val != '':
            if column == 1:
                self.empty_frames = int(curr_val)
                for r in range(self.ui.file_options.rowCount()):
                    self.ui.file_options.item(r, column).setText(str(curr_val))
                    new_total = str(self.total_frames[r] - self.empty_frames)
                    self.nsteps[r] = int(new_total)
                    self.ui.file_options.item(r, 5).setText(new_total)
            elif column == 3:
                self.omega_min[row] = float(curr_val)
            elif column == 4:
                self.omega_max[row] = float(curr_val)
            self.ui.update_image_data.setEnabled(self.update_allowed)
            self.enable_read()

        self.ui.file_options.blockSignals(False)

    def confirm_omega_range(self):
        files = self.yml_files if self.ext in YAML_EXTS else self.files
        omega_range = abs(max(self.omega_max) - min(self.omega_min))
        within_range = omega_range <= MAXIMUM_OMEGA_RANGE
        if not within_range:
            msg = (
                f'All omegas must be set and the '
                f'range must be no greater than 360°.')
            QMessageBox.warning(self.ui, 'HEXRD', msg)
        return within_range

    # Process files
    def read_data(self):
        if not self.confirm_omega_range():
            return
        data = {
            'omega_min': self.omega_min,
            'omega_max': self.omega_max,
            'nsteps': self.nsteps,
            'empty_frames': self.empty_frames,
            'total_frames': self.total_frames,
            'reverse_frames': self.ui.reverse_frames.isChecked()
        }
        if self.ui.all_detectors.isChecked():
            data['idx'] = self.idx
        if self.ext in YAML_EXTS:
            data['yml_files'] = self.yml_files
        if self.frame_data is not None:
            data.update(self.frame_data)
        HexrdConfig().load_panel_state.update(copy.copy(self.state))
        ImageLoadManager().read_data(self.files, data, self.parent())
        self.update_allowed = True
        self.ui.read.setDisabled(True)

    def image_stack_loaded(self, data):
        self.files = data['files']
        self.omega_min = data['omega_min']
        self.omega_max = data['omega_max']
        self.nsteps = data['nsteps']
        self.empty_frames = data['empty_frames']
        self.total_frames = data['total_frames']
        self.frame_data = data['frame_data']
        self.reverse_frames(data['reverse_frames'])
        self.create_table()
        self.enable_read()
        self.update_allowed = False
        self.ui.update_image_data.setEnabled(self.update_allowed)

    def update_image_data(self):
        if not self.confirm_omega_range():
            return
        self.ui.update_image_data.setDisabled(True)
        data = {
            'omega_min': self.omega_min,
            'omega_max': self.omega_max,
            'nsteps': self.nsteps,
        }
        ImageLoadManager().add_omega_metadata(
            HexrdConfig().imageseries_dict, data)

    def show(self):
        self.ui.show()

    def accept_dialog(self):
        if self.ui.read.isEnabled():
            self.read_data()
        self.close_widget()

    def reverse_frames(self, state):
        self.state['frames_reversed'] = state
        self.ui.reverse_frames.setChecked(state)
        self.enable_read()

    def close_widget(self):
        if self.ui.isFloating():
            self.ui.close()

    def location_changed(self):
        self.ui.button_box.setVisible(self.ui.isFloating())
