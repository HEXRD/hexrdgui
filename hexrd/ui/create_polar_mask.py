import numpy as np

from skimage.draw import polygon

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.calibration.polarview import PolarView
from hexrd.ui.hexrd_config import HexrdConfig


def convert_raw_to_polar(det, line):
    panel = create_hedm_instrument().detectors[det]
    cart = panel.pixelToCart(line)
    tth, gvec = panel.cart_to_angles(cart)
    return [np.degrees(tth)]


def create_polar_mask(name, line_data):
    # Calculate current image dimensions
    pv = PolarView(None)
    shape = pv.shape
    # Generate masks from line data
    for line in line_data:
        tth = np.asarray([point[0] for point in line])
        eta = np.asarray([point[1] for point in line])

        j_col = np.floor((tth - np.degrees(pv.tth_min)) / pv.tth_pixel_size)
        i_row = np.floor((eta - np.degrees(pv.eta_min)) / pv.eta_pixel_size)

        rr, cc = polygon(i_row, j_col, shape=shape)
        mask = np.ones(shape, dtype=bool)
        mask[rr, cc] = False
        HexrdConfig().polar_masks[name] = mask
        HexrdConfig().visible_masks.append(name)
