import copy
import numpy as np
from pathlib import Path

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader

from PySide2.QtWidgets import QFileDialog
from PySide2.QtCore import Qt


class RerunClusteringDialog:

    def __init__(self, indexing_runner, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('rerun_clustering_dialog.ui', parent)
        self.indexing_runner = indexing_runner
        self.scored_orientations = None
        self.setup_gui()
        self.setup_connections()

    def setup_gui(self):
        idx_cfg = HexrdConfig().indexing_config['find_orientations']
        clustering_data = idx_cfg.get('clustering', {})
        self.ui.radius.setValue(clustering_data.get('radius', 1.0))
        self.ui.completeness.setValue(
            clustering_data.get('completeness', 0.85))
        self.ui.algorithms.setCurrentText(
            clustering_data.get('algorithm', 'dbscan'))
        needs_min_samples = getattr(
            self.indexing_runner, 'clustering_needs_min_samples', False)
        self.ui.min_samples_label.setEnabled(needs_min_samples)
        self.ui.min_samples.setEnabled(needs_min_samples)
        if self.ui.min_samples.isEnabled():
            self.ui.min_samples.setValue(self.indexing_runner.min_samples)

    def setup_connections(self):
        self.ui.load_file.clicked.connect(self.load_file)
        self.ui.buttonBox.accepted.connect(self.on_accepted)

    def load_file(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Scored Orientations File',
            HexrdConfig().working_dir, 'NPZ files (*.npz)')

        if selected_file:
            self.ui.file_name.setText(Path(selected_file).name)
            self.ui.file_name.setToolTip(selected_file)
            with np.load(selected_file) as data:
                self.indexing_runner.qfib = data['test_quaternions']
                self.indexing_runner.completeness = data['score']

    def save_input(self):
        idx_cfg = copy.deepcopy(HexrdConfig().indexing_config)
        clustering = idx_cfg['find_orientations'].get('clustering', {})
        clustering['radius'] = self.ui.radius.value()
        clustering['completeness'] = self.ui.completeness.value()
        clustering['algorithm'] = self.ui.algorithms.currentText()
        HexrdConfig().indexing_config['find_orientations']['clustering'] = (
            clustering)
        if self.ui.min_samples.isEnabled():
            self.indexing_runner.min_samples = self.ui.min_samples.value()

    def on_accepted(self):
        self.save_input()
        worker = AsyncWorker(self.indexing_runner.run_cluster)
        self.indexing_runner.thread_pool.start(worker)
        worker.signals.result.connect(
            self.indexing_runner.start_fit_grains_runner, Qt.QueuedConnection)
        worker.signals.finished.connect(self.indexing_runner.accept_progress)
        worker.signals.error.connect(self.indexing_runner.on_async_error)
        self.indexing_runner.progress_dialog.exec_()

    def show(self):
        self.setup_gui()
        self.ui.exec_()
