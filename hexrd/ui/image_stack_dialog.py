import copy
from pathlib import Path

from PySide2.QtWidgets import QFileDialog

from hexrd.ui.constants import MAXIMUM_OMEGA_RANGE
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.image_file_manager import ImageFileManager


class ImageStackDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('image_stack_dialog.ui', parent)

        self.parent_dir = HexrdConfig().working_dir
        self.detectors = HexrdConfig().detector_names
        self.detector = self.detectors[0]
        self.state = copy.copy(HexrdConfig().stack_state)

        self.setup_connections()
        self.select_files()
        self.load_omega_from_file(self.state['omega-from-file'])

    def setup_connections(self):
        self.ui.select_directory.clicked.connect(self.select_directory)
        self.ui.omega_from_file.toggled.connect(self.load_omega_from_file)
        self.ui.load_omega_file.clicked.connect(self.select_omega_file)
        self.ui.start_omega.valueChanged.connect(self.update_delta_omega)
        self.ui.stop_omega.valueChanged.connect(self.update_delta_omega)
        self.ui.delta_omega.valueChanged.connect(self.update_stop_omega)
        self.ui.files.textChanged.connect(self.select_files)
        self.ui.empty_frames.valueChanged.connect(self.set_empty_frames)
        self.ui.max_file_frames.valueChanged.connect(self.set_max_file_frames)
        self.ui.max_total_frames.valueChanged.connect(
            self.set_max_total_frames)
        self.ui.detectors.currentTextChanged.connect(self.change_detector)
        self.ui.total_frames.valueChanged.connect(self.update_delta_omega)

    def select_directory(self):
        d = QFileDialog.getExistingDirectory(
                self.ui, 'Select directory', self.parent_dir)
        self.directory = d
        self.parent_dir = d.rsplit('/', 1)[0]
        self.ui.current_directory.setText(d)
        self.ui.current_directory.setToolTip(d)

    def select_files(self):
        if not (search := self.ui.files.text()):
            search = '*'
        files = list(Path(directory).glob(search))
        if files:
            ims = ImageFileManager().open_file(str(files[0]))
            frames = len(ims) if len(ims) else 1
            self.ui.total_frames.setValue(frames * len(files))
            self.set_ranges(frames, len(files))

    def load_omega_from_file(self, checked):
        self.ui.start_label.setDisabled(checked)
        self.ui.stop_label.setDisabled(checked)
        self.ui.delta_label.setDisabled(checked)
        self.ui.start_omega.setDisabled(checked)
        self.ui.stop_omega.setDisabled(checked)
        self.ui.delta_omega.setDisabled(checked)
        self.ui.frames_label.setDisabled(checked)
        self.ui.total_frames.setDisabled(checked)
        self.ui.load_omega_file.setEnabled(checked)
        self.ui.omega_file.setEnabled(checked)

    def select_omega_file(self):
        omega_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Select file(s)',
            HexrdConfig().images_dir, 'NPY files (*.npy)')
        self.ui.omega_file.setText(omega_file)

    def update_stop_omega(self, delta):
        start = self.ui.start_omega.value()
        frames = self.ui.total_frames.value()
        stop = start + (delta * frames)
        self.ui.stop_omega.setValue(stop)

    def update_delta_omega(self):
        start = self.ui.start_omega.value()
        frames = self.ui.total_frames.value()
        stop = self.ui.stop_omega.value()
        delta = abs(stop - start) / frames
        self.ui.delta_omega.setValue(delta)

    def change_detector(self, det):
        self.detector = det
        self.ui.current_directory.setText(
            self.state[self.detector]['directory'])
        self.ui.current_directory.setToolTip(
            self.state[self.detector]['directory'])
        self.ui.files.setText(self.state[self.detector]['files'])

    def set_ranges(self, frames, num_files):
        self.ui.empty_frames.setMaximum(frames)
        self.ui.max_file_frames.setMaximum(frames)
        self.ui.max_total_frames.setMaximum(frames * num_files)
        self.ui.delta_omega.setMaximum(
            (MAXIMUM_OMEGA_RANGE / (frames * num_files)))
        self.ui.stop_omega.setMinimum(
            (self.ui.start_omega.value() - MAXIMUM_OMEGA_RANGE))
        self.ui.stop_omega.setMaximum(
            (self.ui.start_omega.value() + MAXIMUM_OMEGA_RANGE))
