import h5py
import os

from PySide2.QtWidgets import QDialog, QListWidgetItem, QMessageBox

from hexrd.ui.ui_loader import UiLoader

class LoadHDF5Dialog:

  def __init__(self, f, saved_path=None, parent=None):
    self.file = f
    self.paths = []

    self.get_paths(f)

    loader = UiLoader()
    self.ui = loader.load_file('load_hdf5_dialog.ui', parent)
    self.create_list()

  def get_HDF4_paths(self, f):
    try:
      from pyhdf.SD import SD, SDC
      img = SD(f, SDC.READ)
      self.file = img
      self.paths = [p for p in img.datasets()]
    except (Exception, IOError) as error:
      msg = ('ERROR - This installation does not support '
              + 'this file type.')
      QMessageBox.warning(self.ui, 'HEXRD', msg)

  def get_HDF5_paths(self, f):
    img = h5py.File(f, 'r')
    self.file = img
    img.visit(self.add_path)

  def get_paths(self, f):
    ext = os.path.splitext(f)[1]
    if ext in ['.h4', '.hdf4', '.hdf']:
      self.get_HDF4_paths(f)
    else:
      self.get_HDF5_paths(f)

  def add_path(self, name):
    if isinstance(self.file[name], h5py.Dataset):
      self.paths.append(name)

  def create_list(self):
    if not self.paths:
      self.ui.reject()
      return

    path_list = self.ui.hdf5_paths
    path_list.clear()
    for i in range(len(self.paths)):
      path = QListWidgetItem(self.paths[i], path_list)
      path_list.addItem(path)

  def results(self):
    remember = self.ui.remember_path.isChecked()

    path_list = self.ui.hdf5_paths.currentItem().text()
    group = os.path.split(path_list)[0]
    dataset = os.path.split(path_list)[1]

    return group, dataset, remember
