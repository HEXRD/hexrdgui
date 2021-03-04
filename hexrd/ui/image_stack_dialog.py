import copy
import tempfile
import yaml
import numpy as np
from pathlib import Path

from PySide2.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem

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
        self.ui.search.clicked.connect(self.search)
        self.ui.empty_frames.valueChanged.connect(self.set_empty_frames)
        self.ui.max_file_frames.valueChanged.connect(self.set_max_file_frames)
        self.ui.max_total_frames.valueChanged.connect(
            self.set_max_total_frames)
        self.ui.detectors.currentTextChanged.connect(self.change_detector)
        self.ui.files_by_selection.toggled.connect(self.file_selection_changed)
        self.ui.select_files.clicked.connect(self.select_files_manually)
        self.ui.add_wedge.clicked.connect(self.add_wedge)
        self.ui.clear_wedges.clicked.connect(self.clear_wedges)
        self.ui.omega_wedges.cellChanged.connect(self.update_wedges)
        self.ui.all_detectors.toggled.connect(self.detector_selection)
        self.ui.search_directories.clicked.connect(self.search_directories)

    def setup_gui(self):
        self.ui.current_directory.setText(
            self.state[self.detector]['directory'])
        self.ui.current_directory.setToolTip(
            self.state[self.detector]['directory'])
        self.ui.search_text.setText(self.state[self.detector]['search'])
        self.ui.total_frames.setValue(
            self.state['total_frames'] * int(self.state[self.detector]['file_count']))
        self.ui.empty_frames.setValue(self.state['empty_frames'])
        self.ui.max_file_frames.setValue(self.state['max_frame_file'])
        self.ui.max_total_frames.setValue(self.state['max_frames'])
        self.ui.omega_from_file.setChecked(self.state['omega_from_file'])
        if self.state['omega']:
            self.ui.omega_file.setText(self.state['omega'].split(' ')[-1])
        self.ui.omega_from_file.setChecked(self.state['omega_from_file'])
        self.ui.files_by_selection.setChecked(self.state['manual_file'])
        self.ui.files_by_search.setChecked(not self.state['manual_file'])
        self.ui.file_count.setText(
            str(self.state[self.detector]['file_count']))
        self.ui.apply_to_all.setChecked(self.state['apply_to_all'])
        self.ui.all_detectors.setChecked(self.state['all_detectors'])
        if self.state['wedges']:
            self.set_wedges()

    def setup_state(self):
        if sorted(self.state.get('dets', [])) == sorted(self.detectors):
            self.load_omega_from_file(self.state['omega_from_file'])
            self.file_selection_changed(self.state['manual_file'])
            self.detector_selection(self.state['all_detectors'])
        else:
            self.state.clear()
            self.state = {
                'all_detectors': True,
                'dets': self.detectors,
                'empty_frames': 0,
                'max_frame_file': 0,
                'max_frames': 0,
                'omega': '',
                'omega_from_file': True,
                'total_frames': 1,
                'manual_file': True,
                'apply_to_all': True,
                'wedges': []
            }
            for det in self.detectors:
                self.state[det] = {
                    'directory': '',
                    'files': '',
                    'search': '',
                    'file_count': 0,
                }

    def set_wedges(self):
        for i, wedge in enumerate(self.state['wedges']):
            self.ui.omega_wedges.insertRow(i)
            for j, value in enumerate(wedge):
                self.ui.omega_wedges.setItem(
                    i, j, QTableWidgetItem(str(value)))

    def select_directory(self):
        d = QFileDialog.getExistingDirectory(
                self.ui, 'Select directory', self.parent_dir)
        self.state[self.detector]['directory'] = d
        self.parent_dir = d.rsplit('/', 1)[0]
        self.ui.current_directory.setText(d)
        self.ui.current_directory.setToolTip(d)
        if not self.state['manual_file'] and self.state['apply_to_all']:
            self.search_directory(self.detector)

    def search(self):
        if self.ui.apply_to_all.isChecked() and self.ui.files_by_search.isChecked():
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
                self.state[det]['file_count'] = len(files)
                ims = ImageFileManager().open_file(str(files[0]))
                frames = len(ims) if len(ims) else 1
                self.ui.total_frames.setValue(
                    (frames - self.state['empty_frames']) * len(files))
                self.ui.file_count.setText(str(len(files)))
                self.set_ranges(frames, len(files))
                self.state['total_frames'] = frames

    def load_omega_from_file(self, checked):
        self.state['omega_from_file'] = checked
        self.ui.omega_wedges.setDisabled(checked)
        self.ui.add_wedge.setDisabled(checked)
        self.ui.clear_wedges.setDisabled(checked)
        self.ui.load_omega_file.setEnabled(checked)
        self.ui.omega_file.setEnabled(checked)

    def detector_selection(self, checked):
        self.state['all_detectors'] = checked
        self.ui.detector_search.setEnabled(checked)
        self.ui.detectors.setDisabled(checked)
        self.ui.select_directory.setDisabled(checked)

    def select_omega_file(self):
        omega_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Select file',
            HexrdConfig().images_dir, 'NPY files (*.npy)')
        self.ui.omega_file.setText(omega_file)
        self.state['omega'] = omega_file

    def set_empty_frames(self, value):
        self.state['empty_frames'] = value
        empty = self.ui.file_count.value() * value
        total = self.ui.total_frames.value() - empty
        self.ui.total_frames.setValue(total)

    def set_max_file_frames(self, value):
        self.state['max_frame_file'] = value

    def set_max_total_frames(self, value):
        self.state['max_frames'] = value

    def change_detector(self, det):
        self.detector = det
        self.setup_gui()
        if self.state['apply_to_all']:
            self.state[det]['search'] = self.ui.search_text.text()

    def set_ranges(self, frames, num_files):
        self.ui.empty_frames.setMaximum(frames)
        self.ui.max_file_frames.setMaximum(frames)
        self.ui.max_total_frames.setMaximum(frames * num_files)

    def file_selection_changed(self, checked):
        self.state['manual_file'] = checked
        self.ui.select_files.setEnabled(checked)
        self.ui.search_text.setDisabled(checked)
        self.ui.search.setDisabled(checked)
        self.ui.apply_to_all.setDisabled(checked)

    def select_files_manually(self):
        files, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, 'Select file(s)',
            dir=self.state[self.detector]['directory'])
        self.state[self.detector]['files'] = files
        self.state[self.detector]['file_count'] = len(files)
        self.ui.file_count.setText(str(len(files)))
        ims = ImageFileManager().open_file(files[0])
        frames = len(ims) if len(ims) else 1
        self.ui.total_frames.setValue(
            (frames - self.state['empty_frames']) * len(files))
        self.set_ranges(frames, len(files))
        self.state['total_frames'] = frames

    def add_wedge(self):
        row = self.ui.omega_wedges.rowCount()
        self.ui.omega_wedges.insertRow(row)
        self.ui.omega_wedges.setFocus()
        self.ui.omega_wedges.setCurrentCell(row, 0)
        self.state['wedges'].append([])

    def clear_wedges(self):
        self.ui.omega_wedges.setRowCount(0)
        self.state['wedges'].clear()

    def update_wedges(self, row, column):
        if value := self.ui.omega_wedges.item(row, column).text():
            self.state['wedges'][row].insert(column, int(value))

    def search_directories(self):
        pattern = self.ui.detector_search.text()
        for det in self.detectors:
            p = f'{pattern}/{det}' if Path(pattern).is_dir() else f'{pattern}_{det}'
            if Path(p).exists():
                p = f'{pattern}/{det}'
                self.state[det]['directory'] = p
                if det == self.ui.detectors.currentText():
                    self.ui.current_directory.setText(p)
            else:
                msg = (f'Could not find the directory for {det}:\n{p}')
                QMessageBox.warning(self.ui, 'HEXRD', msg)
                break

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
            input_dict['image-files']['files'] = (
                ' '.join(self.state[det]['files']))
            input_dict['options']['empty-frames'] = self.state['empty_frames']
            input_dict['options']['max-frame-file'] = (
                self.state['max_frame_file'])
            input_dict['options']['max-frames'] = self.state['max_frames']
            input_dict['meta']['panel'] = det
            if self.state['omega_from_file']:
                input_dict['meta']['omega'] = (
                    f'! load-numpy-array {self.state["omega"]}')
            data = yaml.dump(input_dict).encode('utf-8')
            t.write(data)
            t.close()
            temp.append([t.name])
            imgs.append(self.state[det]['files'])
        num_files = len(imgs[0])
        return temp, imgs, num_files

    def get_omega_values(self, num_files):
        if self.state['omega_from_file'] and self.state['omega']:
            omega = np.load(self.state['omega'])
        elif not self.state['omega_from_file']:
            omega = []
            for i in range(self.ui.omega_wedges.rowCount()):
                start = int(self.ui.omega_wedges.item(i, 0).text())
                stop = int(self.ui.omega_wedges.item(i, 1).text())
                steps = int(self.ui.omega_wedges.item(i, 2).text())
                delta = (stop - start) / steps
                omega.extend(np.linspace(
                    [start, start + delta],
                    [stop - delta, stop],
                    steps))
            omega = np.array(omega)
        nframes = [self.state['total_frames'] - self.state['empty_frames']]
        nsteps = nframes * num_files
        if not len(omega):
            steps = nsteps[0] * num_files
            delta = 360 / steps
            omega = np.linspace(
                [0, 0 + delta],
                [360 - delta, 360],
                steps)
        return omega[:, 0], omega[:, 1], nsteps

    def build_data(self):
        HexrdConfig().stack_state = copy.deepcopy(self.state)
        temp_files, img_files, num_files = self.get_files()
        start, stop, nsteps = self.get_omega_values(num_files)
        data = {
            'files': temp_files,
            'yml_files': img_files,
            'omega_min': start,
            'omega_max': stop,
            'nsteps': nsteps,
            'empty_frames': self.state['empty_frames'],
            'total_frames': [self.state['total_frames']] * num_files
        }
        if not self.state['omega_from_file']:
            data['wedges'] = self.state['wedges']
        return data

    def check_steps(self):
        steps = 0
        for i in range(self.ui.omega_wedges.rowCount()):
            for j in range(self.ui.omega_wedges.columnCount()):
                if not self.ui.omega_wedges.item(i, j).text():
                    return -1
            steps += int(self.ui.omega_wedges.item(i, 2).text())
        if not (total_frames := self.ui.max_total_frames.value()):
            total_frames = self.ui.total_frames.value()
        return steps if total_frames != steps else 0

    def exec_(self):
        while True:
            error = False
            if self.ui.exec_():
                f, d = [], []
                for det in self.detectors:
                    f.append(self.state[det]['file_count'])
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
                elif (steps := self.check_steps()) != 0:
                    print(steps)
                    if steps > 0:
                        msg = (
                            f'The total number of steps must be equal to the total '
                            f'number of frames: {steps} total steps, '
                            f'{self.ui.total_frames.value()} total frames.')
                    else:
                        msg = f'The omega wedges are incomplete.'
                    QMessageBox.warning(None, 'HEXRD', msg)
                    error = True
                    continue
                if error:
                    return True
                else:
                    return self.build_data()
            else:
                return False
