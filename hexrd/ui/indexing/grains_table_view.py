import numpy as np

from PySide2.QtCore import QSortFilterProxyModel, Qt
from PySide2.QtGui import QCursor
from PySide2.QtWidgets import QMenu, QTableView

from hexrd.xrdutil import _memo_hkls

from hexrd.ui.async_runner import AsyncRunner
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.create_config import create_indexing_config
from hexrd.ui.indexing.view_spots_dialog import ViewSpotsDialog
from hexrd.ui.table_selector_widget import TableSingleRowSelectorDialog


# Sortable columns are grain id, completeness, chi^2, and t_vec_c
SORTABLE_COLUMNS = [
    *range(0, 3),
    *range(6, 9),
]


class GrainsTableView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.material = None
        self.grains_table = None
        self._data_model = None
        self._tolerances = []
        self.selected_tol_id = -1

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

    @property
    def tolerances(self):
        if self._tolerances:
            return self._tolerances

        cfg = create_indexing_config()
        tolerance = cfg.fit_grains.tolerance
        res = []
        for i in range(len(tolerance.tth)):
            res.append({
                'tth': tolerance.tth[i],
                'eta': tolerance.eta[i],
                'ome': tolerance.omega[i],
            })
        return res

    @tolerances.setter
    def tolerances(self, v):
        self._tolerances = v

    def select_tolerance_id(self):
        tolerances = self.tolerances
        headers = ['tth', 'eta', 'ome']
        data = np.empty((len(tolerances), len(headers)), dtype=np.float64)
        for i, tol in enumerate(tolerances):
            for j, header in enumerate(headers):
                data[i, j] = tolerances[i][header]

        dialog = TableSingleRowSelectorDialog(self)
        dialog.table.data = data
        dialog.table.horizontal_headers = headers
        dialog.setWindowTitle('Select tolerances to use')

        if not dialog.exec_():
            return False

        self.selected_tol_id = dialog.selected_row
        return True

    def pull_spots(self):
        if not self.select_tolerance_id():
            # User canceled
            return

        num_grains = len(self.selected_grain_ids)
        grain_str = 'grains' if num_grains != 1 else 'grain'
        title = f'Running pull_spots() on {num_grains} {grain_str}'
        self.async_runner.progress_title = title
        self.async_runner.success_callback = self.visualize_spots
        self.async_runner.run(self.run_pull_spots_on_selected_grains)

    def visualize_spots(self, spots):
        self.spots_viewer = ViewSpotsDialog(spots, self)
        self.spots_viewer.tolerances = self.tolerances[self.selected_tol_id]
        self.spots_viewer.ui.show()

    def run_pull_spots_on_selected_grains(self):
        # Make sure memoized hkls are removed before and after running
        # pull_spots(). If pull_spots() was called earlier with different
        # exclusions, then we would get the wrong answer from pull_spots()
        # unless we cleared these memo hkls.
        _memo_hkls.clear()

        selected_grains = self.selected_grain_ids

        spots_output = {}
        try:
            for grain_id in selected_grains:
                spots_output[grain_id] = self.run_pull_spots(grain_id)
        finally:
            _memo_hkls.clear()

        return spots_output

    def run_pull_spots(self, grain_id):
        grain_params = self.grains_table[grain_id][3:15]

        # Prevent an exception...
        indexing_config = HexrdConfig().indexing_config
        if indexing_config.get('_selected_material') is None:
            indexing_config['_selected_material'] = self.material.name

        cfg = create_indexing_config()

        instr = cfg.instrument.hedm
        imsd = cfg.image_series

        tol_id = self.selected_tol_id
        tolerances = self.tolerances
        tth_tol = tolerances[tol_id]['tth']
        eta_tol = tolerances[tol_id]['eta']
        ome_tol = tolerances[tol_id]['ome']

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
            'tth_tol': tth_tol,
            'eta_tol': eta_tol,
            'ome_tol': ome_tol,
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

    @property
    def data_model(self):
        return self._data_model

    @data_model.setter
    def data_model(self, v):
        self._data_model = v
        self.setup_proxy()

    def setup_proxy(self):

        # Subclass QSortFilterProxyModel to restrict sorting by column
        class GrainsTableSorter(QSortFilterProxyModel):
            def sort(self, column, order):
                if column not in SORTABLE_COLUMNS:
                    return
                return super().sort(column, order)

        proxy_model = GrainsTableSorter(self)
        proxy_model.setSourceModel(self.data_model)
        self.verticalHeader().hide()
        self.setModel(proxy_model)
        self.resizeColumnToContents(0)

        self.setSortingEnabled(True)
        self.horizontalHeader().sortIndicatorChanged.connect(
            self.on_sort_indicator_changed)
        self.sortByColumn(0, Qt.AscendingOrder)
        self.horizontalHeader().setSortIndicatorShown(False)

    def on_sort_indicator_changed(self, index, order):
        """Shows sort indicator for sortable columns, hides for all others."""
        horizontal_header = self.horizontalHeader()
        if index in SORTABLE_COLUMNS:
            horizontal_header.setSortIndicatorShown(True)
            horizontal_header.setSortIndicator(index, order)
        else:
            horizontal_header.setSortIndicatorShown(False)
