from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QFileDialog, QInputDialog, QWidget

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.progress_dialog import ProgressDialog
from hexrdgui.async_worker import AsyncWorker


class SaveImagesDialog:

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        loader = UiLoader()
        self.ui = loader.load_file('save_images_dialog.ui', parent)

        self.progress_dialog = ProgressDialog(self.ui)

        self.setup_gui()
        self.setup_connections()

    def setup_gui(self) -> None:
        self.ui.detectors.clear()
        self.ui.detectors.addItems(HexrdConfig().detector_names)
        self.ui.pwd.setText(self.parent_dir)
        self.ui.pwd.setToolTip(self.parent_dir)
        if HexrdConfig().is_aggregated:
            self.ui.ignore_agg.setEnabled(True)

    def setup_connections(self) -> None:
        self.ui.single_detector.toggled.connect(self.ui.detectors.setEnabled)
        self.ui.change_directory.clicked.connect(self.change_directory)

    @property
    def parent_dir(self) -> str:
        images_dir = HexrdConfig().images_dir
        if images_dir is not None and Path(images_dir).exists():
            return images_dir
        return str(Path.cwd())

    def change_directory(self) -> None:
        caption = 'Select directory for images'
        new_dir = QFileDialog.getExistingDirectory(
            self.ui, caption, dir=self.parent_dir
        )

        if new_dir:
            HexrdConfig().set_images_dir(new_dir)
            self.ui.pwd.setText(self.parent_dir)
            self.ui.pwd.setToolTip(self.parent_dir)

    def save_images(self) -> None:
        if self.ui.ignore_agg.isChecked():
            ims_dict = HexrdConfig().unagg_images
        else:
            ims_dict = HexrdConfig().imageseries_dict
        dets = HexrdConfig().detector_names
        if self.ui.single_detector.isChecked():
            dets = [self.ui.detectors.currentText()]

        selected_format = self.ui.format.currentText().lower()
        style: str | None = None
        if selected_format.startswith('hdf5'):
            selected_format = 'hdf5'
            ext = 'h5'
        elif selected_format.startswith('npz'):
            selected_format = 'frame-cache'
            style = 'npz'
            ext = 'npz'
        else:
            selected_format = 'frame-cache'
            style = 'fch5'
            ext = 'fch5'

        if selected_format == 'frame-cache':
            # Get the user to pick a threshold
            threshold, ok = QInputDialog.getDouble(
                self.ui, 'HEXRD', 'Choose Threshold', 10, 0, 1e12, 3
            )
            if not ok:
                # User canceled...
                return

        for det in dets:
            filename = f'{self.ui.file_stem.text()}_{det}.{ext}'
            path = f'{self.parent_dir}/{filename}'

            kwargs: dict[str, Any] = {}
            if selected_format == 'hdf5':
                # A path must be specified. Set it ourselves for now.
                kwargs['path'] = 'imageseries'
            elif selected_format == 'frame-cache':
                kwargs['threshold'] = threshold
                assert style is not None
                kwargs['style'] = style

                if style == 'npz':
                    # This needs to be specified, but I think it just needs
                    # to be the same as the file name...
                    kwargs['cache_file'] = path

            worker = AsyncWorker(
                HexrdConfig().save_imageseries,
                ims_dict.get(det) if ims_dict is not None else None,
                det,
                path,
                selected_format,
                **kwargs,
            )
            self.thread_pool.start(worker)
            self.progress_dialog.setWindowTitle(f'Saving {filename}')
            self.progress_dialog.setRange(0, 0)
            worker.signals.finished.connect(self.progress_dialog.accept)
            self.progress_dialog.exec()

    def exec(self) -> None:
        if self.ui.exec():
            self.save_images()

    @property
    def thread_pool(self) -> QThreadPool:
        return QThreadPool.globalInstance()
