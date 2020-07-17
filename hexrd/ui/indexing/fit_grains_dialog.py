from PySide2.QtCore import (
    QItemSelectionModel, QObject, QSignalBlocker, Qt, Signal, Slot)
from PySide2.QtWidgets import QHeaderView

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader

from hexrd.ui.indexing.fit_grains_tolerances_model import (
    FitGrainsToleranceModel)

DEBUG = True


class FitGrainsDialog(QObject):
    finished = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        config = HexrdConfig().indexing_config['fit_grains']
        if config.get('do_fit') is False:
            return

        loader = UiLoader()
        self.ui = loader.load_file('fit_grains_dialog.ui', parent)
        self.ui.setWindowTitle('Fit Grains')
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        if DEBUG:
            import importlib
            import hexrd.ui.indexing.fit_grains_tolerances_model
            importlib.reload(hexrd.ui.indexing.fit_grains_tolerances_model)
            from hexrd.ui.indexing.fit_grains_tolerances_model import (
                FitGrainsToleranceModel)

        self.tolerances_model = FitGrainsToleranceModel(self.ui)
        self.update_gui_from_config(config)
        self.ui.tolerances_view.setModel(self.tolerances_model)

        # Stretch columns to fill the available horizontal space
        num_cols = self.tolerances_model.columnCount()
        for i in range(num_cols):
            self.ui.tolerances_view.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.Stretch)

        # Setup connections
        self.ui.finished.connect(self.finished)
        self.ui.tth_max_enable.toggled.connect(self.on_tth_max_toggled)
        self.ui.tth_max_specify.toggled.connect(self.on_tth_specify_toggled)
        self.ui.tolerances_view.selectionModel().selectionChanged.connect(
            self.on_tolerances_select)
        self.ui.add_row.clicked.connect(self.on_tolerances_add_row)
        self.ui.delete_row.clicked.connect(self.on_tolerances_delete_row)
        self.ui.move_up.clicked.connect(self.on_tolerances_move_up)
        self.ui.move_down.clicked.connect(self.on_tolerances_move_down)

    def all_widgets(self):
        """Only includes widgets directly related to config parameters"""
        widgets = [
            self.ui.npdiv,
            self.ui.refit_ome_step_scale,
            self.ui.refit_pixel_scale,
            self.ui.tolerances_view,
            self.ui.threshold,
            self.ui.tth_max_enable,
            self.ui.tth_max_instrument,
            self.ui.tth_max_specify,
            self.ui.tth_max_value,
        ]
        return widgets

    @Slot()
    def on_tolerances_add_row(self):
        new_row_num = self.tolerances_model.rowCount()
        self.tolerances_model.add_row()

        # Select first column of new row
        self.ui.tolerances_view.setFocus(Qt.OtherFocusReason)
        self.ui.tolerances_view.selectionModel().clear()
        model_index = self.tolerances_model.index(new_row_num, 0)
        self.ui.tolerances_view.selectionModel().setCurrentIndex(
            model_index, QItemSelectionModel.Select)
        # Have to repaint - is that because we are in a modal dialog?
        self.ui.tolerances_view.repaint(self.ui.tolerances_view.rect())

    @Slot()
    def on_tolerances_delete_row(self):
        rows = self._get_selected_rows()
        self.tolerances_model.delete_rows(rows)
        self.ui.tolerances_view.selectionModel().clear()
        self.ui.tolerances_view.repaint(self.ui.tolerances_view.rect())

    @Slot()
    def on_tolerances_move_down(self):
        rows = self._get_selected_rows()
        self.tolerances_model.move_rows(rows, 1)
        self.ui.tolerances_view.selectionModel().clear()
        self.ui.tolerances_view.repaint(self.ui.tolerances_view.rect())

    @Slot()
    def on_tolerances_move_up(self):
        rows = self._get_selected_rows()
        self.tolerances_model.move_rows(rows, -1)
        self.ui.tolerances_view.selectionModel().clear()
        self.ui.tolerances_view.repaint(self.ui.tolerances_view.rect())

    @Slot()
    def on_tolerances_select(self):
        """Sets button enable states based on current selection"""
        delete_enable = False
        up_enable = False
        down_enable = False

        # Get list of selected rows
        selected_rows = self._get_selected_rows()
        if selected_rows:
            delete_enable = True

            # Are selected rows contiguous?
            num_selected = len(selected_rows)
            span = selected_rows[-1] - selected_rows[0] + 1
            is_contiguous = num_selected == span
            if is_contiguous:
                up_enable = selected_rows[0] > 0
                last_row = self.tolerances_model.rowCount() - 1
                down_enable = selected_rows[-1] < last_row

        self.ui.delete_row.setEnabled(delete_enable)
        self.ui.move_up.setEnabled(up_enable)
        self.ui.move_down.setEnabled(down_enable)

    @Slot(bool)
    def on_tth_max_toggled(self, checked):
        enabled = checked
        self.ui.tth_max_instrument.setEnabled(enabled)
        self.ui.tth_max_specify.setEnabled(enabled)
        specify = self.ui.tth_max_specify.isChecked()
        self.ui.tth_max_value.setEnabled(enabled and specify)

    @Slot(bool)
    def on_tth_specify_toggled(self, checked):
        self.ui.tth_max_value.setEnabled(checked)

    def update_gui_from_config(self, config):
        blocked = [QSignalBlocker(x) for x in self.all_widgets()]
        self.ui.npdiv.setValue(config.get('npdiv'))
        self.ui.refit_ome_step_scale.setValue(config.get('refit')[1])
        self.ui.refit_pixel_scale.setValue(config.get('refit')[0])
        self.ui.threshold.setValue(config.get('threshold'))

        tth_max = config.get('tth_max')
        if isinstance(tth_max, bool):
            enabled = tth_max
            instrument = tth_max
            value = 0.0
        else:
            enabled = True
            instrument = False
            value = tth_max

        self.ui.tth_max_enable.setChecked(enabled)

        self.ui.tth_max_instrument.setEnabled(enabled)
        self.ui.tth_max_instrument.setChecked(instrument)

        self.ui.tth_max_specify.setEnabled(enabled)
        self.ui.tth_max_specify.setChecked(not instrument)

        self.ui.tth_max_value.setEnabled(enabled and (not instrument))
        self.ui.tth_max_value.setValue(value)

        tolerances = config.get('tolerance')
        self.tolerances_model.update_from_config(tolerances)

    def run(self):
        self.ui.show()

    def _get_selected_rows(self):
        """Returns list of selected rows

        Rows must be *exclusively* selected. If any partial rows are selected,
        this method returns an empty list.
        """
        selection_model = self.ui.tolerances_view.selectionModel()
        selection = selection_model.selection()
        num_rows = self.tolerances_model.rowCount()
        selected_rows = list()
        for row in range(num_rows):
            if selection_model.isRowSelected(row):
                selected_rows.append(row)
            elif selection_model.rowIntersectsSelection(row):
                # Partial row is selected - return empty list
                del selected_rows[:]
                break

        return selected_rows
