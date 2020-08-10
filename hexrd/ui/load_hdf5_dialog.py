import h5py
import os

from PySide2.QtWidgets import QListWidgetItem

from hexrd.ui.ui_loader import UiLoader

class LoadHDF5Dialog:

  def __init__(self, f, saved_path=None, parent=None):
    self.file = f
    self.paths = []

    self.get_paths(f)

    loader = UiLoader()
    self.ui = loader.load_file('load_hdf5_dialog.ui', parent)
    self.create_list()

  def get_paths(self, f):
    img = h5py.File(f, 'r')
    self.file = img
    img.visit(self.add_path)

  def add_path(self, name):
    if isinstance(self.file[name], h5py.Dataset):
      self.paths.append(name)

  def create_list(self):
    path_list = self.ui.hdf5_paths
    path_list.clear()
    for i in range(len(self.paths)):
      path = QListWidgetItem(self.paths[i], path_list)
      path_list.addItem(path)

  def results(self):
    remember = self.ui.remember_path.isChecked()

    path_list = self.ui.hdf5_paths.currentItem().text()
    if not os.path.split(path_list)[0]:
      group = '/'
    else:
      group = os.path.split(path_list)[0]
    dataset = os.path.split(path_list)[1]

    return group, dataset, remember
