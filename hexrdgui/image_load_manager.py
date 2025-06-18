import copy
import functools
import os
import time
import glob
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox

from hexrd import imageseries
from hexrd.imageseries.omega import OmegaImageSeries

from hexrdgui.async_worker import AsyncWorker
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_file_manager import ImageFileManager
from hexrdgui.progress_dialog import ProgressDialog
from hexrdgui.constants import *
from hexrdgui.singletons import QSingleton


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
    omegas_updated = Signal()

    def __init__(self):
        super().__init__(None)
        self.transformed_images = False

    @property
    def thread_pool(self):
        return QThreadPool.globalInstance()

    @property
    def naming_options(self):
        dets = HexrdConfig().detector_names
        if HexrdConfig().instrument_has_roi:
            groups = [HexrdConfig().detector_group(d) for d in dets]
            dets.extend([g for g in groups if g is not None])
        return dets

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
        dets = HexrdConfig().detector_names
        options = self.naming_options
        # Make sure there are the same number of files for each detector
        # and at least one file per detector
        if (not files[0]
                or len(files) != len(dets)
                or any(len(files[0]) != len(elem) for elem in files)):
            return False
        # If the files do not contain detector or group names they will need
        # to be manually matched
        return all(any(o in f for o in options) for f in files[0])

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
        options = self.naming_options
        # Look for files that match everything except detector name
        # ex: /home/user/images/Ruby_line_ff_000017_ge1.npz becomes
        # /home/user/images/Ruby_line_ff_000017_*.npz
        search = []
        for f in fnames:
            path, fname = os.path.split(f)
            files = [option for option in options if option in fname]
            if not files:
                search.append('/'.join([path, fname]))
            else:
                for o in options:
                    next_file = o.join(fname.rsplit(files[0]))
                    search.append('/'.join([path, next_file]))
        files = self.match_selected_files(options, set(search))
        if not self.check_success(files):
            # Look in sibling directories if the matching files were not
            # found in the current directory.
            revised_search = []
            for f in fnames:
                directory = os.path.basename(os.path.dirname(f))
                for d in dets:
                    revised_search.append(d.join(f.split(directory)))
            files = self.match_selected_files(options, revised_search)
        return files

    def match_selected_files(self, options, search):
        dets = HexrdConfig().detector_names
        files = [[] for i in range(len(dets))]
        results = [f for f in search if glob.glob(f, recursive=True)]
        results = [glob.glob(f, recursive=True) for f in results]
        if results:
            for fname in [fname for f in results for fname in f]:
                path, f = os.path.split(fname)
                matches = [i for i, op in enumerate(options) if op in f]
                if not matches:
                    root, dirs = os.path.split(path)
                    matches = [i for i, op in enumerate(options) if op in dirs]
                if len(matches):
                    for m in matches:
                        idx = m % len(dets)
                        files[idx].append('/'.join([path, f]))
        return files

    def read_data(self, files=None, data=None, ui_parent=None, **kwargs):
        # Make sure this is reset to zero when data is being read
        HexrdConfig().current_imageseries_idx = 0

        # When this is pressed read in a complete set of data for all detectors.
        # Run the imageseries processing in a background thread and display a
        # loading dialog
        if files:
            self.parent_dir = HexrdConfig().images_dir
            self.files = files
            self.empty_frames = data['empty_frames'] if data else 0
        self.data = {} if data is None else data
        self.ui_parent = ui_parent
        self.set_state(kwargs.get('state', None))
        self.begin_processing(kwargs.get('postprocess', False))

    def begin_processing(self, postprocess=False):
        self.update_status = HexrdConfig().live_update
        self.live_update_status.emit(False)

        # Create threads and loading dialog
        progress_dialog = ProgressDialog(self.ui_parent)
        progress_dialog.setWindowTitle('Loading Processed Imageseries')
        self.progress_text.connect(progress_dialog.setLabelText)
        self.progress_dialog = progress_dialog

        # Start processing in background
        worker = AsyncWorker(self.process_ims, postprocess)
        self.thread_pool.start(worker)

        worker.signals.progress.connect(progress_dialog.setValue)
        # On completion load imageseries nd close loading dialog
        worker.signals.result.connect(self.finish_processing_ims)
        worker.signals.error.connect(self.on_process_ims_error)
        worker.signals.finished.connect(progress_dialog.accept)
        progress_dialog.exec()

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
        HexrdConfig().reset_unagg_imgs(new_imgs=True)

        # Now that self.state is set, setup the progress variables
        self.setup_progress_variables()

        # Process the imageseries
        self.apply_operations(HexrdConfig().imageseries_dict)
        if self.data:
            self.add_omega_metadata(HexrdConfig().imageseries_dict)
            if 'agg' in self.state and self.state['agg']:
                self.display_aggregation(HexrdConfig().imageseries_dict)
            else:
                HexrdConfig().reset_unagg_imgs()

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

    def on_process_ims_error(self, error):
        exctype, value, tb = error
        msg = f'Failed to process imageseries.\n\n{value}'
        QMessageBox.critical(None, 'Error', msg)
        HexrdConfig().logger.critical(tb)

    def get_dark_aggr_op(self, ims, idx):
        """
        Returns a tuple of the form (function, frames), where func is the
        function to be applied and frames is the number of frames to aggregate.
        """

        i = self.data['idx'] if 'idx' in self.data else idx
        dark_idx = self.state['dark'][i]
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
        for i, key in enumerate(ims_dict.keys()):
            if self.data:
                idx = self.data['idx'] if 'idx' in self.data else i
                if self.state['dark'][idx] != UI_DARK_INDEX_NONE:
                    if (self.state['dark'][idx] == UI_DARK_INDEX_EMPTY_FRAMES
                            and self.empty_frames == 0):
                        msg = ('ERROR: \n No empty frames set. '
                               + 'No dark subtracion will be performed.')
                        QMessageBox.warning(None, 'HEXRD', msg)
                    else:
                        op = self.get_dark_aggr_op(ims_dict[key], i)
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

        # Apply the operations to the imageseries
        for idx, key in enumerate(ims_dict.keys()):
            ops = []

            # Apply dark subtraction
            if key in dark_images:
                self.get_dark_op(ops, dark_images[key])

            if 'trans' in self.state:
                self.get_flip_op(ops, idx)

            if 'rect' in self.state:
                # Apply the rectangle op *last*, if we have one
                # For dexelas, we need to apply flip operations on the whole
                # images, and then extract the subpanels.
                ops.append(('rectangle', self.state['rect'][key]))

            frames = self.get_range(ims_dict[key])
            if self.state.get('frames_reversed', False):
                frames = frames[::-1]
            ims_dict[key] = imageseries.process.ProcessedImageSeries(
                ims_dict[key], ops, frame_list=frames)

            # Set these directly so no signals get emitted
            det_conf = HexrdConfig().config['instrument']['detectors'][key]
            det_conf['pixels']['columns'] = ims_dict[key].shape[1]
            det_conf['pixels']['rows'] = ims_dict[key].shape[0]

        self.images_transformed.emit()

    def display_aggregation(self, ims_dict):
        self.update_progress_text('Aggregating images...')
        # Remember unaggregated images
        HexrdConfig().set_unagg_images()

        # Make sure this is reset to 0
        HexrdConfig().current_imageseries_idx = 0

        if self.state['agg'] == UI_AGG_INDEX_MAXIMUM:
            agg_func = imageseries.stats.max_iter
        elif self.state['agg'] == UI_AGG_INDEX_MEDIAN:
            agg_func = imageseries.stats.median_iter
        else:
            agg_func = imageseries.stats.average_iter

        f = functools.partial(self.aggregate_images, agg_func=agg_func)

        for (key, aggr_img) in zip(ims_dict.keys(), self.aggregate_images_multithread(f, ims_dict)):
            ims_dict[key] = ImageFileManager().open_file(aggr_img)

    def add_omega_metadata(self, ims_dict, data=None):
        # Add on the omega metadata if there is any
        data = self.data if data is None else data
        files = self.data['yml_files'] if 'yml_files' in self.data else self.files
        for key, ims in ims_dict.items():
            # Only override existing omega metadata if the user has explicitly
            # requested it
            if (
                not len(ims.metadata.get('omega', [])) or
                data.get('override_omegas', False)
            ):
                nframes = data.get('nframes', 0)
                # If number of frames is 0 we assume that no value was provided
                # and we should infer that we are using all frames
                nframes = nframes if nframes > 0 else len(ims)
                omw = imageseries.omega.OmegaWedges(nframes)
                if 'wedges' in data:
                    for wedge in data['wedges']:
                        start, stop, nsteps = wedge
                        omw.addwedge(start, stop, nsteps)
                else:
                    for i in range(len(files[0])):
                        nsteps = data['nsteps'][i]
                        start = data['omega_min'][i]
                        stop = data['omega_max'][i]
                        omw.addwedge(start, stop, nsteps)
                ims_dict[key].metadata['omega'] = omw.omegas
            ims_dict[key] = OmegaImageSeries(ims_dict[key])
        self.omegas_updated.emit()

    def get_range(self, ims):
        start = 0
        nsteps = sum(self.data.get('nsteps', [len(ims)]))
        if len(ims) != nsteps:
            # In the case of hdf5 and npz files we need to handle empty
            # frames via the ProcessedImageSeries 'frame_list' arg to slice
            # the frame list
            start = self.data.get('empty_frames', 0)

        # np.arange() would produce a list of np.uint32, which can overflow.
        # Convert to a list of python integers, which cannot overflow.
        return np.arange(start, len(ims)).tolist()

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
        max_workers = HexrdConfig().max_cpus

        futures = []
        progress_dict = {key: 0.0 for key in ims_dict.keys()}
        with ThreadPoolExecutor(max_workers=max_workers) as tp:
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
        max_workers = HexrdConfig().max_cpus

        futures = []
        progress_dict = {key: 0.0 for key in aggr_op_dict.keys()}
        with ThreadPoolExecutor(max_workers=max_workers) as tp:
            for (key, (op, frames, ims)) in aggr_op_dict.items():
                futures.append(tp.submit(
                    self.aggregate_dark, key, op, ims, frames, progress_dict))

            self.wait_with_progress(futures, progress_dict)

        return {f.result()[0]: f.result()[1] for f in futures}
