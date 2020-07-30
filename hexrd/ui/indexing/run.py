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
        else:
            # Create a full indexing config
            config = create_indexing_config()
            self.ome_maps = generate_eta_ome_maps(config, save=False)

        self.ome_maps_select_dialog = None
        self.view_ome_maps()

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
        self.update_progress_text('Running indexer paintGrid')
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
        self.fit_grains_dialog = dialog
        dialog.show()

    def fit_grains_options_accepted(self):
        # Create a full indexing config
        config = create_indexing_config()

        min_samples, mean_rpg = create_clustering_parameters(config,
                                                             self.ome_maps)

        kwargs = {
            'compl': self.completeness,
            'qfib': self.qfib,
            'qsym': config.material.plane_data.getQSym(),
            'cfg': config,
            'min_samples': min_samples,
            'compl_thresh': config.find_orientations.clustering.completeness,
            'radius': config.find_orientations.clustering.radius
        }
        print('Running clustering')
        qbar, cl = run_cluster(**kwargs)

        # Generate grains table
        num_grains = qbar.shape[1]
        shape = (num_grains, 21)
        grains_table = np.empty(shape)
        gw = instrument.GrainDataWriter(array=grains_table)
        for gid, q in enumerate(qbar.T):
            phi = 2*np.arccos(q[0])
            n = xfcapi.unitRowVector(q[1:])
            grain_params = np.hstack([phi*n, const.zeros_3, const.identity_6x1])
            gw.dump_grain(gid, 1., 0., grain_params)
        gw.close()

        print('Running fit_grains')
        fit_results = fit_grains(config, grains_table, write_spots_files=False)
        print('Fit Grains Complete')
        self.view_grain_fitting_results(fit_results)

    def view_grain_fitting_results(self, fit_results):
        for result in fit_results:
            print(result)
        msg = f'Fit Grains results -- length {len(fit_results)} -- written to the console'
        QMessageBox.information(None, 'Grain fitting is complete', msg)

    def update_progress_text(self, text):
        self.progress_text.emit(text)
