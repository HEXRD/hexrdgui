from typing import Union

import numpy as np

from hexrd import constants
from hexrd.rotations import make_rmat_euler, mapAngle
from hexrd.transforms.xfcapi import angles_to_gvec

from hexrdgui.constants import KEV_TO_WAVELENGTH

from .stereo2angle import ij2ang as stereo_ij2ang, ang2ij as ang2stereo_ij


def cart_to_pixels(xys, panel):
    return panel.cartToPixel(xys)[:, [1, 0]]


def pixels_to_cart(ij, panel):
    return panel.pixelToCart(ij[:, [1, 0]])


def cart_to_angles(
    xys, panel, eta_period=None, tvec_s=None, tvec_c=None, apply_distortion=True
):
    # If the eta period is specified, the eta angles will be mapped to be
    # within this period.
    kwargs = {
        'tvec_s': tvec_s,
        'tvec_c': tvec_c,
        'apply_distortion': apply_distortion,
    }
    ang_crds, _ = panel.cart_to_angles(xys, **kwargs)
    ang_crds = np.degrees(ang_crds)

    if eta_period is not None:
        ang_crds[:, 1] = mapAngle(ang_crds[:, 1], eta_period, units='degrees')

    return ang_crds


def angles_to_cart(angles, panel, tvec_s=None, tvec_c=None, apply_distortion=True):
    kwargs = {
        'tth_eta': np.radians(angles),
        'tvec_s': tvec_s,
        'tvec_c': tvec_c,
        'apply_distortion': apply_distortion,
    }
    return panel.angles_to_cart(**kwargs)


def angles_to_pixels(angles, panel, tvec_s=None, tvec_c=None, apply_distortion=True):
    xys = angles_to_cart(
        angles, panel, tvec_s=tvec_s, tvec_c=tvec_c, apply_distortion=apply_distortion
    )
    return cart_to_pixels(xys, panel)


def pixels_to_angles(ij, panel, eta_period=None, tvec_s=None, tvec_c=None):
    xys = pixels_to_cart(ij, panel)

    kwargs = {
        'eta_period': eta_period,
        'tvec_s': tvec_s,
        'tvec_c': tvec_c,
    }
    return cart_to_angles(xys, panel, **kwargs)


def stereo_to_angles(ij, instr, stereo_size):
    # Returns radians
    return stereo_ij2ang(
        ij=ij,
        stereo_size=stereo_size,
        bvec=instr.beam_vector,
    )


def angles_to_stereo(angs, instr, stereo_size):
    # angs is in radians
    return ang2stereo_ij(
        angs=angs,
        stereo_size=stereo_size,
        bvec=instr.beam_vector,
    )


def tth_to_q(tth: Union[np.ndarray, float], beam_energy: float):
    # Convert tth values in degrees to q-space in Angstrom^-1
    # The formula is Q = 4 * pi * sin(theta)/lambda.
    # lambda is the wavelength in Angstrom, and
    # theta = current x-axis value/2 in radians.

    tth = np.radians(tth)
    # The input tth is in degrees, and the beam_energy is in keV
    return 4 * np.pi * np.sin(tth / 2) * beam_energy / KEV_TO_WAVELENGTH


def q_to_tth(q: Union[np.ndarray, float], beam_energy: float):
    # Convert the q-space values (Angstrom^-1) to tth in degrees
    tth = np.arcsin(q / 4 / np.pi * KEV_TO_WAVELENGTH / beam_energy) * 2
    return np.degrees(tth)


def angles_to_chi(tth_eta, sample_tilt, bvec, evec):
    rmat = make_rmat_euler(sample_tilt, 'xyz', extrinsic=True)
    nhat = np.dot(rmat, constants.lab_z)

    angs = np.hstack([tth_eta, np.tile(0, (len(tth_eta), 1))])
    gvecs = angles_to_gvec(angs, beam_vec=bvec, eta_vec=evec)

    dp = np.dot(gvecs, nhat)
    mask = np.abs(dp) > 1.0
    dp[mask] = np.sign(dp[mask])
    return np.degrees(np.arccos(dp))
