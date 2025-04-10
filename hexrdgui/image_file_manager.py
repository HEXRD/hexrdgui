import glob
import os
import numpy as np
import tempfile
import yaml
import h5py

from hexrd import imageseries

from hexrdgui import constants
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.load_hdf5_dialog import LoadHDF5Dialog
from hexrdgui.singletons import Singleton


class ImageFileManager(metaclass=Singleton):

    IMAGE_FILE_EXTS = ['.tiff', '.tif']
    HDF4_FILE_EXTS = ['.h4', '.hdf4', '.hdf']
    HDF5_FILE_EXTS = ['.h5', '.hdf5', '.he5']

    def __init__(self):
        # Clear any previous images
        HexrdConfig().imageseries_dict.clear()

        self.remember = True
        self.path = []

    def load_dummy_images(self, initial=False):
        detector_names = HexrdConfig().detector_names
        iconfig = HexrdConfig().instrument_config

        ims_dict = HexrdConfig().imageseries_dict
        unagg_dict = HexrdConfig().unaggregated_images
        recent_images = HexrdConfig().recent_images
        load_panel_state = HexrdConfig().load_panel_state

        recent_images_modified = False
        load_panel_modified = False

        def get_shape(det_key: str) -> tuple[int, int]:
            # Get the shape of a specific detector
            cols = iconfig['detectors'][det_key]['pixels']['columns']
            rows = iconfig['detectors'][det_key]['pixels']['rows']
            return (rows, cols)

        def make_dummy_ims(shape: tuple[int, int]) -> imageseries.ImageSeries:
            # Make a dummy imageseries
            data = np.ones(shape, dtype=np.uint8)
            ims = imageseries.open(None, 'array', data=data)

            # Set a flag on these image series indicating that they are
            # dummies.
            ims.is_dummy = True
            return ims

        # Check if we will keep any images. If so, we will make
        # the dummy images the same length as the kept images.
        ims_length = 1
        unagg_length = None

        # First, remove any images that no longer belong,
        # or whose shape does not match.
        for det_key, ims in list(ims_dict.items()):
            keep = (
                det_key in detector_names and
                ims.shape == get_shape(det_key)
            )
            if keep:
                # Record the imageseries length and unagg length
                ims_length = len(ims)
                if unagg_dict:
                    unagg_length = len(unagg_dict[det_key])
                continue

            if load_panel_state and not initial:
                s = load_panel_state
                # Need this index for some load panel state items
                ims_idx = list(ims_dict).index(det_key)
                load_panel_modified = True
                for list_key in ('trans', 'dark', 'dark_files'):
                    if len(s.get(list_key, [])) > ims_idx:
                        s[list_key].pop(ims_idx)

                if det_key in s.get('rect', {}):
                    s['rect'].pop(det_key)

            # This image will not be kept
            ims_dict.pop(det_key)
            if unagg_dict and det_key in unagg_dict:
                unagg_dict.pop(det_key)

            if det_key in recent_images:
                recent_images.pop(det_key)
                recent_images_modified = True

        # Now make dummy images for missing ones
        for det_key in detector_names:
            if det_key in ims_dict:
                # Already have an imageseries here
                continue

            det_shape = get_shape(det_key)

            # Make a dummy image
            shape = (ims_length, *det_shape)
            ims_dict[det_key] = make_dummy_ims(shape)

            if unagg_length is not None:
                shape = (unagg_length, *det_shape)
                unagg_dict[det_key] = make_dummy_ims(shape)

        # In case the imageseries length was shorted, truncate
        # the current imageseries index
        if HexrdConfig().current_imageseries_idx >= ims_length:
            HexrdConfig().current_imageseries_idx = ims_length - 1

        if recent_images_modified:
            HexrdConfig().recent_images_changed.emit()

        if load_panel_modified:
            HexrdConfig().load_panel_state_modified.emit()

    def load_images(self, detectors, file_names, options=None):
        HexrdConfig().imageseries_dict.clear()
        for name, f in zip(detectors, file_names):
            if isinstance(f, list):
                f = f[0]
            ims = self.open_file(f, options)
            HexrdConfig().imageseries_dict[name] = ims

        # Save the path if it should be remembered
        if self.remember:
            HexrdConfig().hdf5_path = self.path

    def open_file(self, f, options=None):
        # f could be either a file or numpy array
        ext = os.path.splitext(f)[1] if isinstance(f, str) else None
        if ext is None:
            ims = imageseries.open(None, 'array', data=f)
        elif ext in self.HDF4_FILE_EXTS:
            from pyhdf.SD import SD, SDC
            hdf = SD(f, SDC.READ)
            dset = hdf.select(self.path[1])
            ims = imageseries.open(None, 'array', data=dset)
        elif ext in self.HDF5_FILE_EXTS:
            regular_hdf5 = True
            with h5py.File(f, 'r') as data:
                if data.attrs.get('version') == 'CHESS_EIGER_STREAM_V1':
                    ims_type = 'eiger-stream-v1'
                    registry = (
                        imageseries.load.registry.Registry.adapter_registry
                    )
                    if ims_type not in registry:
                        msg = (
                            '"dectris-compression" must be installed to load '
                            'eiger stream files.\n\n'
                            'Try `pip install dectris-compression`'
                        )
                        raise Exception(msg)

                    ims = imageseries.open(f, 'eiger-stream-v1')
                    regular_hdf5 = False
                else:
                    dset = data['/'.join(self.path)]
                    ndim = dset.ndim
                    if ndim < 3:
                        # Handle raw two dimesional data
                        ims = imageseries.open(None, 'array', data=dset[()])

            if regular_hdf5 and ndim >= 3:
                ims = imageseries.open(
                    f, 'hdf5', path=self.path[0], dataname=self.path[1])
        elif ext == '.npz':
            ims = imageseries.open(f, 'frame-cache', style='npz')
        elif ext == '.fch5':
            ims = imageseries.open(f, 'frame-cache', style='fch5')
        elif ext == '.yml':
            data = yaml.load(open(f))
            form = next(iter(data))
            ims = imageseries.open(f, form)
        else:
            # elif ext in self.IMAGE_FILE_EXTS:
            input_dict = {
                'image-files': {}
            }
            input_dict['image-files']['directory'] = os.path.dirname(f)
            input_dict['image-files']['files'] = glob.escape(os.path.basename(f))
            input_dict['options'] = {} if options is None else options
            input_dict['meta'] = {}
            temp = tempfile.NamedTemporaryFile(delete=False)
            try:
                data = yaml.safe_dump(input_dict).encode('utf-8')
                temp.write(data)
                temp.close()
                ims = imageseries.open(temp.name, 'image-files')
            finally:
                # Ensure the file gets removed from the filesystem
                os.remove(temp.name)
        # else:
        #     ims = imageseries.open(f, 'array')
        return ims

    def open_directory(self, d, files=None, options=None):
        if files is None:
            files = os.listdir(d)

        input_dict = {
            'image-files': {}
        }
        input_dict['image-files']['directory'] = d
        file_str = ''
        for i, f in enumerate(files):
            file_str += os.path.basename(f)
            if i != len(files) - 1:
                file_str += ' '

        input_dict['image-files']['files'] = file_str
        input_dict['options'] = {} if options is None else options
        input_dict['meta'] = {}
        temp = tempfile.NamedTemporaryFile(delete=False)
        try:
            data = yaml.safe_dump(input_dict).encode('utf-8')
            temp.write(data)
            temp.close()
            ims = imageseries.open(temp.name, 'image-files')
        finally:
            # Ensure the file gets removed from the filesystem
            os.remove(temp.name)
        return ims

    def is_hdf(self, extension):
        return self.is_hdf4(extension) or self.is_hdf5(extension)

    def is_hdf4(self, extension):
        return extension in self.HDF4_FILE_EXTS

    def is_hdf5(self, extension):
        return extension in self.HDF5_FILE_EXTS

    def hdf_path_exists(self, f):
        ext = os.path.splitext(f)[1] if isinstance(f, str) else None
        if self.is_hdf5(ext):
            return self.hdf5_path_exists(f)
        elif self.is_hdf4(ext):
            # FIXME: implement an hdf4 path check
            pass
        return False

    def hdf5_path_exists(self, f):
        # If it is a special HDF5 file, just return True
        with h5py.File(f, 'r') as rf:
            if rf.attrs.get('version') == 'CHESS_EIGER_STREAM_V1':
                return True

        all_paths = []
        if HexrdConfig().hdf5_path:
            all_paths.append(HexrdConfig().hdf5_path)
        all_paths += constants.KNOWN_HDF5_PATHS
        with h5py.File(f, 'r') as h5:
            for path, dataname in all_paths:
                if f'{path}/{dataname}' in h5:
                    HexrdConfig().hdf5_path = [path, dataname]
                    self.path = HexrdConfig().hdf5_path
                    return True
            return False

    def path_prompt(self, f):
        path_dialog = LoadHDF5Dialog(f)
        if path_dialog.paths:
            path_dialog.ui.exec()
            group, data, remember = path_dialog.results()
            self.path = [group, data]
            self.remember = remember
            return True
        else:
            return False
