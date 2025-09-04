import numpy as np

from hexrdgui.constants import ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType
from hexrdgui.utils import add_sample_points
from hexrdgui.utils.conversions import cart_to_angles, pixels_to_cart
from hexrdgui.utils.polygon import polygon_to_mask
from hexrdgui.utils.tth_distortion import apply_tth_distortion_if_needed


def convert_raw_to_polar(instr, det, line, apply_tth_distortion=True):
    # This accepts an instrument rather than creating one for performance

    # Make sure there at least 500 sample points so that the conversion
    # looks correct.
    # This needs to be greater than the number of sample points when going
    # from polar to raw, so we can ensure that points along borders get added.
    line = add_sample_points(line, 500)

    panel = instr.detectors[det]
    xys = pixels_to_cart(line, panel)
    # We used to clip_to_panel() here, but we shouldn't do that because
    # users may have clicked points outside of the detector in the polar view.
    # xys, _ = panel.clip_to_panel(xys, buffer_edges=False)

    if HexrdConfig().image_mode == ViewType.stereo:
        # We always use 0 to 2*pi for stereo
        eta_period = np.degrees([0, 2 * np.pi])
    else:
        eta_period = HexrdConfig().polar_res_eta_period

    kwargs = {
        'eta_period': eta_period,
        'tvec_s': instr.tvec
    }
    line = cart_to_angles(xys, panel, **kwargs)

    if apply_tth_distortion:
        line = apply_tth_distortion_if_needed(line, in_degrees=True)

    return [line] if line.size else None


def create_polar_mask(line_data):
    from hexrdgui.calibration.polarview import PolarView
    from hexrdgui.masking.mask_manager import MaskManager
    # Calculate current image dimensions
    # If we pass `None` to the polar view, it is a dummy polar view
    kwargs = {'instrument': None}
    if MaskManager().view_mode == ViewType.stereo:
        kwargs.update({
            'eta_min': 0,
            'eta_max': np.pi * 2,
        })
    pv = PolarView(**kwargs)
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
    polygon = np.vstack([c, r]).T
    if polygon.size < 2:
        return np.ones(shape, dtype=bool)

    return polygon_to_mask(polygon, shape)


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


def create_polar_line_data_from_raw(instr, value, apply_tth_distortion=True):
    # This accepts an instrument rather than creating one for performance
    line_data = []
    for det, data in value:
        if polar := convert_raw_to_polar(
            instr,
            det,
            data,
            apply_tth_distortion=apply_tth_distortion,
        ):
            line_data.extend(polar)
    return line_data


def create_polar_mask_from_raw(value, instr=None, apply_tth_distortion=True):
    if instr is None:
        # An instrument can be passed for improved performance.
        # If one wasn't passed, create one.
        instr = create_hedm_instrument()

    line_data = create_polar_line_data_from_raw(
        instr,
        value,
        apply_tth_distortion=apply_tth_distortion,
    )
    return create_polar_mask(line_data)


def rebuild_polar_masks():
    from hexrdgui.masking.mask_manager import MaskManager
    for mask in MaskManager().masks.values():
        if mask.type == MaskType.threshold:
            continue
        mask.invalidate_masked_arrays()
