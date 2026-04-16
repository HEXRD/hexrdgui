from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QFileDialog, QInputDialog, QWidget

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils.imageseries import get_monolithic_ims
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
        if HexrdConfig().instrument_has_roi:
            self.ui.detectors.addItems(HexrdConfig().detector_group_names)
        else:
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

    def _get_ims(
        self,
        name: str,
        ims_dict: dict | None,
    ) -> Any:
        """Get the image series for a detector or group name.

        When the instrument has ROI-based detector groups, unwraps the
        rectangle operation from the first sub-panel to recover the
        monolithic image series.
        """
        if ims_dict is None:
            return None

        if HexrdConfig().instrument_has_roi:
            first_det = HexrdConfig().detectors_in_group(name)[0]
            subpanel_ims = ims_dict.get(first_det)
            if subpanel_ims is None:
                return None
            return get_monolithic_ims(subpanel_ims)

        return ims_dict.get(name)

    def save_images(self) -> None:
        if self.ui.ignore_agg.isChecked():
            ims_dict = HexrdConfig().unagg_images
        else:
            ims_dict = HexrdConfig().imageseries_dict

        if HexrdConfig().instrument_has_roi:
            dets = HexrdConfig().detector_group_names
        else:
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
                self._get_ims(det, ims_dict),
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
