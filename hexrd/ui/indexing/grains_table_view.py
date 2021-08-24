import numpy as np

from PySide2.QtGui import QCursor
from PySide2.QtWidgets import QMenu, QTableView

from hexrd.ui.async_runner import AsyncRunner
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.create_config import create_indexing_config
from hexrd.ui.indexing.view_spots_dialog import ViewSpotsDialog


class GrainsTableView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.material = None
        self.grains_table = None

        self.async_runner = AsyncRunner(parent)

        # Set our selection behavior
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.ExtendedSelection)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        actions = {}

        def add_actions(d):
            actions.update({menu.addAction(k): v for k, v in d.items()})

        if self.can_run_pull_spots:
            add_actions({'Visualize Spots': self.pull_spots})

        if not actions:
            return super().contextMenuEvent(event)

        action_chosen = menu.exec_(QCursor.pos())

        if action_chosen is None:
            # No action chosen
            return super().contextMenuEvent(event)

        # Run the function for the action that was chosen
        actions[action_chosen]()

        return super().contextMenuEvent(event)

    @property
    def proxy_model(self):
        return self.model()

    @property
    def results_model(self):
        return self.proxy_model.sourceModel()

    @property
    def selected_rows(self):
        return self.selectionModel().selectedRows()

    @property
    def selected_grain_ids(self):
        rows = self.selectionModel().selectedRows()
        # Map these rows through the proxy in case of sorting
        rows = [self.proxy_model.mapToSource(x) for x in rows]
        return [int(self.results_model.data(x)) for x in rows]

    @property
    def can_run_pull_spots(self):
        return all((
            self.selected_grain_ids,
            self.material is not None,
            self.grains_table is not None,
        ))

    def pull_spots(self):
        num_grains = len(self.selected_grain_ids)
        grain_str = 'grains' if num_grains != 1 else 'grain'
        title = f'Running pull_spots() on {num_grains} {grain_str}'
        self.async_runner.progress_title = title
        self.async_runner.success_callback = self.visualize_spots
        self.async_runner.run(self.run_pull_spots_on_selected_grains)

    def visualize_spots(self, spots):
        self.spots_viewer = ViewSpotsDialog(spots, self)
        self.spots_viewer.ui.show()

    def run_pull_spots_on_selected_grains(self):
        selected_grains = self.selected_grain_ids

        # Default to using the last tolerance. We should let the user
        # choose this in the future.
        tol_id = -1
        spots_output = {}
        for grain_id in selected_grains:
            spots_output[grain_id] = self.run_pull_spots(grain_id, tol_id)

        return spots_output

    def run_pull_spots(self, grain_id, tol_id):
        grain_params = self.grains_table[grain_id][3:15]

        # Prevent an exception...
        indexing_config = HexrdConfig().indexing_config
        if indexing_config.get('_selected_material') is None:
            indexing_config['_selected_material'] = self.material.name

        cfg = create_indexing_config()

        instr = cfg.instrument.hedm
        imsd = cfg.image_series
        tolerance = cfg.fit_grains.tolerance

        # Use this plane data rather than the one in the config.
        # This should be set to whatever the fit grains viewer is
        # using, which may be different than the one in the config
        # if the user loaded a grains.out file instead of running
        # through the HEDM workflow.
        plane_data = self.material.planeData

        # Omega period
        oims = next(iter(imsd.values()))
        ome_period = np.radians(oims.omega[0, 0] + np.r_[0., 360.])

        kwargs = {
            'plane_data': plane_data,
            'grain_params': grain_params,
            'tth_tol': tolerance.tth[tol_id],
            'eta_tol': tolerance.eta[tol_id],
            'ome_tol': tolerance.omega[tol_id],
            'imgser_dict': imsd,
            'npdiv': cfg.fit_grains.npdiv,
            'threshold': cfg.fit_grains.threshold,
            'eta_ranges': np.radians(cfg.find_orientations.eta.range),
            'ome_period': ome_period,
            'dirname': cfg.analysis_dir,
            'filename': None,
            'return_spot_list': True,
            'quiet': True,
            'check_only': False,
            'interp': 'nearest',
        }
        return instr.pull_spots(**kwargs)
