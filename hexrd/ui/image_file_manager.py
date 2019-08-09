import os
import tempfile
import yaml

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

    def __init__(self):
        # Clear any previous images
        HexrdConfig().imageseries_dict.clear()

        self.remember = True
        self.path = []

    def load_images(self, detectors, file_names):
        HexrdConfig().imageseries_dict.clear()
        for name, f in zip(detectors, file_names):
            try:
                ims = self.open_file(f)
                HexrdConfig().imageseries_dict[name] = ims
            except (Exception, IOError) as error:
                msg = ('ERROR - Could not read file: \n' + str(error))
                QMessageBox.warning(None, 'HEXRD', msg)
                return

        # Save the path if it should be remembered
        if self.remember:
            self.path = HexrdConfig().hdf5_path
        else:
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
        ext = os.path.splitext(f)[1]
        if self.is_hdf5(ext):
            ims = imageseries.open(f, 'hdf5',
                path=HexrdConfig().hdf5_path[0],
                dataname=HexrdConfig().hdf5_path[1])
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

    def open_directory(self, d):
        files = os.listdir(d)
        input_dict = {
            'image-files': {}
        }
        input_dict['image-files']['directory'] = os.path.dirname(f)
        file_str = ''
        for i, f in enumerate(files):
            file_str += os.path.basename(f)
            if i != len(files - 1):
                file_str += ' '

        input_dict['image-files']['files'] = file_str
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
        return ims


    def is_hdf5(self, extension):
        hdf5_extensions = ['.h5', '.hdf5', '.he5']
        if extension in hdf5_extensions:
            return True

        return False

    def path_exists(self, f):
        try:
            imageseries.open(f, 'hdf5', path=HexrdConfig().hdf5_path[0],
                dataname=HexrdConfig().hdf5_path[1])
            return True
        except:
            return False

    def path_prompt(self, f):
        path_dialog = LoadHDF5Dialog(f)
        if path_dialog.ui.exec_():
            group, data, remember = path_dialog.results()
            HexrdConfig().hdf5_path = [group, data]
            self.remember = remember
        else:
            return
