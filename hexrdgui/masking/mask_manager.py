import math
import numpy as np

from PySide6.QtCore import Signal, QObject
from hexrdgui import utils

from hexrdgui.constants import ViewType
from hexrdgui.masking.constants import MaskType
from hexrdgui.masking.create_polar_mask import (
    create_polar_mask_from_raw, rebuild_polar_masks
)
from hexrdgui.masking.create_raw_mask import (
    recompute_raw_threshold_mask, create_raw_mask, rebuild_raw_masks
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.mask_compatability import load_masks_v1_to_v2
from hexrdgui.singletons import QSingleton
from hexrdgui.utils import unique_name

from hexrd.instrument import unwrap_dict_to_h5

from abc import ABC, abstractmethod


class Mask(ABC):
    def __init__(self, name='', mtype='', visible=True):
        self.type = mtype
        self.name = name
        self.visible = visible
        self.masked_arrays = None

    def update_mask_visibility(self, visibility):
        self.visible = visibility

    # Abstract methods
    @abstractmethod
    def get_data(self):
        pass

    @abstractmethod
    def set_data(self, data):
        pass

    @abstractmethod
    def update_masked_arrays(self):
        pass

    @abstractmethod
    def serialize(self):
        pass

    @abstractmethod
    def deserialize(self, data):
        pass


class RegionMask(Mask):
    def __init__(self, name='', mtype='', visible=True):
        super().__init__(name, mtype, visible)
        self._raw = None

    def get_data(self):
        return self._raw

    def set_data(self, data):
        self._raw = data
        self.update_masked_arrays()

    def update_masked_arrays(self, view=ViewType.raw):
        if view == ViewType.raw:
            self.masked_arrays = create_raw_mask(self._raw)
        else:
            self.masked_arrays = create_polar_mask_from_raw(self._raw)

    def serialize(self):
        data = {
            'name': self.name,
            'mtype': self.type,
            'visible': self.visible,
        }
        for i, (det, values) in enumerate(self._raw):
            data.setdefault(det, {})[str(i)] = values
        return data

    def deserialize(self, data):
        self.name = data['name']
        self.type = data['mtype']
        self.visible = data['visible']
        raw_data = []
        for det in HexrdConfig().detector_names:
            if det not in data.keys():
                continue
            raw_data.extend([(det, v) for v in data[det].values()])
        self.set_data(raw_data)


class ThresholdMask(Mask):
    def __init__(self, name='', mtype='', visible=True):
        super().__init__(name, mtype, visible)
        self.min_val = -math.inf
        self.max_val = math.inf
        self._hidden_mask_data = None

    def update_mask_visibility(self, visible):
        if visible == self.visible:
            return

        self.visible = visible
        if visible and self._hidden_mask_data:
            self.set_data(self._hidden_mask_data)
            self._hidden_mask_data = None
        elif not visible:
            self._hidden_mask_data = self.get_data()
            self.set_data([-math.inf, math.inf])

    def get_data(self):
        return [self.min_val, self.max_val]

    def set_data(self, data):
        self.min_val = data[0]
        self.max_val = data[1]
        self.update_masked_arrays()

    def update_masked_arrays(self):
        self.masked_arrays = recompute_raw_threshold_mask()

    def serialize(self):
        return {
            'min_val': self.min_val,
            'max_val': self.max_val,
            'name': self.name,
            'mtype': self.type,
            'visible': self.visible,
        }

    def deserialize(self, data):
        self.name = data['name']
        self.type = data['mtype']
        self.visible = data['visible']
        self.set_data([data['min_val'], data['max_val']])


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

        self.setup_connections()

    @property
    def visible_masks(self):
        return [k for k, v in self.masks.items() if v.visible]

    @property
    def threshold_mask(self):
        for mask in self.masks.values():
            if mask.type == MaskType.threshold:
                return mask
        return None

    @property
    def mask_names(self):
        return list(self.masks.keys())

    @property
    def masked_images_dict(self):
        return self.create_masked_images_dict()

    @property
    def raw_masks_dict(self):
        """Get a masks dict"""
        masks_dict = {}
        images_dict = HexrdConfig().images_dict
        for name, img in images_dict.items():
            final_mask = np.ones(img.shape, dtype=bool)
            for mask in self.masks.values():
                if not mask.visible or mask.type == MaskType.threshold:
                    continue

                if self.view_mode != ViewType.raw:
                    # Make sure we have the raw masked arrays
                    mask.update_masked_arrays(ViewType.raw)
                for det, arr in mask.masked_arrays:
                    if det == name:
                        final_mask = np.logical_and(final_mask, arr)
                if self.view_mode != ViewType.raw:
                    # Reset the masked arrays for the current view
                    mask.update_masked_arrays(self.view_mode)
            if tm := self.threshold_mask:
                idx = HexrdConfig().current_imageseries_idx
                thresh_mask = tm.masked_arrays[name][idx]
                final_mask = np.logical_and(final_mask, thresh_mask)
            masks_dict[name] = final_mask

        return masks_dict

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
        new_mask.set_data(data)
        self.masks[name] = new_mask
        self.mask_mgr_dialog_update.emit()
        return new_mask

    def remove_mask(self, name):
        removed_mask = self.masks.pop(name)
        self.mask_mgr_dialog_update.emit()
        return removed_mask

    def write_masks_to_group(self, data, h5py_group):
        unwrap_dict_to_h5(h5py_group, data, asattr=False)

    def write_single_mask(self, name):
        d = {'_version': 2}
        d[name] = self.masks[name].serialize()
        self.export_masks_to_file.emit(d)

    def write_all_masks(self, h5py_group=None):
        d = {'_version': 2}
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
        items = load_masks_v1_to_v2(h5py_group)
        actual_view_mode = self.view_mode
        self.view_mode = ViewType.raw
        for key, data in items:
            if key == '_version':
                continue
            elif data['mtype'] == MaskType.threshold:
                new_mask = ThresholdMask(None, None)
            else:
                new_mask = RegionMask(None, None)
            self.masks[key] = new_mask
            new_mask.deserialize(data)

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
        self.masks[name].update_mask_visibility(visibility)

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

    def masks_to_panel_buffer(self, selection, buff_val):
        # Set the visible masks as the panel buffer(s)
        # We must ensure that we are using raw masks
        for det, mask in self.raw_masks_dict.items():
            detector_config = HexrdConfig().detector(det)
            buffer_default = {'status': 0}
            buffer = detector_config.setdefault('buffer', buffer_default)
            buffer_value = detector_config['buffer'].get('value', None)
            if isinstance(buffer_value, np.ndarray) and buff_val.ndim == 2:
                if selection == 'Logical AND with buffer':
                    mask = np.logical_and(mask, buffer_value)
                elif selection == 'Logical OR with buffer':
                    mask = np.logical_or(mask, buffer_value)
            buffer['value'] = mask

    def clear_all(self):
        self.masks.clear()

    def create_masked_images_dict(self, fill_value=0):
        """Get an images dict where masks have been applied"""
        from hexrdgui.create_hedm_instrument import create_hedm_instrument

        images_dict = HexrdConfig().images_dict
        instr = create_hedm_instrument()

        has_masks = bool(self.visible_masks)
        has_panel_buffers = any(panel.panel_buffer is not None
                                for panel in instr.detectors.values())

        if not has_masks and not has_panel_buffers:
            # Force a fill_value of 0 if there are no visible masks
            # and no panel buffers.
            fill_value = 0

        for det, mask in self.raw_masks_dict.items():
            if has_panel_buffers:
                panel = instr.detectors[det]
                utils.convert_panel_buffer_to_2d_array(panel)

            for name, img in images_dict.items():
                if (np.issubdtype(type(fill_value), np.floating) and
                        not np.issubdtype(img.dtype, np.floating)):
                    img = img.astype(float)
                    images_dict[name] = img
                if det == name:
                    img[~mask] = fill_value

                    if has_panel_buffers:
                        img[~panel.panel_buffer] = fill_value

        return images_dict

    def apply_masks_to_panel_buffers(self, instr):
        # Apply raw masks to the panel buffers on the passed instrument
        for det_key, mask in self.raw_masks_dict.items():
            panel = instr.detectors[det_key]

            # Make sure it is a 2D array
            utils.convert_panel_buffer_to_2d_array(panel)

            # Add the mask
            # NOTE: the mask here is False when pixels should be masked.
            # This is the same as the panel buffer, which is why we are
            # doing a `np.logical_and()`.
            panel.panel_buffer = np.logical_and(mask, panel.panel_buffer)
