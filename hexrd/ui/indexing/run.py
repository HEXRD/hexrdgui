import copy

import numpy as np

from PySide2.QtCore import QObject, QThreadPool, Qt, Signal
from PySide2.QtWidgets import QMessageBox

from hexrd import indexer, instrument
from hexrd.cli.find_orientations import write_scored_orientations
from hexrd.cli.fit_grains import write_results as write_fit_grains_results
from hexrd.findorientations import (
    create_clustering_parameters, filter_maps_if_requested,
    generate_eta_ome_maps, generate_orientation_fibers, run_cluster
)
from hexrd.fitgrains import fit_grains
from hexrd.xrdutil import EtaOmeMaps

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.create_config import (
    create_indexing_config, get_indexing_material
)
from hexrd.ui.indexing.fit_grains_options_dialog import FitGrainsOptionsDialog
from hexrd.ui.indexing.fit_grains_results_dialog import FitGrainsResultsDialog
from hexrd.ui.indexing.fit_grains_select_dialog import FitGrainsSelectDialog
from hexrd.ui.indexing.indexing_results_dialog import IndexingResultsDialog
from hexrd.ui.indexing.ome_maps_select_dialog import OmeMapsSelectDialog
from hexrd.ui.indexing.ome_maps_viewer_dialog import OmeMapsViewerDialog
from hexrd.ui.indexing.utils import generate_grains_table
from hexrd.ui.progress_dialog import ProgressDialog
from hexrd.ui.utils import format_big_int


class Runner(QObject):

    progress_text = Signal(str)
    accept_progress_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        self.thread_pool = QThreadPool(self.parent)
        self.progress_dialog = ProgressDialog(self.parent)

        self.setup_connections()

    def setup_connections(self):
        self.progress_text.connect(self.progress_dialog.setLabelText)
        self.accept_progress_signal.connect(self.progress_dialog.accept)

    def update_progress_text(self, text):
        self.progress_text.emit(text)

    def accept_progress(self):
        self.accept_progress_signal.emit()

    def on_async_error(self, t):
        # In case the progress dialog is open...
        self.accept_progress()

        exctype, value, traceback = t
        msg = f'An ERROR occurred: {exctype}: {value}.'
        msg_box = QMessageBox(QMessageBox.Critical, 'Error', msg)
        msg_box.setDetailedText(traceback)
        msg_box.exec_()


class IndexingRunner(Runner):

    clustering_ran = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clear()

    def clear(self):
        self.ome_maps_select_dialog = None
        self.ome_maps_viewer_dialog = None
        self.indexing_results_dialog = None
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

        omaps = HexrdConfig().indexing_config['find_orientations']['orientation_maps']
        if dialog.method_name == 'load':
            self.ome_maps = EtaOmeMaps(dialog.file_name)
            self.ome_maps_select_dialog = None
            self.ome_maps_loaded()

            # Save selected hkls as the active hkls. Convert them to tuples.
            pd = self.ome_maps.planeData
            omaps['active_hkls'] = pd.getHKLs(*self.ome_maps.iHKLList).tolist()
        else:
            # First, save the currently selected hkls as the active hkls
            material = get_indexing_material()
            omaps['active_hkls'] = material.planeData.getHKLs().tolist()

            # Create a full indexing config
            config = create_indexing_config()

            # Setup to generate maps in background
            self.progress_dialog.setWindowTitle('Generating Eta Omega Maps')
            self.progress_dialog.setRange(0, 0)  # no numerical updates

            worker = AsyncWorker(self.run_eta_ome_maps, config)
            self.thread_pool.start(worker)

            worker.signals.result.connect(self.ome_maps_loaded)
            worker.signals.error.connect(self.on_async_error)
            worker.signals.finished.connect(self.accept_progress)
            self.progress_dialog.exec_()

    def run_eta_ome_maps(self, config):
        self.ome_maps = generate_eta_ome_maps(config, save=False)

    def ome_maps_loaded(self):
        self.view_ome_maps()

    def view_ome_maps(self):
        # Now, show the Ome Map viewer
        dialog = OmeMapsViewerDialog(self.ome_maps, self.parent)
        dialog.accepted.connect(self.ome_maps_viewed)
        dialog.rejected.connect(self.clear)
        # Show later so the dialog will move to the front on Mac
        dialog.show_later()

        self.ome_maps_viewer_dialog = dialog

    def ome_maps_viewed(self):
        find_orientations = HexrdConfig().indexing_config['find_orientations']
        dialog = self.ome_maps_viewer_dialog

        # Save the quaternion method used so we can check it in other places
        find_orientations['_quaternion_method'] = dialog.quaternion_method_name

        if dialog.quaternions_hand_picked:
            # If we did the hand-picked method, go ahead and skip now to
            # generating the grains table and running fit grains
            self.qbar = dialog.hand_picked_quaternions
            self.generate_grains_table()
            self.start_fit_grains_runner()
            return

        # The dialog should have automatically updated our internal config
        # Let's go ahead and run the indexing!

        # Create a full indexing config
        config = create_indexing_config()

        # Hexrd normally applies filtering immediately after eta omega
        # maps are loaded. We will perform the user-selected filtering now.
        filter_maps_if_requested(self.ome_maps, config)

        # Setup to run indexing in background
        self.progress_dialog.setWindowTitle('Find Orientations')
        self.progress_dialog.setRange(0, 0)  # no numerical updates

        if find_orientations['use_quaternion_grid']:
            # Load qfib from a numpy file
            self.qfib = np.load(find_orientations['use_quaternion_grid'])
            self.orientation_fibers_generated()
        else:
            worker = AsyncWorker(self.generate_orientation_fibers, config)
            self.thread_pool.start(worker)

            worker.signals.result.connect(self.orientation_fibers_generated)
            worker.signals.error.connect(self.on_async_error)

        self.progress_dialog.exec_()

    def generate_orientation_fibers(self, config):
        # Generate the orientation fibers
        self.update_progress_text('Generating orientation fibers')
        self.qfib = generate_orientation_fibers(config, self.ome_maps)

    def orientation_fibers_generated(self):
        # Perform some validation
        qfib_warning_threshold = 5e7
        if self.qfib.shape[1] > qfib_warning_threshold:
            formatted = format_big_int(self.qfib.shape[1])
            msg = (f'Over {formatted} test orientations were '
                   'generated. This may use up too much memory.\n\n'
                   'Proceed anyways?')

            response = QMessageBox.question(self.parent, 'WARNING', msg)
            if response == QMessageBox.No:
                # Go back to the eta omega maps viewer
                self.accept_progress()
                self.view_ome_maps()
                return

        worker = AsyncWorker(self.run_indexer)
        self.thread_pool.start(worker)

        worker.signals.result.connect(self.indexer_finished)
        worker.signals.error.connect(self.on_async_error)

    def run_indexer(self):
        config = create_indexing_config()

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

        orientations_cfg = HexrdConfig().indexing_config['find_orientations']
        if orientations_cfg.get('_write_scored_orientations'):
            # Write out the scored orientations
            results = {}
            results['scored_orientations'] = {
                'test_quaternions': self.qfib,
                'score': self.completeness
            }
            print(f'Writing scored orientations in {config.working_dir} ...')
            write_scored_orientations(results, config)

    def indexer_finished(self):
        # Compute number of orientations run_cluster() will use
        # to make sure there aren't too many
        config = create_indexing_config()
        min_compl = config.find_orientations.clustering.completeness
        num_orientations = (np.array(self.completeness) > min_compl).sum()

        num_orientations_warning_threshold = 1e6
        if num_orientations > num_orientations_warning_threshold:
            formatted = format_big_int(num_orientations)
            msg = (f'Over {formatted} orientations are staged for '
                   'clustering. This may use up too much memory.\n\n'
                   'Proceed anyways?')

            response = QMessageBox.question(self.parent, 'WARNING', msg)
            if response == QMessageBox.No:
                # Go back to the eta omega maps viewer
                self.accept_progress()
                self.view_ome_maps()
                return

        worker = AsyncWorker(self.run_cluster_functions)
        self.thread_pool.start(worker)

        worker.signals.result.connect(self.confirm_indexing_results,
                                      Qt.QueuedConnection)
        worker.signals.finished.connect(self.accept_progress)
        worker.signals.error.connect(self.on_async_error)

    @property
    def clustering_needs_min_samples(self):
        # Determine whether we need the min_samples for clustering
        find_orientations = HexrdConfig().indexing_config['find_orientations']
        return all((
            find_orientations['use_quaternion_grid'] is None,
            find_orientations['clustering']['algorithm'] != 'fclusterdata',
        ))

    def run_cluster_functions(self):
        if self.clustering_needs_min_samples:
            self.create_clustering_parameters()
        else:
            self.min_samples = 1

        self.run_cluster()

    def create_clustering_parameters(self):
        print('Creating cluster parameters...')
        self.update_progress_text('Creating cluster parameters')
        config = create_indexing_config()
        self.min_samples, mean_rpg = create_clustering_parameters(
            config, self.ome_maps)

    def run_cluster(self):
        print('Running cluster...')
        self.update_progress_text('Running cluster')
        config = create_indexing_config()
        kwargs = {
            'compl': self.completeness,
            'qfib': self.qfib,
            'qsym': config.material.plane_data.getQSym(),
            'cfg': config,
            'min_samples': self.min_samples,
            'compl_thresh': config.find_orientations.clustering.completeness,
            'radius': config.find_orientations.clustering.radius
        }
        self.qbar, cl = run_cluster(**kwargs)

        print('Clustering complete...')
        self.clustering_ran.emit(True)
        self.generate_grains_table()

    def generate_grains_table(self):
        self.update_progress_text('Generating grains table')
        num_grains = self.qbar.shape[1]
        if num_grains == 0:
            print('No grains found')
            return

        plural = 's' if num_grains != 1 else ''

        msg = f'{num_grains} grain{plural} found'
        self.update_progress_text(msg)
        print(msg)

        self.grains_table = generate_grains_table(self.qbar)
        HexrdConfig().find_orientations_grains_table = copy.deepcopy(
            self.grains_table)

    def confirm_indexing_results(self):
        if self.grains_table is None:
            msg = 'No grains found'
            QMessageBox.critical(self.parent, msg, msg)
            return

        dialog = IndexingResultsDialog(self.ome_maps, self.grains_table,
                                       self.parent)

        # We will automatically start fit grains after the indexing
        # is complete. The user can cancel this if they don't want to do it.
        dialog.accepted.connect(self.start_fit_grains_runner)

        # Show later so the dialog will move to the front on Mac
        dialog.show_later()
        self.indexing_results_dialog = dialog

    def start_fit_grains_runner(self):
        if self.grains_table is None:
            msg = 'No grains found'
            QMessageBox.critical(self.parent, msg, msg)
            return

        kwargs = {
            'grains_table': self.grains_table,
            'indexing_runner': self,
            'started_from_indexing': True,
            'parent': self.parent,
        }
        runner = self._fit_grains_runner = FitGrainsRunner(**kwargs)
        runner.run()


class FitGrainsRunner(Runner):

    def __init__(self, grains_table=None, indexing_runner=None,
                 started_from_indexing=False, parent=None):
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
        self.started_from_indexing = started_from_indexing
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
        find_orientations = HexrdConfig().indexing_config['find_orientations']
        quaternion_method = find_orientations.get('_quaternion_method')
        ensure_hkl_seeds_not_excluded = (
            self.started_from_indexing and
            quaternion_method == 'seed_search'
        )

        # Run dialog for user options
        kwargs = {
            'grains_table': self.grains_table,
            'ensure_seed_hkls_not_excluded': ensure_hkl_seeds_not_excluded,
            'parent': self.parent,
        }
        dialog = FitGrainsOptionsDialog(**kwargs)
        dialog.accepted.connect(self.fit_grains_options_accepted)
        dialog.rejected.connect(self.clear)

        def on_grains_table_modified():
            # Update our grains table
            self.grains_table = dialog.grains_table

        dialog.grains_table_modified.connect(on_grains_table_modified)
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
        worker.signals.finished.connect(self.accept_progress)
        self.progress_dialog.exec_()

    def run_fit_grains(self):
        cfg = create_indexing_config()
        write_spots = HexrdConfig().indexing_config.get('_write_spots', False)

        num_grains = self.grains_table.shape[0]
        self.update_progress_text(f'Running fit grains on {num_grains} grains')
        kwargs = {
            'cfg': cfg,
            'grains_table': self.grains_table,
            'write_spots_files': write_spots,
        }
        self.fit_grains_results = fit_grains(**kwargs)
        self.result_grains_table = create_grains_table(self.fit_grains_results)
        print('Fit Grains Complete')
        HexrdConfig().fit_grains_grains_table = copy.deepcopy(
            self.result_grains_table)

        # If we wrote out the spots, let's write out the grains.out file too
        if write_spots:
            write_fit_grains_results(self.fit_grains_results, cfg)

    def view_fit_grains_results(self):
        if self.fit_grains_results is None:
            msg = 'Grain fitting failed'
            QMessageBox.information(self.parent, msg, msg)
            return

        for result in self.fit_grains_results:
            print(result)

        kwargs = {
            'grains_table': self.result_grains_table,
            'parent': self.parent,
        }
        dialog = create_fit_grains_results_dialog(**kwargs)
        self.fit_grains_results_dialog = dialog
        dialog.show_later()


def create_grains_table(fit_grains_results):
    num_grains = len(fit_grains_results)
    shape = (num_grains, 21)
    grains_table = np.empty(shape)
    gw = instrument.GrainDataWriter(array=grains_table)
    for result in fit_grains_results:
        gw.dump_grain(*result)
    gw.close()
    return grains_table


def create_fit_grains_results_dialog(grains_table, parent=None):
    # Use the material to compute stress from strain
    indexing_config = HexrdConfig().indexing_config
    name = indexing_config.get('_selected_material')
    if name not in HexrdConfig().materials:
        name = HexrdConfig().active_material_name
    material = HexrdConfig().material(name)

    # Create the dialog
    dialog = FitGrainsResultsDialog(grains_table, material, parent)
    dialog.ui.resize(1200, 800)

    return dialog
