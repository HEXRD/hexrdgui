import numpy as np

from skimage.draw import polygon
from hexrdgui.constants import ViewType

from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType
from hexrdgui.utils import add_sample_points
from hexrdgui.utils.conversions import angles_to_pixels
from hexrdgui.utils.tth_distortion import apply_tth_distortion_if_needed


def recompute_raw_threshold_mask():
    from hexrdgui.masking.mask_manager import MaskManager
    results = {}
    if tm := MaskManager().threshold_mask:
        for det in HexrdConfig().detector_names:
            ims = HexrdConfig().imageseries(det)
            masks = [None for i in range(len(ims))]
            for idx in range(len(ims)):
                img = HexrdConfig().image(det, idx)
                mask = create_threshold_mask(img, tm.data)
                masks[idx] = mask
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
            if all([np.isnan(x) for x in raw.flatten()]):
                continue

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
        if mask.type == MaskType.threshold:
            continue
        mask.update_masked_arrays(ViewType.raw)
