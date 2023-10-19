import glob
import os
import numpy as np
import tempfile
import yaml
import h5py

from PySide6.QtWidgets import QMessageBox

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
        HexrdConfig().clear_images(initial)
        detectors = HexrdConfig().detector_names
        iconfig = HexrdConfig().instrument_config
        for det in detectors:
            cols = iconfig['detectors'][det]['pixels']['columns']
            rows = iconfig['detectors'][det]['pixels']['rows']
            shape = (rows, cols)
            data = np.ones(shape, dtype=np.uint8)
            ims = imageseries.open(None, 'array', data=data)

            # Set a flag on these image series indicating that they are
            # dummies.
            ims.is_dummy = True

            HexrdConfig().imageseries_dict[det] = ims

    def load_images(self, detectors, file_names, options=None):
        HexrdConfig().imageseries_dict.clear()
        for name, f in zip(detectors, file_names):
            try:
                if isinstance(f, list):
                    f = f[0]
                ims = self.open_file(f, options)
                HexrdConfig().imageseries_dict[name] = ims
            except (Exception, IOError) as error:
                msg = ('ERROR - Could not read file: \n' + str(error))
                QMessageBox.warning(None, 'HEXRD', msg)
                return

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
            with h5py.File(f, 'r') as data:
                dset = data['/'.join(self.path)][()]

            if dset.ndim < 3:
                # Handle raw two dimesional data
                ims = imageseries.open(None, 'array', data=dset)
            else:
                ims = imageseries.open(
                    f, 'hdf5', path=self.path[0], dataname=self.path[1])
        elif ext == '.npz':
            ims = imageseries.open(f, 'frame-cache')
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
                data = yaml.dump(input_dict).encode('utf-8')
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
            data = yaml.dump(input_dict).encode('utf-8')
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
