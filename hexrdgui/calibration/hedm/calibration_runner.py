from functools import partial

import numpy as np

from PySide6.QtCore import QObject, Signal

from hexrd import instrument
from hexrd.fitting.calibration import GrainCalibrator, InstrumentCalibrator

from hexrdgui.calibration.hedm import (
    compute_xyo,
    HEDMCalibrationCallbacks,
    HEDMCalibrationDialog,
    HEDMCalibrationOptionsDialog,
    HEDMCalibrationResultsDialog,
    parse_spots_data,
)
from hexrdgui.calibration.material_calibration_dialog_callbacks import (
    format_material_params_func,
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.indexing.create_config import create_indexing_config, OmegasNotFoundError


class HEDMCalibrationRunner(QObject):

    finished = Signal()

    def __init__(self, async_runner, parent=None):
        super().__init__(parent)

        self.async_runner = async_runner
        self.parent = parent

        self.select_grains_dialog = None
        self.options_dialog = None
        self.clear()

    def clear(self):
        if self.select_grains_dialog:
            self.select_grains_dialog.ui.hide()
            self.select_grains_dialog = None

        if self.options_dialog:
            self.options_dialog.ui.hide()
            self.options_dialog = None

        self.results = None
        self.results_message = ''

    def run(self):
        self.clear()
        self.pre_validate()

        # Create the grains table
        if self.num_active_overlays > 0:
            material = self.material
        else:
            material = HexrdConfig().active_material

        kwargs = {
            'material': material,
            'parent': self.parent,
        }
        dialog = HEDMCalibrationOptionsDialog(**kwargs)
        dialog.accepted.connect(self.on_options_dialog_accepted)
        dialog.show()
        self.options_dialog = dialog

    def on_options_dialog_accepted(self):
        shape = (self.num_active_overlays, 21)
        self.grains_table = np.empty(shape, dtype=np.float64)
        gw = instrument.GrainDataWriter(array=self.grains_table)
        for i, overlay in enumerate(self.active_overlays):
            gw.dump_grain(i, 1, 0, overlay.crystal_params)

        self.synchronize_omega_period()
        self.run_calibration()

    def run_calibration(self):
        # First, run pull_spots() to get the spots data
        self.async_runner.progress_title = 'Running pull spots...'
        self.async_runner.success_callback = self.on_pull_spots_finished
        self.async_runner.run(self.run_pull_spots)

    def on_pull_spots_finished(self, spots_data_dict):
        cfg = create_indexing_config()

        # grab instrument
        instr = cfg.instrument.hedm

        # Save to self
        self.instr = instr

        # Our grains table only contains the grains that the user
        # selected.
        grain_params = self.grain_params
        grain_ids = self.grains_table[:, 0].astype(int)
        ngrains = len(grain_params)

        # Verify the grain IDs are as we expect
        if not np.array_equal(grain_ids, np.arange(ngrains)):
            msg = (
                f'Grain IDs ({grain_ids}) are not as expected: ' f'{np.arange(ngrains)}'
            )
            raise Exception(msg)

        if not np.array_equal(grain_ids, list(spots_data_dict)):
            msg = (
                f'Grain ID order mismatch: "{grain_ids}", ' f'"{list(spots_data_dict)}"'
            )
            raise Exception(msg)

        spots_data = list(spots_data_dict.values())

        # plane data
        material = cfg.material.materials[cfg.material.active]

        ome_period = self.ome_period

        grain_params = grain_params.copy()

        euler_convention = HexrdConfig().euler_angle_convention

        # The styles we will use for plotting points
        plot_styles = {
            'xyo_i': 'rx',
            'xyo_det': 'k.',
        }

        plot_labels = {
            'xyo_i': 'Initial',
            'xyo_det': 'Measured',
        }

        hkls, xyo_det, idx_0 = parse_spots_data(
            spots_data, instr, grain_ids, ome_period
        )

        calibrators = []
        for i in grain_ids:
            data_dict = {
                'hkls': {},
                'pick_xys': {},
            }
            for det_key in instr.detectors:
                data_dict['hkls'][det_key] = hkls[det_key][i]
                data_dict['pick_xys'][det_key] = xyo_det[det_key][i]

            kwargs = {
                'instr': instr,
                'material': material,
                'grain_params': grain_params[i],
                'ome_period': ome_period,
                'index': grain_ids[i],
                'euler_convention': euler_convention,
            }
            calibrator = GrainCalibrator(**kwargs)
            calibrator.data_dict = data_dict
            calibrators.append(calibrator)

        self.ic = InstrumentCalibrator(
            *calibrators,
            euler_convention=euler_convention,
        )

        xyo_i = compute_xyo(calibrators)

        data = {
            'xyo_i': xyo_i,
            'xyo_det': xyo_det,
        }
        kwargs = {
            'data': data,
            'styles': plot_styles,
            'labels': plot_labels,
            'grain_ids': grain_ids,
            'cfg': cfg,
            'title': 'Initial Guess. Proceed?',
            'ome_period': np.degrees(ome_period),
            'parent': self.parent,
        }
        dialog = HEDMCalibrationResultsDialog(**kwargs)
        if not dialog.exec():
            return

        format_extra_params_func = partial(
            format_material_params_func,
            overlays=self.active_overlays,
            calibrators=self.ic.calibrators,
        )

        # Open up the HEDM calibration dialog with these picks
        kwargs = {
            'instr': instr,
            'params_dict': self.ic.params,
            'format_extra_params_func': format_extra_params_func,
            'parent': self.parent,
            'engineering_constraints': self.ic.engineering_constraints,
            'window_title': 'HEDM Calibration',
            'help_url': 'calibration/rotation_series',
        }
        dialog = HEDMCalibrationDialog(**kwargs)

        # Connect interactions to functions
        self._dialog_callback_handler = HEDMCalibrationCallbacks(
            self.active_overlays,
            spots_data,
            dialog,
            self.ic,
            instr,
            self.async_runner,
        )
        self._dialog_callback_handler.instrument_updated.connect(
            self.on_calibration_finished
        )
        dialog.show()

    def on_calibration_finished(self):
        overlays = self.active_overlays
        for overlay, calibrator in zip(overlays, self.ic.calibrators):
            modified = any(
                self.ic.params[param_name].vary for param_name in calibrator.param_names
            )
            if not modified:
                # Just skip over it
                continue

            overlay.crystal_params = calibrator.grain_params

            mat_name = overlay.material_name
            HexrdConfig().flag_overlay_updates_for_material(mat_name)
            HexrdConfig().material_modified.emit(mat_name)

        # In case any overlays changed
        HexrdConfig().overlay_config_changed.emit()
        HexrdConfig().update_overlay_editor.emit()
        self.finished.emit()

    def run_pull_spots(self):
        cfg = create_indexing_config()

        instr = cfg.instrument.hedm
        imsd = cfg.image_series

        outputs = {}
        for i, overlay in enumerate(self.active_overlays):
            kwargs = {
                'plane_data': self.material.planeData,
                'grain_params': overlay.crystal_params,
                'tth_tol': np.degrees(overlay.tth_width),
                'eta_tol': np.degrees(overlay.eta_width),
                'ome_tol': np.degrees(overlay.ome_width),
                'imgser_dict': imsd,
                'npdiv': cfg.fit_grains.npdiv,
                'threshold': cfg.fit_grains.threshold,
                'eta_ranges': overlay.eta_ranges,
                'ome_period': overlay.ome_period,
                'dirname': cfg.analysis_dir,
                'filename': None,
                'return_spot_list': False,
                'check_only': False,
                'interp': 'nearest',
            }
            outputs[i] = instr.pull_spots(**kwargs)

        return outputs

    @property
    def grain_params(self):
        return self.grains_table[:, 3:15]

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

    @property
    def num_active_overlays(self):
        return len(self.active_overlays)

    @property
    def first_active_overlay(self):
        overlays = self.active_overlays
        return overlays[0] if overlays else None

    @property
    def ome_period(self):
        # These should be the same for all overlays, and it is pre-validated
        return self.first_active_overlay.ome_period

    @property
    def material(self):
        return self.first_active_overlay.material

    @property
    def active_overlay_refinements(self):
        return [x.refinements for x in self.active_overlays]

    def synchronize_material(self):
        # This material is used for creating the indexing config.
        # Make sure it matches the material we are using.
        cfg = HexrdConfig().indexing_config
        cfg['_selected_material'] = self.material.name

    def synchronize_omega_period(self):
        # This omega period is deprecated, but still used in some places.
        # Make sure it is synchronized with our overlays' omega period.
        cfg = HexrdConfig().indexing_config
        cfg['find_orientations']['omega']['period'] = np.degrees(self.ome_period)

    def pre_validate(self):
        # Validation to perform before we do anything else
        if not self.active_overlays:
            # No more validation needed.
            return

        ome_periods = []
        for overlay in self.active_overlays:
            if not overlay.has_widths:
                msg = 'All visible rotation series overlays must have widths ' 'enabled'
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
            msg = 'All visible rotation series overlays must have the same ' 'material'
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
