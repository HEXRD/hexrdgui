from abc import ABC, abstractmethod
import copy

import numpy as np

from hexrdgui.constants import OverlayType, ViewType
from hexrdgui.utils import array_index_in_list


class Overlay(ABC):

    # Abstract methods
    @property
    @abstractmethod
    def type(self):
        pass

    @property
    @abstractmethod
    def child_attributes_to_save(self):
        pass

    @abstractmethod
    def generate_overlay(self):
        pass

    @property
    @abstractmethod
    def has_widths(self):
        pass

    @property
    @abstractmethod
    def refinement_labels(self):
        pass

    @property
    @abstractmethod
    def default_refinements(self):
        pass

    @property
    @abstractmethod
    def default_style(self):
        pass

    @property
    @abstractmethod
    def default_highlight_style(self):
        pass

    @property
    @abstractmethod
    def has_picks_data(self):
        pass

    @property
    @abstractmethod
    def calibration_picks_polar(self):
        pass

    @calibration_picks_polar.setter
    @abstractmethod
    def calibration_picks_polar(self, picks):
        pass

    @property
    @abstractmethod
    def data_key(self):
        pass

    @property
    @abstractmethod
    def ranges_key(self):
        pass

    # Concrete methods
    data_key = None
    ranges_key = None
    ranges_indices_key = None

    def __init__(self, material_name, name=None, refinements=None,
                 calibration_picks=None, xray_source=None, style=None,
                 highlight_style=None, visible=True):

        self._material_name = material_name

        if name is None:
            name = self._generate_unique_name()

        if refinements is None:
            refinements = self.default_refinements

        if calibration_picks is None:
            calibration_picks = {}

        if style is None:
            style = self.default_style

        if highlight_style is None:
            highlight_style = self.default_highlight_style

        self.name = name
        self.refinements = refinements
        self._calibration_picks = calibration_picks
        self.xray_source = xray_source
        self.style = style
        self.highlight_style = highlight_style
        self._visible = visible
        self._display_mode = ViewType.raw
        self._data = {}
        self._highlights = []
        self.instrument = None
        self.update_needed = True

        self.setup_connections()

    def setup_connections(self):
        from hexrdgui.image_load_manager import ImageLoadManager

        ImageLoadManager().new_images_loaded.connect(self.on_new_images_loaded)

    @property
    def plot_data_keys(self):
        # These are the data keys that are intended to be plotted.
        # This will be used to perform any needed transforms (such as
        # converting to/from stitched coordinates for ROI instruments).
        keys = (
            self.data_key,
            self.ranges_key,
        )
        return tuple(x for x in keys if x is not None)

    def to_dict(self):
        d = {k: getattr(self, k) for k in self.attributes_to_save}
        d['type'] = self.type.value
        return d

    @property
    def attributes_to_save(self):
        return self.base_attributes_to_save + self.child_attributes_to_save

    @property
    def base_attributes_to_save(self):
        # These names must be identical here, as attributes, and as
        # arguments to the __init__ method.
        return [
            'material_name',
            'name',
            'refinements',
            'calibration_picks',
            'xray_source',
            'style',
            'highlight_style',
            'visible',
        ]

    @property
    def _non_unique_name(self):
        return f'{self.material_name} {self.type.value}'

    def _generate_unique_name(self):
        from hexrdgui.hexrd_config import HexrdConfig

        name = self._non_unique_name
        index = 1
        for overlay in HexrdConfig().overlays:
            if overlay is self:
                break

            if overlay._non_unique_name == name:
                index += 1

        if index > 1:
            name = f'{name} {index}'

        return name

    @staticmethod
    def from_name(name):
        from hexrdgui.hexrd_config import HexrdConfig

        for overlay in HexrdConfig().overlays:
            if overlay.name == name:
                return overlay

        raise Exception(f'{name=} was not found in overlays!')

    @property
    def material_name(self):
        return self._material_name

    @material_name.setter
    def material_name(self, v):
        if self.material_name == v:
            return

        need_rename = self.name.startswith(self._non_unique_name)

        self._material_name = v
        self.update_needed = True

        if need_rename:
            # Update the name to reflect the new material
            self.name = self._generate_unique_name()

    @property
    def material(self):
        from hexrdgui.hexrd_config import HexrdConfig
        return HexrdConfig().material(self.material_name)

    @property
    def plane_data(self):
        return self.material.planeData

    @property
    def eta_period(self):
        from hexrdgui.hexrd_config import HexrdConfig
        return HexrdConfig().polar_res_eta_period

    @property
    def style(self):
        return self._style

    @style.setter
    def style(self, v):
        if hasattr(self, '_style') and self.style == v:
            return

        # Ensure it has all keys
        v = copy.deepcopy(v)
        for key in self.default_style:
            if key not in v:
                v[key] = self.default_style[key]

        self._style = v
        self.update_needed = True

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, v):
        if self.visible == v:
            return

        self._visible = v
        self.update_needed = True

    @property
    def display_mode(self):
        return self._display_mode

    @display_mode.setter
    def display_mode(self, v):
        if self.display_mode == v:
            return

        self._display_mode = v
        self.update_needed = True

    @property
    def instrument(self):
        return self._instrument

    @instrument.setter
    def instrument(self, v):
        self._instrument = v
        self.update_needed = True

    @property
    def refinements(self):
        return self._refinements

    @refinements.setter
    def refinements(self, v):
        self._refinements = np.asarray(v)

    @property
    def refinements_with_labels(self):
        ret = []
        for label, refine in zip(self.refinement_labels, self.refinements):
            ret.append((label, refine))
        return ret

    @property
    def hkls(self):
        return {
            key: np.array(val.get('hkls', [])).tolist()
            for key, val in self.data.items()
        }

    @property
    def data(self):
        if self.update_needed:
            if self.instrument is None or self.display_mode is None:
                # Cannot generate data. Raise an exception.
                msg = (
                    'Instrument and display mode must be set before '
                    'generating new data'
                )
                raise Exception(msg)

            # We are identifying this dict by its id() in the image_canvas.
            # Because of this, make sure we use the same dict so that we
            # do not change ids.
            self._data.clear()
            self._data |= self.generate_overlay()
            self.update_needed = False
        return self._data

    @property
    def highlights(self):
        return self._highlights

    @highlights.setter
    def highlights(self, v):
        self._highlights = v

    @property
    def has_highlights(self):
        return bool(self.highlights)

    def clear_highlights(self):
        self._highlights.clear()

    def path_to_hkl_data(self, detector_key, hkl):
        data_key = self.data_key
        detector_data = self.data[detector_key]
        ind = array_index_in_list(hkl, detector_data['hkls'])
        if ind == -1:
            raise Exception(f'Failed to find path to hkl: {hkl}')

        return (detector_key, data_key, ind)

    def highlight_hkl(self, detector_key, hkl):
        path = self.path_to_hkl_data(detector_key, hkl)
        self.highlights.append(path)

    @property
    def is_powder(self):
        return self.type == OverlayType.powder

    @property
    def is_laue(self):
        return self.type == OverlayType.laue

    @property
    def is_rotation_series(self):
        return self.type == OverlayType.rotation_series

    @property
    def is_const_chi(self):
        return self.type == OverlayType.const_chi

    def on_new_images_loaded(self):
        # Do nothing by default. Subclasses can re-implement.
        pass

    @property
    def calibration_picks(self):
        return self._calibration_picks

    @calibration_picks.setter
    def calibration_picks(self, picks):
        self._validate_picks(picks)

        self.reset_calibration_picks()
        self.calibration_picks.update(picks)

    def _validate_picks(self, picks):
        if self.display_mode != ViewType.cartesian:
            # In Cartesian mode, a fake instrument is used, and thus
            # we cannot validate the picks keys as easily.
            for k in picks:
                if k not in self.data:
                    msg = (
                        f'Keys in picks "{list(picks.keys())}" do not match '
                        f'keys in data "{list(self.data.keys())}"'
                    )
                    raise Exception(msg)

    def reset_calibration_picks(self):
        # Make an empty list for each detector
        self._calibration_picks.clear()

    def pad_picks_data(self):
        # Subclasses only need to override this if they actually need it
        pass
