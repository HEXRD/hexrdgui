import copy
import numpy as np

from hexrd.ui import constants
from hexrd.ui.hexrd_config import HexrdConfig


def apply_raw_mask(imageseries):
    comparison = HexrdConfig().threshold_comparison
    value = HexrdConfig().threshold_value
    for det in HexrdConfig().detector_names:
        ims = imageseries[det]
        masked_ims = [None for i in range(len(ims))]
        for idx in range(len(ims)):
            img = copy.copy(ims[idx])
            masked_img = _create_raw_mask(img, comparison, value)
            masked_ims[idx] = masked_img
        HexrdConfig().imageseries_dict[det] = masked_ims


def remove_raw_mask(ims_dict_copy):
    HexrdConfig().imageseries_dict = copy.copy(ims_dict_copy)
    return None


def _create_raw_mask(img, comparison, value):
    mask = np.ones(img.shape, dtype=bool)
    if comparison == constants.UI_THRESHOLD_LESS_THAN:
        mask = (img < value)
    elif comparison == constants.UI_THRESHOLD_GREATER_THAN:
        mask = (img > value)
    elif comparison == constants.UI_THRESHOLD_EQUAL_TO:
        mask = (img == value)
    img[mask] = 0
    return img
