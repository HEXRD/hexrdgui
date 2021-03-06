import numpy as np

from PySide2.QtCore import QObject, QThreadPool, Signal
from PySide2.QtWidgets import QMessageBox

from hexrd import indexer, instrument
from hexrd.findorientations import (
    create_clustering_parameters, generate_eta_ome_maps,
    generate_orientation_fibers, run_cluster
)
from hexrd.fitgrains import fit_grains
from hexrd.xrdutil import EtaOmeMaps

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.create_config import create_indexing_config
from hexrd.ui.indexing.fit_grains_options_dialog import FitGrainsOptionsDialog
from hexrd.ui.indexing.fit_grains_results_dialog import FitGrainsResultsDialog
from hexrd.ui.indexing.fit_grains_select_dialog import FitGrainsSelectDialog
from hexrd.ui.indexing.ome_maps_select_dialog import OmeMapsSelectDialog
from hexrd.ui.indexing.ome_maps_viewer_dialog import OmeMapsViewerDialog
from hexrd.ui.indexing.utils import generate_grains_table
from hexrd.ui.progress_dialog import ProgressDialog


class Runner(QObject):
    progress_text = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        self.thread_pool = QThreadPool(self.parent)
        self.progress_dialog = ProgressDialog(self.parent)

        self.progress_text.connect(self.progress_dialog.setLabelText)

    def update_progress_text(self, text):
        self.progress_text.emit(text)

    def on_async_error(self, t):
        exctype, value, traceback = t
        msg = f'An ERROR occurred: {exctype}: {value}.'
        msg_box = QMessageBox(QMessageBox.Critical, 'Error', msg)
        msg_box.setDetailedText(traceback)
        msg_box.exec_()


class IndexingRunner(Runner):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.clear()

    def clear(self):
        self.ome_maps_select_dialog = None
        self.ome_maps_viewer_dialog = None
        self.ome_maps = None
        self.grains_table = None

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

        worker.signals.result.connect(self.start_fit_grains_runner)
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
        print('paintGrid complete')
        self.run_clustering()

    def run_clustering(self):
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
        self.update_progress_text('Running clustering')
        self.qbar, cl = run_cluster(**kwargs)

        print('Clustering complete...')
        self.generate_grains_table()

    def generate_grains_table(self):
        self.update_progress_text('Generating grains table')
        num_grains = self.qbar.shape[1]
        if num_grains == 0:
            print('No grains found')
            return

        msg = f'{num_grains} grains found'
        self.update_progress_text(msg)
        print(msg)

        self.grains_table = generate_grains_table(self.qbar)

    def start_fit_grains_runner(self):
        # We will automatically start fit grains after the indexing
        # is complete. The user can cancel this if they don't want to do it.
        if self.grains_table is None:
            msg = 'No grains found'
            QMessageBox.critical(self.parent, msg, msg)
            return

        kwargs = {
            'grains_table': self.grains_table,
            'indexing_runner': self,
            'parent': self.parent,
        }
        runner = self._fit_grains_runner = FitGrainsRunner(**kwargs)
        runner.run()


class FitGrainsRunner(Runner):

    def __init__(self, grains_table=None, indexing_runner=None, parent=None):
        """
        If the grains_table is set, the user will not be asked to specify a
        grains table. Otherwise, a dialog will appear asking the user to
        provide a grains table.

        If the indexing_runner is set, and the grains_table is not set, then
        an option for the grains table will be to use the one found on the
        indexing runner.
        """
        super().__init__(parent)
        self.grains_table = grains_table
        self.indexing_runner = indexing_runner
        self.clear()

    def clear(self):
        self.fit_grains_select_dialog = None
        self.fit_grains_options_dialog = None
        self.fit_grains_results = None

    def run(self):
        # We will go through these steps:
        # 1. If the table is not set, get the user to select one
        # 2. Display the fit grains options
        # 3. Run fit grains
        # 4. View the results
        self.select_grains_table()

    def select_grains_table(self):
        if self.grains_table is not None:
            # The grains table is already set. Go ahead to the options.
            self.view_fit_grains_options()
            return

        dialog = FitGrainsSelectDialog(self.indexing_runner, self.parent)
        dialog.accepted.connect(self.grains_table_selected)
        dialog.rejected.connect(self.clear)
        dialog.show()
        self.fit_grains_select_dialog = dialog

    def grains_table_selected(self):
        self.grains_table = self.fit_grains_select_dialog.grains_table
        self.view_fit_grains_options()

    def view_fit_grains_options(self):
        # Run dialog for user options
        dialog = FitGrainsOptionsDialog(self.parent)
        dialog.accepted.connect(self.fit_grains_options_accepted)
        dialog.rejected.connect(self.clear)
        self.fit_grains_options_dialog = dialog
        dialog.show()

    def fit_grains_options_accepted(self):
        # Setup to run in background
        self.progress_dialog.setWindowTitle('Running Fit Grains')
        self.progress_dialog.setRange(0, 0)  # no numerical updates

        worker = AsyncWorker(self.run_fit_grains)
        self.thread_pool.start(worker)

        worker.signals.result.connect(self.view_fit_grains_results)
        worker.signals.error.connect(self.on_async_error)
        worker.signals.finished.connect(self.progress_dialog.accept)
        self.progress_dialog.exec_()

    def run_fit_grains(self):
        num_grains = self.grains_table.shape[0]
        self.update_progress_text(f'Running fit grains on {num_grains} grains')
        kwargs = {
            'cfg': create_indexing_config(),
            'grains_table': self.grains_table,
            'write_spots_files': False,
        }
        self.fit_grains_results = fit_grains(**kwargs)
        print('Fit Grains Complete')

    def view_fit_grains_results(self):
        if self.fit_grains_results is None:
            msg = 'Grain fitting failed'
            QMessageBox.information(self.parent, msg, msg)
            return

        for result in self.fit_grains_results:
            print(result)

        kwargs = {
            'fit_grains_results': self.fit_grains_results,
            'parent': self.parent,
        }
        dialog = create_fit_grains_results_dialog(**kwargs)
        self.fit_grains_results_dialog = dialog
        dialog.show()


def create_fit_grains_results_dialog(fit_grains_results, parent=None):
    # Build grains table
    num_grains = len(fit_grains_results)
    shape = (num_grains, 21)
    grains_table = np.empty(shape)
    gw = instrument.GrainDataWriter(array=grains_table)
    for result in fit_grains_results:
        gw.dump_grain(*result)
    gw.close()

    # Use the material to compute stress from strain
    material = HexrdConfig().active_material

    # Create the dialog
    dialog = FitGrainsResultsDialog(grains_table, material, parent)
    dialog.ui.resize(1200, 800)

    return dialog
