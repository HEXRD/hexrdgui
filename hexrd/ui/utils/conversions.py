import numpy as np

from hexrd.transforms.xfcapi import mapAngle


def cart_to_pixels(xys, panel):
    return panel.cartToPixel(xys)[:, [1, 0]]


def pixels_to_cart(ij, panel):
    return panel.pixelToCart(ij[:, [1, 0]])


def cart_to_angles(xys, panel, eta_period, tvec_s=None, tvec_c=None,
                   apply_distortion=True):
    kwargs = {
        'tvec_s': tvec_s,
        'tvec_c': tvec_c,
        'apply_distortion': apply_distortion,
    }
    ang_crds, _ = panel.cart_to_angles(xys, **kwargs)
    ang_crds = np.degrees(ang_crds)
    ang_crds[:, 1] = mapAngle(ang_crds[:, 1], eta_period, units='degrees')
    return ang_crds


def angles_to_cart(angles, panel, apply_distortion=True):
    angles = np.radians(angles)
    return panel.angles_to_cart(angles, apply_distortion=apply_distortion)


def angles_to_pixels(angles, panel):
    xys = angles_to_cart(angles, panel)
    return cart_to_pixels(xys, panel)


def pixels_to_angles(ij, panel, eta_period, tvec_s=None, tvec_c=None):
    xys = pixels_to_cart(ij, panel)

    kwargs = {
        'eta_period': eta_period,
        'tvec_s': tvec_s,
        'tvec_c': tvec_c,
    }
    return cart_to_angles(xys, panel, **kwargs)


def stereo_to_angles(ij, stereo_size):
    rad = (stereo_size - 1) / 2
    X = (ij[:, 0] - rad) / rad
    Y = (ij[:, 1] - rad) / rad
    condition = X**2 + Y**2 <= 1
    X = np.where(condition, X, np.nan)
    Y = np.where(condition, Y, np.nan)
    den = 1 + X**2 + Y**2

    vx = 2.0 * X / den
    vy = 2.0 * Y / den
    vz = (1.0 - X**2 - Y**2) / den

    tth = np.arccos(vz)
    eta = np.mod(np.arctan2(vy, vx), 2 * np.pi)

    return np.array([tth, eta])
