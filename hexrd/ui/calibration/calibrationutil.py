#! /usr/bin/env python
# =============================================================================
# Copyright (c) 2012, Lawrence Livermore National Security, LLC.
# Produced at the Lawrence Livermore National Laboratory.
# Written by Joel Bernier <bernier2@llnl.gov> and others.
# LLNL-CODE-529294.
# All rights reserved.
#
# This file is part of HEXRD. For details on dowloading the source,
# see the file COPYING.
#
# Please also see the file LICENSE.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License (as published by the Free
# Software Foundation) version 2.1 dated February 1999.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the IMPLIED WARRANTY OF MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the terms and conditions of the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program (see file LICENSE); if not, write to
# the Free Software Foundation, Inc., 59 Temple Place, Suite 330,
# Boston, MA 02111-1307 USA or visit <http://www.gnu.org/licenses/>.
# =============================================================================

"""
Author: J. V. Bernier
Date: 16 Jan 2019
"""

# =============================================================================
# # IMPORTS
# =============================================================================

import pickle as cpl

import numpy as np

import h5py

import yaml

# import ipywidgets as widgets
# from IPython.display import display

from skimage import io
from skimage.exposure import rescale_intensity
from skimage.filters.edges import binary_erosion
from skimage.restoration import denoise_bilateral

from hexrd import constants as cnst
from hexrd import instrument
from hexrd import matrixutil as mutil
from hexrd import rotations as rot
from hexrd import material

from scipy.ndimage.morphology import binary_fill_holes
from scipy.optimize import least_squares, leastsq


# %%
# =============================================================================
# # Parameters and local funcs
# =============================================================================

r2d = 180. / np.pi
d2r = np.pi / 180.
pi = np.pi
piby2 = 0.5*np.pi

sigma_to_FWHM = 2*np.sqrt(2*np.log(2))

__reflInfo_dtype = [
    ('iRefl', int),
    ('hkl', (int, 3)),
    ('intensity', (float, 2)),
    ('energy', float),
    ('predAngles', (float, 2)),
    ('measAngles', (float, 2)),
    ('measXY', (float, 2)),
    ]


class DummyCrystal(object):
    def __init__(self, tth_list, delth_tth=np.radians(5.)):
        self._tth = np.array(tth_list)
        self._tThWidth = delth_tth

    @property
    def tth(self):
        return self._tth

    @tth.setter
    def tth(self, x):
        self._tth = np.radians(x)

    @property
    def tThWidth(self):
        return self._tThWidth

    @tThWidth.setter
    def tThWidth(self, x):
        self._tThWidth = x

    def getTTh(self):
        return self.tth

    def getTThRanges(self):
        tth_lo = self.getTTh() - 0.5*self.tThWidth
        tth_hi = self.getTTh() + 0.5*self.tThWidth
        return np.vstack([tth_lo, tth_hi]).T

    def getMergedRanges(self, cullDupl=False):
        """
        return indices and ranges for specified planeData, merging where
        there is overlap based on the tThWidth and line positions
        """
        tThs = self.getTTh()
        tThRanges = self.getTThRanges()

        # if you end exlcusions in a doublet (or multiple close rings)
        # then this will 'fail'.  May need to revisit...
        nonoverlap_nexts = np.hstack(
            (tThRanges[:-1, 1] < tThRanges[1:, 0], True)
        )
        iHKLLists = []
        mergedRanges = []
        hklsCur = []
        tThLoIdx = 0
        tThHiCur = 0.
        for iHKL, nonoverlapNext in enumerate(nonoverlap_nexts):
            tThHi = tThRanges[iHKL, -1]
            if not nonoverlapNext:
                tth_diff = abs(tThs[iHKL] - tThs[iHKL + 1])
                if cullDupl and tth_diff < cnst.sqrt_epsf:
                    continue
                else:
                    hklsCur.append(iHKL)
                    tThHiCur = tThHi
            else:
                hklsCur.append(iHKL)
                tThHiCur = tThHi
                iHKLLists.append(hklsCur)
                mergedRanges.append([tThRanges[tThLoIdx, 0], tThHiCur])
                tThLoIdx = iHKL + 1
                hklsCur = []
        return iHKLLists, mergedRanges


# mask setting
def det_panel_mask(instr, img_dict, tolerance=1e-6):
    """
    use small values surrounding image plate to set panel buffers
    """
    for key, panel in instr.detectors.items():
        img = img_dict[key]
        bimg = binary_fill_holes(img > tolerance)
        mask = binary_erosion(bimg, iterations=3)
        panel.panel_buffer = mask


def load_images(img_stem, ip_keys,
                threshold=None,
                denoise=False,
                normalize=False):
    img_dict = dict.fromkeys(ip_keys)
    for ip_key in ip_keys:
        this_img = io.imread(img_stem % ip_key.upper())
        if threshold is not None:
            this_img[this_img < threshold] = 0.
        if denoise:
            this_img = np.array(
                rescale_intensity(
                    denoise_bilateral(this_img,
                                      multichannel=False,
                                      sigma_spatial=1.1,
                                      bins=2**16),
                    out_range=np.uint16),
                dtype=np.uint16
            )
        if normalize:
            this_img = rescale_intensity(this_img, out_range=(-1., 1.))
        img_dict[ip_key] = this_img
    return img_dict


def log_scale_img(img):
    img = np.array(img, dtype=float) - np.min(img) + 1.
    return np.log(img)


# Material instantiation
# FIXME: these two functions are out of date!
def make_matl(mat_name, sgnum, lparms, hkl_ssq_max=500):
    matl = material.Material(mat_name)
    matl.sgnum = sgnum
    matl.latticeParameters = lparms
    matl.hklMax = hkl_ssq_max

    nhkls = len(matl.planeData.exclusions)
    matl.planeData.set_exclusions(np.zeros(nhkls, dtype=bool))
    return matl


# crystallography data extraction from cPickle arhive
def load_plane_data(cpkl, key):
    with open(cpkl, 'rb') as matf:
        mat_list = cpl.load(matf)
    pd = dict(zip([i.name for i in mat_list], mat_list))[key].planeData
    pd.exclusions = np.zeros_like(pd.exclusions, dtype=bool)
    return pd


# Tilt utilities
def convert_tilt(zxz_angles):
    tilt = np.radians(zxz_angles)
    rmat = rot.make_rmat_euler(tilt, 'zxz', extrinsic=False)
    phi, n = rot.angleAxisOfRotMat(rmat)
    return phi*n.flatten()


# pareser for simulation results
def parse_laue_simulation(sim_dict):
    """
    !!!: assumes for single grain
    ???: could eventually add another loop...
    """
    gid = 0

    # output dictionaries for each IP
    valid_xy = dict.fromkeys(sim_dict)
    valid_hkls = dict.fromkeys(sim_dict)
    valid_energy = dict.fromkeys(sim_dict)
    valid_angs = dict.fromkeys(sim_dict)
    for ip_key, sim_results in sim_dict.items():
        # expand results for convenience
        xy_det, hkls_in, angles, dspacing, energy = sim_results
        valid_xy[ip_key] = []
        valid_hkls[ip_key] = []
        valid_energy[ip_key] = []
        valid_angs[ip_key] = []
        for gid in range(len(xy_det)):
            # find valid reflections
            valid_refl = ~np.isnan(xy_det[gid][:, 0])

            valid_xy_tmp = xy_det[gid][valid_refl, :]

            # cull duplicates
            dupl = mutil.findDuplicateVectors(valid_xy_tmp.T, tol=1e-4)

            # find hkls and angles to feed patchs
            valid_xy[ip_key].append(valid_xy_tmp[dupl[1], :])
            valid_hkls[ip_key].append(hkls_in[gid][:, valid_refl][:, dupl[1]])
            valid_energy[ip_key].append(energy[gid][valid_refl])
            valid_angs[ip_key].append(angles[gid][valid_refl, :][dupl[1], :])

        """
        # !!! not working for now
        # need xy coords and pixel sizes
        if distortion is not None:
            valid_xy = distortion[0](valid_xy,
                                     distortion[1],
                                     invert=True)
        """
    return valid_xy, valid_hkls, valid_energy, valid_angs


# Objective function for Laue fitting
def sxcal_obj_func(plist_fit, plist_full, param_flags,
                   instr, meas_xy, hkls_idx,
                   bmat, energy_cutoffs,
                   sim_only=False,
                   return_value_flag=None):
    """
    Objective function for Laue-based fitting.


    energy_cutoffs are [minEnergy, maxEnergy] where min/maxEnergy can be lists

    """
    npi_tot = len(instr.calibration_parameters)

    # fill out full parameter list
    # !!! no scaling for now
    plist_full[param_flags] = plist_fit

    plist_instr = plist_full[:npi_tot]
    grain_params = [plist_full[npi_tot:], ]

    # update instrument
    instr.update_from_parameter_list(plist_instr)

    # beam vector
    bvec = instr.beam_vector

    # right now just stuck on the end and assumed
    # to all be the same length... FIX THIS
    calc_xy = {}
    calc_ang = {}
    npts_tot = 0
    for det_key, panel in instr.detectors.items():
        # counter
        npts_tot += len(meas_xy[det_key])

        # Simulate Laue pattern:
        # returns xy_det, hkls_in, angles, dspacing, energy
        sim_results = panel.simulate_laue_pattern(
            [hkls_idx[det_key], bmat],
            minEnergy=energy_cutoffs[0], maxEnergy=energy_cutoffs[1],
            grain_params=grain_params,
            beam_vec=bvec
        )

        calc_xy_tmp = sim_results[0][0]
        calc_angs_tmp = sim_results[2][0]

        idx = ~np.isnan(calc_xy_tmp[:, 0])
        calc_xy[det_key] = calc_xy_tmp[idx, :]
        calc_ang[det_key] = calc_angs_tmp[idx, :]
        pass

    # return values
    if sim_only:
        retval = {}
        for det_key in calc_xy.keys():
            # ??? calc_xy is always 2-d
            retval[det_key] = [calc_xy[det_key], calc_ang[det_key]]
    else:
        meas_xy_all = []
        calc_xy_all = []
        for det_key in meas_xy.keys():
            meas_xy_all.append(meas_xy[det_key])
            calc_xy_all.append(calc_xy[det_key])
            pass
        meas_xy_all = np.vstack(meas_xy_all)
        calc_xy_all = np.vstack(calc_xy_all)

        diff_vecs_xy = calc_xy_all - meas_xy_all
        retval = diff_vecs_xy.flatten()
        if return_value_flag == 1:
            retval = sum(abs(retval))
        elif return_value_flag == 2:
            denom = npts_tot - len(plist_fit) - 1.
            if denom != 0:
                nu_fac = 1. / denom
            else:
                nu_fac = 1.
            nu_fac = 1 / (npts_tot - len(plist_fit) - 1.)
            retval = nu_fac * sum(retval**2)
    return retval


# Calibration function
def calibrate_instrument_from_laue(
        instr, grain_params, meas_xy, bmat, hkls_idx,
        energy_cutoffs, param_flags=None,
        xtol=cnst.sqrt_epsf, ftol=cnst.sqrt_epsf,
        factor=1., sim_only=False, use_robust_lsq=False):
    """
    """
    npi = len(instr.calibration_parameters)

    pnames = [
        '{:>24s}'.format('beam_energy'),
        '{:>24s}'.format('beam_azimuth'),
        '{:>24s}'.format('beam_polar_angle'),
        '{:>24s}'.format('chi'),
        '{:>24s}'.format('tvec_s[0]'),
        '{:>24s}'.format('tvec_s[1]'),
        '{:>24s}'.format('tvec_s[2]'),
    ]

    for det_key, panel in instr.detectors.items():
        pnames += [
            '{:>24s}'.format('%s tilt[0]' % det_key),
            '{:>24s}'.format('%s tilt[1]' % det_key),
            '{:>24s}'.format('%s tilt[2]' % det_key),
            '{:>24s}'.format('%s tvec[0]' % det_key),
            '{:>24s}'.format('%s tvec[1]' % det_key),
            '{:>24s}'.format('%s tvec[2]' % det_key),
        ]
        if panel.distortion is not None:
            # FIXME: hard-coded distortion kludge
            for dp in panel.distortion[1]:
                pnames += ['{:>24s}'.format('%s distortion[0]' % det_key), ]

    pnames += [
        '{:>24s}'.format('crystal tilt[0]'),
        '{:>24s}'.format('crystal tilt[1]'),
        '{:>24s}'.format('crystal tilt[2]'),
        '{:>24s}'.format('crystal tvec[0]'),
        '{:>24s}'.format('crystal tvec[1]'),
        '{:>24s}'.format('crystal tvec[2]'),
        '{:>24s}'.format('crystal vinv[0]'),
        '{:>24s}'.format('crystal vinv[1]'),
        '{:>24s}'.format('crystal vinv[2]'),
        '{:>24s}'.format('crystal vinv[3]'),
        '{:>24s}'.format('crystal vinv[4]'),
        '{:>24s}'.format('crystal vinv[5]'),
    ]

    # reset parameter flags for instrument as specified
    if param_flags is None:
        param_flags_full = instr.calibration_flags
        param_flags = np.hstack(
            [param_flags_full,
             np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=bool)]
        )
    else:
        # will throw an AssertionError if wrong length
        assert(len(param_flags) == npi + 12)
        instr.calibration_flags = param_flags[:npi]

    # set tilt mapping to ZXZ
    # FIXME: input parameter?
    # rme = rot.RotMatEuler(np.zeros(3), 'zxz', extrinsic=False)
    # instr.tilt_calibration_mapping = rme

    # munge energy cutoffs
    if hasattr(energy_cutoffs[0], '__len__'):
        energy_cutoffs[0] = [0.5*i for i in energy_cutoffs[0]]
        energy_cutoffs[1] = [1.5*i for i in energy_cutoffs[1]]
    else:
        energy_cutoffs[0] = 0.5*energy_cutoffs[0]
        energy_cutoffs[1] = 1.5*energy_cutoffs[1]

    # grab relevant parameters
    # will yield:
    #     0      beam wavelength
    #     1      beam azimuth
    #     2      beam polar angle
    #     3      chi
    #     4:7    tvec_s
    #     panel_0 tilt, tvec, <distortion>
    #     panel_1 tilt, tvec, <distortion>
    #     ...
    #     panel_n tilt, tvec, <distortion>
    #     grain_parameters
    plist_i = instr.calibration_parameters
    plist_full = np.hstack([plist_i, grain_params])
    plist_fit = plist_full[param_flags]
    fit_args = (plist_full, param_flags,
                instr, meas_xy, hkls_idx,
                bmat, energy_cutoffs)
    if sim_only:
        return sxcal_obj_func(
            plist_fit, plist_full, param_flags,
            instr, meas_xy, hkls_idx,
            bmat, energy_cutoffs,
            sim_only=True)
    else:
        print("Set up to refine:")
        for i in np.where(param_flags)[0]:
            print("\t%s = %1.7e" % (pnames[i], plist_full[i]))
        resd = sxcal_obj_func(
            plist_fit, plist_full, param_flags,
            instr, meas_xy, hkls_idx,
            bmat, energy_cutoffs)
        print("Initial SSR: %f" % (np.sqrt(np.sum(resd*resd))))

        # run optimization
        if use_robust_lsq:
            result = least_squares(
                sxcal_obj_func, plist_fit, args=fit_args,
                xtol=xtol, ftol=ftol,
                loss='soft_l1', method='trf'
            )
            x = result.x
            resd = result.fun
            mesg = result.message
            ierr = result.status
        else:
            # do least squares problem
            x, cov_x, infodict, mesg, ierr = leastsq(
                sxcal_obj_func, plist_fit, args=fit_args,
                factor=factor, xtol=xtol, ftol=ftol,
                full_output=1
            )
            resd = infodict['fvec']
        if ierr not in [1, 2, 3, 4]:
            raise RuntimeError("solution not found: ierr = %d" % ierr)
        else:
            print("INFO: optimization fininshed successfully with ierr=%d"
                  % ierr)
            print("INFO: %s" % mesg)

        # ??? output message handling?
        fit_params = plist_full
        fit_params[param_flags] = x

        print("Final parameter values:")
        for i in np.where(param_flags)[0]:
            print("\t%s = %1.7e" % (pnames[i], fit_params[i]))
        print("Final SSR: %f" % (np.sqrt(np.sum(resd*resd))))
        # run simulation with optimized results
        sim_final = sxcal_obj_func(
            x, plist_full, param_flags,
            instr, meas_xy, hkls_idx,
            bmat, energy_cutoffs,
            sim_only=True)

        '''
        # ??? reset instrument here?
        instr.beam_vector = instrument.calc_beam_vec(
                fit_params[0], fit_params[1])
        ii = npi  # offset to where the panel parameters start
        for det_key, panel in instr.detectors.items():
            panel.tilt = convert_tilt(fit_params[ii:ii + 3])
            panel.tvec = fit_params[ii + 3:ii + 6]
            ii += npp
            pass
        '''
        return fit_params, resd, sim_final


# peak fitting
def gaussian_1d(p, x):
    func = p[0]*np.exp(-(x-p[1])**2/2/p[2]**2) + p[3]
    return func


def gaussian_2d(p, data):
    shape = data.shape
    x, y = np.meshgrid(range(shape[1]), range(shape[0]))
    func = p[0]*np.exp(
        -(p[1]*(x-p[4])*(x-p[4])
          + p[2]*(x-p[4])*(y-p[5])
          + p[3]*(y-p[5])*(y-p[5]))
        ) + p[6]*(x-p[4]) + p[7]*(y-p[5]) + p[8]
    return func.flatten() - data.flatten()


def gaussian_2d_int(y, x, *p):
    func = p[0]*np.exp(
        -(p[1]*(x-p[4])*(x-p[4])
          + p[2]*(x-p[4])*(y-p[5])
          + p[3]*(y-p[5])*(y-p[5]))
        )
    return func.flatten()
