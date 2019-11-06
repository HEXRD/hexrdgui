# Some general utilities that are used in multiple places

import math
import numpy as np

import matplotlib.transforms as mtransforms

from hexrd import imageutil
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


def fix_exclusions(mat):
    # The default is to exclude all hkl's after the 5th one.
    # (See Material._newPdata() for more info)
    # Let's not do this...
    excl = [False] * len(mat.planeData.exclusions)
    mat.planeData.exclusions = excl


def make_new_pdata(mat):
    # This generates new PlaneData for a material
    # It also fixes the exclusions (see fix_exclusions() for details)
    mat._newPdata()
    fix_exclusions(mat)


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


def select_merged_rings(selected_rings, indices, ranges):
    """Select indices and ranges for merged rings

    This utility function filters the indices and ranges and returns
    new (indices, ranges) that were selected in the selected_rings.
    """
    new_indices = []
    new_ranges = []
    for ring in selected_rings:
        for i, entry in enumerate(indices):
            if ring in entry:
                new_indices.append(entry)
                new_ranges.append(ranges[i])
                break

    return new_indices, new_ranges


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
