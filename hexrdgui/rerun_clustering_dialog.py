import numpy as np
from pathlib import Path

from typing import Any

from PySide6.QtWidgets import QDialog, QFileDialog, QWidget
from PySide6.QtCore import QTimer, Qt

from hexrdgui.async_worker import AsyncWorker
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url


class RerunClusteringDialog(QDialog):

    def __init__(self, indexing_runner: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('rerun_clustering_dialog.ui', parent)

        add_help_url(self.ui.button_box, 'hedm/indexing/#rerun-clustering')

        self.indexing_runner = indexing_runner
        self.qfib = None
        self.completeness = None
        self.setup_gui()
        self.setup_connections()

    def setup_gui(self) -> None:
        idx_cfg = HexrdConfig().indexing_config['find_orientations']
        clustering_data = idx_cfg['clustering']
        self.ui.radius.setValue(clustering_data['radius'])
        self.ui.completeness.setValue(clustering_data['completeness'])
        self.ui.algorithms.setCurrentText(clustering_data['algorithm'])
        self.ui.min_samples.setValue(self.indexing_runner.min_samples)
        self.update_min_samples_enable_state()

    def setup_connections(self) -> None:
        self.ui.load_file.clicked.connect(self.load_file)
        self.ui.button_box.accepted.connect(self.accept)
        self.ui.algorithms.currentIndexChanged.connect(
            self.update_min_samples_enable_state
        )

    def update_min_samples_enable_state(self) -> None:
        indexing_config = HexrdConfig().indexing_config
        visible = (
            indexing_config['find_orientations']['use_quaternion_grid'] is None
            and self.ui.algorithms.currentText() != 'fclusterdata'
        )

        self.ui.min_samples_label.setVisible(visible)
        self.ui.min_samples.setVisible(visible)

    def load_file(self) -> None:
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui,
            'Load Scored Orientations File',
            HexrdConfig().working_dir,
            'NPZ files (*.npz)',
        )

        if selected_file:
            self.ui.file_name.setText(Path(selected_file).name)
            self.ui.file_name.setToolTip(selected_file)
            with np.load(selected_file) as data:
                self.qfib = data['test_quaternions']
                self.completeness = data['score']

    def save_input(self) -> None:
        idx_cfg = HexrdConfig().indexing_config
        clustering = idx_cfg['find_orientations']['clustering']
        clustering['radius'] = self.ui.radius.value()
        clustering['completeness'] = self.ui.completeness.value()
        clustering['algorithm'] = self.ui.algorithms.currentText()
        if self.indexing_runner.clustering_needs_min_samples:
            self.indexing_runner.min_samples = self.ui.min_samples.value()
        if self.qfib is not None:
            self.indexing_runner.qfib = self.qfib
        if self.completeness is not None:
            self.indexing_runner.completeness = self.completeness

    def accept(self) -> None:
        self.save_input()

        runner = self.indexing_runner
        runner.is_rerunning_clustering = True
        worker = AsyncWorker(runner.run_cluster)
        runner.thread_pool.start(worker)

        worker.signals.result.connect(
            self._on_run_cluster_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        runner.indexing_results_rejected.connect(
            self._on_indexing_results_rejected,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.error.connect(runner.on_async_error)
        runner.progress_dialog.exec()

        super().accept()

    def _on_run_cluster_finished(self) -> None:
        # This function was previously a nested function, but for some reason,
        # in the latest version of Qt (Qt 6.8.1), a queued connection on a
        # nested function no longer seems to work (the application freezes).
        # It appears to work, however, if this is a method on the object.
        runner = self.indexing_runner

        # Since this is a QueuedConnection, we need to accept progress here
        runner.accept_progress()
        runner.confirm_indexing_results()

        if runner.grains_table is None:
            # The previous step must have failed. Show again.
            QTimer.singleShot(0, self.exec)

    def _on_indexing_results_rejected(self) -> None:
        # This function was previously a nested function, but for some reason,
        # in the latest version of Qt (Qt 6.8.1), a queued connection on a
        # nested function no longer seems to work (the application freezes).
        # It appears to work, however, if this is a method on the object.

        # Since this is a QueuedConnection, we need to accept progress here
        self.indexing_runner.accept_progress()
        self.exec()

    def exec(self) -> None:  # type: ignore[override]
        self.setup_gui()
        self.ui.exec()
