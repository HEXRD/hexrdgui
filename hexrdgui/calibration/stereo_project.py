import copy

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from hexrd import constants
from hexrd.rotations import mapAngle

def stereo_projection_of_polar_view(pvarray, tth_grid, eta_grid,
                                    instr, stereo_size):

    kwargs = {
        'points': (eta_grid, tth_grid),
        'values': pvarray,
        'method': 'linear',
        'bounds_error': False,
        'fill_value': np.nan,
    }
    interp_obj = RegularGridInterpolator(**kwargs)

    raw_bkgsub = project_intensities_to_raw(instr, interp_obj)

    return stereo_project(instr, raw_bkgsub, stereo_size)


def project_intensity_detector(det,
                               interp_obj):
    tth, eta = np.degrees(det.pixel_angles())
    eta = mapAngle(eta, (0, 360.0), units='degrees')
    xi = (eta, tth)
    return interp_obj(xi)


def project_intensities_to_raw(instr,
                               interp_obj):
    raw_bkgsub = dict.fromkeys(instr.detectors)
    for d in instr.detectors:
        det = instr.detectors[d]
        raw_bkgsub[d] = project_intensity_detector(det,
                                                   interp_obj)

    return raw_bkgsub


def stereo_project(instr, raw, stereo_size):
    # copy instruments and set viewing direction
    # to be centered at the VISAR
    instr_cp = copy.deepcopy(instr)
    instr_cp.beam_vector = constants.beam_vec

    rad = (stereo_size - 1) / 2
    x = np.linspace(0, stereo_size - 1, stereo_size)
    [X, Y] = np.meshgrid(x, x)
    X = (X - rad) / rad
    Y = (Y - rad) / rad
    condition = X**2 + Y**2 <= 1
    X = np.where(condition, X, np.nan)
    Y = np.where(condition, Y, np.nan)
    den = 1 + X**2 + Y**2

    vx = 2.0 * X / den
    vy = 2.0 * Y / den
    vz = (1.0 - X**2 - Y**2) / den

    tth = np.arccos(vz)
    eta = mapAngle(np.arctan2(vy, vx), (0, 2*np.pi), units='radians')
    #np.mod(np.arctan2(vy, vx), 2 * np.pi)
    angs = np.vstack((tth.flatten(),
                      eta.flatten())).T
    mask = ~np.isnan(angs)
    mask = np.logical_and(mask[:, 0], mask[:, 1])

    stereo = np.zeros((stereo_size, stereo_size))
    fmask = np.ones_like(stereo)
    for d in instr_cp.detectors:
        intensity = np.empty((angs.shape[0],))
        det = instr_cp.detectors[d]
        cart = det.angles_to_cart(angs[mask, :])
        out = det.interpolate_bilinear(cart, raw[d])
        intensity[mask] = out
        im = np.reshape(intensity, (stereo_size, stereo_size))
        im[~condition] = np.nan

        im = np.ma.masked_array(im, mask=np.isnan(im))
        stereo += im.filled(0)
        fmask = np.logical_and(fmask, im.mask)

    return np.ma.masked_array(stereo, mask=fmask)


def prep_polar_data(fid):
    pvarray = np.array(fid['intensities'])
    tth_1dgrid = np.array(fid['tth_coordinates'])[0, :]
    eta_1dgrid = np.array(fid['eta_coordinates'])[:, 0]

    eta_1dgrid = mapAngle(eta, (0, 360.0), units='degrees')
    #np.mod(eta_1dgrid, 360)
    idx = np.argsort(eta_1dgrid)
    eta_1dgrid = eta_1dgrid[idx]
    pvarray = pvarray[idx, :]

    return (pvarray, tth_1dgrid, eta_1dgrid)


def test_stereo_project(polar_file, state_file, stereo_size):
    import cProfile
    import pstats

    import h5py
    from matplotlib import pyplot as plt

    from hexrd.instrument import HEDMInstrument

    profiler = cProfile.Profile()
    profiler.enable()

    with h5py.File(state_file) as ins:
        instr = HEDMInstrument(instrument_config=ins)

    with h5py.File(polar_file) as fid:
        pvarray, tth_grid, eta_grid = prep_polar_data(fid)

    stereo = stereo_projection_of_polar_view(pvarray, tth_grid, eta_grid,
                                             instr, stereo_size)

    profiler.disable()
    pstats.Stats(profiler).sort_stats('tottime').print_stats(30)
    pstats.Stats(profiler).sort_stats('cumtime').print_stats(30)

    plt.figure()
    plt.imshow(stereo, vmin=5, vmax=35)

    plt.show()


if __name__ == '__main__':
    polar_file = 'polar_medium_res.h5'
    state_file = 'xrs1_state_latest.h5'
    stereo_size = 1501

    test_stereo_project(polar_file, state_file, stereo_size)
