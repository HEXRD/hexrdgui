import math
from hexrdgui.constants import ViewType
from hexrdgui.create_polar_mask import (
    convert_raw_to_polar, create_polar_mask_from_raw
)
from hexrdgui.create_raw_mask import (
    apply_threshold_mask, convert_polar_to_raw, create_raw_mask
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.mask_compatability import load_masks_v1_to_v2
from hexrdgui.singletons import Singleton
from hexrdgui.utils import unique_name

from abc import ABC, abstractmethod


class Mask(ABC):
    def __init__(self, mtype='', name='', mask_image=True, show_border=False):
        self.mask_type = mtype
        self.name = name
        self.mask_image = mask_image
        self.show_border = show_border
        self.masked_arrays = None

    # Abstract methods
    @abstractmethod
    def get_data(self):
        pass

    @abstractmethod
    def set_data(self, data):
        pass

    @abstractmethod
    def get_mask_arrays(self):
        pass

    @abstractmethod
    def update_mask_array(self):
        pass

    @abstractmethod
    def serialize(self):
        pass

    @abstractmethod
    def deserialize(self, data):
        pass


class RegionMask(Mask):
    def __init__(self):
        self._polar = None
        self._raw = None

    def get_data(self, view=ViewType.raw):
        if view == ViewType.raw:
            return self._raw
        else:
            return self._polar

    def set_data(self, data, view=ViewType.raw):
        if view == ViewType.raw:
            raw_data = data
            polar_data = []
            for det, value in data:
                polar_data.extend(convert_raw_to_polar(det, value))
        else:
            polar_data = data
            raw_data = convert_polar_to_raw(data)
        self._raw = raw_data
        self._polar = polar_data
        self.update_mask_array()

    def get_mask_arrays(self, view=ViewType.raw):
        if view == ViewType.raw:
            return self._masked_arrays
        else:
            # FIXME: Function parameters changed
            return create_polar_mask_from_raw(self._raw)

    def update_mask_array(self):
        # FIXME: Function parameters changed
        self._masked_arrays = create_raw_mask(self._raw)

    def serialize(self):
        data = {
            'name': self.name,
            'mtype': self.mask_type,
            'visible': self.mask_image,
            'border': self.show_border,
        }
        for det, values in self._raw:
            data.setdefault(det, []).append(values)
        return data

    def deserialize(self, data):
        self.name = data['name']
        self.mask_type = data['mtype']
        self.mask_image = data['visible']
        self.show_border = data['border']
        raw_data = []
        for det in HexrdConfig().detector_names:
            raw_data.append([(det, v) for v in data[det]])
        self.set_data(raw_data)


class ThresholdMask(Mask):
    def __init__(self):
        self._min = -math.inf
        self._max = math.inf

    @property
    def min_val(self):
        return self._min

    @min_val.setter
    def min_val(self, val):
        self._min = val

    @property
    def max_val(self):
        return self._max

    @max_val.setter
    def max_val(self, val):
        self._max = val

    def get_data(self):
        return [self.min_val, self.max_val]

    def set_data(self, data):
        self.min_val = data[0]
        self.max_val = data[1]
        self.update_mask_array()

    def get_mask_arrays(self):
        return self._masked_arrays

    def update_mask_array(self):
        # TODO: rename apply_threshold_mask since its purpose has changed now?
        # FIXME: Function parameters changed
        self._masked_arrays = apply_threshold_mask(self.values)

    def serialize(self):
        return {
            'min_val': self.min_val,
            'max_val': self.max_val,
            'name': self.name,
            'mtype': self.mask_type,
            'visible': self.mask_image,
            'border': self.show_border,
        }

    def deserialize(self, data):
        self.name = data['name']
        self.mask_type = data['mtype']
        self.mask_image = data['visible']
        self.show_border = data['border']
        self.set_data([data['min_val'], data['max_val']])


class MaskManager(metaclass=Singleton):
    def __init__(self, view_mode):
        self.masks = {}
        self.view_mode = view_mode

    @property
    def visible_masks(self):
        return [k for k, v in self.masks if v.mask_image]

    @property
    def visible_boundaries(self):
        return [k for k, v in self.masks if v.show_border]

    @property
    def threshold_mask(self):
        for mask in self.masks.values():
            if mask.mask_type == 'threshold':
                return mask
        return None

    def add_mask(self, name, data, mtype, mask_image=True, show_border=False):
        # Enforce name uniqueness
        name = unique_name(self.masks.keys(), name)
        if mtype == 'threshold':
            new_mask = ThresholdMask(name, mtype, mask_image)
        else:
            new_mask = RegionMask(name, mtype, mask_image, show_border)
        new_mask.set_data(self.view_mode, data)
        self.masks[name] = new_mask

    def remove_mask(self, name):
        self.masks.pop(name)

    def write_all_masks(self, h5py_group=None):
        d = { '_version': 2 }
        for name, mask_info in self.masks:
            d[name] = mask_info.serialize()
        if h5py_group:
            self.write_masks_to_group(d, h5py_group)
        else:
            self.export_masks_to_file(d)

    def save_state(self, h5py_group):
        if 'masks' not in h5py_group:
            h5py_group.create_group('masks')

        self.write_all_masks(h5py_group['masks'])

    def load_masks(self, h5py_group):
        # TODO: Handle case of detector name mismatch (loading wrong mask file)
        items = load_masks_v1_to_v2(h5py_group)
        actual_view_mode = self.view_mode
        self.view_mode = ViewType.raw
        for key, data in items:
            if data['mtype'] == 'threshold':
                new_mask = ThresholdMask(None, None)
                new_mask.deserialize(data)
            else:
                new_mask = RegionMask(None, None)
                new_mask.deserialize(data)
            self.masks[key] = new_mask

        if not HexrdConfig().loading_state:
            # We're importing masks directly,
            # don't wait for the state loaded signal
            # FIXME: This is not connected to anything atm
            self.rebuild_masks()
        self.view_mode = actual_view_mode

    def load_state(self, h5py_group):
        self.masks = {}
        if 'masks' in h5py_group:
            self.load_masks(h5py_group['masks'])

    def update_view_mode(self, mode):
        self.view_mode = mode
