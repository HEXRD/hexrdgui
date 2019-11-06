import numpy as np

from skimage.draw import polygon

from hexrd.ui.hexrd_config import HexrdConfig


def create_polar_mask(line_data, rsimg, pv):
    for line in line_data:
        x = [point[0] for point in line]
        y = [point[1] for point in line]

        j_col = np.floor(pv.tth_to_pixel(np.radians(x)))
        i_row = np.floor(pv.eta_to_pixel(np.radians(y)))

        rr, cc = polygon(i_row, j_col, shape=rsimg.shape)
        mask = np.ones(rsimg.shape, dtype=bool)
        mask[rr, cc] = False
        HexrdConfig().polar_masks.append(mask)
