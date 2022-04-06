import copy
import numpy as np
from pathlib import Path

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader

from PySide2.QtWidgets import QDialog, QFileDialog
from PySide2.QtCore import Qt


class RerunClusteringDialog(QDialog):

    def __init__(self, indexing_runner, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('rerun_clustering_dialog.ui', parent)
        self.indexing_runner = indexing_runner
        self.qfib = None
        self.completeness = None
        self.setup_gui()
        self.setup_connections()

    def setup_gui(self):
        idx_cfg = HexrdConfig().indexing_config['find_orientations']
        clustering_data = idx_cfg['clustering']
        self.ui.radius.setValue(clustering_data['radius'])
        self.ui.completeness.setValue(clustering_data['completeness'])
        self.ui.algorithms.setCurrentText(clustering_data['algorithm'])
        self.ui.min_samples.setValue(self.indexing_runner.min_samples)
        self.update_min_samples_enable_state()

    def setup_connections(self):
        self.ui.load_file.clicked.connect(self.load_file)
        self.ui.button_box.accepted.connect(self.accept)
        self.ui.algorithms.currentIndexChanged.connect(
            self.update_min_samples_enable_state)

    def update_min_samples_enable_state(self):
        indexing_config = HexrdConfig().indexing_config
        visible = (
            indexing_config['find_orientations']['use_quaternion_grid'] is None
            and self.ui.algorithms.currentText() != 'fclusterdata'
        )

        self.ui.min_samples_label.setVisible(visible)
        self.ui.min_samples.setVisible(visible)

    def load_file(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Scored Orientations File',
            HexrdConfig().working_dir, 'NPZ files (*.npz)')

        if selected_file:
            self.ui.file_name.setText(Path(selected_file).name)
            self.ui.file_name.setToolTip(selected_file)
            with np.load(selected_file) as data:
                self.qfib = data['test_quaternions']
                self.completeness = data['score']

    def save_input(self):
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

    def accept(self):
        self.save_input()

        runner = self.indexing_runner
        worker = AsyncWorker(runner.run_cluster)
        runner.thread_pool.start(worker)
        worker.signals.result.connect(
            runner.confirm_indexing_results, Qt.QueuedConnection)
        worker.signals.finished.connect(runner.accept_progress)
        worker.signals.error.connect(runner.on_async_error)
        runner.progress_dialog.exec_()

        super().accept()

    def exec_(self):
        self.setup_gui()
        self.ui.exec_()
