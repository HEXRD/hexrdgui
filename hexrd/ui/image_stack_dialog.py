import copy
import tempfile
import yaml
import numpy as np
from pathlib import Path

from PySide2.QtWidgets import QFileDialog, QMessageBox

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
        self.ui.detectors.addItems(self.detectors)
        self.setup_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.select_directory.clicked.connect(self.select_directory)
        self.ui.omega_from_file.toggled.connect(self.load_omega_from_file)
        self.ui.load_omega_file.clicked.connect(self.select_omega_file)
        self.ui.start_omega.valueChanged.connect(self.update_delta_omega)
        self.ui.stop_omega.valueChanged.connect(self.update_delta_omega)
        self.ui.delta_omega.valueChanged.connect(self.update_stop_omega)
        self.ui.search.clicked.connect(self.search)
        self.ui.empty_frames.valueChanged.connect(self.set_empty_frames)
        self.ui.max_file_frames.valueChanged.connect(self.set_max_file_frames)
        self.ui.max_total_frames.valueChanged.connect(
            self.set_max_total_frames)
        self.ui.detectors.currentTextChanged.connect(self.change_detector)
        self.ui.total_frames.valueChanged.connect(self.update_delta_omega)
        self.ui.files_by_selection.toggled.connect(self.file_selection_changed)
        self.ui.select_files.clicked.connect(self.select_files_manually)

    def setup_gui(self):
        self.ui.current_directory.setText(
            self.state[self.detector]['directory'])
        self.ui.current_directory.setToolTip(
            self.state[self.detector]['directory'])
        self.ui.search_text.setText(self.state[self.detector]['search'])
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
        self.ui.files_by_selection.setChecked(self.state['manual-file'])
        self.ui.files_by_search.setChecked(not self.state['manual-file'])
        self.ui.file_count.setText(str(self.state[self.detector]['file-count']))
        self.ui.apply_to_all.setChecked(self.state['apply-to-all'])

    def setup_state(self):
        if sorted(self.state.get('dets', [])) == sorted(self.detectors):
            self.search()
            self.load_omega_from_file(self.state['omega-from-file'])
            self.file_selection_changed(self.state['manual-file'])
        else:
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
                'manual-file': True,
                'apply-to-all': True,
            }
            for det in self.detectors:
                self.state[det] = {
                    'directory': '',
                    'files': '',
                    'search': '',
                    'file-count': 0,
                }

    def select_directory(self):
        d = QFileDialog.getExistingDirectory(
                self.ui, 'Select directory', self.parent_dir)
        self.state[self.detector]['directory'] = d
        self.parent_dir = d.rsplit('/', 1)[0]
        self.ui.current_directory.setText(d)
        self.ui.current_directory.setToolTip(d)
        if not self.state['manual-file'] and self.state['apply-to-all']:
            self.search_directory(self.detector)

    def search(self):
        if self.ui.apply_to_all.isChecked() and self.ui.search.isChecked():
            for det in self.detectors:
                self.search_directory(det)
        else:
            self.search_directory(self.detector)

    def search_directory(self, det):
        self.state[det]['search'] = self.ui.search_text.text()
        if not (search := self.ui.search_text.text()):
            search = '*'
        if directory := self.state[det]['directory']:
            if files := list(Path(directory).glob(search)):
                self.state[det]['files'] = sorted([str(f) for f in files])
                self.state[det]['file-count'] = len(files)
                ims = ImageFileManager().open_file(str(files[0]))
                frames = len(ims) if len(ims) else 1
                self.ui.total_frames.setValue(frames * len(files))
                self.ui.file_count.setText(str(len(files)))
                self.set_ranges(frames, len(files))
                self.state['total-frames'] = frames

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
            self.ui, 'Select file',
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
        self.setup_gui()
        if self.state['apply-to-all']:
            self.state[det]['search'] = self.ui.search_text.text()

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

    def file_selection_changed(self, checked):
        self.state['manual-file'] = checked
        self.ui.select_files.setEnabled(checked)
        self.ui.search_text.setDisabled(checked)
        self.ui.search.setDisabled(checked)
        self.ui.apply_to_all.setDisabled(checked)

    def select_files_manually(self):
        files, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, 'Select file(s)',
            dir=self.state[self.detector]['directory'])
        self.state[self.detector]['files'] = files
        self.state[self.detector]['file-count'] = len(files)
        self.ui.file_count.setText(str(len(files)))
        ims = ImageFileManager().open_file(files[0])
        frames = len(ims) if len(ims) else 1
        self.ui.total_frames.setValue(frames * len(files))
        self.set_ranges(frames, len(files))
        self.state['total-frames'] = frames

    def get_files(self):
        temp, imgs = [], []
        for det in self.detectors:
            d = self.state[det]['directory']
            t = tempfile.NamedTemporaryFile(suffix='.yml', delete=False)
            input_dict = {
                'image-files': {},
                'options': {},
                'meta': {}
            }
            input_dict['image-files']['directory'] = d
            input_dict['image-files']['files'] = ' '.join(self.state[det]['files'])
            input_dict['options']['empty-frames'] = self.state['empty-frames']
            input_dict['options']['max-frame-file'] = (
                self.state['max-frame-file'])
            input_dict['options']['max-frames'] = self.state['max-frames']
            input_dict['meta']['panel'] = det
            if self.state['omega-from-file']:
                input_dict['meta']['omega'] = (
                    f'! load-numpy-array {self.state["omega"]}')
            else:
                input_dict['meta']['ostart'] = self.state['ostart']
                input_dict['meta']['ostop'] = self.state['ostop']
            data = yaml.dump(input_dict).encode('utf-8')
            t.write(data)
            t.close()
            temp.append([t.name])
            imgs.append(self.state[det]['files'])
        num_files = len(imgs[0])
        return temp, imgs, num_files

    def get_omega_values(self, num_files):
        start = self.state['ostart']
        stop = self.state['ostop']
        delta = self.state['delta']
        frames = self.state['total-frames']
        omega = np.linspace(
            [start, start + delta],
            [stop - delta, stop],
            (frames * num_files))
        return omega[:, 0], omega[:, 1]

    def build_data(self):
        HexrdConfig().stack_state = copy.deepcopy(self.state)
        temp_files, img_files, num_files = self.get_files()
        start, stop = self.get_omega_values(num_files)
        data = {
            'files': temp_files,
            'yml_files': img_files,
            'omega_min': start,
            'omega_max': stop,
            'delta': [self.state['delta']] * num_files,
            'empty_frames': self.state['empty-frames'],
            'total_frames': [self.state['total-frames']] * num_files,
        }
        return data

    def exec_(self):
        while True:
            error = False
            if self.ui.exec_():
                f, d = [], []
                for det in self.detectors:
                    f.append(self.state[det]['file-count'])
                    d.append(self.state[det]['directory'])
                if dets := [det for det in d if not det]:
                    msg = (
                        f'The directory have not been set for '
                        f'the following detector(s):\n{" ".join(dets)}.')
                    QMessageBox.warning(self.ui, 'HEXRD', msg)
                    error = True
                    continue
                elif idx := [i for i, n in enumerate(f) if f[0] != n]:
                    dets = [self.state['dets'][i] for i in idx]
                    msg = (
                        f'The number of files for each detector must match. '
                        f'The following detector(s) do not:\n{" ".join(dets)}')
                    QMessageBox.warning(None, 'HEXRD', msg)
                    error = True
                    continue
                if error:
                    return True
                else:
                    return self.build_data()
