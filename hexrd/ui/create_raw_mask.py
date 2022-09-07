import copy
import numpy as np

from skimage.draw import polygon

from hexrd.ui import constants
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.utils.conversions import angles_to_pixels


def apply_threshold_mask(imageseries):
    for det in HexrdConfig().detector_names:
        ims = imageseries[det]
        masked_ims = [None for i in range(len(ims))]
        masks = [None for i in range(len(ims))]
        for idx in range(len(ims)):
            img = copy.copy(ims[idx])
            masked_img, mask = create_threshold_mask(img)
            masked_ims[idx] = masked_img
            masks[idx] = mask
        HexrdConfig().set_threshold_mask(det, masks)
        HexrdConfig().imageseries_dict[det] = masked_ims


def remove_threshold_mask(ims_dict_copy):
    HexrdConfig().imageseries_dict = copy.copy(ims_dict_copy)


def create_threshold_mask(img):
    comparison = HexrdConfig().threshold_comparison
    value = HexrdConfig().threshold_value
    mask = np.ones(img.shape, dtype=bool)
    if comparison == constants.UI_THRESHOLD_LESS_THAN:
        mask = (img > value)
    elif comparison == constants.UI_THRESHOLD_GREATER_THAN:
        mask = (img < value)
    elif comparison == constants.UI_THRESHOLD_EQUAL_TO:
        mask = (img == value)
    img[~mask] = 0
    return img, mask


def convert_polar_to_raw(line_data):
    raw_line_data = []
    for line in line_data:
        for key, panel in create_hedm_instrument().detectors.items():
            raw = angles_to_pixels(line, panel)
            if all([np.isnan(x) for x in raw.flatten()]):
                continue
            raw_line_data.append((key, raw))
    return raw_line_data


def create_raw_mask(name, line_data):
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
        HexrdConfig().masks.setdefault(name, []).append((det, final_mask))


def rebuild_raw_masks():
    HexrdConfig().masks.clear()
    for name, line_data in HexrdConfig().raw_mask_coords.items():
        create_raw_mask(name, line_data)
