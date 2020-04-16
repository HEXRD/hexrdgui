# Some general utilities that are used in multiple places

import math
import numpy as np

import matplotlib.transforms as mtransforms

from hexrd import imageutil
from hexrd import instrument
from hexrd.rotations import angleAxisOfRotMat, RotMatEuler
from hexrd.transforms.xfcapi import makeRotMatOfExpMap


def convert_tilt_convention(iconfig, old_convention,
                            new_convention):
    """
    convert the tilt angles from an old convention to a new convention

    This should work for both configs with statuses and without
    """
    if new_convention == old_convention:
        return

    def _get_tilt_array(data):
        # This works for both a config with statuses, and without
        if isinstance(data, dict):
            return data.get('value')
        return data

    def _set_tilt_array(data, val):
        # This works for both a config with statuses, and without
        if isinstance(data, dict):
            data['value'] = val
        else:
            data.clear()
            data.extend(val)

    old_axes, old_extrinsic = old_convention
    new_axes, new_extrinsic = new_convention

    det_keys = iconfig['detectors'].keys()
    if old_axes is not None and old_extrinsic is not None:
        # First, convert these to the matrix invariants
        rme = RotMatEuler(np.zeros(3), old_axes, old_extrinsic)
        for key in det_keys:
            tilts = iconfig['detectors'][key]['transform']['tilt']
            rme.angles = np.array(_get_tilt_array(tilts))
            phi, n = angleAxisOfRotMat(rme.rmat)
            _set_tilt_array(tilts, (phi * n.flatten()).tolist())

        if new_axes is None or new_extrinsic is None:
            # We are done
            return

    # Update to the new mapping
    rme = RotMatEuler(np.zeros(3), new_axes, new_extrinsic)
    for key in det_keys:
        tilts = iconfig['detectors'][key]['transform']['tilt']
        tilt = np.array(_get_tilt_array(tilts))
        rme.rmat = makeRotMatOfExpMap(tilt)
        # Use np.ndarray.tolist() to convert back to native python types
        _set_tilt_array(tilts, np.array(rme.angles).tolist())


def make_new_pdata(mat):
    # This generates new PlaneData for a material
    # This also preserves the previous exclusions of the plane data
    prev_exclusions = mat.planeData.exclusions
    mat._newPdata()
    mat.planeData.exclusions = prev_exclusions


def coords2index(im, x, y):
    """
    This function is modified from here:
    https://github.com/joferkington/mpldatacursor/blob/7dabc589ed02c35ac5d89de5931f91e0323aa795/mpldatacursor/pick_info.py#L28

    Converts data coordinates to index coordinates of the array.

    Parameters
    -----------
    im : An AxesImage instance
        The image artist to operate on
    x : number
        The x-coordinate in data coordinates.
    y : number
        The y-coordinate in data coordinates.

    Returns
    --------
    i, j : Index coordinates of the array associated with the image.
    """
    xmin, xmax, ymin, ymax = im.get_extent()
    if im.origin == 'upper':
        ymin, ymax = ymax, ymin
    data_extent = mtransforms.Bbox([[ymin, xmin], [ymax, xmax]])
    array_extent = mtransforms.Bbox([[0, 0], im.get_array().shape[:2]])
    trans = (mtransforms.BboxTransformFrom(data_extent) +
             mtransforms.BboxTransformTo(array_extent))

    return trans.transform_point([y, x]).astype(int)


def snip_width_pixels():

    from hexrd.ui.hexrd_config import HexrdConfig

    pixel_size_tth = HexrdConfig().polar_pixel_size_tth
    snip_width_deg = HexrdConfig().polar_snip1d_width

    # Convert the snip width into pixels using pixel_size_tth
    # Always round up
    return math.ceil(snip_width_deg / pixel_size_tth)


def run_snip1d(img):

    from hexrd.ui.hexrd_config import HexrdConfig

    snip_width = snip_width_pixels()
    numiter = HexrdConfig().polar_snip1d_numiter

    # !!!: need a selector between
    # imageutil.fast_snip1d() and imageutil.snip1d()
    return imageutil.snip1d(img, snip_width, numiter)


def remove_none_distortions(iconfig):
    # This modifies the iconfig in place to remove distortion
    # parameters that are set to None
    # This also assumes an iconfig without statuses
    for det in iconfig['detectors'].values():
        if det.get('distortion', {}).get('function_name', '').lower() == 'none':
            del det['distortion']


def create_hedm_instrument():
    # Takes the current config and creates an HEDMInstrument from it
    from hexrd.ui.hexrd_config import HexrdConfig

    # HEDMInstrument expects None Euler angle convention for the
    # config. Let's get it as such.
    iconfig = HexrdConfig().instrument_config_none_euler_convention
    rme = HexrdConfig().rotation_matrix_euler()
    return instrument.HEDMInstrument(instrument_config=iconfig,
                                     tilt_calibration_mapping=rme)
