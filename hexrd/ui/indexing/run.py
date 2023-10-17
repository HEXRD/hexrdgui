import copy

import numpy as np

from PySide6.QtCore import QObject, QThreadPool, Qt, Signal
from PySide6.QtWidgets import QMessageBox

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
from hexrd.ui.indexing.utils import generate_grains_table, hkls_missing_in_list
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
        self.clear_cancel_tracker()

        self.setup_connections()

    def setup_connections(self):
        self.progress_text.connect(self.progress_dialog.setLabelText)
        self.accept_progress_signal.connect(self.progress_dialog.accept)

    def update_progress_text(self, text):
        self.progress_text.emit(text)

    def accept_progress(self):
        self.accept_progress_signal.emit()

        # Hide the cancel button again
        self.progress_dialog.cancel_visible = False

    def on_async_error(self, t):
        # In case the progress dialog is open...
        self.accept_progress()

        exctype, value, traceback = t
        msg = f'An ERROR occurred: {exctype}: {value}.'
        msg_box = QMessageBox(QMessageBox.Critical, 'Error', msg)
        msg_box.setDetailedText(traceback)
        msg_box.exec()

    def reset_cancel_tracker(self):
        self.cancel_tracker = CancelTracker()

    def clear_cancel_tracker(self):
        self.cancel_tracker = None

    def on_cancel_clicked(self):
        self.cancel_tracker.need_to_cancel = True

    @property
    def operation_canceled(self):
        return self.cancel_tracker and self.cancel_tracker.need_to_cancel


class IndexingRunner(Runner):

    clustering_ran = Signal(bool)
    indexing_results_rejected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clear()

    def clear(self):
        self.ome_maps_select_dialog = None
        self.ome_maps_viewer_dialog = None
        self.indexing_results_dialog = None
        self.ome_maps = None
        self.grains_table = None
        self.is_rerunning_clustering = False

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

        indexing_config = HexrdConfig().indexing_config
        omaps = indexing_config['find_orientations']['orientation_maps']
        if dialog.method_name == 'load':
            self.ome_maps = EtaOmeMaps(dialog.file_name)
            self.ome_maps_select_dialog = None

            # Perform a little validation to ensure the plane data matches the
            # currently selected material. They should match *exactly*.
            pd = self.ome_maps.planeData
            material = get_indexing_material()

            file_hkls = pd.getHKLs().tolist()
            mat_hkls = material.planeData.getHKLs().tolist()
            missing1 = hkls_missing_in_list(mat_hkls, file_hkls)
            missing2 = hkls_missing_in_list(file_hkls, mat_hkls)
            if missing1 or missing2:
                msg = (
                    'The selected material must match the material used to '
                    'generate the eta omega maps exactly. The HKLs, however, '
                    'do not match.'
                )
                if missing1:
                    msg += (
                        '\n\nThe following hkls were found in the selected '
                        'material, but not in the file:\n\n'
                    )
                    msg += ', '.join([str(x) for x in missing1])
                if missing2:
                    msg += (
                        '\n\nThe following hkls were found in the file, '
                        'but not in the selected material:\n\n'
                    )
                    msg += ', '.join([str(x) for x in missing2])
                print(msg)
                QMessageBox.critical(self.parent, 'Error', msg)
                return

            # Save selected hkls as the active hkls. Convert them to tuples.
            omaps['active_hkls'] = pd.getHKLs(*self.ome_maps.iHKLList).tolist()

            self.ome_maps_loaded()
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
            self.progress_dialog.exec()

    def run_eta_ome_maps(self, config):
        self.ome_maps = generate_eta_ome_maps(config, save=False)

    def ome_maps_loaded(self):
        self.view_ome_maps()

    def view_ome_maps(self):
        # Now, show the Ome Map viewer
        dialog = OmeMapsViewerDialog(self.ome_maps, self.parent)
        dialog.accepted.connect(self.ome_maps_viewed)
        # Don't clear if this is rejected because we might have just
        # gone back after rejecting indexing results, and the user
        # might want to rerun the clustering.

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

        self.progress_dialog.exec()

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

        def on_finished():
            # Since this is a QueuedConnection, we must accept the progress
            # before proceeding.
            self.accept_progress()
            self.confirm_indexing_results()

        worker.signals.result.connect(on_finished, Qt.QueuedConnection)
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

        def on_rejected():
            if not self.is_rerunning_clustering:
                # If the dialog is rejected, go back to the
                # eta-omega maps viewer
                self.view_ome_maps()

            self.indexing_results_rejected.emit()

        dialog.rejected.connect(on_rejected)

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

        # Reset the local cancel tracker (used to track if we have canceled)
        self.reset_cancel_tracker()

        worker = AsyncWorker(self.run_fit_grains)
        self.thread_pool.start(worker)

        worker.signals.result.connect(self.fit_grains_finished)
        worker.signals.error.connect(self.on_async_error)
        worker.signals.finished.connect(self.accept_progress)

        self.progress_dialog.cancel_visible = True
        self.progress_dialog.cancel_clicked.connect(self.on_cancel_clicked)
        self.progress_dialog.exec()

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
        if self.cancel_tracker:
            kwargs['check_if_canceled_func'] = (
                self.cancel_tracker.get_need_to_cancel
            )

        self.fit_grains_results = fit_grains(**kwargs)
        if self.operation_canceled:
            # Operation was canceled
            return

        self.result_grains_table = create_grains_table(self.fit_grains_results)
        print('Fit Grains Complete')
        HexrdConfig().fit_grains_grains_table = copy.deepcopy(
            self.result_grains_table)

        # If we wrote out the spots, let's write out the grains.out file too
        if write_spots:
            write_fit_grains_results(self.fit_grains_results, cfg)

    def fit_grains_finished(self):
        if self.operation_canceled:
            # Operation was canceled.
            self.view_fit_grains_options()
            return

        if self.fit_grains_results is None:
            msg = 'Grain fitting failed'
            QMessageBox.information(self.parent, msg, msg)
            return

        for result in self.fit_grains_results:
            print(result)

        self.view_fit_grains_results()

    def view_fit_grains_results(self):
        find_orientations = HexrdConfig().indexing_config['find_orientations']
        quaternion_method = find_orientations.get('_quaternion_method')
        allow_export_workflow = (
            self.started_from_indexing and
            quaternion_method == 'seed_search'
        )

        kwargs = {
            'grains_table': self.result_grains_table,
            'allow_export_workflow': allow_export_workflow,
            'parent': self.parent,
        }
        dialog = create_fit_grains_results_dialog(**kwargs)
        self.fit_grains_results_dialog = dialog
        dialog.show_later()


class CancelTracker:
    """This class is used to set/get whether a cancel is needed

    This will definitely be accessed by multiple threads, and a lock
    might be necessary in the future if it becomes more complex.
    """
    def __init__(self):
        self.need_to_cancel = False

    def get_need_to_cancel(self):
        return self.need_to_cancel


def create_grains_table(fit_grains_results):
    num_grains = len(fit_grains_results)
    shape = (num_grains, 21)
    grains_table = np.empty(shape)
    gw = instrument.GrainDataWriter(array=grains_table)
    for result in fit_grains_results:
        gw.dump_grain(*result)
    gw.close()
    return grains_table


def create_fit_grains_results_dialog(grains_table, parent=None,
                                     allow_export_workflow=True):
    # Use the material to compute stress from strain
    indexing_config = HexrdConfig().indexing_config
    name = indexing_config.get('_selected_material')
    if name not in HexrdConfig().materials:
        name = HexrdConfig().active_material_name
    material = HexrdConfig().material(name)

    # Create the dialog
    kwargs = {
        'data': grains_table,
        'material': material,
        'parent': parent,
        'allow_export_workflow': allow_export_workflow,
    }
    dialog = FitGrainsResultsDialog(**kwargs)
    dialog.ui.resize(1200, 800)

    return dialog
