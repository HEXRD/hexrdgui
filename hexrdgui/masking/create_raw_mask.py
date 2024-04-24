import numpy as np

from skimage import measure

from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils import (
    add_sample_points,
    remove_duplicate_neighbors,
)
from hexrdgui.utils.conversions import angles_to_pixels
from hexrdgui.utils.polygon import polygon_to_mask
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
            raw = angles_to_pixels(line, panel, tvec_s=instr.tvec)

            # Remove nans
            raw = raw[~np.isnan(raw.min(axis=1))]

            # Check if all points lie off the detector. If so, skip it.
            # We want to keep these invalid rows for now, though, as
            # we will still use them when we draw the polygon mask.
            invalid_rows = (
                np.any(raw < -0.5, axis=1) |
                np.any(raw > (panel.cols - 0.5, panel.rows - 0.5), axis=1)
            )

            if len(raw[~invalid_rows]) == 0:
                # No raw coordinates on the detector
                continue

            # Remove duplicate neighbors
            raw = remove_duplicate_neighbors(raw)

            # Keep raw points off the detector, to ensure we
            # can draw the polygon correctly.
            # Then, find contours along the polygon.
            # We will create a higher resolution shape so that we
            # can keep resolution from the mask coordinates
            res = 2
            mask_shape = np.array(panel.shape) * res

            mask = ~polygon_to_mask(raw * res, mask_shape)

            # Add borders so that border coordinates are kept.
            contours = measure.find_contours(np.pad(mask, 1))
            for contour in contours:
                raw_line_data.append((key, (contour[:, [1, 0]] - 1) / res))

    return raw_line_data


def create_raw_mask(line_data):
    masks = []
    for det in HexrdConfig().detector_names:
        det_lines = [line for line in line_data if det == line[0]]
        img = HexrdConfig().image(det, 0)
        final_mask = np.ones(img.shape, dtype=bool)
        for _, data in det_lines:
            mask = polygon_to_mask(data, img.shape)
            final_mask = np.logical_and(final_mask, mask)
        masks.append((det, final_mask))
    return masks


def rebuild_raw_masks():
    from hexrdgui.masking.mask_manager import MaskManager
    for mask in MaskManager().masks.values():
        mask.invalidate_masked_arrays()
