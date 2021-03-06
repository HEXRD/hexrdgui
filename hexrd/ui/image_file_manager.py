import os
import numpy as np
import tempfile
import yaml
import h5py

from PySide2.QtWidgets import QMessageBox

from hexrd import imageseries

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.load_hdf5_dialog import LoadHDF5Dialog


class Singleton(type):

    _instance = None

    def __call__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Singleton, cls).__call__(*args, **kwargs)

        return cls._instance


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
            HexrdConfig().imageseries_dict[det] = ims

    def load_images(self, detectors, file_names):
        HexrdConfig().imageseries_dict.clear()
        for name, f in zip(detectors, file_names):
            try:
                if isinstance(f, list):
                    f = f[0]
                ims = self.open_file(f)
                HexrdConfig().imageseries_dict[name] = ims
            except (Exception, IOError) as error:
                msg = ('ERROR - Could not read file: \n' + str(error))
                QMessageBox.warning(None, 'HEXRD', msg)
                return

        # Save the path if it should be remembered
        if self.remember:
            HexrdConfig().hdf5_path = self.path

    def load_aps_imageseries(self, detectors, directory_names):
        HexrdConfig().imageseries_dict.clear()
        for name, d in zip(detectors, directory_names):
            try:
                ims = self.open_directory(d)
                HexrdConfig().imageseries_dict[name] = ims
            except (Exception, IOError) as error:
                msg = ('ERROR - Could not read file: \n' + str(error))
                QMessageBox.warning(None, 'HEXRD', msg)
                return

    def open_file(self, f):
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
            data = h5py.File(f, 'r')
            dset = data['/'.join(self.path)][()]
            if dset.ndim < 3:
                # Handle raw two dimesional data
                ims = imageseries.open(None, 'array', data=dset)
            else:
                data.close()
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
            input_dict['image-files']['files'] = os.path.basename(f)
            input_dict['options'] = {}
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
        hdf_extensions = ['.h4', '.hdf4', '.hdf', '.h5', '.hdf5', '.he5']
        if extension in hdf_extensions:
            return True

        return False

    def path_exists(self, f):
        try:
            path, dataname = HexrdConfig().hdf5_path
            imageseries.open(f, 'hdf5', path=path, dataname=dataname)
            self.path = HexrdConfig().hdf5_path
            return True
        except:
            return False

    def path_prompt(self, f):
        path_dialog = LoadHDF5Dialog(f)
        if path_dialog.paths:
            path_dialog.ui.exec_()
            group, data, remember = path_dialog.results()
            self.path = [group, data]
            self.remember = remember
            return True
        else:
            return False
