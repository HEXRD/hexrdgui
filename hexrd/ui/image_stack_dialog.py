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

        self.setup_state()
        self.setup_gui()
        self.setup_connections()

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

    def setup_gui(self):
        self.ui.detectors.addItems(self.detectors)
        self.ui.current_directory.setText(self.state[self.detector]['directory'])
        self.ui.current_directory.setToolTip(self.state[self.detector]['directory'])
        self.ui.files.setText(self.state[self.detector]['files'])
        self.ui.empty_frames.setValue(self.state['empty-frames'])
        self.ui.max_file_frames.setValue(self.state['max-frame-file'])
        self.ui.max_total_frames.setValue(self.state['max-frames'])
        self.ui.omega_from_file.setChecked(self.state['omega-from-file'])
        if self.state['omega']:
            self.ui.omega_file.setText(self.state['omega'].split(' ')[-1])
        self.ui.omega_from_file.setChecked(self.state['omega-from-file'])
        self.ui.start_omega.setValue(self.state['ostart'])
        self.ui.delta_omega.setValue(self.state['delta'])
        self.ui.stop_omega.setValue(self.state['ostop'])

    def setup_state(self):
        if sorted(self.state.get('dets', [])) == sorted(self.detectors):
            self.select_files()
            self.load_omega_from_file(self.state['omega-from-file'])
            return

        self.state.clear()
        self.state = {
            'dets': self.detectors,
            'empty-frames': 0,
            'max-frame-file': 0,
            'max-frames': 0,
            'omega': '',
            'ostart': 0,
            'ostop': 360,
            'delta': 360,
            'omega-from-file': False,
            'total-frames': 1,
        }
        for det in self.detectors:
            self.state[det] = {
                'directory': '',
                'files': ''
            }

    def select_directory(self):
        d = QFileDialog.getExistingDirectory(
                self.ui, 'Select directory', self.parent_dir)
        self.state[self.detector]['directory'] = d
        self.parent_dir = d.rsplit('/', 1)[0]
        self.ui.current_directory.setText(d)
        self.ui.current_directory.setToolTip(d)

    def select_files(self):
        self.state[self.detector]['files'] = self.ui.files.text()
        directory = self.state[self.detector]['directory']
        if not (search := self.ui.files.text()):
            search = '*'
        files = list(Path(directory).glob(search))
        if files:
            ims = ImageFileManager().open_file(str(files[0]))
            frames = len(ims) if len(ims) else 1
            self.ui.total_frames.setValue(frames * len(files))
            self.state['total-frames'] = frames
            self.set_ranges(frames, len(files))

    def load_omega_from_file(self, checked):
        self.state['omega-from-file'] = checked
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
        self.state[self.detector]['omega'] = omega_file

    def update_stop_omega(self, delta):
        start = self.ui.start_omega.value()
        frames = self.ui.total_frames.value()
        stop = start + (delta * frames)
        self.ui.stop_omega.setValue(stop)
        self.state['ostop'] = stop
        self.state['delta'] = delta

    def update_delta_omega(self):
        start = self.ui.start_omega.value()
        frames = self.ui.total_frames.value()
        stop = self.ui.stop_omega.value()
        delta = abs(stop - start) / frames
        self.ui.delta_omega.setValue(delta)
        self.state['ostart'] = start
        self.state['ostop'] = stop
        self.state['delta'] = delta

    def set_empty_frames(self, value):
        self.state['empty-frames'] = value

    def set_max_file_frames(self, value):
        self.state['max-frame-file'] = value

    def set_max_total_frames(self, value):
        self.state['max-frames'] = value

    def change_detector(self, det):
        self.detector = det
        self.ui.current_directory.setText(self.state[self.detector]['directory'])
        self.ui.current_directory.setToolTip(self.state[self.detector]['directory'])
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

    def exec_(self):
        if self.ui.exec_():
            return True
