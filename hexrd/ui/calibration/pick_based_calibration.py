# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 14:20:48 2020

@author: berni
"""

import copy

import numpy as np

from scipy import ndimage
from scipy.integrate import nquad
from scipy.optimize import leastsq

from skimage import filters
from skimage.feature import blob_log

from hexrd.ui.calibration.calibrationutil import (
    gaussian_2d, gaussian_2d_int, sxcal_obj_func,
    __reflInfo_dtype as reflInfo_dtype
)
from hexrd.ui.utils.conversions import angles_to_cart
from hexrd.constants import fwhm_to_sigma
from hexrd.fitting.calibration import PowderCalibrator
from hexrd.transforms import xfcapi
from hexrd import xrdutil


def enrich_pick_data(picks, instr, materials):
    # add plane_data, xy points from angles...
    data_key = 'pick_xys'
    for pick_data in picks:
        # need plane data
        material_name = pick_data['material']
        plane_data = materials[material_name].planeData
        pick_data['plane_data'] = plane_data

        # now add additional data depending on pick type
        pick_dict = pick_data['picks']
        pick_type = pick_data['type']

        # loop over detectors
        pick_data[data_key] = dict.fromkeys(pick_dict)
        for det_key, panel in instr.detectors.items():
            if pick_type == 'laue':
                # need grain parameters and stacked picks
                grain_params = pick_data['options']['crystal_params']
                tth_eta_picks = pick_dict[det_key]
                if len(tth_eta_picks) == 0:
                    tth_eta_picks = np.empty((0, 2))
                    pick_data[data_key][det_key] = np.empty((0, 2))
                else:
                    # calculate cartesian coords
                    tth_eta_picks = np.vstack(tth_eta_picks)
                    xy_picks = panel.angles_to_cart(
                        np.radians(tth_eta_picks),
                        tvec_c=np.asarray(grain_params[3:6], dtype=float)
                    )
                    pick_data[data_key][det_key] = xy_picks
            elif pick_type == 'powder':
                # !!! need translation vector from overlay
                tvec_c = np.asarray(
                    pick_data['options']['tvec'], dtype=float
                ).flatten()

                # calculate cartesian coords
                # !!! uses translation vector
                pdl = []
                for ring_picks in pick_dict[det_key]:
                    if len(ring_picks) > 0:
                        xy_picks = panel.angles_to_cart(
                            np.atleast_2d(np.radians(ring_picks)),
                            tvec_c=tvec_c
                        )
                    else:
                        xy_picks = []
                    pdl.append(xy_picks)
                pick_data[data_key][det_key] = pdl


# %% CLASSES

class LaueCalibrator(object):
    calibrator_type = 'laue'
    _nparams = 12

    def __init__(self, instr, plane_data, grain_params, flags,
                 min_energy=5., max_energy=25.):
        self._instr = instr
        self._plane_data = copy.deepcopy(plane_data)
        self._plane_data.wavelength = self._instr.beam_energy  # force
        self._params = np.asarray(grain_params, dtype=float).flatten()
        assert len(self._params) == self._nparams, \
            "grain parameters must have %d elements" % self._nparams
        self._full_params = np.hstack(
            [self._instr.calibration_parameters, self._params]
        )
        assert len(flags) == len(self._full_params), \
            "flags must have %d elements; you gave %d" \
            % (len(self._full_params), len(flags))
        self._flags = flags
        self._energy_cutoffs = [min_energy, max_energy]

    @property
    def instr(self):
        return self._instr

    @property
    def plane_data(self):
        self._plane_data.wavelength = self.energy_cutoffs[-1]
        self._plane_data.exclusions = None
        return self._plane_data

    @property
    def params(self):
        return self._params

    @params.setter
    def params(self, x):
        x = np.atleast_1d(x)
        if len(x) != len(self.params):
            raise RuntimeError("params must have %d elements"
                               % len(self.params))
        self._params = x

    @property
    def full_params(self):
        return self._full_params

    @property
    def npi(self):
        return len(self._instr.calibration_parameters)

    @property
    def npe(self):
        return len(self._params)

    @property
    def flags(self):
        return self._flags

    @flags.setter
    def flags(self, x):
        x = np.atleast_1d(x)
        nparams_instr = len(self.instr.calibration_parameters)
        nparams_extra = len(self.params)
        nparams = nparams_instr + nparams_extra
        if len(x) != nparams:
            raise RuntimeError("flags must have %d elements" % nparams)
        self._flags = np.asarrasy(x, dtype=bool)
        self._instr.calibration_flags = self._flags[:nparams_instr]

    @property
    def energy_cutoffs(self):
        return self._energy_cutoffs

    @energy_cutoffs.setter
    def energy_cutoffs(self, x):
        assert len(x) == 2, "input must have 2 elements"
        assert x[1] > x[0], "first element must be < than second"
        self._energy_cutoffs = x

    def _autopick_points(self, raw_img_dict, tth_tol=5., eta_tol=5.,
                         npdiv=2, do_smoothing=True, smoothing_sigma=2,
                         use_blob_detection=True, blob_threshold=0.25,
                         fit_peaks=True, min_peak_int=1., fit_tth_tol=0.1):
        """


        Parameters
        ----------
        raw_img_dict : TYPE
            DESCRIPTION.
        tth_tol : TYPE, optional
            DESCRIPTION. The default is 5..
        eta_tol : TYPE, optional
            DESCRIPTION. The default is 5..
        npdiv : TYPE, optional
            DESCRIPTION. The default is 2.
        do_smoothing : TYPE, optional
            DESCRIPTION. The default is True.
        smoothing_sigma : TYPE, optional
            DESCRIPTION. The default is 2.
        use_blob_detection : TYPE, optional
            DESCRIPTION. The default is True.
        blob_threshold : TYPE, optional
            DESCRIPTION. The default is 0.25.
        fit_peaks : TYPE, optional
            DESCRIPTION. The default is True.

        Returns
        -------
        None.

        """
        labelStructure = ndimage.generate_binary_structure(2, 1)
        rmat_s = np.eye(3)  # !!! forcing to identity
        omega = 0.  # !!! same ^^^

        rmat_c = xfcapi.makeRotMatOfExpMap(self.params[:3])
        tvec_c = self.params[3:6]
        # vinv_s = self.params[6:12]  # !!!: patches don't take this yet

        # run simulation
        # ???: could we get this from overlays?
        laue_sim = self.instr.simulate_laue_pattern(
            self.plane_data,
            minEnergy=self.energy_cutoffs[0],
            maxEnergy=self.energy_cutoffs[1],
            rmat_s=None, grain_params=np.atleast_2d(self.params),
        )

        # loop over detectors for results
        refl_dict = dict.fromkeys(self.instr.detectors)
        for det_key, det in self.instr.detectors.items():
            det_config = det.config_dict(
                chi=self.instr.chi,
                tvec=self.instr.tvec,
                beam_vector=self.instr.beam_vector
            )

            xy_det, hkls, angles, dspacing, energy = laue_sim[det_key]
            '''
            valid_xy = []
            valid_hkls = []
            valid_angs = []
            valid_energy = []
            '''
            # !!! not necessary to loop over grains since we can only handle 1
            # for gid in range(len(xy_det)):
            gid = 0
            # find valid reflections
            valid_refl = ~np.isnan(xy_det[gid][:, 0])
            valid_xy = xy_det[gid][valid_refl, :]
            valid_hkls = hkls[gid][:, valid_refl]
            valid_angs = angles[gid][valid_refl, :]
            valid_energy = energy[gid][valid_refl]
            # pass

            # make patches
            refl_patches = xrdutil.make_reflection_patches(
                det_config,
                valid_angs, det.angularPixelSize(valid_xy),
                rmat_c=rmat_c, tvec_c=tvec_c,
                tth_tol=tth_tol, eta_tol=eta_tol,
                npdiv=npdiv, quiet=True)

            reflInfoList = []
            img = raw_img_dict[det_key]
            native_area = det.pixel_area
            num_patches = len(refl_patches)
            meas_xy = np.nan*np.ones((num_patches, 2))
            meas_angs = np.nan*np.ones((num_patches, 2))
            for iRefl, patch in enumerate(refl_patches):
                # check for overrun
                irow = patch[-1][0]
                jcol = patch[-1][1]
                if np.any([irow < 0, irow >= det.rows,
                           jcol < 0, jcol >= det.cols]):
                    continue
                if not np.all(
                        det.clip_to_panel(
                            np.vstack([patch[1][0].flatten(),
                                       patch[1][1].flatten()]).T
                            )[1]
                        ):
                    continue
                # use nearest interpolation
                spot_data = img[irow, jcol] * patch[3] * npdiv**2 / native_area
                spot_data -= np.amin(spot_data)
                patch_size = spot_data.shape

                sigmax = 0.25*np.min(spot_data.shape) * fwhm_to_sigma

                # optional gaussian smoothing
                if do_smoothing:
                    spot_data = filters.gaussian(spot_data, smoothing_sigma)

                if use_blob_detection:
                    spot_data_scl = 2.*spot_data/np.max(spot_data) - 1.

                    # Compute radii in the 3rd column.
                    blobs_log = blob_log(spot_data_scl,
                                         min_sigma=2,
                                         max_sigma=min(sigmax, 20),
                                         num_sigma=10,
                                         threshold=blob_threshold,
                                         overlap=0.1)
                    numPeaks = len(blobs_log)
                else:
                    labels, numPeaks = ndimage.label(
                        spot_data > np.percentile(spot_data, 99),
                        structure=labelStructure
                    )
                    slabels = np.arange(1, numPeaks + 1)
                tth_edges = patch[0][0][0, :]
                eta_edges = patch[0][1][:, 0]
                delta_tth = tth_edges[1] - tth_edges[0]
                delta_eta = eta_edges[1] - eta_edges[0]
                if numPeaks > 0:
                    peakId = iRefl
                    if use_blob_detection:
                        coms = blobs_log[:, :2]
                    else:
                        coms = np.array(
                            ndimage.center_of_mass(
                                spot_data, labels=labels, index=slabels
                                )
                            )
                    if numPeaks > 1:
                        #
                        center = np.r_[spot_data.shape]*0.5
                        com_diff = coms - np.tile(center, (numPeaks, 1))
                        closest_peak_idx = np.argmin(
                            np.sum(com_diff**2, axis=1)
                        )
                        #
                    else:
                        closest_peak_idx = 0
                        pass   # end multipeak conditional
                    #
                    coms = coms[closest_peak_idx]
                    #
                    if fit_peaks:
                        sigm = 0.2*np.min(spot_data.shape)
                        if use_blob_detection:
                            sigm = min(blobs_log[closest_peak_idx, 2], sigm)
                        y0, x0 = coms.flatten()
                        ampl = float(spot_data[int(y0), int(x0)])
                        # y0, x0 = 0.5*np.array(spot_data.shape)
                        # ampl = np.max(spot_data)
                        a_par = c_par = 0.5/float(sigm**2)
                        b_par = 0.
                        bgx = bgy = 0.
                        bkg = np.min(spot_data)
                        params = [ampl,
                                  a_par, b_par, c_par,
                                  x0, y0, bgx, bgy, bkg]
                        #
                        result = leastsq(gaussian_2d, params, args=(spot_data))
                        #
                        fit_par = result[0]
                        #
                        coms = np.array([fit_par[5], fit_par[4]])
                        '''
                        print("%s, %d, (%.2f, %.2f), (%d, %d)"
                              % (det_key, iRefl, coms[0], coms[1],
                                 patch_size[0], patch_size[1]))
                        '''
                        row_cen = fit_tth_tol * patch_size[0]
                        col_cen = fit_tth_tol * patch_size[1]
                        if np.any(
                            [coms[0] < row_cen,
                             coms[0] >= patch_size[0] - row_cen,
                             coms[1] < col_cen,
                             coms[1] >= patch_size[1] - col_cen]
                        ):
                            continue
                        if (fit_par[0] < min_peak_int):
                            continue

                        # intensities
                        spot_intensity, int_err = nquad(
                            gaussian_2d_int,
                            [[0., 2.*y0], [0., 2.*x0]],
                            args=fit_par)
                        pass
                    com_angs = np.hstack([
                        tth_edges[0] + (0.5 + coms[1])*delta_tth,
                        eta_edges[0] + (0.5 + coms[0])*delta_eta
                        ])

                    # grab intensities
                    if not fit_peaks:
                        if use_blob_detection:
                            spot_intensity = 10
                            max_intensity = 10
                        else:
                            spot_intensity = np.sum(
                                spot_data[labels == slabels[closest_peak_idx]]
                            )
                            max_intensity = np.max(
                                spot_data[labels == slabels[closest_peak_idx]]
                            )
                    else:
                        max_intensity = np.max(spot_data)
                    # need xy coords
                    # !!! forcing ome = 0. -- could be inconsistent with rmat_s
                    cmv = np.atleast_2d(np.hstack([com_angs, omega]))
                    gvec_c = xfcapi.anglesToGVec(
                        cmv,
                        chi=self.instr.chi,
                        rMat_c=rmat_c,
                        bHat_l=self.instr.beam_vector)
                    new_xy = xfcapi.gvecToDetectorXY(
                        gvec_c,
                        det.rmat, rmat_s, rmat_c,
                        det.tvec, self.instr.tvec, tvec_c,
                        beamVec=self.instr.beam_vector)
                    meas_xy[iRefl, :] = new_xy
                    if det.distortion is not None:
                        meas_xy[iRefl, :] = det.distortion.apply_inverse(
                            meas_xy[iRefl, :]
                        )
                    meas_angs[iRefl, :] = com_angs
                else:
                    peakId = -999
                    #
                    spot_intensity = np.nan
                    max_intensity = np.nan
                    pass
                reflInfoList.append([peakId, valid_hkls[:, iRefl],
                                     (spot_intensity, max_intensity),
                                     valid_energy[iRefl],
                                     valid_angs[iRefl, :],
                                     meas_angs[iRefl, :],
                                     meas_xy[iRefl, :]])
                pass
            reflInfo = np.array(
                [tuple(i) for i in reflInfoList],
                dtype=reflInfo_dtype)
            refl_dict[det_key] = reflInfo

        # !!! ok, here is where we would populated the data_dict from refl_dict
        return refl_dict

    def _evaluate(self, reduced_params, data_dict):
        """
        """
        # first update instrument from input parameters
        full_params = np.asarray(self.full_params)
        full_params[self.flags] = reduced_params

        self.instr.update_from_parameter_list(full_params[:self.npi])
        self.params = full_params[self.npi:]

        # grab reflection data from picks input
        pick_hkls_dict = dict.fromkeys(self.instr.detectors)
        pick_xys_dict = dict.fromkeys(self.instr.detectors)
        for det_key in self.instr.detectors:
            # find valid reflections and recast hkls to int
            xys = data_dict['pick_xys'][det_key]
            hkls = np.asarray(data_dict['hkls'][det_key], dtype=int)

            valid_idx = ~np.isnan(xys[:, 0])

            # fill local dicts
            pick_hkls_dict[det_key] = np.atleast_2d(hkls[valid_idx, :]).T
            pick_xys_dict[det_key] = np.atleast_2d(xys[valid_idx, :])

        return pick_hkls_dict, pick_xys_dict

    def residual(self, reduced_params, data_dict):
        # need this for laue obj
        bmatx = self.plane_data.latVecOps['B']
        pick_hkls_dict, pick_xys_dict = self._evaluate(
            reduced_params, data_dict
        )
        # munge energy cutoffs
        energy_cutoffs = np.r_[0.5, 1.5] * np.asarray(self.energy_cutoffs)

        return sxcal_obj_func(
            reduced_params, self.full_params, self.flags,
            self.instr, pick_xys_dict, pick_hkls_dict,
            bmatx, energy_cutoffs
        )

    def model(self, reduced_params, data_dict):
        # need this for laue obj
        bmatx = self.plane_data.latVecOps['B']
        pick_hkls_dict, pick_xys_dict = self._evaluate(
            reduced_params, data_dict,
        )

        return sxcal_obj_func(
            reduced_params, self.full_params, self.flags,
            self.instr, pick_xys_dict, pick_hkls_dict,
            bmatx, self.energy_cutoffs,
            sim_only=True
        )


class CompositeCalibration(object):
    def __init__(self, instr, processed_picks, img_dict):
        self.instr = instr
        self.npi = len(self.instr.calibration_parameters)
        self.data = processed_picks
        calibrator_list = []
        params = []
        param_flags = []
        for pick_data in processed_picks:
            if pick_data['type'] == 'powder':
                # flags for calibrator
                lpflags = [i[1] for i in pick_data['refinements']]
                flags = np.hstack(
                    [self.instr.calibration_flags, lpflags]
                )
                param_flags.append(lpflags)
                calib = PowderCalibrator(
                    self.instr, pick_data['plane_data'], img_dict, flags
                )
                params.append(calib.full_params[-calib.npe:])
                calibrator_list.append(calib)

            elif pick_data['type'] == 'laue':
                # flags for calibrator
                gparams = pick_data['options']['crystal_params']
                min_energy = pick_data['options']['min_energy']
                max_energy = pick_data['options']['max_energy']

                gpflags = [i[1] for i in pick_data['refinements']]
                flags = np.hstack(
                    [self.instr.calibration_flags, gpflags]
                )
                param_flags.append(gpflags)
                calib = LaueCalibrator(
                    self.instr, pick_data['plane_data'],
                    gparams, flags,
                    min_energy=min_energy, max_energy=max_energy
                )
                params.append(calib.full_params[-calib.npe:])
                calibrator_list.append(calib)

        self.calibrators = calibrator_list
        self.params = np.hstack(params)
        self.param_flags = np.hstack(param_flags)
        self.full_params = np.hstack(
            [self.instr.calibration_parameters, self.params]
        )
        self.flags = np.hstack(
            [self.instr.calibration_flags, self.param_flags]
        )

    def reduced_params(self):
        return self.full_params[self.flags]

    def residual(self, reduced_params, pick_data_list):
        # first update full parameter list
        self.full_params[self.flags] = reduced_params
        instr_params = self.full_params[:self.npi]
        addtl_params = self.full_params[self.npi:]

        def powder_residual(calib, these_reduced_params, data_dict):
            # Convert our data_dict into the input data format that
            # the powder calibrator is expecting.
            calibration_data = {}
            for det_key in data_dict['hkls']:
                panel = self.instr.detectors[det_key]

                picks_list = []
                for i, hkl in enumerate(data_dict['hkls'][det_key]):
                    picks = data_dict['picks'][det_key][i]
                    if not picks:
                        continue

                    # Each row consists of 8 columns:
                    # First two are measured x, y
                    # Third is unknown (appears unused in the PowderCalibrator)
                    # Four - six are the hkl indices
                    # Seven and Eight are unknown (appears unused here)

                    # We are going to convert our data into rows of 6 columns.
                    # We will fill in zero for the third column, and ignore
                    # the last two columns.

                    # Convert the angles to Cartesian
                    cartesian_picks = angles_to_cart(picks, panel)
                    repeated_zero = np.repeat([[0]], len(cartesian_picks),
                                              axis=0)
                    repeated_hkl = np.repeat([hkl], len(cartesian_picks),
                                             axis=0)
                    formatted = np.hstack((cartesian_picks, repeated_zero,
                                           repeated_hkl))
                    picks_list.append(formatted)

                calibration_data[det_key] = picks_list

            return calib.residual(these_reduced_params, calibration_data)

        def laue_residual(calib, these_reduced_params, data_dict):
            return calib.residual(these_reduced_params, data_dict)

        residual_funcs = {
            PowderCalibrator: powder_residual,
            LaueCalibrator: laue_residual,
        }

        # loop calibrators and collect residuals
        ii = 0
        residual = []
        for ical, calib in enumerate(self.calibrators):
            # make copy offull params for this calibrator
            these_full_params = np.hstack(
                [instr_params, addtl_params[ii:ii + calib.npe]]
            )

            # pull out reduced list
            these_reduced_params = these_full_params[calib.flags]

            # call to calibrator residual api with proper index into pick data
            f = residual_funcs[type(calib)]
            residual.append(
                f(calib, these_reduced_params, pick_data_list[ical])
            )

            # advance alibrator extra parameter offset
            ii += calib.npe

        # return single hstacked residual
        return np.hstack(residual)


def run_calibration(picks, instr, img_dict, materials):
    enrich_pick_data(picks, instr, materials)

    # Run composite calibration
    instr_calibrator = CompositeCalibration(instr, picks, img_dict)

    x0_comp = instr_calibrator.reduced_params()

    x1, cox_x, infodict, mesg, ierr = leastsq(
                        instr_calibrator.residual, x0_comp, args=(picks, ),
                        factor=0.1, full_output=True
                    )
    return instr_calibrator


if __name__ == '__main__':

    import json
    import pickle as pkl

    # %% grab serialiazed objects
    instr = pkl.load(open('instrument.pkl', 'rb'))

    with open('calibration_picks.json', 'r') as f:
        picks = json.load(f)

    material_names = [x['material'] for x in picks]
    materials = {x: pkl.load(open(f'{x}.pkl', 'rb')) for x in material_names}

    # instrument parameter flags
    # !!! these come from the GUI tree view
    iflags = np.array(
        [0,
         1, 1,
         0,
         0, 0, 0,
         0, 0, 1, 1, 1, 1,
         0, 0, 0, 1, 1, 1],
        dtype=bool
    )
    instr.calibration_flags = iflags  # update instrument

    instr_calibrator = run_calibration(picks, instr, materials)
    instr.write_config('new-instrument-comp.yml')

    # %%
    """
    Now we just need to update the values in the GUI; the instrument class is
    updated already, can just grab its parameter dict
    The powder and laue parameters can be lifted from the corresp classes
    """
    for ical, cal_class in enumerate(instr_calibrator.calibrators):
        pnames = ['{:>24s}'.format(i[0]) for i in picks[ical]['refinements']]
        print("calibrator type: %s" % cal_class.calibrator_type)
        print("refined parameters:")
        for pname, param in zip(pnames, cal_class.params):
            print("\t%s = %.7e" % (pname, param))
