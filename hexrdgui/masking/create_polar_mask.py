import numpy as np

from skimage.draw import polygon
from hexrdgui.constants import ViewType

from hexrdgui.create_hedm_instrument import create_view_hedm_instrument
from hexrdgui.calibration.polarview import PolarView
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType
from hexrdgui.utils import add_sample_points
from hexrdgui.utils.conversions import pixels_to_angles


def convert_raw_to_polar(instr, det, line):
    # This accepts an instrument rather than creating one for performance

    # Make sure there at least 300 sample points so that the conversion
    # looks correct.
    line = add_sample_points(line, 300)

    kwargs = {
        'ij': line,
        'panel': instr.detectors[det],
        'eta_period': HexrdConfig().polar_res_eta_period,
        'tvec_s': instr.tvec,
    }

    return [pixels_to_angles(**kwargs)]


def create_polar_mask(line_data):
    # Calculate current image dimensions
    # If we pass `None` to the polar view, it is a dummy polar view
    pv = PolarView(None)
    shape = pv.shape
    num_pix_eta = shape[0]

    # If any consecutive pixel coordinates for the mask are greater than this
    # distance apart (in eta), then that means the mask is being split
    # above/below the image, and we need to split the mask up.
    eta_max_pix_diff = num_pix_eta * 0.95

    # Generate masks from line data
    final_mask = np.ones(shape, dtype=bool)
    for line in line_data:
        # Remove any nans
        line = line[~np.isnan(line.min(axis=1))]
        tth = line[:, 0]
        eta = line[:, 1]

        j_col = np.floor((tth - np.degrees(pv.tth_min)) / pv.tth_pixel_size)
        i_row = np.floor((eta - np.degrees(pv.eta_min)) / pv.eta_pixel_size)

        gaps, = np.nonzero(np.abs(np.diff(i_row)) > eta_max_pix_diff)

        if gaps.size == 1:
            # Add an extra gap at the second biggest gap
            idx = eta.shape[0] - 3
            second_biggest_gap, = np.where(np.argsort(np.diff(eta)) == idx)
            gaps = np.sort(np.hstack((gaps, second_biggest_gap)))

        if gaps.size == 2:
            # This mask is split between the top and bottom of the image.
            # We need to split it up into two polygons.

            # There should be exactly two gaps. Add one to these indices.
            gaps += 1

            # Now split them up into two polygons along with some buffering
            i_row1, i_row2 = _split_coords_1d(i_row, gaps[0], gaps[1])
            i_row1, i_row2 = _buffer_coords_1d(i_row1, i_row2, 0, shape[0] - 1)

            j_col1, j_col2 = _split_coords_1d(j_col, gaps[0], gaps[1])
            j_col1, j_col2 = _interpolate_split_coords_1d(j_col1, j_col2)

            # Create the masks
            masks = [
                _pixel_perimeter_to_mask(i_row1, j_col1, shape),
                _pixel_perimeter_to_mask(i_row2, j_col2, shape),
            ]
        else:
            # Just one mask
            masks = [_pixel_perimeter_to_mask(i_row, j_col, shape)]

        for mask in masks:
            final_mask = np.logical_and(final_mask, mask)

    return final_mask


def _pixel_perimeter_to_mask(r, c, shape):
    # The arguments are all forwarded to skimage.draw.polygon
    rr, cc = polygon(r, c, shape=shape)
    mask = np.ones(shape, dtype=bool)
    mask[rr, cc] = False
    return mask


def _split_coords_1d(x, gap1, gap2):
    coords1 = np.hstack((x[gap2:], x[:gap1]))
    coords2 = x[gap1:gap2]
    return coords1, coords2


def _buffer_coords_1d(coords1, coords2, min_val, max_val):
    # Buffer the coords with whichever is closer on the sides,
    # min_val or max_val
    if max_val - coords1[0] < coords1[0] - min_val:
        # coords1 is closer to the max, and coords2 is closer to the min
        # If the coord is already greater than the max, just leave it alone.
        border1 = max(max_val, coords1[0])
        border2 = min_val
    else:
        # coords2 is closer to the max, and coords1 is closer to the min
        # If the coord is already greater than the max, just leave it alone.
        border1 = min_val
        border2 = max(max_val, coords2[0])

    coords1 = np.hstack((border1, coords1, border1))
    coords2 = np.hstack((border2, coords2, border2))
    return coords1, coords2


def _interpolate_split_coords_1d(coords1, coords2):
    # Buffer the coords with interpolation between values.
    if abs(coords1[0] - coords2[-1]) < abs(coords1[0] - coords2[0]):
        # coords1[0] and coords2[-1] are attached
        coords1_first = (coords1[0] + coords2[-1]) / 2
        coords1_last = (coords1[-1] + coords2[0]) / 2
        coords2_first = coords1_last
        coords2_last = coords1_first
    else:
        # coords1[0] and coords2[0] are attached
        coords1_first = (coords1[0] + coords2[0]) / 2
        coords1_last = (coords1[-1] + coords2[-1]) / 2
        coords2_first = coords1_first
        coords2_last = coords1_last

    coords1 = np.hstack((coords1_first, coords1, coords1_last))
    coords2 = np.hstack((coords2_first, coords2, coords2_last))
    return coords1, coords2


def create_polar_line_data_from_raw(instr, value):
    # This accepts an instrument rather than creating one for performance
    line_data = []
    for det, data in value:
        line_data.extend(convert_raw_to_polar(instr, det, data))
    return line_data


def create_polar_mask_from_raw(value, instr=None):
    if instr is None:
        # An instrument can be passed for improved performance.
        # If one wasn't passed, create one.
        instr = create_hedm_instrument()

    line_data = create_polar_line_data_from_raw(instr, value)
    return create_polar_mask(line_data)


def rebuild_polar_masks():
    from hexrdgui.masking.mask_manager import MaskManager
    for mask in MaskManager().masks.values():
        if mask.type == MaskType.threshold:
            continue
        mask.invalidate_masked_arrays()
