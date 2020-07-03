import numpy as np

from skimage.draw import polygon

from hexrd.ui import constants
from hexrd.ui.hexrd_config import HexrdConfig


def create_polar_mask(line_data):
    # Calculate current image dimensions
    eta_min = constants.UI_ETA_MIN_DEGREES
    eta_max = constants.UI_ETA_MAX_DEGREES
    eta_range =  eta_max - eta_min
    eta_pixel_size = HexrdConfig().polar_pixel_size_eta
    neta = int(np.ceil(eta_range / eta_pixel_size))

    tth_min = HexrdConfig().polar_res_tth_min
    tth_max = HexrdConfig().polar_res_tth_max
    tth_range = tth_max - tth_min
    tth_pixel_size = HexrdConfig().polar_pixel_size_tth
    ntth = int(np.ceil(tth_range / tth_pixel_size))

    shape = (neta, ntth)
    # Generate masks from line data
    for line in line_data:
        tth = np.asarray([point[0] for point in line])
        eta = np.asarray([point[1] for point in line])

        j_col = np.floor((tth - tth_min) / tth_pixel_size)
        i_row = np.floor((eta - eta_min) / eta_pixel_size)

        rr, cc = polygon(i_row, j_col, shape=shape)
        mask = np.ones(shape, dtype=bool)
        mask[rr, cc] = False
        HexrdConfig().polar_masks.append(mask)
