import copy
import numpy as np

from PySide6.QtCore import Signal

from hexrd import rotations
import hexrd.constants as cnst
from hexrd.fitting.calibration.lmfit_param_handling import fix_detector_y
from hexrd.transforms import xfcapi

from hexrdgui.calibration.calibration_dialog import CalibrationDialog
from hexrdgui.calibration.hedm.calibration_results_dialog import (
    HEDMCalibrationResultsDialog,
)
from hexrdgui.calibration.material_calibration_dialog_callbacks import (
    MaterialCalibrationDialogCallbacks,
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.indexing.create_config import create_indexing_config
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals


class HEDMCalibrationDialog(CalibrationDialog):

    apply_refinement_selections_needed = Signal()

    def __init__(self, *args, **kwargs):
        # Need to initialize this before setup_connections() is called
        self.extra_ui = UiLoader().load_file(
            'hedm_calibration_custom_widgets.ui',
            kwargs.get('parent'),
        )
        # Load the refit settings before connections are made
        self.load_refit_settings()

        # This will, among other things, call `setup_connections()`
        super().__init__(*args, **kwargs)

        self.ui.extra_widgets_layout.addWidget(self.extra_ui)
        self.setup_refinement_options()

        # Hide refinements
        self.show_refinements(False)

        self.ui.canvas_settings_group.setVisible(False)
        self.ui.picks_group.setVisible(False)
        self.ui.engineering_constraints_label.setVisible(False)
        self.ui.engineering_constraints.setVisible(False)

        self.ui.adjustSize()
        self._base_height = self.ui.size().height()

    def setup_connections(self):
        super().setup_connections()

        self.extra_ui.show_refinements.toggled.connect(
            self.show_refinements,
        )

        # Connecting to "toggled" instead of "clicked" causes a render
        # flash of the refinements tree view for some reason. I have
        # no idea why. But let's use "clicked" instead to avoid that.
        self.extra_ui.fix_strain.clicked.connect(
            self.apply_refinement_selections)
        self.extra_ui.refinement_choice.currentIndexChanged.connect(
            self.apply_refinement_selections)

        self.extra_ui.do_refit.toggled.connect(
            self.save_refit_settings)
        self.extra_ui.refit_pixel_scale.valueChanged.connect(
            self.save_refit_settings)
        self.extra_ui.refit_ome_step_scale.valueChanged.connect(
            self.save_refit_settings)

    def show_refinements(self, b):
        self.tree_view.setVisible(b)
        if b:
            # Increase the size to at least double the height of the base size
            size = self.ui.size()
            size.setHeight(max(2 * self._base_height, size.height()))
            self.ui.resize(size)

    def initialize_tree_view(self):
        super().initialize_tree_view()
        self.show_refinements(self.extra_ui.show_refinements.isChecked())
        self.apply_refinement_selections()

        self.tree_view.dict_modified.connect(
            self.on_refinements_editor_modified)

    def setup_refinement_options(self):
        w = self.extra_ui.refinement_choice
        w.clear()

        for key, label in REFINEMENT_OPTIONS.items():
            w.addItem(label, key)

    def on_refinements_editor_modified(self, index):
        # If anything other than the boundary constraints was modified,
        # put it in "custom" mode.
        model = self.tree_view.model()
        if self.delta_boundaries:
            boundary_columns = [model.DELTA_IDX]
        else:
            boundary_columns = [model.MIN_IDX, model.MAX_IDX]

        if index.column() in boundary_columns:
            return

        # Set it to "custom"
        idx = list(REFINEMENT_OPTIONS).index('custom')

        w = self.extra_ui.refinement_choice
        fix_strain_w = self.extra_ui.fix_strain
        with block_signals(w, fix_strain_w):
            w.setCurrentIndex(idx)

            # Also disable fixing the strain
            fix_strain_w.setChecked(False)

    @property
    def fix_strain(self):
        return self.extra_ui.fix_strain.isChecked()

    @fix_strain.setter
    def fix_strain(self, b):
        self.extra_ui.fix_strain.setChecked(b)

    @property
    def refinement_choice(self):
        return self.extra_ui.refinement_choice.currentData()

    @refinement_choice.setter
    def refinement_choice(self, v):
        w = self.extra_ui.refinement_choice
        i = w.findData(v)
        if i == -1:
            raise Exception(f'Invalid refinement choice: {v}')

        w.setCurrentIndex(i)

    @property
    def fix_det_y(self):
        return self.extra_ui.refinement_choice.currentData() == 'fix_det_y'

    @property
    def fix_grain_centroid(self):
        w = self.extra_ui.refinement_choice
        return w.currentData() == 'fix_grain_centroid'

    @property
    def fix_grain_y(self):
        return self.extra_ui.refinement_choice.currentData() == 'fix_grain_y'

    @property
    def custom_refinements(self):
        return self.extra_ui.refinement_choice.currentData() == 'custom'

    def apply_refinement_selections(self):
        self.apply_refinement_selections_needed.emit()

    @property
    def do_refit(self):
        return self.extra_ui.do_refit.isChecked()

    @do_refit.setter
    def do_refit(self, b):
        self.extra_ui.do_refit.setChecked(b)

    @property
    def refit_pixel_scale(self):
        return self.extra_ui.refit_pixel_scale.value()

    @refit_pixel_scale.setter
    def refit_pixel_scale(self, v):
        self.extra_ui.refit_pixel_scale.setValue(v)

    @property
    def refit_ome_step_scale(self):
        return self.extra_ui.refit_ome_step_scale.value()

    @refit_ome_step_scale.setter
    def refit_ome_step_scale(self, v):
        self.extra_ui.refit_ome_step_scale.setValue(v)

    def load_refit_settings(self):
        # Load refit settings from the indexing config
        indexing_config = HexrdConfig().indexing_config
        calibration_config = indexing_config['_hedm_calibration']
        fit_grains_config = indexing_config['fit_grains']

        self.do_refit = calibration_config['do_refit']
        self.refit_pixel_scale = fit_grains_config['refit'][0]
        self.refit_ome_step_scale = fit_grains_config['refit'][1]

    def save_refit_settings(self):
        # Save refit settings to the indexing config
        indexing_config = HexrdConfig().indexing_config
        calibration_config = indexing_config['_hedm_calibration']
        fit_grains_config = indexing_config['fit_grains']

        calibration_config['do_refit'] = self.do_refit
        fit_grains_config['refit'][0] = self.refit_pixel_scale
        fit_grains_config['refit'][1] = self.refit_ome_step_scale

    @property
    def extra_ui_settings(self):
        keys = [
            'fix_strain',
            'refinement_choice',
            'do_refit',
            'refit_pixel_scale',
            'refit_ome_step_scale',
        ]
        return {k: getattr(self, k) for k in keys}

    @extra_ui_settings.setter
    def extra_ui_settings(self, settings):
        block_signals_widgets = [
            self.extra_ui.fix_strain,
            self.extra_ui.refinement_choice,
        ]
        with block_signals(*block_signals_widgets):
            for k, v in settings.items():
                setattr(self, k, v)


class HEDMCalibrationCallbacks(MaterialCalibrationDialogCallbacks):

    def __init__(self, overlays, spots_data, *args, **kwargs):
        self.overlays = overlays
        self.xyo_i_list = []
        self.extra_ui_undo_stack = []
        self.spots_data = spots_data

        super().__init__(overlays, *args, **kwargs)

        # Save the initial predictions
        xyo_i = compute_xyo(self.calibrators)
        self.xyo_i_list.append(xyo_i)

    def setup_connections(self):
        super().setup_connections()

        self.dialog.apply_refinement_selections_needed.connect(
            self.apply_refinement_selections)

    @property
    def grain_ids(self):
        # These are always ordered as expected...
        return np.arange(len(self.calibrators))

    @property
    def ome_period(self) -> np.ndarray:
        # This should be the same for every overlay
        return self.overlays[0].ome_period

    @property
    def xyo_det(self):
        # This should never change, so we cache it
        if not hasattr(self, '_xyo_det'):
            _, xyo_det, _ = parse_spots_data(
                self.spots_data,
                self.instr,
                self.grain_ids,
                self.ome_period,
            )
            self._xyo_det = xyo_det

        return self._xyo_det

    def on_calibration_finished(self):
        super().on_calibration_finished()

        cfg = create_indexing_config()

        # The styles we will use for plotting points
        plot_styles = {
            'xyo_i': 'rx',
            'xyo_det': 'k.',
            'xyo_f': 'b+',
        }

        plot_labels = {
            'xyo_i': 'Initial',
            'xyo_det': 'Measured',
            'xyo_f': 'Final',
        }

        xyo_i = self.xyo_i_list[-1]

        xyo_f = compute_xyo(self.calibrators)
        self.xyo_i_list.append(xyo_f)

        data = {
            'xyo_i': xyo_i,
            'xyo_det': self.xyo_det,
            'xyo_f': xyo_f,
        }
        kwargs = {
            'data': data,
            'styles': plot_styles,
            'labels': plot_labels,
            'grain_ids': self.grain_ids,
            'cfg': cfg,
            'title': 'Final results. Accept?',
            'ome_period': np.degrees(self.ome_period),
        }
        dialog = HEDMCalibrationResultsDialog(**kwargs)
        if not dialog.exec():
            # Do an "undo"
            self.pop_undo_stack()

    def push_undo_stack(self):
        self.extra_ui_undo_stack.append(self.dialog.extra_ui_settings)
        return super().push_undo_stack()

    def pop_undo_stack(self):
        self.dialog.extra_ui_settings = self.extra_ui_undo_stack.pop()

        # Remove the last xyo_i
        self.xyo_i_list.pop(-1)
        return super().pop_undo_stack()

    def _copy_deltas(self, prev_params, new_params, copy_vary):
        delta_boundaries = self.dialog.delta_boundaries
        for name, param in new_params.items():
            if name not in prev_params:
                continue

            prev_param = prev_params[name]

            if copy_vary:
                param.vary = prev_param.vary

            if delta_boundaries:
                if hasattr(prev_param, 'delta'):
                    delta = prev_param.delta
                else:
                    delta = min(
                        prev_param.value - prev_param.min,
                        prev_param.max - prev_param.value,
                    )

                param.min = param.value - delta
                param.max = param.value + delta
                param.delta = delta

    def reset_params(self):
        self.calibrator.reset_lmfit_params()

    def apply_refinement_selections(self):
        dialog = self.dialog

        if not dialog.custom_refinements:
            # First, restore all overlay values and default refinements
            self.reset_params()

        params_dict = self.calibrator.params

        def finalize():
            # The dialog parameters should have the deltas set on them
            prev_params = dialog.params_dict
            self._copy_deltas(prev_params, params_dict, copy_vary=False)
            # Round the calibrator numbers to 3 decimal places
            self.round_param_numbers()
            dialog.params_dict = params_dict

        # Next, apply strain settings
        if dialog.fix_strain:
            for calibrator in self.calibrators:
                calibrator.fix_strain_to_identity(params_dict)

        # If we are doing custom refinements, don't make any more changes
        if dialog.custom_refinements:
            finalize()
            return

        if dialog.fix_grain_centroid:
            # This only applies to the first grain
            calibrator = self.calibrators[0]
            calibrator.fix_translation_to_origin(params_dict)

        if dialog.fix_grain_y:
            # This only applies to the first grain
            calibrator = self.calibrators[0]
            calibrator.fix_y_to_zero(params_dict)

        if dialog.fix_det_y:
            fix_detector_y(
                self.instr,
                params_dict,
                self.calibrator.relative_constraints,
            )

        finalize()

    def run_calibration(self, **extra_kwargs):
        do_refit = self.dialog.do_refit

        # First, run the calibration one time as normal
        if not do_refit:
            # Run the calibration as normal and exit
            return super().run_calibration(**extra_kwargs)

        # We essentially the beginning and end of super().run_calibration(),
        # but in the middle, we perform a refit and re-run the calibration.
        # Add the current parameters to the undo stack
        self.push_undo_stack()

        odict = copy.deepcopy(self.dialog.advanced_options)

        # Make a copy of the calibrator that we will modify for the refit
        ic = copy.deepcopy(self.calibrator)

        # Run the calibration using the first set of parameters
        x0 = self.calibrator.params.valuesdict()
        print('Running pre-refit calibration...')
        ic.run_calibration(odict=odict, **extra_kwargs)

        cfg = create_indexing_config()

        # load imageseries dict
        ims_dict = cfg.image_series
        ims = next(iter(ims_dict.values()))    # grab first member
        delta_ome = ims.metadata['omega'][:, 1] - ims.metadata['omega'][:, 0]
        # In the spirit of Joel, I'm leaving his comment here...
        assert np.max(np.abs(np.diff(delta_ome))) < cnst.sqrt_epsf, \
            "something funky going one with your omegas"
        delta_ome = delta_ome[0]   # any one member will do

        # refit tolerances
        if cfg.fit_grains.refit is not None:
            n_pixels_tol = cfg.fit_grains.refit[0]
            ome_tol = cfg.fit_grains.refit[1]*delta_ome
        else:
            n_pixels_tol = 2
            ome_tol = 2.*delta_ome

        spots_data = self.spots_data
        instr = self.instr
        grain_ids = self.grain_ids
        ome_period = self.ome_period

        hkls, xyo_det, idx_0 = parse_spots_data(
            spots_data,
            instr,
            grain_ids,
            ome_period,
        )
        if not hasattr(self, '_xyo_det'):
            # Cache this now since it won't change
            # It is needed after the calibration
            self._xyo_det = xyo_det

        ngrains = len(self.calibrators)
        xyo_f = compute_xyo(ic.calibrators)

        print('Removing HKLs to perform refit...')
        # define difference vectors for spot fits
        for det_key, panel in instr.detectors.items():
            for ig in range(ngrains):
                x_diff = abs(xyo_det[det_key][ig][:, 0] -
                             xyo_f[det_key][ig][:, 0])
                y_diff = abs(xyo_det[det_key][ig][:, 1] -
                             xyo_f[det_key][ig][:, 1])
                ome_diff = np.degrees(
                    xfcapi.angularDifference(
                        xyo_det[det_key][ig][:, 2],
                        xyo_f[det_key][ig][:, 2])
                )

                # filter out reflections with centroids more than
                # a pixel and delta omega away from predicted value
                idx_1 = np.logical_and(
                    x_diff <= n_pixels_tol*panel.pixel_size_col,
                    np.logical_and(
                        y_diff <= n_pixels_tol*panel.pixel_size_row,
                        ome_diff <= ome_tol
                    )
                )

                print("INFO: Will keep %d of %d input reflections "
                      % (sum(idx_1), sum(idx_0[det_key][ig]))
                      + "on panel %s for re-fit" % det_key)

                idx_new = np.zeros_like(idx_0[det_key][ig], dtype=bool)
                idx_new[np.where(idx_0[det_key][ig])[0][idx_1]] = True
                idx_0[det_key][ig] = idx_new

        # reparse data
        hkls_refit, xyo_det_refit, idx_0 = parse_spots_data(
            spots_data,
            instr,
            grain_ids,
            ome_period,
            refit_idx=idx_0,
        )

        # Update the data dicts on the calibrators
        # We don't want to modify the data dicts on the original
        # calibrator, so only do it on the copy.
        for i, calibrator in enumerate(ic.calibrators):
            data_dict = {
                'hkls': {},
                'pick_xys': {},
            }
            for det_key in instr.detectors:
                data_dict['hkls'][det_key] = hkls[det_key][i]
                data_dict['pick_xys'][det_key] = xyo_det[det_key][i]

            calibrator.data_dict = data_dict

        # perform refit
        print('Performing refit calibration...')
        result = ic.run_calibration(odict=odict, **extra_kwargs)

        # Update the params dict on the original calibrator
        self.calibrator.params = ic.params

        # And trigger that calibrator to update its calibrator parameters
        self.calibrator.update_all_from_params(ic.params)

        # Round the calibrator numbers to 3 decimal places
        self.round_param_numbers()

        x1 = result.params.valuesdict()

        results_message = 'Calibration Results:\n'
        for name in x0:
            if not result.params[name].vary:
                continue

            old = x0[name]
            new = x1[name]
            results_message += f'{name}: {old:6.3g} ---> {new:6.3g}\n'

        print(results_message)

    def draw_picks_on_canvas(self):
        pass

    def clear_drawn_picks(self):
        pass

    def on_edit_picks_clicked(self):
        raise NotImplementedError

    def save_picks_to_file(self, selected_file):
        raise NotImplementedError

    def load_picks_from_file(self, selected_file):
        raise NotImplementedError


def compute_xyo(calibrators) -> dict[str, list]:
    xyo = {}
    for calibrator in calibrators:
        results = calibrator.model()
        for det_key, values in results.items():
            xyo.setdefault(det_key, [])
            xyo[det_key].append(values[0])

    return xyo


def parse_spots_data(spots_data, instr, grain_ids, ome_period=None,
                     refit_idx=None):
    hkls = {}
    xyo_det = {}
    idx_0 = {}
    for det_key, panel in instr.detectors.items():
        hkls[det_key] = []
        xyo_det[det_key] = []
        idx_0[det_key] = []

        for ig, grain_id in enumerate(grain_ids):
            data = spots_data[grain_id][1][det_key]
            # Convert to numpy array to make operations easier
            data = np.array(data, dtype=object)

            # FIXME: hexrd is not happy if some detectors end up with no
            # grain data, which sometimes happens with subpanels like Dexelas
            if data.size == 0:
                continue

            valid_reflections = data[:, 0] >= 0
            not_saturated = data[:, 4] < panel.saturation_level

            if refit_idx is None:
                idx = np.logical_and(valid_reflections, not_saturated)
                idx_0[det_key].append(idx)
            else:
                idx = refit_idx[det_key][ig]
                idx_0[det_key].append(idx)

            hkls[det_key].append(np.vstack(data[idx, 2]))
            meas_omes = np.vstack(data[idx, 6])[:, 2].reshape(sum(idx), 1)
            xyo_det_values = np.hstack([np.vstack(data[idx, 7]), meas_omes])

            # re-map omegas if need be
            if ome_period is not None:
                xyo_det_values[:, 2] = rotations.mapAngle(
                    xyo_det_values[:, 2],
                    ome_period,
                )

            xyo_det[det_key].append(xyo_det_values)

    return hkls, xyo_det, idx_0


REFINEMENT_OPTIONS = {
    'fix_det_y': 'Fix origin based on current sample/detector position',
    'fix_grain_centroid': 'Reset origin to grain centroid position',
    'fix_grain_y': 'Reset Y axis origin to grain\'s Y position',
    'custom': 'Custom refinement parameters',
}
