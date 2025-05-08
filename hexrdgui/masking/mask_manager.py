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
    def __init__(
        self,
        name=None,
        mtype='',
        visible=True,
        show_border=False,
        mode=None,
        xray_source=None
    ):
        self.type = mtype
        self.visible = visible
        self.show_border = show_border
        self.masked_arrays = None
        self.masked_arrays_view_mode = ViewType.raw
        self.creation_view_mode = mode
        self.xray_source = xray_source
        if (
            mode == ViewType.polar and
            HexrdConfig().has_multi_xrs and xray_source is None
        ):
            # The x-ray source is only relevant for polar masks
            self.xray_source = HexrdConfig().active_beam_name
        self.name = name
        if name is None:
            prefix = self.type
            if self.xray_source is not None:
                prefix = f'{self.xray_source}_{prefix}'
            else:
                prefix = f'{mode}_{prefix}'
            # Enforce name uniqueness
            self.name = unique_name(MaskManager().mask_names, f'{prefix}_mask')

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
            mode=data.get('creation_view_mode', None),
            xray_source=data.get('xray_source', None),
        )


class RegionMask(Mask):
    def __init__(
        self,
        name='',
        mtype='',
        visible=True,
        show_border=False,
        mode=None,
        xray_source=None
    ):
        super().__init__(name, mtype, visible, show_border, mode, xray_source)
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
        if (
            self.masked_arrays is None or
            self.masked_arrays_view_mode != image_mode
        ):
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
            'creation_view_mode': self.creation_view_mode,
            'xray_source': self.xray_source,
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
            mode=data.get('creation_view_mode', None),
            xray_source=data.get('xray_source', None),
        )
        raw_data = []
        for det in HexrdConfig().detector_names:
            if det not in data['data'].keys():
                continue
            raw_data.extend([(det, v) for v in data['data'][det].values()])
        new_cls.data = raw_data
        return new_cls


class ThresholdMask(Mask):
    def __init__(
        self,
        name='',
        mtype='',
        visible=True,
        mode=None,
        xray_source=None
    ):
        super().__init__(name, mtype, visible, mode, xray_source)
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
            'creation_view_mode': self.creation_view_mode,
            'xray_source': self.xray_source,
        }

    @classmethod
    def deserialize(cls, data):
        new_cls = cls(
            name=data['name'],
            mtype=data['mtype'],
            visible=data.get('visible', True),
            mode=data.get('creation_view_mode', None),
            xray_source=data.get('xray_source', None),
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
        self.view_mode = None
        self.boundary_color = '#000'  # Default to black
        self.boundary_style = 'dashed'
        self.boundary_width = 1
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
        HexrdConfig().active_beam_switched.connect(
            self.update_masks_for_active_beam)

    def update_masks_for_active_beam(self):
        xrs = HexrdConfig().active_beam_name
        for mask in self.masks.values():
            # If mask's mode or source doesn't match current, hide it
            if (
                mask.creation_view_mode == ViewType.polar and
                mask.xray_source != xrs
            ):
                if not hasattr(mask, '_original_visible'):
                    # Remember original states so we can toggle back
                    mask._original_visible = mask.visible
                    mask._original_show_border = mask.show_border
                self.update_mask_visibility(mask.name, False)
                self.update_border_visibility(mask.name, False)
            else:
                # Restore original states if they exist
                if hasattr(mask, '_original_visible'):
                    self.update_mask_visibility(
                        mask.name, mask._original_visible)
                    self.update_border_visibility(
                        mask.name, mask._original_show_border)
                    # Clear the stored states
                    delattr(mask, '_original_visible')
                    delattr(mask, '_original_show_border')
        self.mask_mgr_dialog_update.emit()
        self.masks_changed()

    def view_mode_changed(self, mode):
        self.view_mode = mode
        self.update_masks_for_active_beam()

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

    def add_mask(self, data, mtype, name=None, visible=True):
        if mtype == MaskType.threshold:
            new_mask = ThresholdMask(name, mtype, visible)
        else:
            mode = None if mtype == MaskType.pinhole else self.view_mode
            new_mask = RegionMask(name, mtype, visible, mode=mode)
        new_mask.data = data
        self.masks[new_mask.name] = new_mask
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
            '__boundary_color': self.boundary_color,
            '__boundary_style': self.boundary_style,
            '__boundary_width': self.boundary_width,
        }
        self.export_masks_to_file.emit(d)

    def write_masks(self, h5py_group=None):
        d = {
            '__boundary_color': self.boundary_color,
            '__boundary_style': self.boundary_style,
            '__boundary_width': self.boundary_width,
        }
        for name, mask_info in self.masks.items():
            d[name] = mask_info.serialize()
        if h5py_group:
            self.write_masks_to_group(d, h5py_group)
        else:
            self.export_masks_to_file.emit(d)

    def save_state(self, h5py_group):
        if 'masks' not in h5py_group:
            h5py_group.create_group('masks')

        self.write_masks(h5py_group['masks'])

    def load_masks(self, h5py_group):
        items = load_masks(h5py_group)
        actual_view_mode = self.view_mode
        self.view_mode = ViewType.raw
        for key, data in items.items():
            if key.startswith('__boundary_'):
                setattr(self, key.split('__', 1)[1], data)
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
        if self.view_mode is None:
            self.view_mode_changed(ViewType.raw)
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
                [-math.inf, math.inf], MaskType.threshold, name='threshold')
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
                # NOTE: The `logical_and` and `logical_or` here are being
                # applied to the *masks*, not the un-masked regions. This is
                # why they are inverted.
                if selection == 'Union of panel buffer and current masks':
                    mask = np.logical_and(mask, buffer_value)
                elif selection == 'Intersection of panel buffer and current masks':
                    mask = np.logical_or(mask, buffer_value)
            detector_config['buffer'] = mask

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
