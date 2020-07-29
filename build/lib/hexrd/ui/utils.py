# Some general utilities that are used in multiple places

import numpy as np

import matplotlib.transforms as mtransforms

from hexrd.rotations import angleAxisOfRotMat, RotMatEuler
from hexrd.transforms.xfcapi import makeRotMatOfExpMap


def convert_tilt_convention(iconfig, old_convention,
                            new_convention):
    """
    convert the tilt angles from an old convention to a new convention
    """
    if new_convention == old_convention:
        return

    old_axes, old_extrinsic = old_convention
    new_axes, new_extrinsic = new_convention

    det_keys = iconfig['detectors'].keys()
    if old_axes is not None and old_extrinsic is not None:
        # First, convert these to the matrix invariants
        rme = RotMatEuler(np.zeros(3), old_axes, old_extrinsic)
        for key in det_keys:
            tilt_dict = iconfig['detectors'][key]['transform']['tilt']
            tilt = np.array(tilt_dict['value'])
            rme.rmat = makeRotMatOfExpMap(tilt)
            tilt_dict['value'] = list(rme.angles)

        if new_axes is None or new_extrinsic is None:
            # We are done
            return

    # Update to the new mapping
    rme = RotMatEuler(np.zeros(3), new_axes, new_extrinsic)
    for key in det_keys:
       tilt_dict = iconfig['detectors'][key]['transform']['tilt']
       rme.angles = np.array(tilt_dict['value'])
       phi, n = angleAxisOfRotMat(rme.rmat)
       tilt_dict['value'] = (phi * n.flatten()).tolist()


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
