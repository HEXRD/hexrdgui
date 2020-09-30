# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 14:20:48 2020

@author: berni
"""

import numpy as np

from scipy.optimize import leastsq

from hexrd.ui.calibration.calibrationutil import sxcal_obj_func


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
                tth_eta_picks = np.vstack(pick_dict[det_key])

                # calculate cartesian coords
                xy_picks = panel.angles_to_cart(
                    np.radians(tth_eta_picks),
                    tvec_c=np.asarray(grain_params[3:6], dtype=float)
                )
                pick_data[data_key][det_key] = xy_picks
            elif pick_type == 'powder':
                # need translation vector
                tvec_c = np.asarray(
                    pick_data['options']['tvec'], dtype=float
                ).flatten()

                # calculate cartesian coords
                pdl = []
                for ring_picks in pick_dict[det_key]:
                    if len(ring_picks) > 0:
                        xy_picks = panel.angles_to_cart(
                            np.atleast_2d(np.radians(ring_picks)),
                            tvec_c=tvec_c
                        )
                        pdl.append(xy_picks)
                pick_data[data_key][det_key] = pdl


# %% CLASSES

class LaueCalibrator(object):
    calibrator_type = 'laue'
    _nparams = 12

    def __init__(self, instr, plane_data, grain_params, flags,
                 min_energy=5., max_energy=25.):
        self._instr = instr
        self._plane_data = plane_data
        self._plane_data.wavelength = self._instr.beam_energy  # force
        self._params = np.asarray(grain_params, dtype=float).flatten()
        assert len(self._params) == self._nparams, \
            "grain parameters must have %d elements" % self._nparams
        self._full_params = np.hstack(
            [self._instr.calibration_parameters, self._params]
        )
        assert len(flags) == len(self._full_params), \
            "flags must have %d elements" % len(self._full_params)
        self._flags = flags
        self._energy_cutoffs = [min_energy, max_energy]

    @property
    def instr(self):
        return self._instr

    @property
    def plane_data(self):
        self._plane_data.wavelength = self._instr.beam_energy
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
        assert x[1] > x[0, "first element must be < than second"]
        self._energy_cutoffs = x

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


class PowderCalibrator(object):
    _CALIBRATOR_TYPE = 'powder'

    def __init__(self, instr, plane_data, flags):
        self._instr = instr
        self._plane_data = plane_data
        self._plane_data.wavelength = self._instr.beam_energy  # force
        self._params = np.asarray(self._plane_data.lparms, dtype=float)
        self._full_params = np.hstack(
            [self._instr.calibration_parameters, self._params]
        )
        assert len(flags) == len(self._full_params), \
            "flags must have %d elements" % len(self._full_params)
        self._flags = flags

    @property
    def calibrator_type(self):
        return self._CALIBRATOR_TYPE

    @property
    def instr(self):
        return self._instr

    @property
    def plane_data(self):
        self._plane_data.wavelength = self._instr.beam_energy
        return self._plane_data

    @property
    def params(self):
        return self._params

    @params.setter
    def params(self, x):
        x = np.atleast_1d(x)
        if len(x) != len(self.plane_data.lparms):
            raise RuntimeError("params must have %d elements"
                               % len(self.plane_data.lparms))
        self._params = x
        self._plane_data.lparms = x

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

    def _evaluate(self, reduced_params, data_dict, output='residual'):
        """
        """
        # need this for dsp
        bmatx = self.plane_data.latVecOps['B']
        hkls_ref = self.plane_data.hkls.T
        dsp_ref = self.plane_data.getPlaneSpacings()

        # first update instrument from input parameters
        full_params = np.asarray(self.full_params)
        full_params[self.flags] = reduced_params

        self.instr.update_from_parameter_list(full_params[:self.npi])
        self.params = full_params[self.npi:]

        wlen = self.instr.beam_wavelength

        # working with Patrick's pick dicts
        pick_angs_dict = data_dict['picks']
        pick_xys_dict = data_dict['pick_xys']
        tvec_c = np.asarray(
            data_dict['options']['tvec'], dtype=float
        ).flatten()

        # build residual
        retval = []
        for det_key, panel in self.instr.detectors.items():
            pick_angs = pick_angs_dict[det_key]
            pick_xys = pick_xys_dict[det_key]
            assert len(pick_angs) == len(dsp_ref), "picks are wrong length"
            assert len(pick_angs) == len(pick_xys), "pick xy data inconsistent"
            # the data structure is:
            #     [x, y, tth, eta, h, k, l, dsp0]
            # FIXME: clean this up!
            pdata = []
            for ir, hkld in enumerate(zip(hkls_ref, dsp_ref)):
                npts = len(pick_angs[ir])
                if npts > 0:
                    tth_eta_meas = np.atleast_2d(np.radians(pick_angs[ir]))
                    xy_meas = np.atleast_2d(pick_xys[ir])
                    pdata.append(
                        np.hstack(
                            [xy_meas,
                             tth_eta_meas,
                             np.tile(np.hstack(hkld), (npts, 1))]
                        )
                    )
            # pdata = np.vstack(data_dict[det_key])
            pdata = np.vstack(pdata)
            if len(pdata) > 0:
                hkls = pdata[:, 4:7]
                gvecs = np.dot(hkls, bmatx.T)
                dsp0 = 1./np.sqrt(np.sum(gvecs*gvecs, axis=1))
                # dsp0 = pdata[:, -2]
                eta0 = pdata[:, 3]

                # derive reference tth
                tth0 = 2.*np.arcsin(0.5*wlen/dsp0)
                calc_xy = panel.angles_to_cart(np.vstack([tth0, eta0]).T,
                                               tvec_c=tvec_c)

                # distortion if applicable, from ideal --> warped
                if panel.distortion is not None:
                    calc_xy = panel.distortion.apply_inverse(calc_xy)

                if output == 'residual':
                    retval.append(
                        (pdata[:, :2].flatten() - calc_xy.flatten())
                    )
                elif output == 'model':
                    retval.append(
                        calc_xy.flatten()
                    )
                else:
                    raise RuntimeError("unrecognized output flag '%s'"
                                       % output)
            else:
                continue
        return np.hstack(retval)

    def residual(self, reduced_params, data_dict):
        return self._evaluate(reduced_params, data_dict)

    def model(self, reduced_params, data_dict):
        return self._evaluate(reduced_params, data_dict, output='model')


class CompositeCalibration(object):
    def __init__(self, instr, processed_picks):
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
                    self.instr, pick_data['plane_data'], flags
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

            # call to calibrator residual api with porper index into pick data
            residual.append(
                calib.residual(
                    these_reduced_params,
                    pick_data_list[ical]
                )
            )

            # advance alibrator extra parameter offset
            ii += calib.npe

        # return single hstacked residual
        return np.hstack(residual)


def run_calibration(picks, instr, materials):
    enrich_pick_data(picks, instr, materials)

    # Run composite calibration
    instr_calibrator = CompositeCalibration(instr, picks)

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
