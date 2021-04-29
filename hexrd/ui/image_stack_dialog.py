import copy
import tempfile
import yaml
import numpy as np
from pathlib import Path

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem

from hexrd.ui.constants import MAXIMUM_OMEGA_RANGE
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.image_file_manager import ImageFileManager


class ImageStackDialog(QObject):

    # Emitted when images are cleared
    clear_images = Signal()

    def __init__(self, parent=None, load_panel=None):
        super(ImageStackDialog, self).__init__(parent)
        loader = UiLoader()
        self.ui = loader.load_file('image_stack_dialog.ui', parent)

        self.load_panel = load_panel
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
        self.ui.clear_file_selections.clicked.connect(
            self.clear_selected_files)
        self.clear_images.connect(self.load_panel.clear_from_stack_dialog)

    def setup_gui(self):
        self.ui.current_directory.setText(
            self.state[self.detector]['directory'])
        self.ui.current_directory.setToolTip(
            self.state[self.detector]['directory'])
        self.ui.search_text.setText(self.state[self.detector]['search'])
        self.ui.empty_frames.setValue(self.state['empty_frames'])
        self.ui.max_file_frames.setValue(self.state['max_file_frames'])
        self.ui.max_total_frames.setValue(self.state['max_total_frames'])
        self.ui.omega_from_file.setChecked(self.state['omega_from_file'])
        if self.state['omega']:
            self.ui.omega_file.setText(self.state['omega'].split(' ')[-1])
        self.ui.omega_from_file.setChecked(self.state['omega_from_file'])
        self.ui.files_by_selection.setChecked(self.state['manual_file'])
        self.ui.files_by_search.setChecked(not self.state['manual_file'])
        file_count = self.state[self.detector]['file_count']
        self.ui.file_count.setText(str(file_count))
        self.ui.apply_to_all.setChecked(self.state['apply_to_all'])
        self.ui.all_detectors.setChecked(self.state['all_detectors'])
        self.ui.total_frames.setValue(self.state['total_frames'] * file_count)
        self.set_ranges(
            self.state['total_frames'],
            int(self.state[self.detector]['file_count']))
        if self.state['wedges']:
            self.set_wedges()
        self.total_frames()

    def setup_state(self):
        if (sorted(self.state.get('dets', [])) != sorted(self.detectors)
                or 'max_frame_file' in self.state.keys()):
            self.state.clear()
        if self.state:
            self.find_previous_images(self.state[self.detector]['files'])
            self.load_omega_from_file(self.state['omega_from_file'])
            self.file_selection_changed(self.state['manual_file'])
            self.detector_selection(self.state['all_detectors'])
        else:
            self.state.clear()
            self.state = {
                'all_detectors': True,
                'dets': self.detectors,
                'empty_frames': 0,
                'max_file_frames': 0,
                'max_total_frames': 0,
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
        if self.ui.omega_wedges.rowCount() == 0:
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
                total = (frames - self.state['empty_frames']) * len(files)
                self.ui.total_frames.setValue(total)
                self.ui.file_count.setText(str(len(files)))
                self.set_ranges(frames, len(files))
                self.state['total_frames'] = frames
                self.total_frames()

    def load_omega_from_file(self, checked):
        self.state['omega_from_file'] = checked
        self.ui.omega_wedges.setDisabled(checked)
        self.ui.add_wedge.setDisabled(checked)
        self.ui.clear_wedges.setDisabled(checked)
        self.ui.load_omega_file.setEnabled(checked)
        self.ui.omega_file.setEnabled(checked)

    def detector_selection(self, checked):
        self.state['all_detectors'] = checked
        self.ui.single_detector.setChecked(not checked)
        self.ui.search_directories.setEnabled(checked)
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
        self.total_frames()

    def set_max_file_frames(self, value):
        self.state['max_file_frames'] = value
        self.total_frames()

    def set_max_total_frames(self, value):
        self.state['max_total_frames'] = value
        self.total_frames()

    def total_frames(self):
        file_count = int(self.ui.file_count.text())
        total = self.state['total_frames'] * file_count
        if empty := self.ui.empty_frames.value():
            total = total - (empty * file_count)
        if max_file := self.ui.max_file_frames.value():
            total = min(total, max_file * file_count)
        if max_total := self.ui.max_total_frames.value():
            total = min(total, max_total)
        self.ui.total_frames.setValue(total)

    def change_detector(self, det):
        self.detector = det
        self.setup_gui()
        if self.state['apply_to_all']:
            self.state[det]['search'] = self.ui.search_text.text()

    def set_ranges(self, frames, num_files):
        self.ui.empty_frames.setMaximum(frames - 1)
        self.ui.max_file_frames.setMaximum(frames)
        self.ui.max_total_frames.setMaximum(frames * num_files)

    def file_selection_changed(self, checked):
        self.state['manual_file'] = checked
        self.ui.select_files.setEnabled(checked)
        self.ui.search_text.setDisabled(checked)
        self.ui.search.setDisabled(checked)
        self.ui.apply_to_all.setDisabled(checked)

    def select_files_manually(self, files):
        if not files:
            files, selected_filter = QFileDialog.getOpenFileNames(
                self.ui, 'Select file(s)',
                dir=self.state[self.detector]['directory'])
            self.state[self.detector]['files'] = files
            self.state[self.detector]['file_count'] = len(files)
            self.ui.file_count.setText(str(len(files)))

    def find_previous_images(self, files):
        try:
            ims = ImageFileManager().open_file(files[0])
            frames = len(ims) if len(ims) else 1
            total = (frames - self.state['empty_frames']) * len(files)
            self.ui.total_frames.setValue(total)
            self.set_ranges(frames, len(files))
            self.state['total_frames'] = frames
            self.total_frames()
        except Exception as e:
            msg = (
                f'Unable to open previously loaded images, please make sure '
                f'directory path is correct and that images still exist.')
            QMessageBox.warning(self.parent(), 'HEXRD', msg)
            for det in self.detectors:
                self.state[det]['files'] = ''
                self.state[det]['file_count'] = 0

    def add_wedge(self):
        row = self.ui.omega_wedges.rowCount()
        self.ui.omega_wedges.insertRow(row)
        self.ui.omega_wedges.setFocus()
        self.ui.omega_wedges.setCurrentCell(row, 0)
        self.state['wedges'].append([0, 0, 0])

    def clear_wedges(self):
        self.ui.omega_wedges.setRowCount(0)
        self.state['wedges'].clear()

    def update_wedges(self, row, column):
        if value := self.ui.omega_wedges.item(row, column).text():
            self.state['wedges'][row][column] = int(value)

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
        imgs = []
        for det in self.detectors:
            imgs.append(self.state[det]['files'])
        num_files = len(imgs[0])
        return imgs, num_files

    def clear_selected_files(self):
        for det in self.detectors:
            self.state[det]['files'].clear()
            self.state[det]['file_count'] = 0
        self.ui.file_count.setText('0')
        self.clear_images.emit()

    def get_omega_values(self, num_files):
        if self.state['omega_from_file'] and self.state['omega']:
            omega = np.load(self.state['omega'])
        elif not self.state['omega_from_file']:
            omega = []
            nframes = self.ui.total_frames.value() // num_files
            nsteps = [nframes] * num_files
            row_count = self.ui.omega_wedges.rowCount()
            length = num_files if row_count == 1 else 1
            for i in range(row_count):
                start = int(self.ui.omega_wedges.item(i, 0).text())
                stop = int(self.ui.omega_wedges.item(i, 1).text())
                steps = int(self.ui.omega_wedges.item(i, 2).text())
                delta = (stop - start) / length
                omega.extend(np.linspace(
                    [start, start + delta],
                    [stop - delta, stop],
                    length))
            omega = np.array(omega)
        if not len(omega):
            delta = MAXIMUM_OMEGA_RANGE / num_files
            omega = np.linspace(
                [0, 0 + delta],
                [MAXIMUM_OMEGA_RANGE - delta, MAXIMUM_OMEGA_RANGE],
                num_files)
        return omega[:, 0], omega[:, 1], nsteps

    def build_data(self):
        HexrdConfig().stack_state = copy.deepcopy(self.state)
        img_files, num_files = self.get_files()
        start, stop, nsteps = self.get_omega_values(num_files)
        self.state['total_frames'] = self.ui.total_frames.value() // num_files
        data = {
            'files': img_files,
            'omega_min': start,
            'omega_max': stop,
            'nsteps': nsteps,
            'empty_frames': self.state['empty_frames'],
            'total_frames': [self.state['total_frames']] * num_files,
            'frame_data': {
                'max_file_frames': self.state['max_file_frames'],
                'max_total_frames': self.state['max_total_frames']
            }
        }
        if not self.state['omega_from_file']:
            data['frame_data']['wedges'] = self.state['wedges']
        return data

    def check_steps(self):
        if self.ui.omega_from_file.isChecked():
            return
        steps = 0
        for i in range(self.ui.omega_wedges.rowCount()):
            for j in range(self.ui.omega_wedges.columnCount()):
                if not self.ui.omega_wedges.item(i, j).text():
                    return -1
            steps += int(self.ui.omega_wedges.item(i, 2).text())
        return steps if self.ui.total_frames.value() != steps else 0

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
                if idx := [i for i, n in enumerate(f) if f[0] == 0]:
                    msg = (f'No files have been selected for the detectors.')
                    QMessageBox.warning(None, 'HEXRD', msg)
                    error = True
                    continue
                if idx := [i for i, n in enumerate(f) if f[0] != n]:
                    dets = [self.state['dets'][i] for i in idx]
                    msg = (
                        f'The number of files for each detector must match. '
                        f'The following detector(s) do not:\n{" ".join(dets)}')
                    QMessageBox.warning(None, 'HEXRD', msg)
                    error = True
                    continue
                if (steps := self.check_steps()) != 0:
                    if steps > 0:
                        msg = (
                            f'The total number of steps must be equal to the '
                            f'total number of frames: {steps} total steps, '
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
