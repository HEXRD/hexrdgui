from __future__ import annotations

from typing import Any

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


def recompute_raw_threshold_mask() -> dict:
    from hexrdgui.masking.mask_manager import MaskManager

    results = {}
    if tm := MaskManager().threshold_mask:
        for det in HexrdConfig().detector_names:
            ims = HexrdConfig().imageseries(det)
            assert ims is not None
            if tm.visible:
                mask_list: list[np.ndarray | None] = [None for i in range(len(ims))]
                for idx in range(len(ims)):
                    img = HexrdConfig().image(det, idx)
                    mask = create_threshold_mask(img, tm.data)
                    mask_list[idx] = mask
                masks: Any = mask_list
            else:
                masks = np.ones(ims.shape, dtype=np.bool_)
            results[det] = masks
    return results


def create_threshold_mask(img: np.ndarray, values: list[float]) -> np.ndarray:
    lt_val, gt_val = values
    lt_mask = img < lt_val
    gt_mask = img > gt_val

    return ~np.logical_or(lt_mask, gt_mask)


def convert_polar_to_raw(line_data: Any, reverse_tth_distortion: bool = True) -> list:
    for i, line in enumerate(line_data):
        # Make sure there are at least 300 sample points
        # so that the conversion will appear correct.
        line = add_sample_points(line, 300)

        if reverse_tth_distortion:
            orig = line
            # If we are applying tth distortion in the polar view, we need to
            # convert back to polar coordinates without tth distortion applied
            line = apply_tth_distortion_if_needed(line, in_degrees=True, reverse=True)

            # Any points past the critical beta will end up with nan in their
            # two theta values. Howver, it is essential that we keep points
            # past the critical beta to catch all of the detector edges in the
            # mask. So right now, if any points were past the critical beta,
            # we just restore them to their original values. These aren't as
            # accurate as the points where the distortion was
            # "reverse-applied", but they are good enough for catching the
            # detector edges.
            row_has_nan = np.isnan(line[:, 0])
            line[row_has_nan] = orig[row_has_nan]

        line_data[i] = line

    raw_line_data = []
    instr = create_hedm_instrument()
    for line in line_data:
        for key, panel in instr.detectors.items():
            raw = angles_to_pixels(line, panel, tvec_s=instr.tvec)

            # Remove nans
            raw = raw[~np.isnan(raw.min(axis=1))]
            if raw.size == 0:
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

            mask = ~polygon_to_mask(raw * res, tuple(mask_shape))
            if not mask.any():
                # The mask did not affect this panel.
                continue

            # Add borders so that border coordinates are kept.
            contours = measure.find_contours(np.pad(mask, 1))
            for contour in contours:
                # Add 0.5 so all coordinates will be positive before rescaling,
                # then remove that 0.5 again afterward.
                contour = ((contour[:, [1, 0]] - 1) + 0.5) / res - 0.5

                # Now, if any masks occur along the raw border, extend
                # them by another half pixel *past* the border.
                # This helps ensure that the corresponding warped
                # polar pixels will always be masked out.
                contour[np.isclose(contour, -0.5)] -= 0.5
                contour[np.isclose(contour[:, 1], panel.shape[0] - 0.5), 1] += 0.5
                contour[np.isclose(contour[:, 0], panel.shape[1] - 0.5), 0] += 0.5

                raw_line_data.append((key, contour))

    return raw_line_data


def create_raw_mask(line_data: Any) -> list:
    masks = []
    for det in HexrdConfig().detector_names:
        det_lines = [line for line in line_data if det == line[0]]
        img = HexrdConfig().image(det, 0)
        assert img is not None
        final_mask = np.ones(img.shape, dtype=bool)
        for _, data in det_lines:
            mask = polygon_to_mask(data, img.shape)
            final_mask = np.logical_and(final_mask, mask)
        masks.append((det, final_mask))
    return masks


def rebuild_raw_masks() -> None:
    from hexrdgui.masking.mask_manager import MaskManager

    for mask in MaskManager().masks.values():
        mask.invalidate_masked_arrays()
