import copy
import math
import numpy as np
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QTableWidgetItem,
    QTreeWidgetItem,
    QAbstractItemView,
    QWidget,
)

from hexrdgui.constants import MAXIMUM_OMEGA_RANGE
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.image_file_manager import ImageFileManager
from hexrdgui.utils.dialog import add_help_url


class ImageStackDialog(QObject):

    # Emitted when images are cleared
    clear_images = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        simple_image_series_dialog: Any = None,
    ) -> None:
        super(ImageStackDialog, self).__init__(parent)
        loader = UiLoader()
        self.ui = loader.load_file('image_stack_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.WindowType.Tool)

        add_help_url(self.ui.button_box, 'configuration/images/#image-stack')

        self.simple_image_series_dialog = simple_image_series_dialog
        self.detectors = HexrdConfig().detector_names
        self.detector = self.detectors[0]
        self.state = copy.copy(HexrdConfig().stack_state)

        self.setup_state()
        self.ui.detectors.addItems(self.detectors)
        self.setup_connections()
        self.setup_gui()

    def setup_connections(self) -> None:
        self.ui.select_directory.clicked.connect(self.select_directory)
        self.ui.omega_from_file.toggled.connect(self.load_omega_from_file)
        self.ui.load_omega_file.clicked.connect(self.select_omega_file)
        self.ui.search.clicked.connect(self.search)
        self.ui.empty_frames.valueChanged.connect(self.set_empty_frames)
        self.ui.max_file_frames.valueChanged.connect(self.set_max_file_frames)
        self.ui.max_total_frames.valueChanged.connect(self.set_max_total_frames)
        self.ui.detectors.currentTextChanged.connect(self.change_detector)
        self.ui.files_by_selection.toggled.connect(self.file_selection_changed)
        self.ui.select_files.clicked.connect(self.select_files_manually)
        self.ui.add_wedge.clicked.connect(self.add_wedge)
        self.ui.clear_wedges.clicked.connect(self.clear_wedges)
        self.ui.omega_wedges.cellChanged.connect(self.update_wedges)
        self.ui.all_detectors.toggled.connect(self.detector_selection)
        self.ui.search_directories.clicked.connect(self.search_directories)
        self.ui.clear_file_selections.clicked.connect(self.clear_selected_files)
        self.clear_images.connect(
            self.simple_image_series_dialog.clear_from_stack_dialog
        )
        self.ui.add_omega.toggled.connect(self.add_omega_toggled)
        self.ui.reverse_frames.toggled.connect(self.reverse_frames)
        self.ui.button_box.accepted.connect(self.check_data)
        self.ui.button_box.rejected.connect(self.close_widget)
        HexrdConfig().detectors_changed.connect(self.detectors_changed)

    def setup_gui(self) -> None:
        self.ui.current_directory.setText(self.state[self.detector]['directory'])
        self.ui.current_directory.setToolTip(self.state[self.detector]['directory'])
        self.ui.search_text.setText(self.state[self.detector]['search'])
        self.ui.empty_frames.setValue(self.state['empty_frames'])
        self.ui.max_file_frames.setValue(self.state['max_file_frames'])
        self.ui.max_total_frames.setValue(self.state['max_total_frames'])
        self.ui.omega_from_file.setChecked(self.state['omega_from_file'])
        if self.state['omega']:
            self.ui.omega_file.setText(self.state['omega'].split(' ')[-1])
        self.ui.files_by_selection.setChecked(self.state['manual_file'])
        self.ui.files_by_search.setChecked(not self.state['manual_file'])
        file_count = self.state[self.detector]['file_count']
        self.ui.file_count.setText(str(file_count))
        self.ui.apply_to_all.setChecked(self.state['apply_to_all'])
        self.ui.all_detectors.setChecked(self.state['all_detectors'])
        self.ui.add_omega.setChecked(self.state['add_omega_data'])
        self.ui.total_frames.setText(str(self.state['total_frames'] * file_count))
        self.update_files_tree()
        self.set_ranges(
            self.state['total_frames'], int(self.state[self.detector]['file_count'])
        )
        if self.state['wedges']:
            self.set_wedges()
        self.total_frames()

    def setup_state(self) -> None:
        if (
            sorted(self.state.get('dets', [])) != sorted(self.detectors)
            or 'max_frame_file' in self.state.keys()
        ):
            self.state.clear()
        if self.state:
            self.find_previous_images(self.state[self.detector]['files'])
            self.add_omega_toggled(self.state.get('add_omega_data', True))
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
                'wedges': [],
                'add_omega_data': True,
                'reverse_frames': False,
            }
        self.setup_detectors_state()

    def setup_detectors_state(self) -> None:
        for det in self.detectors:
            self.state[det] = {
                'directory': '',
                'files': '',
                'search': '',
                'file_count': 0,
            }

    def set_wedges(self) -> None:
        if self.ui.omega_wedges.rowCount() == 0:
            for i, wedge in enumerate(self.state['wedges']):
                self.ui.omega_wedges.insertRow(i)
                for j, value in enumerate(wedge):
                    self.ui.omega_wedges.setItem(i, j, QTableWidgetItem(str(value)))

    def select_directory(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self.ui, 'Select directory', self.ui.current_directory.text()
        )
        self.state[self.detector]['directory'] = d
        HexrdConfig().working_dir = d.rsplit('/', 1)[0]
        self.ui.current_directory.setText(d)
        self.ui.current_directory.setToolTip(d)
        if not self.state['manual_file'] and self.state['apply_to_all']:
            self.search_directory(self.detector)
        self.update_frames()

    def search(self) -> None:
        if self.ui.apply_to_all.isChecked() and self.ui.files_by_search.isChecked():
            for det in self.detectors:
                self.search_directory(det)
        else:
            self.search_directory(self.detector)
        self.update_frames()
        self.update_files_tree()

    def search_directory(self, det: str) -> None:
        self.state[det]['search'] = self.ui.search_text.text()
        if not (search := self.ui.search_text.text()):
            search = '*'
        if self.detector in search:
            pattern = search.split(self.detector)
            search = f'{pattern[0]}{det}{pattern[1]}'
        if directory := self.state[det]['directory']:
            if files := list(Path(directory).glob(search)):
                files = [f for f in files if f.is_file()]
                self.state[det]['files'] = sorted([str(f) for f in files])
                self.state[det]['file_count'] = len(files)
                self.ui.file_count.setText(str(len(files)))

    def update_frames(self) -> None:
        files = self.state[self.detector]['files']
        frames = 0
        if files:
            ims = ImageFileManager().open_file(str(files[0]))
            frames = len(ims) if len(ims) else 1
        self.ui.total_frames.setText(str(frames))
        self.set_ranges(frames, len(files))
        self.state['total_frames'] = frames
        self.total_frames()

    def load_omega_from_file(self, checked: bool) -> None:
        self.state['omega_from_file'] = checked
        self.ui.omega_wedges.setDisabled(False)
        self.ui.add_wedge.setDisabled(checked)
        self.ui.clear_wedges.setDisabled(checked)
        self.ui.load_omega_file.setEnabled(checked)
        self.ui.omega_file.setEnabled(checked)
        if checked:
            self.ui.omega_wedges.setEditTriggers(
                QAbstractItemView.EditTrigger.NoEditTriggers
            )
        else:
            self.ui.omega_wedges.setEditTriggers(
                QAbstractItemView.EditTrigger.AllEditTriggers
            )

    def detector_selection(self, checked: bool) -> None:
        self.state['all_detectors'] = checked
        self.ui.single_detector.setChecked(not checked)
        self.ui.search_directories.setEnabled(checked)
        self.ui.detector_search.setEnabled(checked)
        self.ui.select_directory.setDisabled(checked)

    def select_omega_file(self) -> None:
        omega_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Select file', HexrdConfig().images_dir or "", 'NPY files (*.npy)'
        )
        self.ui.omega_file.setText(omega_file)
        self.state['omega'] = omega_file
        wedges = np.load(omega_file)
        for wedge in wedges:
            self.add_wedge(wedge=wedge)

    def set_empty_frames(self, value: int) -> None:
        self.state['empty_frames'] = value
        self.total_frames()

    def set_max_file_frames(self, value: int) -> None:
        self.state['max_file_frames'] = value
        self.total_frames()

    def set_max_total_frames(self, value: int) -> None:
        self.state['max_total_frames'] = value
        self.total_frames()

    def total_frames(self) -> None:
        file_count = int(self.ui.file_count.text())
        total = self.frames_per_image * file_count
        if max_total := self.state['max_total_frames']:
            total = min(total, max_total)
        self.ui.total_frames.setText(str(total))

    def change_detector(self, det: str) -> None:
        if not det:
            return
        self.detector = det
        self.setup_gui()
        self.ui.current_directory.setText(self.state[det]['directory'])
        if self.state['apply_to_all']:
            self.state[det]['search'] = self.ui.search_text.text()

    def set_ranges(self, frames: int, num_files: int) -> None:
        self.ui.empty_frames.setMaximum(max(frames - 1, 0))
        self.ui.max_file_frames.setMaximum(frames)
        self.ui.max_total_frames.setMaximum(frames * num_files)

    def file_selection_changed(self, checked: bool) -> None:
        self.state['manual_file'] = checked
        self.ui.select_files.setEnabled(checked)
        self.ui.search_text.setDisabled(checked)
        self.ui.search.setDisabled(checked)
        self.ui.apply_to_all.setDisabled(checked)
        self.update_files_tree()

    def select_files_manually(self) -> None:
        files, selected_filter = QFileDialog.getOpenFileNames(
            self.ui, 'Select file(s)', dir=self.state[self.detector]['directory']
        )
        if files:
            self.state[self.detector]['files'] = files
            self.state[self.detector]['file_count'] = len(files)
            ims = ImageFileManager().open_file(str(files[0]))
            frames = len(ims) if len(ims) else 1
            self.ui.total_frames.setText(str(frames))
            self.ui.file_count.setText(str(len(files)))
            self.set_ranges(frames, len(files))
            self.state['total_frames'] = frames
            self.total_frames()
        self.update_files_tree()

    def find_previous_images(self, files: Any) -> None:
        try:
            ims = ImageFileManager().open_file(files[0])
            frames = len(ims) if len(ims) else 1
            self.ui.total_frames.setText(str(frames))
            self.set_ranges(frames, len(files))
            self.state['total_frames'] = frames
            self.total_frames()
        except Exception:
            msg = (
                'Unable to open previously loaded images, please make sure '
                'directory path is correct and that images still exist.'
            )
            QMessageBox.warning(self.parent(), 'HEXRD', msg)  # type: ignore[arg-type]
            for det in self.detectors:
                self.state[det]['files'] = []
                self.state[det]['file_count'] = 0

    def add_wedge(self, checked: bool = False, wedge: Any = None) -> None:
        row = self.ui.omega_wedges.rowCount()
        self.ui.omega_wedges.insertRow(row)
        if wedge is None:
            self.ui.omega_wedges.setFocus()
            self.ui.omega_wedges.setCurrentCell(row, 0)
            self.state['wedges'].append([0, 0, 0])
        else:
            for idx, val in enumerate(wedge):
                self.ui.omega_wedges.setItem(row, idx, QTableWidgetItem(f'{val}'))

    def clear_wedges(self) -> None:
        self.ui.omega_wedges.setRowCount(0)
        self.state['wedges'].clear()

    def update_wedges(self, row: int, column: int) -> None:
        if self.state['omega_from_file'] and self.state['omega']:
            # User loaded values from file. We are just populating the
            # table for inspection, no need to duplicate values in state.
            return

        if value := self.ui.omega_wedges.item(row, column).text():
            data = float(value)
            self.state['wedges'][row][column] = data
            if column == 2:
                self.state['wedges'][row][column] = int(data)

    def search_directories(self) -> None:
        pattern = self.ui.detector_search.text()
        directory = Path(pattern).resolve()
        if directory.is_dir():
            for det in self.detectors:
                self.state[det]['directory'] = str(directory)
                if (directory / det).resolve().exists():
                    self.state[det]['directory'] = str(directory / det)
                if det == self.ui.detectors.currentText():
                    self.ui.current_directory.setText(self.state[det]['directory'])
        else:
            msg = f'Could not find directory:\n{pattern}'
            QMessageBox.warning(self.ui, 'HEXRD', msg)

    def get_files(self) -> tuple[list[Any], int]:
        imgs = []
        for det in self.detectors:
            imgs.append(sorted(self.state[det]['files']))
        num_files = len(imgs[0])
        return imgs, num_files

    def clear_selected_files(self) -> None:
        for det in self.detectors:
            self.state[det]['files'] = []
            self.state[det]['file_count'] = 0
        self.ui.file_count.setText('0')
        self.update_files_tree()
        self.clear_images.emit()

    def add_omega_toggled(self, checked: bool) -> None:
        self.state['add_omega_data'] = checked
        self.ui.omega_from_file.setEnabled(checked)
        self.ui.omega_wedges.setEnabled(checked)
        if checked:
            self.load_omega_from_file(self.ui.omega_from_file.isChecked())
        else:
            self.ui.omega_wedges.setEnabled(checked)
            self.ui.add_wedge.setEnabled(checked)
            self.ui.clear_wedges.setEnabled(checked)
            self.ui.load_omega_file.setEnabled(checked)
            self.ui.omega_file.setEnabled(checked)

    def reverse_frames(self, state: bool) -> None:
        self.state['reverse_frames'] = state

    @property
    def frames_per_image(self) -> int:
        frames = self.state['total_frames']
        frames -= self.state['empty_frames']
        if self.state['max_file_frames']:
            frames = min(frames, self.state['max_file_frames'])
        return frames

    def get_omega_values(self, num_files: int) -> tuple[Any, Any, Any]:
        # Returns the omega values that are used to populate the
        # SimpleImageSeries dialog table
        ome_arr_dtype = np.dtype([('start', float), ('stop', float), ('steps', int)])
        wedges = self.state['wedges']
        if self.state['omega_from_file'] and self.state['omega']:
            # user selected a file
            wedges = np.load(self.state['omega'])
        if wedges and num_files > 1:
            # we create a wedge for each image based on the number
            # of frames per image and number of steps in each wedge
            omega: Any = []
            max_total_frames = self.state['max_total_frames']
            steps = self.frames_per_image
            for i, (start, stop, nsteps) in enumerate(wedges):
                last_wedge = i == len(wedges) - 1
                images_per_wedge = math.ceil(nsteps / steps)
                delta = (stop - start) / images_per_wedge
                for j in range(images_per_wedge):
                    last_image = j == images_per_wedge - 1
                    stop = start + delta
                    if last_wedge and last_image and max_total_frames:
                        steps = max_total_frames % steps
                    omega.append((start, stop, steps))
                    start = stop
        elif wedges and num_files == 1:
            # single images need a single wedge, even if discontinuous
            nsteps = sum([i[-1] for i in wedges])
            omega = [(wedges[0][0], wedges[-1][1], nsteps)]
        else:
            # user did not select file or enter wedges
            delta = MAXIMUM_OMEGA_RANGE / num_files
            omega = np.linspace(
                [0, 0 + delta],
                [MAXIMUM_OMEGA_RANGE - delta, MAXIMUM_OMEGA_RANGE],
                num_files,
                dtype=np.uint16,
            )
            omega = [
                (b, e, self.frames_per_image) for [b, e] in omega
            ]  # type: ignore[misc]
            if max_total := self.state['max_total_frames']:
                # The max_total is subtracted off of the end of the imageseries
                # We need to account for the edge case where the max_total is
                # equivalent to ignoring one or more entire files
                for i, (start, stop, nsteps) in enumerate(omega):
                    if max_total < nsteps:
                        omega[i] = (start, stop, max_total)
                    max_total = max(max_total - nsteps, 0)
        omega = np.asarray(omega, dtype=ome_arr_dtype)
        return omega['start'], omega['stop'], omega['steps']

    def build_data(self) -> None:
        HexrdConfig().stack_state = copy.deepcopy(self.state)
        img_files, num_files = self.get_files()
        start, stop, nsteps = self.get_omega_values(num_files)
        total_frames = self.frames_per_image
        if max_total := self.state['max_total_frames']:
            total_frames = min(self.frames_per_image, max_total)
        data = {
            'files': img_files,
            'omega_min': start,
            'omega_max': stop,
            'nsteps': nsteps,
            'empty_frames': self.state['empty_frames'],
            'total_frames': [total_frames] * num_files,
            'frame_data': {
                'max_file_frames': self.state['max_file_frames'],
                'max_total_frames': self.state['max_total_frames'],
            },
            'reverse_frames': self.state.get('reverse_frames', False),
            'nframes': sum(nsteps),
        }
        if not self.state['omega_from_file'] and self.state['wedges']:
            data['frame_data']['wedges'] = self.state['wedges']

        self.simple_image_series_dialog.image_stack_loaded(data)
        self.simple_image_series_dialog.show()

    def check_steps(self) -> tuple[int, str | None]:
        # Make sure that the wedges are correct
        err = None
        steps = 0
        if self.ui.no_omega.isChecked():
            # We will compute the omega data, assume
            # the steps and total frames are correct
            steps = int(self.ui.total_frames.text())
        else:
            if self.ui.omega_from_file.isChecked():
                try:
                    wedges = np.load(self.state['omega'])
                    steps = sum(wedges[:, 2:3].flatten())
                except FileNotFoundError:
                    err = 'Invalid omega file selected.'
            else:
                for row in range(self.ui.omega_wedges.rowCount()):
                    try:
                        self.ui.omega_wedges.item(row, 0).text()
                        self.ui.omega_wedges.item(row, 1).text()
                        steps_str = self.ui.omega_wedges.item(row, 2).text()
                        steps += int(float(steps_str))
                    except (AttributeError, ValueError):
                        err = 'Empty or invalid entry in omega wedges table.'
        return steps, err

    def check_data(self) -> None:
        steps, err = self.check_steps()
        total_frames = int(self.ui.total_frames.text())
        if err:
            QMessageBox.warning(None, 'HEXRD', err)
            return

        counts = []
        directories = []
        for det in self.detectors:
            counts.append(self.state[det]['file_count'])
            directories.append(self.state[det]['directory'])
        if dets := [det for det in directories if not det]:
            msg = (
                f'The directory has not been set for '
                f'the following detector(s):\n{" ".join(dets)}.'
            )
            QMessageBox.warning(self.ui, 'HEXRD', msg)
            return
        elif any([c == 0 for c in counts]):
            msg = 'Files have not been selected for all detectors.'
            QMessageBox.warning(None, 'HEXRD', msg)
            return
        elif any([c for c in counts if counts[0] != c]):
            msg = 'The number of files for each detector must match.'
            QMessageBox.warning(None, 'HEXRD', msg)
            return
        elif steps != total_frames:
            msg = f'''
                   The total number of steps must be equal to the total
                   number of frames:
                   {steps} total steps, {total_frames} total frames.
                   '''
            QMessageBox.warning(None, 'HEXRD', msg)
            return
        self.build_data()
        self.close_widget()

    def show(self) -> None:
        self.ui.show()

    def close_widget(self) -> None:
        if self.ui.isFloating():
            self.ui.close()

    def detectors_changed(self) -> None:
        self.detectors = HexrdConfig().detector_names
        self.detector = self.detectors[0]
        # update the state
        self.state['dets'] = self.detectors
        self.setup_detectors_state()
        # update the GUI
        self.ui.detectors.clear()
        self.ui.detectors.addItems(self.detectors)
        self.setup_gui()

    def update_files_tree(self) -> None:
        self.ui.files_found.clear()
        for det in self.state['dets']:
            parent = QTreeWidgetItem(self.ui.files_found)
            files = self.state[det]['files']
            parent.setText(0, f'{det} ({len(files)} files)')
            for f in files:
                child = QTreeWidgetItem(parent)
                child.setText(0, Path(f).name)
                child.setText(1, f'{self.frames_per_image}')
            self.ui.files_found.expandItem(parent)
