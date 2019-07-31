import fabio
import os
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

    def __init__(self):
        self.remember_path = False

    def load_images(self, detectors, file_names):
        HexrdConfig().images_dict.clear()
        for name, f in zip(detectors, file_names):
            try:
                img, ims = self.open_file(f)
                HexrdConfig().images_dict[name] = img
                if ims is not None:
                    HexrdConfig().imageseries_dict[name] = ims
            except (Exception, IOError) as error:
                msg = ('ERROR - Could not read file: \n' + str(error))
                QMessageBox.warning(None, 'HEXRD', msg)
                return

        if not self.remember_path:
            HexrdConfig().hdf5_path = []

    def open_file(self, f):
        ext = os.path.splitext(f)[1]
        try:
            if self.is_hdf5(ext):
                img = self.handle_hdf5(f)
            elif ext == '.npz':
                img = imageseries.open(f, 'frame-cache')
            elif ext == '.yml':
                data = yaml.load(open(f))
                form = next(iter(data))
                img = imageseries.open(f, form)
            else:
                img = imageseries.open(f, 'array')
            return img[0], img
        except:
            img = fabio.open(f).data
            return img, None

    def is_hdf5(self, extension):
        hdf5_extensions = ['.h5', '.hdf5', '.he5']
        if extension in hdf5_extensions:
            return True

        return False

    def handle_hdf5(self, f):
        try:
            img = imageseries.open(
                f, 'hdf5', path=HexrdConfig().hdf5_path[0],
                dataname=HexrdConfig().hdf5_path[1])
        except:
            path_dialog = LoadHDF5Dialog(f)
            if path_dialog.ui.exec_():
                group, data, remember = path_dialog.results()
                HexrdConfig().hdf5_path = [group, data]
                img = imageseries.open(
                    f, 'hdf5', path=HexrdConfig().hdf5_path[0],
                    dataname=HexrdConfig().hdf5_path[1])
            if remember:
                self.remember_path = True

        return img
