from pathlib import Path

from PySide6.QtCore import (
    QItemSelectionModel, QModelIndex, QObject, Qt, Signal)
from PySide6.QtWidgets import (
    QDialogButtonBox, QFileDialog, QHeaderView, QMessageBox
)

import numpy as np

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.indexing.grains_table_model import GrainsTableModel
from hexrdgui.plot_grains import plot_grains
from hexrdgui.reflections_table import ReflectionsTable
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals
from hexrdgui.utils.dialog import add_help_url

from hexrdgui.indexing.fit_grains_tolerances_model import (
    FitGrainsToleranceModel)
from hexrdgui.indexing.utils import hkls_missing_in_list


class FitGrainsOptionsDialog(QObject):
    accepted = Signal()
    rejected = Signal()
    grains_table_modified = Signal()

    def __init__(self, grains_table, ensure_active_hkls_not_excluded=True,
                 parent=None):
        super().__init__(parent)

        self.grains_table = grains_table
        self.ensure_active_hkls_not_excluded = ensure_active_hkls_not_excluded

        config = HexrdConfig().indexing_config['fit_grains']
        if config.get('do_fit') is False:
            return

        loader = UiLoader()
        self.ui = loader.load_file('fit_grains_options_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        url = 'hedm/fit_grains/#fit-grains-options'
        add_help_url(self.ui.button_box, url)

        self.update_materials()

        kwargs = {
            'grains_table': grains_table,
            'excluded_columns': list(range(9, 15)),
            'parent': self.ui.grains_table_view,
        }
        self.data_model = GrainsTableModel(**kwargs)
        view = self.ui.grains_table_view
        view.data_model = self.data_model
        view.material = self.material
        view.can_modify_grains = True

        ok_button = self.ui.button_box.button(QDialogButtonBox.Ok)
        ok_button.setText('Fit Grains')

        self.tolerances_model = FitGrainsToleranceModel(self.ui)
        self.update_gui_from_config(config)
        self.ui.tolerances_view.setModel(self.tolerances_model)

        # Stretch columns to fill the available horizontal space
        num_cols = self.tolerances_model.columnCount()
        for i in range(num_cols):
            self.ui.tolerances_view.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.Stretch)

        self.setup_connections()

    def setup_connections(self):
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.rejected)
        self.ui.tolerances_view.selectionModel().selectionChanged.connect(
            self.on_tolerances_select)
        self.ui.add_row.clicked.connect(self.on_tolerances_add_row)
        self.ui.delete_row.clicked.connect(self.on_tolerances_delete_row)
        self.ui.move_up.clicked.connect(self.on_tolerances_move_up)
        self.ui.move_down.clicked.connect(self.on_tolerances_move_down)

        self.ui.material.currentIndexChanged.connect(
            self.selected_material_changed)
        self.ui.choose_hkls.pressed.connect(self.choose_hkls)

        self.ui.apply_min_sfac.clicked.connect(self.apply_min_sfac_to_hkls)

        self.ui.set_spots_directory.clicked.connect(self.set_working_dir)

        HexrdConfig().overlay_config_changed.connect(self.update_num_hkls)

        self.tolerances_model.data_modified.connect(
            self.tolerance_data_modified)

        HexrdConfig().materials_dict_modified.connect(self.update_materials)

        self.ui.plot_grains.clicked.connect(self.plot_grains)
        self.data_model.grains_table_modified.connect(
            self.on_grains_table_modified)

    def all_widgets(self):
        """Only includes widgets directly related to config parameters"""
        widgets = [
            self.ui.npdiv,
            self.ui.refit_ome_step_scale,
            self.ui.refit_pixel_scale,
            self.ui.tolerances_view,
            self.ui.threshold,
        ]
        return widgets

    def show(self):
        self.ui.show()

    def update_materials(self):
        prev = self.selected_material
        material_names = list(HexrdConfig().materials)

        self.ui.material.clear()
        self.ui.material.addItems(material_names)

        if prev in material_names:
            self.ui.material.setCurrentText(prev)
        else:
            self.ui.material.setCurrentText(HexrdConfig().active_material_name)

    def on_accepted(self):
        if not self.validate():
            self.ui.show()
            return

        # Save the selected options on the config
        self.update_config()
        self.accepted.emit()

    def validate(self):
        if self.ensure_active_hkls_not_excluded:
            # Verify that the active hkls are not excluded
            indexing_config = HexrdConfig().indexing_config
            omaps = indexing_config['find_orientations']['orientation_maps']
            active_hkls = omaps.get('active_hkls', [])

            hkl_list = self.material.planeData.getHKLs()
            missing = hkls_missing_in_list(active_hkls, hkl_list)
            if missing:
                msg = (
                    'Active HKLs used in indexing must not be excluded. '
                    'Missing active HKLs are:\n\n'
                )
                msg += '\n'.join([str(x) for x in missing])
                msg += '\n\nThese will now be automatically enabled.\n'
                print(msg)
                QMessageBox.critical(self.parent(), 'Warning', msg)

                pd = self.material.planeData
                new_exclusions = pd.exclusions
                for i, hkl_dict in enumerate(pd.hklDataList):
                    for missing_hkl in missing:
                        if np.array_equal(hkl_dict['hkl'], missing_hkl):
                            new_exclusions[i] = False

                pd.exclusions = new_exclusions

                HexrdConfig().flag_overlay_updates_for_material(
                    self.material.name)
                HexrdConfig().overlay_config_changed.emit()

        return True

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

    def on_tolerances_delete_row(self):
        rows = self._get_selected_rows()
        self.tolerances_model.delete_rows(rows)
        self.ui.tolerances_view.selectionModel().clear()
        self.ui.tolerances_view.repaint(self.ui.tolerances_view.rect())

    def on_tolerances_move_down(self):
        rows = self._get_selected_rows()
        self.tolerances_model.move_rows(rows, 1)
        self.ui.tolerances_view.selectionModel().clear()
        self.ui.tolerances_view.repaint(self.ui.tolerances_view.rect())

    def on_tolerances_move_up(self):
        rows = self._get_selected_rows()
        self.tolerances_model.move_rows(rows, -1)
        self.ui.tolerances_view.selectionModel().clear()
        self.ui.tolerances_view.repaint(self.ui.tolerances_view.rect())

    def on_tolerances_select(self):
        """Sets button enable states based on current selection"""
        delete_enable = False
        up_enable = False
        down_enable = False

        # Get list of selected rows
        selected_rows = self._get_selected_rows()
        if selected_rows:
            # Enable delete if more than 1 row
            num_rows = self.tolerances_model.rowCount()
            delete_enable = num_rows > 1

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

    def tolerance_data_modified(self):
        # Update the tolerances on the table
        all_tolerances = self.tolerances_model.data_columns
        tolerances = []
        for tth, eta, ome in zip(*all_tolerances):
            tolerances.append({
                'tth': tth,
                'eta': eta,
                'ome': ome,
            })

        self.ui.grains_table_view.tolerances = tolerances

    def update_config(self):
        # Set the new config options on the internal config
        config = HexrdConfig().indexing_config['fit_grains']
        config['npdiv'] = self.ui.npdiv.value()
        config['refit'][0] = self.ui.refit_pixel_scale.value()
        config['refit'][1] = self.ui.refit_ome_step_scale.value()
        config['threshold'] = self.ui.threshold.value()

        # The user sets the HKLs manually. Make sure this is set to False to
        # reflect that.
        config['tth_max'] = False

        self.tolerances_model.copy_to_config(config)

        indexing_config = HexrdConfig().indexing_config
        indexing_config['analysis_name'] = Path(self.spots_path).stem
        indexing_config['working_dir'] = str(Path(self.spots_path).parent)
        indexing_config['_selected_material'] = self.selected_material
        indexing_config['_write_spots'] = self.ui.write_out_spots.isChecked()

    def update_gui_from_config(self, config):
        with block_signals(*self.all_widgets()):
            self.ui.npdiv.setValue(config.get('npdiv'))
            self.ui.refit_pixel_scale.setValue(config.get('refit')[0])
            self.ui.refit_ome_step_scale.setValue(config.get('refit')[1])
            self.ui.threshold.setValue(config.get('threshold'))

            tolerances = config.get('tolerance')
            self.tolerances_model.update_from_config(tolerances)

            indexing_config = HexrdConfig().indexing_config
            self.selected_material = indexing_config.get('_selected_material')
            working_dir = indexing_config.get(
                'working_dir', str(Path(HexrdConfig().working_dir).parent))
            analysis_name = indexing_config.get(
                'analysis_name', Path(HexrdConfig().working_dir).stem)
            self.spots_path = str(Path(working_dir) / analysis_name)
            write_spots = indexing_config.get('_write_spots', False)
            self.ui.write_out_spots.setChecked(write_spots)

            self.update_num_hkls()

    def run(self):
        self.ui.show()

    def _get_selected_rows(self):
        """Returns list of selected rows

        Rows must be *exclusively* selected. If any partial rows are selected,
        this method returns an empty list.
        """
        selection_model = self.ui.tolerances_view.selectionModel()
        num_rows = self.tolerances_model.rowCount()
        selected_rows = list()
        for row in range(num_rows):
            if selection_model.isRowSelected(row, QModelIndex()):
                selected_rows.append(row)
            elif selection_model.rowIntersectsSelection(row, QModelIndex()):
                # Partial row is selected - return empty list
                del selected_rows[:]
                break

        return selected_rows

    @property
    def material_options(self):
        w = self.ui.material
        return [w.itemText(i) for i in range(w.count())]

    def selected_material_changed(self):
        if hasattr(self, '_table'):
            self._table.material = self.material

        self.ui.grains_table_view.material = self.material
        self.update_num_hkls()

    @property
    def selected_material(self):
        return self.ui.material.currentText()

    @selected_material.setter
    def selected_material(self, name):
        if (
            name is None or
            name not in self.material_options or
            name == self.selected_material
        ):
            return

        self.ui.material.setCurrentText(name)
        # Make sure these things get updated
        self.selected_material_changed()

    @property
    def material(self):
        return HexrdConfig().material(self.selected_material)

    @property
    def reflections_table(self):
        if hasattr(self, '_table'):
            return self._table

        kwargs = {
            'material': self.material,
            'title_prefix': 'Select hkls for grain fitting: ',
            'parent': self.ui,
        }
        self._table = ReflectionsTable(**kwargs)
        return self._table

    def choose_hkls(self):
        self.reflections_table.show()

    def update_num_hkls(self):
        if self.material is None:
            num_hkls = 0
        else:
            num_hkls = len(self.material.planeData.getHKLs())

        text = f'Number of hkls selected:  {num_hkls}'
        self.ui.num_hkls_selected.setText(text)

    def apply_min_sfac_to_hkls(self):
        min_sfac = self.ui.min_sfac_value.value()
        table = self.reflections_table

        # Get the rescaled structure factor from the table, in case the user
        # modified the structure factor scaling.
        sf = table.rescaled_structure_factor

        exclusions = np.zeros_like(table.exclusions, dtype=bool)
        exclusions[sf < min_sfac] = True
        table.exclusions = exclusions
        # Update the number of hkls first so it is fast
        # (might take longer to update the table)
        self.update_num_hkls()
        table.update_table()

    def set_working_dir(self):
        caption = 'Select directory to write spots files to'
        d = QFileDialog.getExistingDirectory(
            self.ui, caption, dir=self.spots_path)

        if d:
            self.spots_path = d

    def plot_grains(self):
        plot_grains(self.grains_table, None, parent=self.ui)

    def on_grains_table_modified(self):
        self.grains_table = self.data_model.full_grains_table
        self.grains_table_modified.emit()
