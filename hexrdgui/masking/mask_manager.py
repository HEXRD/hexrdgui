import math
import numpy as np

from PySide6.QtCore import Signal, QObject
from hexrdgui import utils

from hexrdgui.constants import ViewType
from hexrdgui.masking.constants import CURRENT_MASK_VERSION, MaskType
from hexrdgui.masking.create_polar_mask import (
    create_polar_mask_from_raw, rebuild_polar_masks
)
from hexrdgui.masking.create_raw_mask import (
    recompute_raw_threshold_mask, create_raw_mask, rebuild_raw_masks
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.mask_compatibility import load_masks
from hexrdgui.singletons import QSingleton
from hexrdgui.utils import unique_name

from hexrd.instrument import unwrap_dict_to_h5

from abc import ABC, abstractmethod


class Mask(ABC):
    def __init__(self, name='', mtype='', visible=True, show_border=False):
        self.type = mtype
        self.name = name
        self.visible = visible
        self.show_border = show_border
        self.masked_arrays = None
        self.masked_arrays_view_mode = ViewType.raw

    def get_masked_arrays(self):
        if self.masked_arrays is None:
            self.update_masked_arrays()

        return self.masked_arrays

    def invalidate_masked_arrays(self):
        self.masked_arrays = None

    def update_border_visibility(self, visibility):
        self.show_border = visibility

    # Abstract methods
    @property
    @abstractmethod
    def data(self):
        pass

    @data.setter
    @abstractmethod
    def data(self, values):
        pass

    @abstractmethod
    def update_masked_arrays(self):
        pass

    @abstractmethod
    def serialize(self):
        pass

    @classmethod
    def deserialize(cls, data):
        return cls(
            name=data['name'],
            mtype=data['mtype'],
            visible=data.get('visible', True),
            show_border=data.get('border', False),
        )


class RegionMask(Mask):
    def __init__(self, name='', mtype='', visible=True, show_border=False):
        super().__init__(name, mtype, visible, show_border)
        self._raw = None

    @property
    def data(self):
        return self._raw

    @data.setter
    def data(self, values):
        self._raw = values
        self.invalidate_masked_arrays()

    def update_masked_arrays(self, view=ViewType.raw, instr=None):
        self.masked_arrays_view_mode = view
        if view == ViewType.raw:
            self.masked_arrays = create_raw_mask(self._raw)
        else:
            # Do not apply tth distortion for pinhole mask types
            apply_tth_distortion = self.type != MaskType.pinhole
            self.masked_arrays = create_polar_mask_from_raw(
                self._raw,
                instr,
                apply_tth_distortion=apply_tth_distortion,
            )

    def get_masked_arrays(self, image_mode=ViewType.raw, instr=None):
        if self.masked_arrays is None or self.masked_arrays_view_mode != image_mode:
            self.update_masked_arrays(image_mode, instr)

        return self.masked_arrays

    def update_border_visibility(self, visibility):
        can_have_border = [MaskType.region, MaskType.polygon, MaskType.pinhole]
        if self.type not in can_have_border:
            # Only rectangle, ellipse and hand-drawn masks can show borders
            visibility = False
        self.show_border = visibility

    def serialize(self):
        data = {
            'name': self.name,
            'mtype': self.type,
            'visible': self.visible,
            'border': self.show_border,
            'data': {},
        }
        for i, (det, values) in enumerate(self._raw):
            data['data'].setdefault(det, {})[str(i)] = values
        return data

    @classmethod
    def deserialize(cls, data):
        new_cls = cls(
            name=data['name'],
            mtype=data['mtype'],
            visible=data.get('visible', True),
            show_border=data.get('border', False),
        )
        raw_data = []
        for det in HexrdConfig().detector_names:
            if det not in data['data'].keys():
                continue
            raw_data.extend([(det, v) for v in data['data'][det].values()])
        new_cls.data = raw_data
        return new_cls


class ThresholdMask(Mask):
    def __init__(self, name='', mtype='', visible=True):
        super().__init__(name, mtype, visible)
        self.min_val = -math.inf
        self.max_val = math.inf

    @property
    def data(self):
        return [self.min_val, self.max_val]

    @data.setter
    def data(self, values):
        self.min_val = values[0]
        self.max_val = values[1]
        self.invalidate_masked_arrays()

    def update_masked_arrays(self, view=ViewType.raw):
        self.masked_arrays = recompute_raw_threshold_mask()

    def update_border_visibility(self, visibility):
        # Cannot show borders for threshold
        self.show_border = False

    def serialize(self):
        return {
            'min_val': self.min_val,
            'max_val': self.max_val,
            'name': self.name,
            'mtype': self.type,
            'visible': self.visible,
            'border': self.show_border,
        }

    @classmethod
    def deserialize(cls, data):
        new_cls = cls(
            name=data['name'],
            mtype=data['mtype'],
            visible=data.get('visible', True),
        )
        new_cls.data = [data['min_val'], data['max_val']]
        return new_cls


class MaskManager(QObject, metaclass=QSingleton):
    """Emitted when a new raw mask has been created"""
    raw_masks_changed = Signal()

    """Emitted when a new polar mask has been created"""
    polar_masks_changed = Signal()

    """Emitted when the masks have changed and the
    MaskManagerDialog table should be updated"""
    mask_mgr_dialog_update = Signal()

    """Emitted when the threshold mask status changes via the dialog"""
    threshold_mask_changed = Signal()

    """Emitted when we need to open a save file dialog

    The argument is the dict of data to export to hdf5
    """
    export_masks_to_file = Signal(dict)

    def __init__(self):
        super().__init__(None)
        self.masks = {}
        self.view_mode = ViewType.raw
        self.boundary_color = '#000'  # Default to black

        self.setup_connections()

    @property
    def visible_masks(self):
        return [k for k, v in self.masks.items() if v.visible]

    @property
    def visible_boundaries(self):
        return [k for k, v in self.masks.items() if v.show_border]

    @property
    def threshold_mask(self):
        for mask in self.masks.values():
            if mask.type == MaskType.threshold:
                return mask
        return None

    @property
    def mask_names(self):
        return list(self.masks.keys())

    def setup_connections(self):
        self.threshold_mask_changed.connect(self.threshold_toggled)
        HexrdConfig().save_state.connect(self.save_state)
        HexrdConfig().load_state.connect(self.load_state)
        HexrdConfig().detectors_changed.connect(self.clear_all)
        HexrdConfig().state_loaded.connect(self.rebuild_masks)

    def view_mode_changed(self, mode):
        self.view_mode = mode

    def masks_changed(self):
        if self.view_mode in (ViewType.polar, ViewType.stereo):
            self.polar_masks_changed.emit()
        elif self.view_mode == ViewType.raw:
            self.raw_masks_changed.emit()

    def rebuild_masks(self):
        if self.view_mode == ViewType.raw:
            rebuild_raw_masks()
        elif self.view_mode in (ViewType.polar, ViewType.stereo):
            rebuild_polar_masks()
        self.masks_changed()
        self.mask_mgr_dialog_update.emit()

    def add_mask(self, name, data, mtype, visible=True):
        # Enforce name uniqueness
        name = unique_name(self.mask_names, name)
        if mtype == MaskType.threshold:
            new_mask = ThresholdMask(name, mtype, visible)
        else:
            new_mask = RegionMask(name, mtype, visible)
        new_mask.data = data
        self.masks[name] = new_mask
        self.mask_mgr_dialog_update.emit()
        return new_mask

    def remove_mask(self, name):
        removed_mask = self.masks.pop(name)
        self.mask_mgr_dialog_update.emit()
        return removed_mask

    def write_masks_to_group(self, data, h5py_group):
        h5py_group.attrs['_version'] = CURRENT_MASK_VERSION
        unwrap_dict_to_h5(h5py_group, data, asattr=False)

    def write_single_mask(self, name):
        d = {
            name: self.masks[name].serialize(),
            '__boundary_color': self.boundary_color
        }
        self.export_masks_to_file.emit(d)

    def write_all_masks(self, h5py_group=None):
        d = {'__boundary_color': self.boundary_color}
        for name, mask_info in self.masks.items():
            d[name] = mask_info.serialize()
        if h5py_group:
            self.write_masks_to_group(d, h5py_group)
        else:
            self.export_masks_to_file.emit(d)

    def save_state(self, h5py_group):
        if 'masks' not in h5py_group:
            h5py_group.create_group('masks')

        self.write_all_masks(h5py_group['masks'])

    def load_masks(self, h5py_group):
        items = load_masks(h5py_group)
        actual_view_mode = self.view_mode
        self.view_mode = ViewType.raw
        for key, data in items.items():
            if key == '__boundary_color':
                self.boundary_color = data
                continue
            elif data['mtype'] == MaskType.threshold:
                new_mask = ThresholdMask.deserialize(data)
            else:
                new_mask = RegionMask.deserialize(data)

            self.masks[key] = new_mask

        if not HexrdConfig().loading_state:
            # We're importing masks directly,
            # don't wait for the state loaded signal
            self.rebuild_masks()
        self.view_mode = actual_view_mode

    def load_state(self, h5py_group):
        self.masks = {}
        if 'masks' in h5py_group:
            self.load_masks(h5py_group['masks'])
        self.mask_mgr_dialog_update.emit()

    def update_view_mode(self, mode):
        self.view_mode = mode

    def update_mask_visibility(self, name, visibility):
        self.masks[name].visible = visibility

    def update_border_visibility(self, name, visibility):
        self.masks[name].update_border_visibility(visibility)

    @property
    def contains_border_only_masks(self):
        # If we have any border-only masks, that means the display images
        # are different from computed images, and require extra computation.
        # If this returns False, we can skip that extra computation and
        # set display images and computed images to be the same.
        return any(x.show_border and not x.visible
                   for x in self.masks.values())

    def threshold_toggled(self):
        if self.threshold_mask:
            self.remove_mask(self.threshold_mask.name)
        else:
            self.add_mask(
                'threshold', [-math.inf, math.inf], MaskType.threshold)
        self.mask_mgr_dialog_update.emit()

    def update_name(self, old_name, new_name):
        mask = self.remove_mask(old_name)
        mask.name = new_name
        self.masks[new_name] = mask

    def masks_to_panel_buffer(self, selection):
        # Set the visible masks as the panel buffer(s)
        # We must ensure that we are using raw masks
        for det, mask in HexrdConfig().raw_masks_dict.items():
            detector_config = HexrdConfig().detector(det)
            buffer_value = detector_config.get('buffer', None)
            if isinstance(buffer_value, np.ndarray) and buffer_value.ndim == 2:
                if selection == 'Logical AND with buffer':
                    # Need to invert so True is invalid
                    mask = ~np.logical_and(~mask, ~buffer_value)
                elif selection == 'Logical OR with buffer':
                    # Need to invert so True is invalid
                    mask = ~np.logical_or(~mask, ~buffer_value)
            detector_config['buffer'] = buffer_value

        HexrdConfig().rerender_needed.emit()

    def clear_all(self):
        self.masks.clear()

    def apply_masks_to_panel_buffers(self, instr):
        # Apply raw masks to the panel buffers on the passed instrument
        for det_key, mask in HexrdConfig().raw_masks_dict.items():
            panel = instr.detectors[det_key]

            # Make sure it is a 2D array
            utils.convert_panel_buffer_to_2d_array(panel)

            # Add the mask
            # NOTE: the mask here is False when pixels should be masked.
            # This is the same as the panel buffer, which is why we are
            # doing a `np.logical_and()`.
            panel.panel_buffer = np.logical_and(mask, panel.panel_buffer)
