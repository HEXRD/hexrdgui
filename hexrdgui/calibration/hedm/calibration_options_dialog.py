import numpy as np

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QTableWidget, QTableWidgetItem

from hexrd import constants as cnst

from hexrdgui.constants import OverlayType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.indexing.create_config import (
    create_indexing_config, OmegasNotFoundError
)
from hexrdgui.refinements_editor import RefinementsEditor
from hexrdgui.reflections_table import ReflectionsTable
from hexrdgui.select_grains_dialog import SelectGrainsDialog
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class HEDMCalibrationOptionsDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, material, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('hedm_calibration_options_dialog.ui',
                                   parent)
        self.refinements_editor = RefinementsEditor(self.ui)
        self.refinements_editor.hide_bottom_buttons = True

        self.material = material
        self.parent = parent

        self.setup_refinement_options()
        self.setup_table()
        self.update_materials()
        self.update_gui()
        self.apply_refinement_selections()
        self.setup_connections()

    def setup_connections(self):
        self.ui.view_grains_table.clicked.connect(self.edit_grains_table)
        self.ui.view_refinements.clicked.connect(self.view_refinements)

        self.ui.material.currentIndexChanged.connect(self.material_changed)
        self.ui.choose_hkls.pressed.connect(self.choose_hkls)

        HexrdConfig().overlay_config_changed.connect(self.update_num_hkls)

        self.ui.tolerances_selected_grain.currentIndexChanged.connect(
            self.update_tolerances_table)
        self.ui.tolerances_table.itemChanged.connect(
            self.on_tolerances_changed)
        self.refinements_editor.tree_view.dict_modified.connect(
            self.on_refinements_editor_modified)
        self.ui.fix_strain.toggled.connect(self.apply_refinement_selections)
        self.ui.refinement_choice.currentIndexChanged.connect(
            self.apply_refinement_selections)

        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def update_gui(self):
        config = HexrdConfig().indexing_config['fit_grains']
        self.refit_pixel_scale = config['refit'][0]
        self.refit_ome_step_scale = config['refit'][1]

        indexing_config = HexrdConfig().indexing_config

        calibration_config = indexing_config['_hedm_calibration']
        self.do_refit = calibration_config['do_refit']

        indexing_config = HexrdConfig().indexing_config
        self.npdiv = indexing_config['fit_grains']['npdiv']
        self.threshold = indexing_config['fit_grains']['threshold']

        self.update_tolerances_grain_options()
        self.update_num_hkls()
        self.update_num_grains_selected()

    def update_config(self):
        config = HexrdConfig().indexing_config['fit_grains']
        config['refit'][0] = self.refit_pixel_scale
        config['refit'][1] = self.refit_ome_step_scale

        indexing_config = HexrdConfig().indexing_config
        calibration_config = indexing_config['_hedm_calibration']
        calibration_config['do_refit'] = self.do_refit

        indexing_config = HexrdConfig().indexing_config
        indexing_config['fit_grains']['npdiv'] = self.npdiv
        indexing_config['fit_grains']['threshold'] = self.threshold

    def setup_refinement_options(self):
        w = self.ui.refinement_choice
        w.clear()

        for key, label in REFINEMENT_OPTIONS.items():
            w.addItem(label, key)

    def show(self):
        self.ui.show()

    def on_accepted(self):
        self.apply_refinement_selections()

        try:
            self.validate()
        except Exception as e:
            QMessageBox.critical(self.parent, 'HEXRD', f'Error: {e}')
            self.show()
            return

        self.refinements_editor.update_config()
        self.refinements_editor.ui.accept()

        self.update_config()
        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

    def validate(self):
        # Validation to perform before we do anything else
        if not self.active_overlays:
            msg = 'At least one grain must be selected'
            raise Exception(msg)

        ome_periods = []
        for overlay in self.active_overlays:
            if not overlay.has_widths:
                msg = (
                    'All visible rotation series overlays must have widths '
                    'enabled'
                )
                raise Exception(msg)

            ome_periods.append(overlay.ome_period)

        for i in range(1, len(ome_periods)):
            if not np.allclose(ome_periods[0], ome_periods[i]):
                msg = (
                    'All visible rotation series overlays must have '
                    'identical omega periods'
                )
                raise Exception(msg)

        materials = [overlay.material_name for overlay in self.active_overlays]
        if not all(x == materials[0] for x in materials):
            msg = (
                'All visible rotation series overlays must have the same '
                'material'
            )
            raise Exception(msg)

        # Make sure the material is updated in the indexing config
        self.synchronize_material()

        # Ensure we have omega metadata
        try:
            create_indexing_config()
        except OmegasNotFoundError:
            msg = (
                'No omega metadata found. Be sure to import the image '
                'series using the "Simple Image Series" import tool.'
            )
            raise Exception(msg)

    def synchronize_material(self):
        # This material is used for creating the indexing config.
        # Make sure it matches the material we are using.
        cfg = HexrdConfig().indexing_config
        cfg['_selected_material'] = self.material.name

    def update_materials(self):
        prev = self.selected_material
        material_names = list(HexrdConfig().materials)

        self.ui.material.clear()
        self.ui.material.addItems(material_names)

        if prev in material_names:
            self.ui.material.setCurrentText(prev)
        else:
            self.ui.material.setCurrentText(self.material.name)

    def material_changed(self):
        # First, update the material on self.material
        self.material = HexrdConfig().material(self.selected_material)

        # Deselect all grains
        self.deselect_all_grains()

    def deselect_all_grains(self):
        for overlay in self.overlays:
            overlay.visible = False

        self.update_tolerances_grain_options()
        self.update_num_grains_selected()
        HexrdConfig().overlay_config_changed.emit()
        HexrdConfig().update_overlay_manager.emit()
        self.update_refinements_editor()

    def update_tolerances_grain_options(self):
        w = self.ui.tolerances_selected_grain
        if w.count() > 0:
            prev = int(w.currentText())
        else:
            prev = None

        with block_signals(w):
            w.clear()
            items = [str(i) for i in range(len(self.active_overlays))]
            w.addItems(items)
            if prev is not None and prev < len(items):
                w.setCurrentIndex(prev)

        self.update_tolerances_table()

    def setup_table(self):
        w = self.ui.tolerances_table
        for i in range(3):
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignCenter)
            w.setItem(0, i, item)

        content_height = calc_table_height(w)
        w.setMaximumHeight(content_height)

    def update_tolerances_table(self):
        w = self.ui.tolerances_table
        if len(self.active_overlays) == 0:
            # Cannot update
            with block_signals(w):
                for i in range(3):
                    w.item(0, i).setText('')
            return

        grain_w = self.ui.tolerances_selected_grain
        idx = int(grain_w.currentText())

        overlay = self.active_overlays[idx]

        values = [
            overlay.tth_width,
            overlay.eta_width,
            overlay.ome_width,
        ]
        for col, val in enumerate(values):
            item = w.item(0, col)
            item.setText(f'{np.round(np.degrees(val), 10)}')

    def on_tolerances_changed(self):
        if len(self.active_overlays) == 0:
            # Can't do anything. Just return
            return

        grain_w = self.ui.tolerances_selected_grain
        idx = int(grain_w.currentText())

        overlay = self.active_overlays[idx]

        w = self.ui.tolerances_table
        columns = [
            'tth_width',
            'eta_width',
            'ome_width',
        ]
        for col, attr in enumerate(columns):
            item = w.item(0, col)
            try:
                val = float(item.text())
            except ValueError:
                # Invalid. Continue.
                val = getattr(overlay, attr)
                item.setText(f'{np.round(np.degrees(val), 10)}')
                continue

            setattr(overlay, attr, np.radians(val))

        overlay.update_needed = True

        HexrdConfig().overlay_config_changed.emit()
        HexrdConfig().update_overlay_editor.emit()

    def on_refinements_editor_modified(self):
        # Set it to "custom"
        idx = list(REFINEMENT_OPTIONS).index('custom')

        w = self.ui.refinement_choice
        fix_strain_w = self.ui.fix_strain
        with block_signals(w, fix_strain_w):
            w.setCurrentIndex(idx)

            # Also disable fixing the strain
            fix_strain_w.setChecked(False)

        # Trigger an update to the config
        self.refinements_editor.update_config()

    @property
    def selected_material(self) -> str:
        return self.ui.material.currentText()

    @selected_material.setter
    def selected_material(self, v: str):
        self.ui.material.setCurrentText(v)

    @property
    def do_refit(self):
        return self.ui.do_refit.isChecked()

    @do_refit.setter
    def do_refit(self, b):
        self.ui.do_refit.setChecked(b)

    @property
    def refit_pixel_scale(self):
        return self.ui.refit_pixel_scale.value()

    @refit_pixel_scale.setter
    def refit_pixel_scale(self, v):
        self.ui.refit_pixel_scale.setValue(v)

    @property
    def refit_ome_step_scale(self):
        return self.ui.refit_ome_step_scale.value()

    @refit_ome_step_scale.setter
    def refit_ome_step_scale(self, v):
        self.ui.refit_ome_step_scale.setValue(v)

    @property
    def npdiv(self):
        return self.ui.npdiv.value()

    @npdiv.setter
    def npdiv(self, v):
        self.ui.npdiv.setValue(v)

    @property
    def threshold(self):
        return self.ui.threshold.value()

    @threshold.setter
    def threshold(self, v):
        self.ui.threshold.setValue(v)

    def choose_hkls(self):
        kwargs = {
            'material': self.material,
            'title_prefix': 'Select hkls for HEDM calibration: ',
            'parent': self.ui,
        }
        self._reflections_table = ReflectionsTable(**kwargs)
        self._reflections_table.show()

    def update_num_hkls(self):
        if self.material is None:
            num_hkls = 0
        else:
            num_hkls = len(self.material.planeData.getHKLs())

        text = f'Number of hkls selected:  {num_hkls}'
        self.ui.num_hkls_selected.setText(text)

    def update_num_grains_selected(self):
        num_grains = len(self.active_overlays)
        text = f'Number of grains selected: {num_grains}'
        self.ui.num_grains_selected.setText(text)

    def edit_grains_table(self):
        dialog = SelectGrainsDialog(None, self.ui)
        if not dialog.exec():
            return

        selected_grains = dialog.selected_grains

        # Hide any grains that were not selected.
        # Show any grains that were selected.
        # And add any new grains that don't have overlays.
        new_overlays_needed = list(range(len(selected_grains)))
        for overlay in self.overlays:
            if not overlay.is_rotation_series:
                overlay.visible = False
                continue

            match_idx = -1
            for i in new_overlays_needed:
                grain_params = selected_grains[i][3:15]
                if np.allclose(overlay.crystal_params, grain_params):
                    match_idx = i
                    break

            overlay.visible = match_idx != -1
            if match_idx != -1:
                new_overlays_needed.remove(match_idx)

        # Now create new overlays for any missing selected grains
        for i in new_overlays_needed:
            HexrdConfig().append_overlay(
                self.material.name,
                OverlayType.rotation_series,
            )

            # Grab that overlay we just made, and set the grain params
            overlay = HexrdConfig().overlays[-1]
            overlay.crystal_params = selected_grains[i][3:15]
            overlay.update_needed = True
            overlay.visible = True

        HexrdConfig().overlay_config_changed.emit()

        self.update_tolerances_grain_options()
        self.update_num_grains_selected()
        self.apply_refinement_selections()
        self.update_refinements_editor()
        HexrdConfig().update_overlay_manager.emit()

    @property
    def fix_strain(self):
        return self.ui.fix_strain.isChecked()

    @fix_strain.setter
    def fix_strain(self, b):
        self.ui.fix_strain.setChecked(b)

    @property
    def fix_det_y(self):
        return self.ui.refinement_choice.currentData() == 'fix_det_y'

    @property
    def fix_grain_centroid(self):
        return self.ui.refinement_choice.currentData() == 'fix_grain_centroid'

    @property
    def fix_grain_y(self):
        return self.ui.refinement_choice.currentData() == 'fix_grain_y'

    @property
    def custom_refinements(self):
        return self.ui.refinement_choice.currentData() == 'custom'

    def apply_refinement_selections(self):
        def perform_updates():
            self.update_refinements_editor()
            HexrdConfig().overlay_config_changed.emit()
            HexrdConfig().update_overlay_editor.emit()
            HexrdConfig().update_instrument_toolbox.emit()

        # First, apply strain settings
        for overlay in self.active_overlays:
            refinements = overlay.refinements
            crystal_params = overlay.crystal_params
            if self.fix_strain:
                crystal_params[6:] = cnst.identity_6x1
                for i in range(6, len(refinements)):
                    refinements[i] = False
            elif not self.custom_refinements:
                # Make all strain parameters refinable, but only
                # if we are not doing custom refinements.
                for i in range(6, len(refinements)):
                    refinements[i] = True

        # If we are doing custom refinements, don't make any more changes
        if self.custom_refinements:
            perform_updates()
            return

        # Set all rotation series orientation/position refinement params
        for idx, overlay in enumerate(self.active_overlays):
            refinements = overlay.refinements
            crystal_params = overlay.crystal_params

            # The position and orientation will be refinable by default
            for i in range(6):
                refinements[i] = True

            if idx == 0:
                # First grain may be affected by refinement choices
                if self.fix_grain_centroid:
                    crystal_params[3:6] = cnst.zeros_3
                    for i in range(3, 6):
                        refinements[i] = False
                elif self.fix_grain_y:
                    crystal_params[4] = 0
                    refinements[4] = False

        def recursive_set_refinable(cur, b):
            if 'status' not in cur:
                for key, value in cur.items():
                    recursive_set_refinable(value, b)
                return

            if isinstance(cur['status'], list):
                for i in range(len(cur['status'])):
                    cur['status'][i] = b
            else:
                cur['status'] = b

        # Now make all detector parameters refinable by default.
        iconfig = HexrdConfig().config['instrument']

        # Mark everything under "beam" and "oscillation stage" as not refinable
        recursive_set_refinable(iconfig['beam'], False)
        recursive_set_refinable(iconfig['oscillation_stage'], False)

        # Mark everything under detectors as refinable
        recursive_set_refinable(iconfig['detectors'], True)

        if self.fix_det_y:
            # Fix the detector y translation values
            for det_key, conf in iconfig['detectors'].items():
                conf['transform']['translation']['status'][1] = False

        # Now trigger updates everywhere
        perform_updates()

    def view_refinements(self):
        self.update_refinements_editor()
        self.refinements_editor.ui.show()

    def update_refinements_editor(self):
        self.refinements_editor.reset_dict()

    @property
    def overlays(self):
        return HexrdConfig().overlays

    @property
    def visible_overlays(self):
        return [x for x in self.overlays if x.visible]

    @property
    def visible_rotation_series_overlays(self):
        return [x for x in self.visible_overlays if x.is_rotation_series]

    @property
    def active_overlays(self):
        return self.visible_rotation_series_overlays


def calc_table_height(table: QTableWidget) -> int:
    """Calculate table height."""
    res = 0
    for i in range(table.verticalHeader().count()):
        if not table.verticalHeader().isSectionHidden(i):
            res += table.verticalHeader().sectionSize(i)
    if table.horizontalScrollBar().isHidden():
        res += table.horizontalScrollBar().height()
    if not table.horizontalHeader().isHidden():
        res += table.horizontalHeader().height()
    return res


REFINEMENT_OPTIONS = {
    'fix_det_y': 'Fix origin based on current sample/detector position',
    'fix_grain_centroid': 'Reset origin to grain centroid position',
    'fix_grain_y': 'Reset Y axis origin to grain\'s Y position',
    'custom': 'Custom refinement parameters',
}
