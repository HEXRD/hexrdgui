import os
import yaml
import glob
import re
import numpy as np
import copy

from hexrd import imageseries

from PySide2.QtGui import QCursor
from PySide2.QtCore import QObject, Qt, QPersistentModelIndex, QThreadPool, Signal, QDir
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

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    def __init__(self, parent=None):
        super(LoadPanel, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('load_panel.ui', parent)

        self.ims = HexrdConfig().imageseries_dict
        self.parent_dir = HexrdConfig().images_dir if HexrdConfig().images_dir else ''
        self.unaggregated_images = None

        self.files = []
        self.omega_min = []
        self.omega_max = []
        self.idx = 0
        self.ext = ''

        self.setup_gui()
        self.setup_connections()

    # Setup GUI

    def setup_gui(self):
        self.state = self.setup_processing_options()

        if 'subdirs' in self.state:
            self.ui.subdirectories.setChecked(self.state['subdirs'])
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
        HexrdConfig().detectors_changed.connect(self.detectors_changed)
        HexrdConfig().instrument_config_loaded.connect(self.config_changed)

    def setup_processing_options(self):
        num_dets = len(HexrdConfig().get_detector_names())
        if (not HexrdConfig().load_panel_state
                or not isinstance(HexrdConfig().load_panel_state['trans'], list)):
            HexrdConfig().load_panel_state = {
                'agg': 0,
                'trans': [0 for x in range(num_dets)],
                'dark': [0 for x in range(num_dets)],
                'dark_files': [None for x in range(num_dets)]}

        return HexrdConfig().load_panel_state

    # Handle GUI changes

    def dark_mode_changed(self):
        self.state['dark'][self.idx] = self.ui.darkMode.currentIndex()

        if self.state['dark'][self.idx] == 4:
            self.ui.selectDark.setEnabled(True)
            self.ui.dark_file.setText(
                self.dark_files[self.idx] if self.dark_files[self.idx] else '(No File Selected)')
            self.enable_read()
        else:
            self.ui.selectDark.setEnabled(False)
            self.ui.dark_file.setText(
                '(Using ' + str(self.ui.darkMode.currentText()) + ')')
            self.enable_read()
            self.state['dark_files'][self.idx] = None

    def detectors_changed(self):
        self.ui.detector.clear()
        self.ui.detector.addItems(HexrdConfig().get_detector_names())

    def agg_changed(self):
        self.state['agg'] = self.ui.aggregation.currentIndex()
        if self.ui.aggregation.currentIndex() == 0:
            self.unaggregated_images = None

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
        self.detectors_changed()
        self.ui.file_options.setRowCount(0)
        self.reset_data()
        self.enable_read()
        HexrdConfig().load_panel_state = {}
        self.state = self.setup_processing_options()

    def switch_detector(self):
        self.idx = self.ui.detector.currentIndex()
        if not self.ui.all_detectors.isChecked():
            self.ui.transform.setCurrentIndex(self.state['trans'][self.idx])
            self.ui.darkMode.setCurrentIndex(self.state['dark'][self.idx])
            self.dark_mode_changed()
        self.create_table()

    def apply_to_all_changed(self, checked):
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
        if new_dir and new_dir != self.parent_dir:
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
            selected_files = QDir(self.parent_dir).entryList(QDir.Files)
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
            if not self.ui.subdirectories.isChecked():
                dets = HexrdConfig().get_detector_names()
                ext = os.path.splitext(f)[1]
                if ext.split('.')[1] not in dets:
                    chunks = re.split(r'[_-]', name)
                    for det in dets:
                        if det in chunks:
                            name = name.replace(det, '')
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
            wedge = (data['meta']['ostop'] - data['meta']['ostart']) / self.total_frames[0]
            self.delta.append(wedge)
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
            self.match_dirs_images(fnames)
        else:
            self.match_images(fnames)

        if self.files and self.ext == '.yml':
            self.get_yml_files()

    def find_directories(self):
        # Find all detector directories
        num_det = len(HexrdConfig().get_detector_names())
        for sub_dir in os.scandir(os.path.dirname(self.parent_dir)):
            if (os.path.isdir(sub_dir)
                    and sub_dir.name in HexrdConfig().get_detector_names()):
                self.directories.append(sub_dir.path)
        # Show error if expected detector directories are not found
        if len(self.directories) != num_det:
            dir_names = []
            if len(self.directories) > 0:
                for path in dirs:
                    dir_names.append(os.path.basename(path))
            diff = list(
                set(HexrdConfig().get_detector_names()) - set(dir_names))
            msg = (
                'ERROR - No directory found for the following detectors: \n'
                + str(diff)[1:-1])
            QMessageBox.warning(None, 'HEXRD', msg)
            return

    def match_images(self, fnames):
        dets = HexrdConfig().get_detector_names()
        self.files = [[] for i in range(len(dets))]
        for item in os.scandir(self.parent_dir):
            file_name = os.path.splitext(item.name)[0]
            ext = os.path.splitext(item.name)[1]
            det = ext.split('.')[1] if len(ext.split('.')) > 1 else ''
            if det not in dets:
                chunks = re.split(r'[_-]', file_name)
                for name in dets:
                    if name in chunks:
                        det = name
                        file_name = file_name.replace(name, '')
            if det not in dets:
                continue
            pos = dets.index(det)
            if os.path.isfile(item) and file_name in fnames:
                self.files[pos].append(item.path)
        # Display error if equivalent files are not found for ea. detector
        files_per_det = all(len(fnames) == len(elem) for elem in self.files)
        if not files_per_det:
            msg = ('ERROR - There must be the same number of files for each detector.')
            QMessageBox.warning(None, 'HEXRD', msg)
            self.files = []
            return


    def match_dirs_images(self, fnames):
        dets = HexrdConfig().get_detector_names()
        self.files = [[] for i in range(len(dets))]
        # Find the images with the same name for the remaining detectors
        for i, dir in enumerate(self.directories):
            pos = dets.index(os.path.basename(dir))
            for item in os.scandir(dir):
                fname = os.path.splitext(item.name)[0]
                if os.path.isfile(item) and fname in fnames:
                    self.files[pos].append(item.path)
            # Display error if equivalent files are not found for ea. detector
            if len(self.files[pos]) != len(fnames):
                msg = ('ERROR - Could not find equivalent file(s) in ' + dir)
                QMessageBox.warning(None, 'HEXRD', msg)
                self.files = []
                break

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
        # When this is pressed read in a complete set of data for all detectors.
        # Run the imageseries processing in a background thread and display a
        # loading dialog

        # Create threads and loading dialog
        thread_pool = QThreadPool(self.parent())
        progress_dialog = CalProgressDialog(self.parent())
        progress_dialog.setWindowTitle('Loading Processed Imageseries')

        # Start processing in background
        worker = AsyncWorker(self.process_ims)
        thread_pool.start(worker)

        # On completion load imageseries nd close loading dialog
        worker.signals.result.connect(self.finish_processing_ims)
        worker.signals.finished.connect(progress_dialog.accept)
        progress_dialog.exec_()

    def process_ims(self):
        # Open selected images as imageseries
        det_names = HexrdConfig().get_detector_names()

        if len(self.files[0]) > 1:
            for i, det in enumerate(det_names):
                if self.directories:
                    dirs = self.directories[i]
                else:
                    dirs = self.parent_dir
                ims = ImageFileManager().open_directory(dirs, self.files[i])
                HexrdConfig().imageseries_dict[det] = ims
        else:
            ImageFileManager().load_images(det_names, self.files)

        # Process the imageseries
        self.apply_operations(HexrdConfig().imageseries_dict)
        if self.state['agg']:
            self.display_aggregation(HexrdConfig().imageseries_dict)
        elif '' not in self.omega_min:
            self.add_omega_metadata(HexrdConfig().imageseries_dict)

    def finish_processing_ims(self):
        # Display processed images on completion
        # The setEnabled options will not be needed once the panel
        # is complete - those dialogs will be removed.
        self.parent().action_edit_angles.setEnabled(True)
        self.parent().image_tab_widget.load_images()
        self.new_images_loaded.emit()

    def apply_operations(self, ims_dict):
        # Apply the operations to the imageseries
        for idx, key in enumerate(ims_dict.keys()):
            if self.ui.all_detectors.isChecked():
                idx = self.idx
            ops = []
            if self.state['dark'][idx] != 5:
                if not self.empty_frames and self.state['dark'][idx] == 1:
                    msg = ('ERROR: \n No empty frames set. '
                            + 'No dark subtracion will be performed.')
                    QMessageBox.warning(None, 'HEXRD', msg)
                    return
                else:
                    self.get_dark_op(ops, ims_dict[key], idx)

            if self.state['trans'][idx]:
                self.get_flip_op(ops, idx)

            frames = self.get_range(ims_dict[key])

            ims_dict[key] = imageseries.process.ProcessedImageSeries(
                ims_dict[key], ops, frame_list=frames)

    def get_dark_op(self, oplist, ims, idx):
        # Create or load the dark image if selected
        if self.state['dark'][idx] != 4:
            frames = len(ims)
            if frames > 120:
                frames = 120
            if self.state['dark'][idx] == 0:
                darkimg = imageseries.stats.median(ims, frames)
            elif self.state['dark'][idx] == 1:
                darkimg = imageseries.stats.average(ims, self.empty_frames)
            elif self.state['dark'][idx] == 2:
                darkimg = imageseries.stats.average(ims, frames)
            else:
                darkimg = imageseries.stats.max(ims, frames)
        else:
            darkimg = imageseries.stats.median(
                ImageFileManager().open_file(self.dark_files[idx]))

        oplist.append(('dark', darkimg))

    def get_flip_op(self, oplist, idx):
        # Change the image orientation
        if self.state['trans'][idx] == 0:
            return

        if self.state['trans'][idx] == 1:
            key = 'v'
        elif self.state['trans'][idx] == 2:
            key = 'h'
        elif self.state['trans'][idx] == 3:
            key = 't'
        elif self.state['trans'][idx] == 4:
            key = 'r90'
        elif self.state['trans'][idx] == 5:
            key = 'r180'
        else:
            key = 'r270'

        oplist.append(('flip', key))

    def get_range(self, ims):
        if self.ext == '.yml':
            return range(len(ims))
        else:
            return range(self.empty_frames, len(ims))

    def display_aggregation(self, ims_dict):
        # Remember unaggregated images
        self.unaggregated_images = copy.copy(ims_dict)

        # Display aggregated image from imageseries
        for key in ims_dict.keys():
            if self.state['agg'] == 1:
                ims_dict[key] = [imageseries.stats.max(
                    ims_dict[key], len(ims_dict[key]))]
            elif self.state['agg'] == 2:
                ims_dict[key] = [imageseries.stats.median(
                    ims_dict[key], len(ims_dict[key]))]
            else:
                ims_dict[key] = [imageseries.stats.average(
                    ims_dict[key], len(ims_dict[key]))]

    def add_omega_metadata(self, ims_dict):
        # Add on the omega metadata if there is any
        files = self.yml_files if self.ext == '.yml' else self.files
        for key in ims_dict.keys():
            nframes = len(ims_dict[key])
            omw = imageseries.omega.OmegaWedges(nframes)
            for i in range(len(files[0])):
                nsteps = self.total_frames[i] - self.empty_frames
                start = self.omega_min[i]
                stop = self.omega_max[i]

                # Don't add wedges if defaults are unchanged
                if not (start - stop):
                    return

                omw.addwedge(start, stop, nsteps)

            ims_dict[key].metadata['omega'] = omw.omegas
