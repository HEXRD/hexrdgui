import copy
import functools
import os
import time
import glob
from concurrent.futures import ThreadPoolExecutor

from hexrd import imageseries

from PySide2.QtCore import QObject, QThreadPool, Signal
from PySide2.QtWidgets import QMessageBox

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.progress_dialog import ProgressDialog
from hexrd.ui.constants import *
from hexrd.ui.singletons import QSingleton


class NoEmptyFramesException(Exception):
    pass


class ImageLoadManager(QObject, metaclass=QSingleton):

    # Emitted when new images are loaded
    progress_text = Signal(str)
    update_needed = Signal()
    new_images_loaded = Signal()
    images_transformed = Signal()
    live_update_status = Signal(bool)
    state_updated = Signal()
    enable_transforms = Signal()

    def __init__(self):
        super(ImageLoadManager, self).__init__(None)
        self.transformed_images = False

    def load_images(self, fnames):
        files = self.explict_selection(fnames)
        manual = False
        if not files:
            files = self.match_files(fnames)
            matched = self.check_success(files)
            if not matched:
                manual = True
                files = [[fname] for fname in fnames]
        return files, manual

    def check_success(self, files):
        detectors = HexrdConfig().detector_names
        # Make sure there are the same number of files for each detector
        # and at least one file per detector
        if (not files[0]
                or len(files) != len(detectors)
                or any(len(files[0]) != len(elem) for elem in files)):
            return False
        # If the files do not contain detector names they will need to
        # be manually matched
        return all(any(d in f for d in detectors) for f in files[0])

    def explict_selection(self, fnames):
        # Assume the user has selected all of the files they would like to load
        dets = HexrdConfig().detector_names
        files = [[] for i in range(len(dets))]
        for fname in fnames:
            path, f = os.path.split(fname)
            matches = [i for i, det in enumerate(dets) if det in f]
            if matches:
                idx = matches[0]
                files[idx].append(fname)
        if self.check_success(files):
            return files
        else:
            return []

    def match_files(self, fnames):
        dets = HexrdConfig().detector_names
        # Look for files that match everything except detector name
        # ex: /home/user/images/Ruby_line_ff_000017_ge1.npz becomes
        # /home/user/images/Ruby_line_ff_000017_*.npz
        search = []
        for f in fnames:
            path, fname = os.path.split(f)
            files = [det for det in dets if det in fname]
            if not files:
                search.append('/'.join([path, fname]))
            else:
                for d in dets:
                    next_file = d.join(fname.rsplit(files[0]))
                    search.append('/'.join([path, next_file]))
        files = self.match_selected_files(fnames, search)
        if not self.check_success(files):
            # Look in sibling directories if the matching files were not
            # found in the current directory.
            revised_search = []
            for f in fnames:
                directory = os.path.basename(os.path.dirname(f))
                for d in dets:
                    revised_search.append(d.join(f.split(directory)))
            files = self.match_selected_files(fnames, revised_search)
        return files

    def match_selected_files(self, fnames, search):
        dets = HexrdConfig().detector_names
        files = [[] for i in range(len(dets))]
        results = [f for f in search if glob.glob(f, recursive=True)]
        results = [glob.glob(f, recursive=True) for f in results]
        if results:
            for fname in [fname for f in results for fname in f]:
                path, f = os.path.split(fname)
                matches = [i for i, det in enumerate(dets) if det in f]
                if not matches:
                    root, dirs = os.path.split(path)
                    matches = [i for i, det in enumerate(dets) if det in dirs]
                if len(matches):
                    idx = matches[0]
                    files[idx].append('/'.join([path, f]))
        return files

    def read_data(self, files, data=None, parent=None):
        # When this is pressed read in a complete set of data for all detectors.
        # Run the imageseries processing in a background thread and display a
        # loading dialog
        self.parent_dir = HexrdConfig().images_dir
        self.set_state()
        self.parent = parent
        self.files = files
        self.data = {} if data is None else data
        self.empty_frames = data['empty_frames'] if data else 0

        self.begin_processing()

    def begin_processing(self, postprocess=False):
        self.update_status = HexrdConfig().live_update
        self.live_update_status.emit(False)

        # Create threads and loading dialog
        thread_pool = QThreadPool(self.parent)
        progress_dialog = ProgressDialog(self.parent)
        progress_dialog.setWindowTitle('Loading Processed Imageseries')
        self.progress_text.connect(progress_dialog.setLabelText)
        self.progress_dialog = progress_dialog

        # Start processing in background
        worker = AsyncWorker(self.process_ims, postprocess)
        thread_pool.start(worker)

        worker.signals.progress.connect(progress_dialog.setValue)
        # On completion load imageseries nd close loading dialog
        worker.signals.result.connect(self.finish_processing_ims)
        worker.signals.finished.connect(progress_dialog.accept)
        progress_dialog.exec_()

    def set_state(self, state=None):
        if state is None:
            self.state = HexrdConfig().load_panel_state
        else:
            self.state = state
        self.state_updated.emit()

    def process_ims(self, postprocess, update_progress):
        self.update_progress = update_progress
        self.update_progress(0)

        if not postprocess:
            # Open selected images as imageseries
            self.parent_dir = HexrdConfig().images_dir
            det_names = HexrdConfig().detector_names

            options = {
                'empty-frames': self.data.get('empty_frames', 0),
                'max-file-frames': self.data.get('max_file_frames', 0),
                'max-total-frames': self.data.get(
                    'max_total_frames', 0),
            }

            if len(self.files[0]) > 1:
                for i, det in enumerate(det_names):
                    dirs = os.path.dirname(self.files[i][0])
                    ims = ImageFileManager().open_directory(dirs, self.files[i], options)
                    HexrdConfig().imageseries_dict[det] = ims
            else:
                ImageFileManager().load_images(det_names, self.files, options)
        HexrdConfig().reset_unagg_imgs()

        # Now that self.state is set, setup the progress variables
        self.setup_progress_variables()

        # Process the imageseries
        self.apply_operations(HexrdConfig().imageseries_dict)
        if self.data:
            self.add_omega_metadata(HexrdConfig().imageseries_dict)
            if 'agg' in self.state and self.state['agg']:
                self.display_aggregation(HexrdConfig().imageseries_dict)

        self.update_progress(100)

    def finish_processing_ims(self):
        # Display processed images on completion
        self.new_images_loaded.emit()
        self.enable_transforms.emit()
        self.live_update_status.emit(self.update_status)
        if not self.update_status:
            self.update_needed.emit()
        if self.transformed_images:
            HexrdConfig().deep_rerender_needed.emit()

    def get_dark_aggr_op(self, ims, idx):
        """
        Returns a tuple of the form (function, frames), where func is the
        function to be applied and frames is the number of frames to aggregate.
        """
        dark_idx = self.state['dark'][idx]
        if dark_idx == UI_DARK_INDEX_FILE:
            ims = ImageFileManager().open_file(self.state['dark_files'][idx])

        # Create or load the dark image if selected
        frames = len(ims)
        if dark_idx != UI_DARK_INDEX_FILE and frames > 120:
            frames = 120

        if dark_idx == UI_DARK_INDEX_MEDIAN:
            f = imageseries.stats.median_iter
        elif dark_idx == UI_DARK_INDEX_EMPTY_FRAMES:
            f = imageseries.stats.average_iter
            frames = self.empty_frames
        elif dark_idx == UI_DARK_INDEX_AVERAGE:
            f = imageseries.stats.average_iter
        elif dark_idx == UI_DARK_INDEX_MAXIMUM:
            f = imageseries.stats.max_iter
        else:
            f = imageseries.stats.median_iter

        return (f, frames, ims)

    def get_dark_aggr_ops(self, ims_dict):
        """
        Returns a dict of tuples of the form (function, frames), where func is the
        function to be applied and frames is the number of frames to aggregate.
        The key is the detector name.
        """
        ops = {}
        for idx, key in enumerate(ims_dict.keys()):
            if self.data:
                if 'idx' in self.data:
                    idx = self.data['idx']
                if self.state['dark'][idx] != UI_DARK_INDEX_NONE:
                    if (self.state['dark'][idx] == UI_DARK_INDEX_EMPTY_FRAMES
                            and self.empty_frames == 0):
                        msg = ('ERROR: \n No empty frames set. '
                               + 'No dark subtracion will be performed.')
                        QMessageBox.warning(None, 'HEXRD', msg)
                    else:
                        op = self.get_dark_aggr_op(ims_dict[key], idx)
                        ops[key] = op

        return ops

    def apply_operations(self, ims_dict):
        # First perform dark aggregation if we need to
        dark_aggr_ops = {}
        if 'dark' in self.state:
            dark_aggr_ops = self.get_dark_aggr_ops(ims_dict)

        # Now run the dark aggregation
        dark_images = {}
        if dark_aggr_ops:
            self.update_progress_text('Aggregating dark images...')
            dark_images = self.aggregate_dark_multithread(dark_aggr_ops)

        if 'zero-min' in self.state:
            # Get the minimum over all the detectors
            all_mins = [imageseries.stats.min(x) for x in ims_dict.values()]
            global_min = min([x.min() for x in all_mins])

        # Apply the operations to the imageseries
        for idx, key in enumerate(ims_dict.keys()):
            ops = []
            # Apply dark subtraction
            if key in dark_images:
                self.get_dark_op(ops, dark_images[key])
            if 'trans' in self.state:
                self.get_flip_op(ops, idx)
            if 'rect' in self.state:
                ops.append(('rectangle', self.state['rect'][idx]))
            if 'zero-min' in self.state:
                ops.append(('add', -global_min))

            frames = self.get_range(ims_dict[key])
            ims_dict[key] = imageseries.process.ProcessedImageSeries(
                ims_dict[key], ops, frame_list=frames)
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'pixels', 'columns', 'value'],
                ims_dict[key].shape[1])
            HexrdConfig().set_instrument_config_val(
                ['detectors', key, 'pixels', 'rows', 'value'],
                ims_dict[key].shape[0])
        self.images_transformed.emit()

    def display_aggregation(self, ims_dict):
        self.update_progress_text('Aggregating images...')
        # Remember unaggregated images
        HexrdConfig().set_unagg_images()

        if self.state['agg'] == UI_AGG_INDEX_MAXIMUM:
            agg_func = imageseries.stats.max_iter
        elif self.state['agg'] == UI_AGG_INDEX_MEDIAN:
            agg_func = imageseries.stats.median_iter
        else:
            agg_func = imageseries.stats.average_iter

        f = functools.partial(self.aggregate_images, agg_func=agg_func)

        for (key, aggr_img) in zip(ims_dict.keys(), self.aggregate_images_multithread(f, ims_dict)):
            ims_dict[key] = ImageFileManager().open_file(aggr_img)

    def add_omega_metadata(self, ims_dict):
        # Add on the omega metadata if there is any
        files = self.data['yml_files'] if 'yml_files' in self.data else self.files
        for key, ims in ims_dict.items():
            nframes = len(ims)
            omw = imageseries.omega.OmegaWedges(nframes)
            if 'wedges' in self.data:
                for wedge in self.data['wedges']:
                    start, stop, nsteps = wedge
                    omw.addwedge(start, stop, nsteps)
            else:
                for i in range(len(files[0])):
                    nsteps = self.data['nsteps'][i]
                    start = self.data['omega_min'][i]
                    stop = self.data['omega_max'][i]

                    omw.addwedge(start, stop, nsteps)
            ims_dict[key].metadata['omega'] = omw.omegas

    def get_range(self, ims):
        start = 0
        if len(ims) != self.data.get('total_frames', [len(ims)])[0]:
            # In the case of hdf5 and npz files we need to handle empty
            # frames via the ProcessedImageSeries 'frame_list' arg to slice
            # the frame list
            start = self.data.get('empty_frames', 0)
        return range(start, len(ims))

    def get_flip_op(self, oplist, idx):
        if self.data:
            idx = self.data.get('idx', idx)
        # Change the image orientation
        if self.state['trans'][idx] == UI_TRANS_INDEX_NONE:
            return

        self.transformed_images = True
        if self.state['trans'][idx] == UI_TRANS_INDEX_FLIP_VERTICALLY:
            key = 'v'
        elif self.state['trans'][idx] == UI_TRANS_INDEX_FLIP_HORIZONTALLY:
            key = 'h'
        elif self.state['trans'][idx] == UI_TRANS_INDEX_TRANSPOSE:
            key = 't'
        elif self.state['trans'][idx] == UI_TRANS_INDEX_ROTATE_90:
            key = 'r90'
        elif self.state['trans'][idx] == UI_TRANS_INDEX_ROTATE_180:
            key = 'r180'
        else:
            key = 'r270'

        oplist.append(('flip', key))

    def get_dark_op(self, oplist, dark):
        oplist.append(('dark', dark))

    def setup_progress_variables(self):
        self.current_progress_step = 0

        ims_dict = HexrdConfig().imageseries_dict
        num_ims = len(ims_dict)

        progress_macro_steps = 0
        for idx in range(num_ims):
            if self.data and 'idx' in self.data:
                idx = self.data['idx']

            if ('dark' in self.state and
                    self.state['dark'][idx] != UI_DARK_INDEX_NONE):
                progress_macro_steps += 1

        if 'agg' in self.state and self.state['agg']:
            progress_macro_steps += num_ims

        self.progress_macro_steps = progress_macro_steps

    def increment_progress_step(self):
        self.current_progress_step += 1

    def update_progress_text(self, text):
        self.progress_text.emit(text)

    def calculate_nchunk(self, num_ims, frames):
        """
        Calculate the number of chunks

         :param num_ims: The number of image series.
         :param frames: The number of frames being processed.
        """
        step = int(frames * num_ims / 100)
        step = step if step > 2 else 2
        nchunk = int(frames / step)
        if nchunk > frames or nchunk < 1:
            # One last sanity check
            nchunk = frames

        return nchunk

    def aggregate_images(self, key, ims, agg_func, progress_dict):
        frames = len(ims)
        num_ims = len(progress_dict)
        nchunk = self.calculate_nchunk(num_ims, frames)

        for i, img in enumerate(agg_func(ims, nchunk)):
            progress_dict[key] = (i + 1) / nchunk

        return [img]

    def wait_with_progress(self, futures, progress_dict):
        """
        Wait for futures to be resolved and update progress using the progress
        dict.
        """
        n_macro_steps = self.progress_macro_steps
        orig_progress = self.progress_dialog.value()
        while not all([f.done() for f in futures]):
            total = sum([v for v in progress_dict.values()])
            progress = total * 100 / n_macro_steps
            self.update_progress(orig_progress + progress)
            time.sleep(0.1)

    def aggregate_images_multithread(self, f, ims_dict):
        """
        Use ThreadPoolExecutor to aggregate images

        :param f: The aggregation function
        :param ims_dict: The imageseries to aggregate
        """
        futures = []
        progress_dict = {key: 0.0 for key in ims_dict.keys()}
        with ThreadPoolExecutor() as tp:
            for (key, ims) in ims_dict.items():
                futures.append(tp.submit(f, key, ims, progress_dict=progress_dict))

            self.wait_with_progress(futures, progress_dict)

        return [f.result() for f in futures]

    def aggregate_dark(self, key, func, ims, frames, progress_dict):
        """
        Generate aggregated dark image.

        :param key: The detector
        :param func: The aggregation function
        :param ims: The imageseries
        :param frames: The number of frames to use
        :param progress_dict: Dict for progress reporting
        """
        nchunk = self.calculate_nchunk(len(HexrdConfig().imageseries_dict), frames)

        for i, darkimg in enumerate(func(ims, nchunk, nframes=frames)):
            progress_dict[key] = (i + 1) / nchunk

        return (key, darkimg)

    def aggregate_dark_multithread(self, aggr_op_dict):
        """
        Use ThreadPoolExecutor to dark aggregation. Returns a dict mapping the
        detector name to dark image.

        :param aggr_op_dict: A dict mapping the detector name to a tuple of the form
                            (func, frames, ims), where func is the function to use to do
                            the aggregation, frames is number of images to aggregate, and
                            ims is the image series to perform the aggregation on.
        """
        futures = []
        progress_dict = {key: 0.0 for key in aggr_op_dict.keys()}
        with ThreadPoolExecutor() as tp:
            for (key, (op, frames, ims)) in aggr_op_dict.items():
                futures.append(tp.submit(
                    self.aggregate_dark, key, op, ims, frames, progress_dict))

            self.wait_with_progress(futures, progress_dict)

        return {f.result()[0]: f.result()[1] for f in futures}

