import copy
import os

from hexrd import imageseries

from PySide2.QtCore import QObject, QThreadPool, Signal
from PySide2.QtWidgets import QMessageBox

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.progress_dialog import ProgressDialog


class Singleton(type(QObject)):

    _instance = None

    def __call__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Singleton, cls).__call__(*args, **kwargs)

        return cls._instance


class ImageLoadManager(QObject, metaclass=Singleton):

    # Emitted when new images are loaded
    update_needed = Signal()
    new_images_loaded = Signal()

    def __init__(self):
        super(ImageLoadManager, self).__init__(None)
        self.unaggregated_images = None

    def check_images(self, fnames):
        dets = HexrdConfig().get_detector_names()
        files = [[] for i in range(len(dets))]
        core_name = os.path.split(fnames[0])[1]
        for det in dets:
            if det in fnames[0]:
                core_name = core_name.replace(det, '')
        matches = 0
        for file in fnames:
            file_name = os.path.split(file)[1]
            for det in dets:
                if (det in file_name) and (core_name == file_name.replace(det, '')):
                    matches += 1
                    pos = dets.index(det)
                    files[pos].append(file)
        # Display error if selected files do not match ea. detector
        if not len(fnames) == matches:
            msg = ('ERROR - Files must contain detector name.')
            QMessageBox.warning(None, 'HEXRD', msg)
            return []
        else:
            return files

    def match_images(self, fnames):
        dets = HexrdConfig().get_detector_names()
        files = [[] for i in range(len(dets))]
        core_name = fnames[0]
        for det in dets:
            if det in fnames[0]:
                core_name = fnames[0].replace(det, '')
        for item in os.scandir(HexrdConfig().images_dir):
            if os.path.isfile(item):
                file_name = os.path.splitext(item.name)[0]
                for det in dets:
                    if (det in file_name) and (core_name == file_name.replace(det, '')):
                        pos = dets.index(det)
                        files[pos].append(item.path)
        # Display error if equivalent files are not found for ea. detector
        files_per_det = all(len(fnames) == len(elem) for elem in files)
        if not files_per_det:
            msg = ('ERROR - There must be the same number of files for each detector.')
            QMessageBox.warning(None, 'HEXRD', msg)
            return []
        else:
            return files

    def match_dirs_images(self, fnames, directories):
        dets = HexrdConfig().get_detector_names()
        files = [[] for i in range(len(dets))]
        # Find the images with the same name for the remaining detectors
        for i, dir in enumerate(directories):
            pos = dets.index(os.path.basename(dir))
            for item in os.scandir(dir):
                fname = os.path.splitext(item.name)[0]
                if os.path.isfile(item) and fname in fnames:
                    files[pos].append(item.path)
            # Display error if equivalent files are not found for ea. detector
            if len(files[pos]) != len(fnames):
                msg = ('ERROR - Could not find equivalent file(s) in ' + dir)
                QMessageBox.warning(None, 'HEXRD', msg)
                return []
                break
        return files

    def read_data(self, files, data=None, parent=None):
        # When this is pressed read in a complete set of data for all detectors.
        # Run the imageseries processing in a background thread and display a
        # loading dialog
        self.parent_dir = HexrdConfig().images_dir
        self.state = HexrdConfig().load_panel_state
        self.parent = parent
        self.files = files
        self.data = data
        self.empty_frames = data['empty_frames'] if data else 0

        # Create threads and loading dialog
        thread_pool = QThreadPool(self.parent)
        progress_dialog = ProgressDialog(self.parent)
        progress_dialog.setWindowTitle('Loading Processed Imageseries')
        self.progress_dialog = progress_dialog

        # Start processing in background
        worker = AsyncWorker(self.process_ims)
        thread_pool.start(worker)

        worker.signals.progress.connect(progress_dialog.setValue)
        # On completion load imageseries nd close loading dialog
        worker.signals.result.connect(self.finish_processing_ims)
        worker.signals.finished.connect(progress_dialog.accept)
        progress_dialog.exec_()

    def process_ims(self, update_progress):
        self.update_progress = update_progress
        self.update_progress(0)

        # Open selected images as imageseries
        self.parent_dir = HexrdConfig().images_dir
        det_names = HexrdConfig().get_detector_names()

        if len(self.files[0]) > 1:
            for i, det in enumerate(det_names):
                if self.data is None:
                    dirs = self.parent_dir
                elif 'directories' in self.data:
                    dirs = self.data['directories'][i]

                ims = ImageFileManager().open_directory(dirs, self.files[i])
                HexrdConfig().imageseries_dict[det] = ims
        else:
            ImageFileManager().load_images(det_names, self.files)

        # Now that self.state is set, setup the progress variables
        self.setup_progress_variables()

        # Process the imageseries
        self.apply_operations(HexrdConfig().imageseries_dict)
        if self.data:
            if self.state['agg']:
                self.display_aggregation(HexrdConfig().imageseries_dict)
            else:
                self.add_omega_metadata(HexrdConfig().imageseries_dict)

        self.update_progress(100)

    def finish_processing_ims(self):
        # Display processed images on completion
        self.update_needed.emit()
        self.new_images_loaded.emit()

    def apply_operations(self, ims_dict):
        # Apply the operations to the imageseries
        for idx, key in enumerate(ims_dict.keys()):
            ops = []
            if self.data:
                if 'idx' in self.data:
                    idx = self.data['idx']
                if self.state['dark'][idx] != 5:
                    if (self.state['dark'][idx] == 1
                            and self.empty_frames == 0):
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

    def display_aggregation(self, ims_dict):
        self.update_progress_text('Aggregating images...')
        # Remember unaggregated images
        self.unaggregated_images = copy.copy(ims_dict)
        # Display aggregated image from imageseries
        for key, ims in ims_dict.items():
            frames = len(ims)
            step = int(frames * len(ims_dict) / 100)
            step = step if step > 2 else 2
            nchunk = int(frames / step)
            if nchunk > frames or nchunk < 1:
                # One last sanity check
                nchunk = frames

            if self.state['agg'] == 1:
                f = imageseries.stats.max_iter
            elif self.state['agg'] == 2:
                f = imageseries.stats.median_iter
            else:
                f = imageseries.stats.average_iter

            for i, img in enumerate(f(ims, nchunk)):
                progress = self.calculate_progress(i, nchunk)
                self.update_progress(progress)

            self.increment_progress_step()
            ims_dict[key] = [img]

    def add_omega_metadata(self, ims_dict):
        # Add on the omega metadata if there is any
        files = self.data['yml_files'] if 'yml_files' in self.data else self.files
        for key in ims_dict.keys():
            nframes = len(ims_dict[key])
            omw = imageseries.omega.OmegaWedges(nframes)
            for i in range(len(files[0])):
                nsteps = self.data['total_frames'][i] - self.empty_frames
                start = self.data['omega_min'][i]
                stop = self.data['omega_max'][i]

                # Don't add wedges if defaults are unchanged
                if not (start - stop):
                    return

                omw.addwedge(start, stop, nsteps)

            ims_dict[key].metadata['omega'] = omw.omegas

    def get_range(self, ims):
        if self.data and 'yml_files' in self.data:
            return range(len(ims))
        else:
            return range(self.empty_frames, len(ims))

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

    def get_dark_op(self, oplist, ims, idx):
        dark_idx = self.state['dark'][idx]
        if dark_idx == 4:
            ims = ImageFileManager().open_file(self.dark_files[idx])

        # Create or load the dark image if selected
        frames = len(ims)
        if dark_idx != 4 and frames > 120:
            frames = 120

        if dark_idx == 0:
            f = imageseries.stats.median_iter
        elif dark_idx == 1:
            f = imageseries.stats.average_iter
            frames = self.empty_frames
        elif dark_idx == 2:
            f = imageseries.stats.average_iter
        elif dark_idx == 3:
            f = imageseries.stats.max_iter
        else:
            f = imageseries.stats.median_iter

        self.update_progress_text('Aggregating dark images...')

        step = int(frames * len(HexrdConfig().imageseries_dict) / 100)
        step = step if step > 2 else 2
        nchunk = int(frames / step)
        if nchunk > frames or nchunk < 1:
            # One last sanity check
            nchunk = frames

        for i, darkimg in enumerate(f(ims, nchunk, nframes=frames)):
            progress = self.calculate_progress(i, nchunk)
            self.update_progress(progress)

        self.increment_progress_step()

        oplist.append(('dark', darkimg))

    def reset_unagg_imgs(self):
        self.unaggregated_images = None

    def setup_progress_variables(self):
        self.current_progress_step = 0

        ims_dict = HexrdConfig().imageseries_dict
        num_ims = len(ims_dict)

        progress_macro_steps = 0
        for idx in range(num_ims):
            if self.data and 'idx' in self.data:
                idx = self.data['idx']

            if self.state['dark'][idx] != 5:
                progress_macro_steps += 1

        if self.state['agg']:
            progress_macro_steps += num_ims

        self.progress_macro_steps = progress_macro_steps

    def calculate_progress(self, i, nchunk):
        numerator = self.current_progress_step + i / nchunk
        return numerator / self.progress_macro_steps * 100

    def increment_progress_step(self):
        self.current_progress_step += 1

    def update_progress_text(self, text):
        if self.progress_dialog is not None:
            self.progress_dialog.setLabelText(text)
