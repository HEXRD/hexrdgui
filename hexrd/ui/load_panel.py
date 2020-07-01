import copy
import os
import yaml
import glob
import numpy as np

from PySide2.QtGui import QCursor
from PySide2.QtCore import QObject, Qt, QPersistentModelIndex, QDir, Signal
from PySide2.QtWidgets import QTableWidgetItem, QFileDialog, QMenu, QMessageBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.image_load_manager import ImageLoadManager
from hexrd.ui.ui_loader import UiLoader

"""
    This panel is in charge of loading file(s) for the experiment. It is built
    up in a few steps, and defines how they should be loaded, transformed, and
    attempts to apply intelligent templates to avoid manual entry of everything.
    The final act is to click load data and bring the data set in.
"""


class LoadPanel(QObject):

    # Emitted when images are loaded
    images_loaded = Signal()

    def __init__(self, parent=None):
        super(LoadPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('load_panel.ui', parent)

        self.ims = HexrdConfig().imageseries_dict
        self.parent_dir = HexrdConfig().images_dir if HexrdConfig().images_dir else ''

        self.files = []
        self.omega_min = []
        self.omega_max = []
        self.idx = 0
        self.ext = ''
        self.progress_dialog = None
        self.current_progress_step = 0
        self.progress_macro_steps = 0

        self.setup_gui()
        self.setup_connections()

    # Setup GUI

    def setup_gui(self):
        self.setup_processing_options()

        self.ui.subdirectories.setChecked(self.state.get('subdirs', False))
        self.ui.all_detectors.setChecked(self.state.get('apply_to_all', False))
        self.ui.image_folder.setEnabled(self.ui.subdirectories.isChecked())
        self.ui.aggregation.setCurrentIndex(self.state['agg'])
        self.ui.transform.setCurrentIndex(self.state['trans'][0])
        self.ui.darkMode.setCurrentIndex(self.state['dark'][0])
        self.dark_files = self.state['dark_files']

        self.dark_mode_changed()
        if not self.parent_dir:
            self.ui.img_directory.setText('No directory set')
        else:
            if self.ui.subdirectories.isChecked():
                self.ui.img_directory.setText(os.path.dirname(self.parent_dir))
            else:
                self.ui.img_directory.setText(self.parent_dir)

        self.detectors_changed()
        self.ui.file_options.resizeColumnsToContents()

    def setup_connections(self):
        HexrdConfig().load_panel_state_reset.connect(
            self.setup_processing_options)

        self.ui.image_folder.clicked.connect(self.select_folder)
        self.ui.image_files.clicked.connect(self.select_images)
        self.ui.selectDark.clicked.connect(self.select_dark_img)
        self.ui.read.clicked.connect(self.read_data)
        self.ui.aps_imageseries.toggled.connect(self.munge_data)
        self.ui.subdirectories.toggled.connect(self.subdirs_changed)

        self.ui.darkMode.currentIndexChanged.connect(self.dark_mode_changed)
        self.ui.detector.currentIndexChanged.connect(self.switch_detector)
        self.ui.aggregation.currentIndexChanged.connect(self.agg_changed)
        self.ui.transform.currentIndexChanged.connect(self.trans_changed)
        self.ui.all_detectors.toggled.connect(self.apply_to_all_changed)

        self.ui.file_options.customContextMenuRequested.connect(
            self.contextMenuEvent)
        self.ui.file_options.cellChanged.connect(self.omega_data_changed)

        self.ui.file_options.cellChanged.connect(self.enable_aggregations)

    def setup_processing_options(self):
        self.state = copy.copy(HexrdConfig().load_panel_state)
        num_dets = len(HexrdConfig().detector_names)
        self.state.setdefault('agg', 0)
        self.state.setdefault('trans', [0 for x in range(num_dets)])
        self.state.setdefault('dark', [0 for x in range(num_dets)])
        self.state.setdefault('dark_files', [None for x in range(num_dets)])

    # Handle GUI changes

    def dark_mode_changed(self):
        self.state['dark'][self.idx] = self.ui.darkMode.currentIndex()

        if self.state['dark'][self.idx] == 4:
            self.ui.selectDark.setEnabled(True)
            if self.dark_files[self.idx]:
                self.ui.dark_file.setText(self.dark_files[self.idx])
            else:
                self.ui.dark_file.setText('(No File Selected)')
            self.enable_read()
        else:
            self.ui.selectDark.setEnabled(False)
            self.ui.dark_file.setText(
                '(Using ' + str(self.ui.darkMode.currentText()) + ')')
            self.enable_read()
            self.state['dark_files'][self.idx] = None

    def detectors_changed(self):
        self.ui.detector.clear()
        self.ui.detector.addItems(HexrdConfig().detector_names)

    def agg_changed(self):
        self.state['agg'] = self.ui.aggregation.currentIndex()
        if self.ui.aggregation.currentIndex() == 0:
            ImageLoadManager().reset_unagg_imgs()

    def trans_changed(self):
        self.state['trans'][self.idx] = self.ui.transform.currentIndex()

    def dir_changed(self):
        if self.ui.subdirectories.isChecked():
            self.ui.img_directory.setText(os.path.dirname(self.parent_dir))
        else:
            self.ui.img_directory.setText(self.parent_dir)

    def subdirs_changed(self, checked):
        self.dir_changed()
        self.ui.image_folder.setEnabled(checked)
        self.state['subdirs'] = checked

    def config_changed(self):
        self.setup_processing_options()
        self.detectors_changed()
        self.ui.file_options.setRowCount(0)
        self.reset_data()
        self.enable_read()
        self.setup_gui()

    def switch_detector(self):
        self.idx = self.ui.detector.currentIndex()
        if not self.ui.all_detectors.isChecked():
            self.ui.transform.setCurrentIndex(self.state['trans'][self.idx])
            if self.ui.darkMode.isEnabled():
                self.ui.darkMode.setCurrentIndex(self.state['dark'][self.idx])
                self.dark_mode_changed()
        self.create_table()

    def apply_to_all_changed(self, checked):
        HexrdConfig().load_panel_state['apply_to_all'] = checked
        if not checked:
            self.switch_detector()

    def munge_data(self, state):
        self.ui.subdirectories.setChecked(state)
        self.ui.subdirectories.setDisabled(state)

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

    def select_dark_img(self):
        # This takes one image to use for dark subtraction.
        caption = HexrdConfig().images_dirtion = 'Select image file'
        selected_file, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, caption, dir=self.parent_dir)

        if selected_file:
            self.dark_files[self.idx] = selected_file[0]
            self.state['dark_files'][self.idx] = self.dark_files[self.idx]
            self.dark_mode_changed()
            self.enable_read()

    def select_images(self):
        # This takes one or more images for a single detector.
        if self.ui.aps_imageseries.isChecked():
            files = QDir(self.parent_dir).entryInfoList(QDir.Files)
            selected_files = []
            for file in files:
                selected_files.append(file.absoluteFilePath())
        else:
            caption = HexrdConfig().images_dirtion = 'Select image file(s)'
            selected_files, selected_filter = QFileDialog.getOpenFileNames(
                self.ui, caption, dir=self.parent_dir)

        if selected_files:
            if self.parent_dir is None or not self.ui.subdirectories.isChecked():
                self.select_folder(os.path.dirname(selected_files[0]))
            self.reset_data()
            self.load_image_data(selected_files)
            self.create_table()
            self.enable_read()

    def reset_data(self):
        self.directories = []
        self.empty_frames = 0
        self.total_frames = []
        self.omega_min = []
        self.omega_max = []
        self.delta = []
        self.files = []

    def enable_aggregations(self, row, column):
        if not (column == 1 or column == 2):
            return

        enable = True
        total_frames = np.sum(self.total_frames)
        if total_frames - self.empty_frames < 2:
            enable = False
        self.ui.darkMode.setEnabled(enable)
        self.ui.aggregation.setEnabled(enable)

        if not enable:
            # Update dark mode settings
            num_dets = len(HexrdConfig().detector_names)
            self.state['dark'] = [5 for x in range(num_dets)]
            self.ui.darkMode.setCurrentIndex(5)
            # Update aggregation settings
            self.state['agg'] = 0
            self.ui.aggregation.setCurrentIndex(0)

    def load_image_data(self, selected_files):
        self.ext = os.path.splitext(selected_files[0])[1]
        has_omega = False

        # Select the path if the file(s) are HDF5
        if (ImageFileManager().is_hdf5(self.ext) and not
                ImageFileManager().path_exists(selected_files[0])):
            if ImageFileManager().path_prompt(selected_files[0]) is not None:
                return

        fnames = []
        tmp_ims = []
        for img in selected_files:
            f = os.path.split(img)[1]
            name = os.path.splitext(f)[0]
            if self.ext != '.yml':
                tmp_ims.append(ImageFileManager().open_file(img))

            fnames.append(name)

        self.find_images(fnames)

        if not self.files:
            return

        if self.ext == '.yml':
            for yf in self.yml_files[0]:
                ims = ImageFileManager().open_file(yf)
                self.total_frames.append(len(ims) if len(ims) > 0 else 1)

            for f in self.files[0]:
                with open(f, 'r') as raw_file:
                    data = yaml.safe_load(raw_file)
                if 'ostart' in data['meta'] or 'omega' in data['meta']:
                    self.get_yaml_omega_data(data)
                else:
                    self.omega_min = ['0'] * len(self.yml_files[0])
                    self.omega_max = ['0.25'] * len(self.yml_files[0])
                    self.delta = [''] * len(self.yml_files[0])
                self.empty_frames = data['options']['empty-frames']
        else:
            for ims in tmp_ims:
                has_omega = 'omega' in ims.metadata
                self.total_frames.append(len(ims) if len(ims) > 0 else 1)
                if has_omega:
                    self.get_omega_data(ims)
                else:
                    self.omega_min.append('0')
                    self.omega_max.append('0.25')
                    self.delta.append('')

    def get_omega_data(self, ims):
        minimum = ims.metadata['omega'][0][0]
        size = len(ims.metadata['omega']) - 1
        maximum = ims.metadata['omega'][size][1]

        self.omega_min.append(minimum)
        self.omega_max.append(maximum)
        self.delta.append((maximum - minimum)/len(ims))

    def get_yaml_omega_data(self, data):
        if 'ostart' in data['meta']:
            self.omega_min.append(data['meta']['ostart'])
            self.omega_max.append(data['meta']['ostop'])
            num = data['meta']['ostop'] - data['meta']['ostart']
            denom = self.total_frames[0]
            self.delta.append(num / denom)
        else:
            if isinstance(data['meta']['omega'], str):
                words = data['meta']['omega'].split()
                fname = os.path.join(self.parent_dir, words[2])
                nparray = np.load(fname)
            else:
                nparray = data['meta']['omega']

            for idx, vals in enumerate(nparray):
                self.omega_min.append(vals[0])
                self.omega_max.append(vals[1])
                self.delta.append((vals[1] - vals[0]) / self.total_frames[idx])

    def find_images(self, fnames):
        if (self.ui.subdirectories.isChecked()):
            self.find_directories()
            self.files = ImageLoadManager().match_dirs_images(fnames, self.directories)
        else:
            self.files = ImageLoadManager().match_images(fnames)

        if self.files and self.ext == '.yml':
            self.get_yml_files()

    def find_directories(self):
        # Find all detector directories
        num_det = len(HexrdConfig().detector_names)
        for sub_dir in os.scandir(os.path.dirname(self.parent_dir)):
            if (os.path.isdir(sub_dir)
                    and sub_dir.name in HexrdConfig().detector_names):
                self.directories.append(sub_dir.path)
        # Show error if expected detector directories are not found
        if len(self.directories) != num_det:
            dir_names = []
            if len(self.directories) > 0:
                for path in self.directories:
                    dir_names.append(os.path.basename(path))
            diff = list(
                set(HexrdConfig().detector_names) - set(dir_names))
            msg = (
                'ERROR - No directory found for the following detectors: \n'
                + str(diff)[1:-1])
            QMessageBox.warning(None, 'HEXRD', msg)
            return

    def get_yml_files(self):
        self.yml_files = []
        for det in self.files:
            files = []
            for f in det:
                with open(f, 'r') as yml_file:
                    data = yaml.safe_load(yml_file)['image-files']
                raw_images = data['files'].split()
                for raw_image in raw_images:
                    files.extend(glob.glob(
                        os.path.join(data['directory'], raw_image)))
            self.yml_files.append(files)

    def enable_read(self):
        if (self.ext == '.tiff'
                or '' not in self.omega_min and '' not in self.omega_max):
            if self.state['dark'][self.idx] == 4 and self.dark_files is not None:
                self.ui.read.setEnabled(len(self.files))
                return
            elif self.state['dark'][self.idx] != 4 and len(self.files):
                self.ui.read.setEnabled(True)
                return
        self.ui.read.setEnabled(False)

    # Handle table setup and changes

    def create_table(self):
        # Create the table if files have successfully been selected
        if not len(self.files):
            return

        if self.ext == '.yml':
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

        # Populate the rows
        for i in range(self.ui.file_options.rowCount()):
            curr = table_files[self.idx][i]
            self.ui.file_options.item(i, 0).setText(os.path.split(curr)[1])
            self.ui.file_options.item(i, 1).setText(str(self.empty_frames))
            self.ui.file_options.item(i, 2).setText(str(self.total_frames[i]))
            self.ui.file_options.item(i, 3).setText(str(self.omega_min[i]))
            self.ui.file_options.item(i, 4).setText(str(self.omega_max[i]))
            self.ui.file_options.item(i, 5).setText(str(self.delta[i]))

            # Set tooltips
            self.ui.file_options.item(i, 0).setToolTip(curr)
            self.ui.file_options.item(i, 3).setToolTip('Minimum must be set')
            self.ui.file_options.item(i, 4).setToolTip(
                'Must set either maximum or delta')
            self.ui.file_options.item(i, 5).setToolTip(
                'Must set either maximum or delta')

            # Don't allow editing of file name or total frames
            self.ui.file_options.item(i, 0).setFlags(Qt.ItemIsEnabled)
            self.ui.file_options.item(i, 2).setFlags(Qt.ItemIsEnabled)
            # If raw data offset can only be changed in YAML file
            if self.ext == '.yml':
                self.ui.file_options.item(i, 1).setFlags(Qt.ItemIsEnabled)

        self.ui.file_options.resizeColumnsToContents()

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
                    for i in range(len(self.files)):
                        self.files[i].append(self.directories[i] + f)
            else:
                self.directories = []
                self.files = []
        self.enable_read()

    def omega_data_changed(self, row, column):
        # Update the values for equivalent files when the data is changed
        self.blockSignals(True)

        curr_val = self.ui.file_options.item(row, column).text()
        total_frames = self.total_frames[row] - self.empty_frames
        if curr_val != '':
            if column == 1:
                self.empty_frames = int(curr_val)
                for r in range(self.ui.file_options.rowCount()):
                    self.ui.file_options.item(r, column).setText(str(curr_val))
                self.omega_data_changed(row, 3)
            # Update delta when min or max omega are changed
            elif column == 3:
                self.omega_min[row] = float(curr_val)
                if self.omega_max[row] or self.delta[row]:
                    self.omega_data_changed(row, 4)
            elif column == 4:
                self.omega_max[row] = float(curr_val)
                if self.omega_min[row] != '':
                    diff = abs(self.omega_max[row] - self.omega_min[row])
                    delta = diff / total_frames
                    self.delta[row] = delta
                    self.ui.file_options.item(row, 5).setText(
                        str(round(delta, 2)))
            elif column == 5:
                self.delta[row] = float(curr_val)
                if self.omega_min[row] != '':
                    diff = self.delta[row] * total_frames
                    maximum = self.omega_min[row] + diff
                    self.omega_max[row] = maximum
                    self.ui.file_options.item(row, 4).setText(
                        str(float(maximum)))
            self.enable_read()

        self.blockSignals(False)

    # Process files

    def read_data(self):
        data = {
            'omega_min': self.omega_min,
            'omega_max': self.omega_max,
            'empty_frames': self.empty_frames,
            'total_frames': self.total_frames,
            'directories': self.directories,
            }
        if self.ui.all_detectors.isChecked():
            data['idx'] = self.idx
        if self.ext == '.yml':
            data['yml_files'] = self.yml_files
        HexrdConfig().load_panel_state.update(copy.copy(self.state))
        ImageLoadManager().read_data(self.files, data, self.parent())
        self.images_loaded.emit()
