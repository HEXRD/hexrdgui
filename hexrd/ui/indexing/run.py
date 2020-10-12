import os

import numpy as np

from PySide2.QtCore import QObject, QThreadPool, Signal
from PySide2.QtWidgets import QMessageBox

from hexrd import constants as const
from hexrd import fitgrains, indexer, instrument
from hexrd.findorientations import (
    create_clustering_parameters, find_orientations,
    generate_eta_ome_maps, generate_orientation_fibers,
    run_cluster
)
from hexrd.fitgrains import fit_grains
from hexrd.transforms import xfcapi
from hexrd.xrdutil import EtaOmeMaps

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.create_config import create_indexing_config
from hexrd.ui.indexing.fit_grains_options_dialog import FitGrainsOptionsDialog
from hexrd.ui.indexing.fit_grains_results_dialog import FitGrainsResultsDialog
from hexrd.ui.indexing.ome_maps_select_dialog import OmeMapsSelectDialog
from hexrd.ui.indexing.ome_maps_viewer_dialog import OmeMapsViewerDialog
from hexrd.ui.progress_dialog import ProgressDialog


class IndexingRunner(QObject):
    progress_text = Signal(str)

    def __init__(self, parent=None):
        super(IndexingRunner, self).__init__(parent)

        self.parent = parent
        self.ome_maps_select_dialog = None
        self.ome_maps_viewer_dialog = None
        self.fit_grains_dialog = None
        self.fit_grains_results = None
        self.thread_pool = QThreadPool(self.parent)
        self.progress_dialog = ProgressDialog(self.parent)

        self.ome_maps = None
        self.progress_text.connect(self.progress_dialog.setLabelText)

    def clear(self):
        self.ome_maps_select_dialog = None
        self.ome_maps_viewer_dialog = None
        self.fit_grains_dialog = None

        self.ome_maps = None

    def run(self):
        # We will go through these steps:
        # 1. Have the user select/generate eta omega maps
        # 2. Have the user view and threshold the eta omega maps
        # 3. Run the indexing
        self.select_ome_maps()

    def select_ome_maps(self):
        dialog = OmeMapsSelectDialog(self.parent)
        dialog.accepted.connect(self.ome_maps_selected)
        dialog.rejected.connect(self.clear)
        dialog.show()
        self.ome_maps_select_dialog = dialog

    def ome_maps_selected(self):
        dialog = self.ome_maps_select_dialog
        if dialog is None:
            return

        if dialog.method_name == 'load':
            self.ome_maps = EtaOmeMaps(dialog.file_name)
            self.ome_maps_select_dialog = None
            self.view_ome_maps()
        else:
            # Create a full indexing config
            config = create_indexing_config()

            # Setup to generate maps in background
            self.progress_dialog.setWindowTitle('Generating Eta Omega Maps')
            self.progress_dialog.setRange(0, 0)  # no numerical updates

            worker = AsyncWorker(self.run_eta_ome_maps, config)
            self.thread_pool.start(worker)

            worker.signals.result.connect(self.view_ome_maps)
            worker.signals.finished.connect(self.progress_dialog.accept)
            self.progress_dialog.exec_()

    def run_eta_ome_maps(self, config):
        self.ome_maps = generate_eta_ome_maps(config, save=False)

    def view_ome_maps(self):
        # Now, show the Ome Map viewer

        dialog = OmeMapsViewerDialog(self.ome_maps, self.parent)
        dialog.accepted.connect(self.ome_maps_viewed)
        dialog.rejected.connect(self.clear)
        dialog.show()

        self.ome_maps_viewer_dialog = dialog

    def ome_maps_viewed(self):
        # The dialog should have automatically updated our internal config
        # Let's go ahead and run the indexing!

        # For now, always use all hkls from eta omega maps
        hkls = list(range(len(self.ome_maps.iHKLList)))
        indexing_config = HexrdConfig().indexing_config
        indexing_config['find_orientations']['seed_search']['hkl_seeds'] = hkls

        # Create a full indexing config
        config = create_indexing_config()

        # Setup to run indexing in background
        self.progress_dialog.setWindowTitle('Find Orientations')
        self.progress_dialog.setRange(0, 0)  # no numerical updates

        worker = AsyncWorker(self.run_indexer, config)
        self.thread_pool.start(worker)

        worker.signals.result.connect(self.view_fit_grains_options)
        worker.signals.finished.connect(self.progress_dialog.accept)
        self.progress_dialog.exec_()

    def run_indexer(self, config):
        # Generate the orientation fibers
        self.update_progress_text('Generating orientation fibers')
        self.qfib = generate_orientation_fibers(config, self.ome_maps)

        # Find orientations
        self.update_progress_text('Running indexer (paintGrid)')
        ncpus = config.multiprocessing
        self.completeness = indexer.paintGrid(
            self.qfib,
            self.ome_maps,
            etaRange=np.radians(config.find_orientations.eta.range),
            omeTol=np.radians(config.find_orientations.omega.tolerance),
            etaTol=np.radians(config.find_orientations.eta.tolerance),
            omePeriod=np.radians(config.find_orientations.omega.period),
            threshold=config.find_orientations.threshold,
            doMultiProc=ncpus > 1,
            nCPUs=ncpus)
        print('Indexing complete')

    def view_fit_grains_options(self):
        # Run dialog for user options
        dialog = FitGrainsOptionsDialog(self.parent)
        dialog.accepted.connect(self.fit_grains_options_accepted)
        dialog.rejected.connect(self.clear)
        self.fit_grains_options_dialog = dialog
        dialog.show()

    def fit_grains_options_accepted(self):
        # Create a full indexing config
        config = create_indexing_config()

        # Setup to run in background
        self.progress_dialog.setWindowTitle('Fit Grains')
        self.progress_dialog.setRange(0, 0)  # no numerical updates

        worker = AsyncWorker(self.run_fit_grains, config)
        self.thread_pool.start(worker)

        worker.signals.result.connect(self.view_fit_grains_results)
        worker.signals.error.connect(self.on_async_error)
        worker.signals.finished.connect(self.progress_dialog.accept)
        self.progress_dialog.exec_()

    def run_fit_grains(self, config):
        self.fit_grains_results = None
        min_samples, mean_rpg = create_clustering_parameters(config,
                                                             self.ome_maps)

        # Add fit_grains config
        dialog_config = HexrdConfig().indexing_config['fit_grains']
        config.set('fitgrains:npdiv', dialog_config['npdiv'])
        config.set('fitgrains:refit', dialog_config['refit'])
        config.set('fitgrains:threshold', dialog_config['threshold'])
        config.set('fitgrains:tth_max', dialog_config['tth_max'])
        config.set('fitgrains:tolerance:tth', dialog_config['tth_tolerances'])
        config.set('fitgrains:tolerance:eta', dialog_config['eta_tolerances'])
        config.set(
            'fitgrains:tolerance:omega', dialog_config['omega_tolerances'])

        kwargs = {
            'compl': self.completeness,
            'qfib': self.qfib,
            'qsym': config.material.plane_data.getQSym(),
            'cfg': config,
            'min_samples': min_samples,
            'compl_thresh': config.find_orientations.clustering.completeness,
            'radius': config.find_orientations.clustering.radius
        }
        self.update_progress_text('Running clustering')
        qbar, cl = run_cluster(**kwargs)

        # Generate grains table
        num_grains = qbar.shape[1]
        if num_grains == 0:
            print('Fit Grains Complete - no grains were found')
            return

        shape = (num_grains, 21)
        grains_table = np.empty(shape)
        gw = instrument.GrainDataWriter(array=grains_table)
        for gid, q in enumerate(qbar.T):
            phi = 2*np.arccos(q[0])
            n = xfcapi.unitRowVector(q[1:])
            grain_params = np.hstack([phi*n, const.zeros_3, const.identity_6x1])
            gw.dump_grain(gid, 1., 0., grain_params)
        gw.close()

        self.update_progress_text(f'Found {num_grains} grains. Running fit optimization.')

        self.fit_grains_results = fit_grains(config, grains_table, write_spots_files=False)
        print('Fit Grains Complete')

    def view_fit_grains_results(self):
        if self.fit_grains_results is None:
            QMessageBox.information(
                self.parent, "No Grains Fond", "No grains were found")
            return

        for result in self.fit_grains_results:
            print(result)

        # Build grains table
        num_grains = len(self.fit_grains_results)
        shape = (num_grains, 21)
        grains_table = np.empty(shape)
        gw = instrument.GrainDataWriter(array=grains_table)
        for result in self.fit_grains_results:
            gw.dump_grain(*result)
        gw.close()

        # Display results dialog
        dialog = FitGrainsResultsDialog(grains_table, self.parent)
        dialog.ui.resize(1200, 800)
        self.fit_grains_results_dialog = dialog
        dialog.show()

    def update_progress_text(self, text):
        self.progress_text.emit(text)

    def on_async_error(self, t):
        exctype, value, traceback = t
        msg = f'An ERROR occurred: {exctype}: {value}.'
        msg_box = QMessageBox(QMessageBox.Critical, 'Error', msg)
        msg_box.setDetailedText(traceback)
        msg_box.exec_()
