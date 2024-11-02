import numpy as np

from PySide6.QtCore import QObject, Signal

from hexrd import constants as cnst, instrument
from hexrd.fitting import calibration
from hexrd.transforms import xfcapi

from hexrdgui.calibration.hedm import (
    HEDMCalibrationOptionsDialog,
    HEDMCalibrationResultsDialog,
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.indexing.create_config import (
    create_indexing_config, OmegasNotFoundError
)
from hexrdgui.message_box import MessageBox
from hexrdgui.utils import instr_to_internal_dict


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
        dialog = self.options_dialog

        shape = (self.num_active_overlays, 21)
        self.grains_table = np.empty(shape, dtype=np.float64)
        gw = instrument.GrainDataWriter(array=self.grains_table)
        for i, overlay in enumerate(self.active_overlays):
            gw.dump_grain(i, 1, 0, overlay.crystal_params)

        self.synchronize_omega_period()

        # Grab some selections from the dialog
        self.do_refit = dialog.do_refit
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

        param_flags = self.param_flags
        grain_flags = self.grain_flags

        # User selected these from the dialog
        do_refit = self.do_refit

        # Our grains table only contains the grains that the user
        # selected.
        grain_parameters = self.grain_parameters
        grain_ids = self.grains_table[:, 0].astype(int)

        # Order the spots data list in the order of the grain ids
        spots_data = [spots_data_dict[gid] for gid in grain_ids]

        # plane data
        plane_data = cfg.material.plane_data
        bmat = plane_data.latVecOps['B']

        ome_period = self.ome_period

        grain_parameters = grain_parameters.copy()
        ngrains = len(grain_parameters)

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

        hkls, xyo_det, idx_0 = parse_spots_data(spots_data, instr, grain_ids)

        xyo_i = calibration.calibrate_instrument_from_sx(
            instr, grain_parameters, bmat, xyo_det, hkls,
            ome_period=np.radians(ome_period), sim_only=True
        )

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
            'ome_period': ome_period,
            'parent': self.parent,
        }
        dialog = HEDMCalibrationResultsDialog(**kwargs)
        if not dialog.exec():
            return

        # Run optimization
        params, resd, xyo_f = calibration.calibrate_instrument_from_sx(
            instr, grain_parameters, bmat, xyo_det, hkls,
            ome_period=np.radians(ome_period),
            param_flags=param_flags,
            grain_flags=grain_flags
        )

        # update calibration crystal params
        grain_parameters = params[-grain_parameters.size:].reshape(ngrains, 12)

        if not do_refit:
            data = {
                'xyo_i': xyo_i,
                'xyo_det': xyo_det,
                'xyo_f': xyo_f,
            }
            kwargs = {
                'data': data,
                'styles': plot_styles,
                'labels': plot_labels,
                'grain_ids': grain_ids,
                'cfg': cfg,
                'title': 'Final results. Accept?',
                'ome_period': ome_period,
                'parent': self.parent,
            }
            dialog = HEDMCalibrationResultsDialog(**kwargs)
            if not dialog.exec():
                return

            # All done! Update the results.
            self.results = grain_parameters
            self.on_calibration_finished()
            return

        # load imageseries dict
        ims_dict = cfg.image_series
        ims = next(iter(ims_dict.values()))    # grab first member
        delta_ome = ims.metadata['omega'][:, 1] - ims.metadata['omega'][:, 0]
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
            spots_data, instr, grain_ids, refit_idx=idx_0)

        # perform refit
        params, resd, xyo_f = calibration.calibrate_instrument_from_sx(
            instr, grain_parameters, bmat, xyo_det_refit, hkls_refit,
            ome_period=np.radians(ome_period),
            param_flags=param_flags,
            grain_flags=grain_flags
        )

        data = {
            'xyo_i': xyo_i,
            'xyo_det': xyo_det,
            'xyo_f': xyo_f,
        }
        kwargs = {
            'data': data,
            'styles': plot_styles,
            'labels': plot_labels,
            'grain_ids': grain_ids,
            'cfg': cfg,
            'title': 'Final results. Accept?',
            'ome_period': ome_period,
            'parent': self.parent,
        }
        dialog = HEDMCalibrationResultsDialog(**kwargs)
        if not dialog.exec():
            return

        # update calibration crystal params
        grain_parameters = params[-grain_parameters.size:].reshape(ngrains, 12)

        self.results = grain_parameters
        self.on_calibration_finished()

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
                'quiet': True,
                'check_only': False,
                'interp': 'nearest',
            }
            outputs[i] = instr.pull_spots(**kwargs)

        return outputs

    def on_calibration_finished(self):
        self.write_results_message()

        # Update the instrument
        self.update_config()

    def write_results_message(self):
        msg = ''

        pnames = calibration.generate_parameter_names(self.instr,
                                                      self.grain_parameters)

        # First, show any updates to instrument parameters
        instr_flags = self.instr.calibration_flags
        if any(instr_flags):
            cfg = create_indexing_config()
            old_instr = cfg.instrument.hedm
            old_values = old_instr.calibration_parameters[instr_flags]
            new_values = self.instr.calibration_parameters[instr_flags]
            refinable = np.where(instr_flags)[0]

            for i, old, new in zip(refinable, old_values, new_values):
                name = pnames[i]
                msg += f'\t{name}: {old: 12.8f}  => {new: 12.8f}\n'

        # Next, the overlay parameters
        pname_start_ind = len(instr_flags)
        for results, overlay in zip(self.results, self.active_overlays):
            name = overlay.name
            refinements = overlay.refinements
            if any(refinements):
                old_values = overlay.crystal_params[refinements]
                new_values = results[refinements]
                refinable = np.where(refinements)[0]

                for i, old, new in zip(refinable, old_values, new_values):
                    name = pnames[pname_start_ind + i]
                    msg += f'\t{name}: {old: 12.8f}  => {new: 12.8f}\n'

            pname_start_ind += len(refinements)

        self.results_message = msg

    def update_config(self):
        # Print the results message first
        print('Optimization successful!')
        print(self.results_message)

        kwargs = {
            'title': 'HEXRD',
            'message': 'Optimization successful!',
            'details': self.results_message,
            'parent': self.parent,
        }
        msg_box = MessageBox(**kwargs)
        msg_box.exec()

        # Update rotation series parameters from the results
        for results, overlay in zip(self.results, self.active_overlays):
            overlay.crystal_params[:] = results

        # Update modified instrument parameters
        output_dict = instr_to_internal_dict(self.instr)

        # Save the previous iconfig to restore the statuses
        prev_iconfig = HexrdConfig().config['instrument']

        # Update the config
        HexrdConfig().config['instrument'] = output_dict

        # This adds in any missing keys. In particular, it is going to
        # add in any "None" detector distortions
        HexrdConfig().set_detector_defaults_if_missing()

        # Add status values
        HexrdConfig().add_status(output_dict)

        # Set the previous statuses to be the current statuses
        HexrdConfig().set_statuses_from_prev_iconfig(prev_iconfig)

        # Tell GUI that the overlays need to be re-computed
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)

        # update the materials panel
        if self.material is HexrdConfig().active_material:
            HexrdConfig().active_material_modified.emit()

        # Update the overlay editor in case it is visible
        HexrdConfig().update_overlay_editor.emit()

        # redraw updated overlays
        HexrdConfig().overlay_config_changed.emit()

        # Keep a copy of the output grains table on HexrdConfig
        grains_table = self.grains_table.copy()
        grains_table[:, 3:15] = self.results
        HexrdConfig().hedm_calibration_output_grains_table = grains_table

        # Done!
        self.finished.emit()

    @property
    def grain_parameters(self):
        return self.grains_table[:, 3:15]

    @property
    def param_flags(self):
        return HexrdConfig().get_statuses_instrument_format()

    @property
    def grain_flags(self):
        return np.array(self.active_overlay_refinements).flatten()

    @property
    def all_flags(self):
        return np.concatenate((self.param_flags, self.grain_flags))

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
        return np.degrees(self.first_active_overlay.ome_period)

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
        cfg['find_orientations']['omega']['period'] = self.ome_period

    def pre_validate(self):
        # Validation to perform before we do anything else
        if not self.active_overlays:
            # No more validation needed.
            return

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


def parse_spots_data(spots_data, instr, grain_ids, refit_idx=None):
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
            xyo_det[det_key].append(np.hstack([np.vstack(data[idx, 7]),
                                               meas_omes]))

    return hkls, xyo_det, idx_0
