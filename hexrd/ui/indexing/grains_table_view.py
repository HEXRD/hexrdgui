import numpy as np

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu, QMessageBox, QTableView

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

    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.material = None
        self.pull_spots_allowed = True
        self.can_modify_grains = False
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

        if self.can_modify_grains and self.num_selected_grains > 0:
            suffix = 's' if self.num_selected_grains > 1 else ''
            add_actions({f'Delete Grain{suffix}': self.delete_selected_grains})

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
    def grains_table(self):
        if not self.source_model:
            return None

        return self.source_model.full_grains_table

    @property
    def proxy_model(self):
        return self.model()

    @property
    def source_model(self):
        if not self.proxy_model:
            return None
        return self.proxy_model.sourceModel()

    @property
    def selected_rows(self):
        if not self.selectionModel():
            return []
        return self.selectionModel().selectedRows()

    @property
    def selected_grain_ids(self):
        # Map these rows through the proxy in case of sorting
        rows = [self.proxy_model.mapToSource(x) for x in self.selected_rows]
        return [int(self.source_model.data(x)) for x in rows]

    @property
    def selected_grains(self):
        grain_ids = self.selected_grain_ids
        if not grain_ids or self.grains_table is None:
            return None

        return self.grains_table[grain_ids]

    @property
    def num_selected_grains(self):
        return len(self.selected_grain_ids)

    @property
    def can_run_pull_spots(self):
        return (
            self.pull_spots_allowed and
            self.selected_grain_ids and
            self.material is not None and
            self.grains_table is not None
        )

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

    @property
    def num_grains(self):
        return len(self.data_model.grains_table)

    def select_tolerance_id(self):
        tolerances = self.tolerances
        if len(tolerances) == 1:
            self.selected_tol_id = 0
            return True

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

    def delete_selected_grains(self):
        if self.num_selected_grains == self.num_grains:
            # Don't let the user delete all of the grains
            msg = 'Cannot delete all grains'
            print(msg)
            QMessageBox.critical(self, 'HEXRD', msg)
            return

        self.data_model.delete_grains(self.selected_grain_ids)

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

        # Since the data is large, make sure it gets deleted when we finish
        self.spots_viewer.ui.finished.connect(self.spots_viewer.clear_data)

    def run_pull_spots_on_selected_grains(self):
        selected_grains = self.selected_grain_ids

        spots_output = {}
        for grain_id in selected_grains:
            spots_output[grain_id] = self.run_pull_spots(grain_id)

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
        if v is None:
            self.setModel(None)
            return

        self.setup_proxy()

        # A new selection model is created each time a new data model is set.
        self.selectionModel().selectionChanged.connect(
            self.on_selection_changed)

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

    def on_selection_changed(self):
        return self.selection_changed.emit()

    def on_sort_indicator_changed(self, index, order):
        """Shows sort indicator for sortable columns, hides for all others."""
        horizontal_header = self.horizontalHeader()
        if index in SORTABLE_COLUMNS:
            horizontal_header.setSortIndicatorShown(True)
            horizontal_header.setSortIndicator(index, order)
        else:
            horizontal_header.setSortIndicatorShown(False)
