from __future__ import annotations

import math
import numpy as np

from PySide6.QtCore import Signal, QObject
from hexrdgui import utils

from hexrdgui.constants import ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.masking.constants import CURRENT_MASK_VERSION, MaskType
from hexrdgui.masking.create_polar_mask import (
    create_polar_mask_from_raw,
    rebuild_polar_masks,
)
from hexrdgui.masking.create_raw_mask import (
    recompute_raw_threshold_mask,
    create_raw_mask,
    rebuild_raw_masks,
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.mask_compatibility import load_masks
from hexrdgui.singletons import QSingleton
from hexrdgui.utils import unique_name

from hexrd.instrument import unwrap_dict_to_h5
from hexrd.utils.panel_buffer import panel_buffer_from_str

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import h5py
    from hexrd.instrument import HEDMInstrument


class Mask(ABC):
    # Type hint for dynamically-set attributes used in update_masks_for_active_beam
    _original_visible: bool
    _original_show_border: bool

    def __init__(
        self,
        name: str | None = None,
        mtype: str = '',
        visible: bool = True,
        show_border: bool = False,
        mode: str | None = None,
        xray_source: str | None = None,
        highlight: bool = False,
    ) -> None:
        self.type = mtype
        self.visible = visible
        self.show_border = show_border
        self._highlight = highlight
        self.masked_arrays: Any = None
        self.masked_arrays_view_mode = ViewType.raw
        self.creation_view_mode = mode
        self.xray_source = xray_source
        if (
            mode == ViewType.polar
            and HexrdConfig().has_multi_xrs
            and xray_source is None
        ):
            # The x-ray source is only relevant for polar masks
            self.xray_source = HexrdConfig().active_beam_name
        self.name: str | None = name
        if name is None:
            prefix = self.type
            if self.xray_source is not None:
                prefix = f'{self.xray_source}_{prefix}'
            else:
                prefix = f'{mode}_{prefix}'
            # Enforce name uniqueness
            self.name = unique_name(MaskManager().mask_names, f'{prefix}_mask')

    def get_masked_arrays(self) -> Any:
        if self.masked_arrays is None:
            self.update_masked_arrays()

        return self.masked_arrays

    def invalidate_masked_arrays(self) -> None:
        self.masked_arrays = None

    def update_border_visibility(self, visibility: bool) -> None:
        self.show_border = visibility

    # Abstract methods
    @property
    @abstractmethod
    def data(self) -> Any:
        pass

    @data.setter
    @abstractmethod
    def data(self, values: Any) -> None:
        pass

    @abstractmethod
    def update_masked_arrays(self) -> None:
        pass

    @abstractmethod
    def serialize(self) -> dict[str, Any]:
        pass

    @property
    @abstractmethod
    def highlight(self) -> bool:
        pass

    @highlight.setter
    @abstractmethod
    def highlight(self, value: bool) -> None:
        pass

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> 'Mask':
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
        name: str = '',
        mtype: str = '',
        visible: bool = True,
        show_border: bool = False,
        mode: str | None = None,
        xray_source: str | None = None,
        highlight: bool = False,
    ) -> None:
        super().__init__(
            name, mtype, visible, show_border, mode, xray_source, highlight
        )
        self._raw: list[tuple[str, np.ndarray]] | None = None

    @property
    def data(self) -> Any:
        return self._raw

    @data.setter
    def data(self, values: Any) -> None:
        self._raw = values
        self.invalidate_masked_arrays()

    @property
    def highlight(self) -> bool:
        return self._highlight

    @highlight.setter
    def highlight(self, value: bool) -> None:
        if self.type == MaskType.powder:
            return
        self._highlight = value

    def update_masked_arrays(
        self, view: str = ViewType.raw, instr: HEDMInstrument | None = None
    ) -> None:
        self.masked_arrays_view_mode = view
        assert self._raw is not None
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

    def get_masked_arrays(
        self,
        image_mode: str = ViewType.raw,
        instr: HEDMInstrument | None = None,
    ) -> Any:
        if self.masked_arrays is None or self.masked_arrays_view_mode != image_mode:
            self.update_masked_arrays(image_mode, instr)

        return self.masked_arrays

    def update_border_visibility(self, visibility: bool) -> None:
        can_have_border = [MaskType.region, MaskType.polygon, MaskType.pinhole]
        if self.type not in can_have_border:
            # Only rectangle, ellipse and hand-drawn masks can show borders
            visibility = False
        self.show_border = visibility

    def serialize(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            'name': self.name,
            'mtype': self.type,
            'visible': self.visible,
            'border': self.show_border,
            'creation_view_mode': self.creation_view_mode,
            'xray_source': self.xray_source,
            'data': {},
        }
        for i, (det, values) in enumerate(self._raw or []):
            data['data'].setdefault(det, {})[str(i)] = values
        return data

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> 'RegionMask':
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
        name: str | None = None,
        mtype: str = '',
        visible: bool = True,
        mode: str | None = None,
        xray_source: str | None = None,
    ) -> None:
        super().__init__(name, mtype, visible, mode=mode, xray_source=xray_source)
        self.min_val = -math.inf
        self.max_val = math.inf

    @property
    def data(self) -> list[float]:
        return [self.min_val, self.max_val]

    @data.setter
    def data(self, values: list[float]) -> None:
        self.min_val = values[0]
        self.max_val = values[1]
        self.invalidate_masked_arrays()

    @property
    def highlight(self) -> bool:
        return False

    @highlight.setter
    def highlight(self, value: bool) -> None:
        # Threshold masks do not support highlight; ignore assignments
        pass

    def update_masked_arrays(self, view: str = ViewType.raw) -> None:
        self.masked_arrays = recompute_raw_threshold_mask()

    def update_border_visibility(self, visibility: bool) -> None:
        # Cannot show borders for threshold
        self.show_border = False

    def serialize(self) -> dict[str, Any]:
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
    def deserialize(cls, data: dict[str, Any]) -> 'ThresholdMask':
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

    """Emitted when mask highlight states change"""
    mask_highlights_changed = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.masks: dict[str, Mask] = {}
        self.view_mode: str | None = None
        self.boundary_color = '#000'  # Default to black
        self.highlight_color = '#FF0'  # Default to yellow
        self.highlight_opacity = 0.5
        self.boundary_style = 'dashed'
        self.boundary_width = 1
        self.setup_connections()

    @property
    def visible_masks(self) -> list[str]:
        return [k for k, v in self.masks.items() if v.visible]

    @property
    def visible_boundaries(self) -> list[str]:
        return [k for k, v in self.masks.items() if v.show_border]

    @property
    def visible_highlights(self) -> list[str]:
        return [k for k, v in self.masks.items() if v.highlight]

    @property
    def threshold_mask(self) -> Mask | None:
        for mask in self.masks.values():
            if mask.type == MaskType.threshold:
                return mask
        return None

    @property
    def mask_names(self) -> list[str]:
        return list(self.masks.keys())

    def invalidate_detector_masks(self, det_keys: list[str]) -> None:
        for mask in self.masks.values():
            if any(v[0] in det_keys for v in mask.data):
                mask.invalidate_masked_arrays()

    def setup_connections(self) -> None:
        self.threshold_mask_changed.connect(self.threshold_toggled)
        HexrdConfig().save_state.connect(self.save_state)
        HexrdConfig().load_state.connect(self.load_state)
        HexrdConfig().detectors_changed.connect(self.clear_all)
        HexrdConfig().state_loaded.connect(self.rebuild_masks)
        HexrdConfig().active_beam_switched.connect(self.update_masks_for_active_beam)

    def update_masks_for_active_beam(self) -> None:
        if self.view_mode != ViewType.polar:
            return

        xrs = HexrdConfig().active_beam_name
        for mask in self.masks.values():
            # If mask's mode or source doesn't match current, hide it
            if mask.creation_view_mode == ViewType.polar and mask.xray_source != xrs:
                if not hasattr(mask, '_original_visible'):
                    # Remember original states so we can toggle back
                    mask._original_visible = mask.visible
                    mask._original_show_border = mask.show_border
                if mask.name is not None:
                    self.update_mask_visibility(mask.name, False)
                    self.update_border_visibility(mask.name, False)
            else:
                # Restore original states if they exist
                if hasattr(mask, '_original_visible') and mask.name is not None:
                    self.update_mask_visibility(mask.name, mask._original_visible)
                    self.update_border_visibility(mask.name, mask._original_show_border)
                    # Clear the stored states
                    delattr(mask, '_original_visible')
                    delattr(mask, '_original_show_border')
        self.mask_mgr_dialog_update.emit()
        self.masks_changed()

    def view_mode_changed(self, mode: str) -> None:
        self.view_mode = mode
        self.update_masks_for_active_beam()

    def highlights_changed(self) -> None:
        self.mask_highlights_changed.emit()

    def masks_changed(self) -> None:
        if self.view_mode in (ViewType.polar, ViewType.stereo):
            self.polar_masks_changed.emit()
        elif self.view_mode == ViewType.raw:
            self.raw_masks_changed.emit()

    def rebuild_masks(self) -> None:
        if self.view_mode == ViewType.raw:
            rebuild_raw_masks()
        elif self.view_mode in (ViewType.polar, ViewType.stereo):
            rebuild_polar_masks()
        self.masks_changed()
        self.mask_mgr_dialog_update.emit()

    def add_mask(
        self,
        data: Any,
        mtype: str,
        name: str | None = None,
        visible: bool = True,
    ) -> Mask:
        new_mask: Mask
        if mtype == MaskType.threshold:
            new_mask = ThresholdMask(name, mtype, visible)
        else:
            mode = None if mtype == MaskType.pinhole else self.view_mode
            new_mask = RegionMask(name or '', mtype, visible, mode=mode)
        new_mask.data = data
        assert new_mask.name is not None
        self.masks[new_mask.name] = new_mask
        self.mask_mgr_dialog_update.emit()
        return new_mask

    def remove_mask(self, name: str) -> Mask:
        removed_mask = self.masks.pop(name)
        self.mask_mgr_dialog_update.emit()
        return removed_mask

    def write_masks_to_group(
        self, data: dict[str, Any], h5py_group: h5py.Group
    ) -> None:
        h5py_group.attrs['_version'] = CURRENT_MASK_VERSION
        unwrap_dict_to_h5(h5py_group, data, asattr=False)

    def write_single_mask(self, name: str) -> None:
        d = {
            name: self.masks[name].serialize(),
            '__boundary_color': self.boundary_color,
            '__boundary_style': self.boundary_style,
            '__boundary_width': self.boundary_width,
            '__highlight_color': self.highlight_color,
            '__highlight_opacity': self.highlight_opacity,
        }
        self.export_masks_to_file.emit(d)

    def write_masks(self, h5py_group: h5py.Group | None = None) -> None:
        d: dict[str, Any] = {
            '__boundary_color': self.boundary_color,
            '__boundary_style': self.boundary_style,
            '__boundary_width': self.boundary_width,
            '__highlight_color': self.highlight_color,
            '__highlight_opacity': self.highlight_opacity,
        }
        for name, mask_info in self.masks.items():
            d[name] = mask_info.serialize()
        if h5py_group:
            self.write_masks_to_group(d, h5py_group)
        else:
            self.export_masks_to_file.emit(d)

    def save_state(self, h5py_group: h5py.Group) -> None:
        if 'masks' not in h5py_group:
            h5py_group.create_group('masks')

        self.write_masks(h5py_group['masks'])

    def load_masks(self, h5py_group: h5py.Group) -> None:
        items = load_masks(h5py_group)
        actual_view_mode = self.view_mode
        self.view_mode = ViewType.raw
        for key, data in items.items():
            if key.startswith('__'):
                setattr(self, key.split('__', 1)[1], data)
                continue
            elif data['mtype'] == MaskType.threshold:
                new_mask: Mask = ThresholdMask.deserialize(data)
            else:
                new_mask = RegionMask.deserialize(data)

            self.masks[key] = new_mask

        if not HexrdConfig().loading_state:
            # We're importing masks directly,
            # don't wait for the state loaded signal
            self.rebuild_masks()
        self.view_mode = actual_view_mode

    def load_state(self, h5py_group: h5py.Group) -> None:
        self.masks = {}
        if 'masks' in h5py_group:
            self.load_masks(h5py_group['masks'])
        if self.view_mode is None:
            self.view_mode_changed(ViewType.raw)
        self.mask_mgr_dialog_update.emit()

    def update_view_mode(self, mode: str) -> None:
        self.view_mode = mode

    def update_mask_visibility(self, name: str, visibility: bool) -> None:
        self.masks[name].visible = visibility

    def update_border_visibility(self, name: str, visibility: bool) -> None:
        self.masks[name].update_border_visibility(visibility)

    @property
    def contains_border_only_masks(self) -> bool:
        # If we have any border-only masks, that means the display images
        # are different from computed images, and require extra computation.
        # If this returns False, we can skip that extra computation and
        # set display images and computed images to be the same.
        return any(x.show_border and not x.visible for x in self.masks.values())

    def threshold_toggled(self) -> None:
        threshold = self.threshold_mask
        if threshold is not None:
            assert threshold.name is not None
            self.remove_mask(threshold.name)
        else:
            self.add_mask([-math.inf, math.inf], MaskType.threshold, name='threshold')
        self.mask_mgr_dialog_update.emit()

    def update_name(self, old_name: str, new_name: str) -> None:
        mask = self.remove_mask(old_name)
        mask.name = new_name
        self.masks[new_name] = mask

    def masks_to_panel_buffer(self, selection: str) -> None:
        # Set the visible masks as the panel buffer(s)
        # We must ensure that we are using raw masks
        instr = None
        for det, mask in HexrdConfig().raw_masks_dict.items():
            detector_config = HexrdConfig().detector(det)
            buffer_value = detector_config.get('buffer', None)
            if isinstance(buffer_value, str):
                # Convert to an array
                if instr is None:
                    instr = create_hedm_instrument()

                panel = instr.detectors[det]
                buffer_value = panel_buffer_from_str(buffer_value, panel)

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

    def clear_all(self) -> None:
        self.masks.clear()

    def apply_masks_to_panel_buffers(self, instr: HEDMInstrument) -> None:
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

    def get_mask_by_name(self, name: str) -> Mask:
        return self.masks[name]
