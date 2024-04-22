import numpy as np

from skimage.draw import polygon

from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils import add_sample_points
from hexrdgui.utils.conversions import angles_to_cart, cart_to_pixels
from hexrdgui.utils.tth_distortion import apply_tth_distortion_if_needed


def recompute_raw_threshold_mask():
    from hexrdgui.masking.mask_manager import MaskManager
    results = {}
    if tm := MaskManager().threshold_mask:
        for det in HexrdConfig().detector_names:
            ims = HexrdConfig().imageseries(det)
            if tm.visible:
                masks = [None for i in range(len(ims))]
                for idx in range(len(ims)):
                    img = HexrdConfig().image(det, idx)
                    mask = create_threshold_mask(img, tm.data)
                    masks[idx] = mask
            else:
                masks = np.ones(ims.shape, dtype=bool)
            results[det] = masks
    return results


def create_threshold_mask(img, values):
    lt_val, gt_val = values
    lt_mask = img < lt_val
    gt_mask = img > gt_val

    return ~np.logical_or(lt_mask, gt_mask)


def convert_polar_to_raw(line_data, reverse_tth_distortion=True):
    for i, line in enumerate(line_data):
        # Make sure there are at least 300 sample points
        # so that the conversion will appear correct.
        line = add_sample_points(line, 300)

        if reverse_tth_distortion:
            # If we are applying tth distortion in the polar view, we need to
            # convert back to polar coordinates without tth distortion applied
            line = apply_tth_distortion_if_needed(line, in_degrees=True,
                                                  reverse=True)

        line_data[i] = line

    raw_line_data = []
    instr = create_hedm_instrument()
    for line in line_data:
        for key, panel in instr.detectors.items():
            cart = angles_to_cart(line, panel, tvec_s=instr.tvec)
            raw = cart_to_pixels(cart, panel)

            # If any rows contain invalid values (negative or past the raw
            # border), set those values to nan. Then add points to connect
            # border points, to ensure all border values get masked.
            invalid_rows = (
                np.any(raw < 0, axis=1) |
                np.any(raw > (panel.cols - 1, panel.rows - 1), axis=1)
            )
            raw[invalid_rows] = np.nan

            if np.all(np.any(np.isnan(raw), axis=1)):
                # No coordinates lie on this detector
                continue

            # Find all points that cross the border.
            valid = ~np.any(np.isnan(raw), axis=1)
            edge_indices = np.where(np.logical_xor(valid[:-1], valid[1:]))[0]
            if len(edge_indices) != 0:

                # For each index, add a point exactly on the border.
                # We will construct an equation for a line from the
                # two nearest points, find the border intersection,
                # and add a point right there.
                add_coords = []
                add_indices = []
                for idx in edge_indices:
                    new_idx = idx + 1
                    if np.any(np.isnan(raw[idx])):
                        coords1 = raw[idx + 1]
                        tmp_idx = idx + 2
                        # Some points have duplicate neighbors for some reason
                        while np.allclose(coords1, raw[tmp_idx]):
                            tmp_idx += 1
                        coords2 = raw[tmp_idx]
                    else:
                        coords1 = raw[idx]
                        tmp_idx = idx - 1
                        # Some points have duplicate neighbors for some reason
                        while np.allclose(coords1, raw[tmp_idx]):
                            tmp_idx -= 1
                        coords2 = raw[tmp_idx]

                    # Create equation of line
                    m = 1 / np.divide(*(coords2 - coords1))
                    b = coords1[1] - m * coords1[0]

                    # Find all border intersections
                    max_x = panel.cols - 1
                    max_y = panel.rows - 1
                    intersections = np.array([
                        [0, b],
                        [max_x, m * max_x + b],
                        [-b / m, 0],
                        [(max_y - b) / m, max_y],
                    ])
                    # The correct intersection should be the closest to coords1
                    distances = np.sqrt(
                        ((coords1 - intersections)**2).sum(axis=1)
                    )
                    new_coords = intersections[np.argmin(distances)]

                    add_coords.append(new_coords)
                    add_indices.append(new_idx)

                raw = np.insert(raw, add_indices, add_coords, axis=0)

            # Go ahead and get rid of nan coordinates. They cause trouble
            # with scikit image's polygon.
            raw = raw[~np.isnan(raw.min(axis=1))]
            raw_line_data.append((key, raw))

    return raw_line_data


def create_raw_mask(line_data):
    masks = []
    for det in HexrdConfig().detector_names:
        det_lines = [line for line in line_data if det == line[0]]
        img = HexrdConfig().image(det, 0)
        final_mask = np.ones(img.shape, dtype=bool)
        for _, data in det_lines:
            rr, cc = polygon(data[:, 1], data[:, 0], shape=img.shape)
            if len(rr) >= 1:
                mask = np.ones(img.shape, dtype=bool)
                mask[rr, cc] = False
                final_mask = np.logical_and(final_mask, mask)
        masks.append((det, final_mask))
    return masks


def rebuild_raw_masks():
    from hexrdgui.masking.mask_manager import MaskManager
    for mask in MaskManager().masks.values():
        mask.invalidate_masked_arrays()
