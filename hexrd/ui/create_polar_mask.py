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


def create_polar_mask(line_data, name):
    # Calculate current image dimensions
    pv = PolarView(None)
    shape = pv.shape
    # Generate masks from line data
    final_mask = np.ones(shape, dtype=bool)
    for line in line_data:
        tth = np.asarray([point[0] for point in line])
        eta = np.asarray([point[1] for point in line])

        j_col = np.floor((tth - np.degrees(pv.tth_min)) / pv.tth_pixel_size)
        i_row = np.floor((eta - np.degrees(pv.eta_min)) / pv.eta_pixel_size)

        rr, cc = polygon(i_row, j_col, shape=shape)
        mask = np.ones(shape, dtype=bool)
        mask[rr, cc] = False
        final_mask = np.logical_and(final_mask, mask)
    HexrdConfig().polar_masks[name] = final_mask


def rebuild_polar_masks():
    HexrdConfig().polar_masks.clear()
    for name, line_data in HexrdConfig().polar_masks_line_data.items():
        if not isinstance(line_data, list):
            line_data = [line_data]
        create_polar_mask(line_data, name)
    for name, value in HexrdConfig().raw_masks_line_data.items():
        det, data = value[0]
        line_data = convert_raw_to_polar(det, data)
        create_polar_mask(line_data, name)
