from __future__ import annotations

from abc import ABC, abstractmethod
import copy
from typing import TYPE_CHECKING, Any

import numpy as np

from hexrdgui.constants import OverlayType, ViewType
from hexrdgui.utils import array_index_in_list

if TYPE_CHECKING:
    from hexrd.material import Material
    from hexrd.material import PlaneData


class Overlay(ABC):

    # Abstract methods
    @property
    @abstractmethod
    def type(self) -> OverlayType:
        pass

    @property
    @abstractmethod
    def child_attributes_to_save(self) -> list[str]:
        pass

    @abstractmethod
    def generate_overlay(self) -> dict[str, Any]:
        pass

    @property
    @abstractmethod
    def has_widths(self) -> bool:
        pass

    @property
    @abstractmethod
    def refinement_labels(self) -> list[str]:
        pass

    @property
    @abstractmethod
    def default_refinements(self) -> list[bool] | np.ndarray:
        pass

    @property
    @abstractmethod
    def default_style(self) -> dict[str, Any]:
        pass

    @property
    @abstractmethod
    def default_highlight_style(self) -> dict[str, Any]:
        pass

    @property
    @abstractmethod
    def has_picks_data(self) -> bool:
        pass

    @property
    @abstractmethod
    def calibration_picks_polar(self) -> dict[str, Any] | list[Any]:
        pass

    @calibration_picks_polar.setter
    @abstractmethod
    def calibration_picks_polar(self, picks: dict[str, Any] | list[Any]) -> None:
        pass

    @property
    @abstractmethod
    def data_key(self) -> str | None:
        pass

    @property
    @abstractmethod
    def ranges_key(self) -> str | None:
        pass

    # Concrete methods
    data_key = None  # type: ignore[assignment]  # noqa: F811
    ranges_key = None  # type: ignore[assignment]  # noqa: F811
    ranges_indices_key: str | None = None

    def __init__(
        self,
        material_name: str,
        name: str | None = None,
        refinements: list[bool] | np.ndarray | None = None,
        calibration_picks: dict[str, Any] | None = None,
        xray_source: str | None = None,
        style: dict[str, Any] | None = None,
        highlight_style: dict[str, Any] | None = None,
        visible: bool = True,
    ) -> None:

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
        self._data: dict[str, Any] = {}
        self._highlights: list[Any] = []
        self.instrument = None
        self.update_needed = True

        self.setup_connections()

    def setup_connections(self) -> None:
        from hexrdgui.image_load_manager import ImageLoadManager

        ImageLoadManager().new_images_loaded.connect(self.on_new_images_loaded)

    @property
    def plot_data_keys(self) -> tuple[str, ...]:
        # These are the data keys that are intended to be plotted.
        # This will be used to perform any needed transforms (such as
        # converting to/from stitched coordinates for ROI instruments).
        keys = (
            self.data_key,
            self.ranges_key,
        )
        return tuple(x for x in keys if x is not None)

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.attributes_to_save}
        d['type'] = self.type.value
        return d

    @property
    def attributes_to_save(self) -> list[str]:
        return self.base_attributes_to_save + self.child_attributes_to_save

    @property
    def base_attributes_to_save(self) -> list[str]:
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
    def _non_unique_name(self) -> str:
        return f'{self.material_name} {self.type.value}'

    def _generate_unique_name(self) -> str:
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
    def from_name(name: str) -> 'Overlay':
        from hexrdgui.hexrd_config import HexrdConfig

        for overlay in HexrdConfig().overlays:
            if overlay.name == name:
                return overlay

        raise Exception(f'{name=} was not found in overlays!')

    @property
    def material_name(self) -> str:
        return self._material_name

    @material_name.setter
    def material_name(self, v: str) -> None:
        if self.material_name == v:
            return

        need_rename = self.name.startswith(self._non_unique_name)

        self._material_name = v
        self.update_needed = True

        if need_rename:
            # Update the name to reflect the new material
            self.name = self._generate_unique_name()

    @property
    def material(self) -> Material:
        from hexrdgui.hexrd_config import HexrdConfig

        return HexrdConfig().material(self.material_name)

    @property
    def plane_data(self) -> PlaneData:
        return self.material.planeData

    @property
    def eta_period(self) -> np.ndarray:
        from hexrdgui.hexrd_config import HexrdConfig

        return HexrdConfig().polar_res_eta_period

    @property
    def style(self) -> dict[str, Any]:
        return self._style

    @style.setter
    def style(self, v: dict[str, Any]) -> None:
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
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, v: bool) -> None:
        if self.visible == v:
            return

        self._visible = v
        self.update_needed = True

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @display_mode.setter
    def display_mode(self, v: str) -> None:
        if self.display_mode == v:
            return

        self._display_mode = v
        self.update_needed = True

    @property
    def instrument(self) -> Any:
        return self._instrument

    @instrument.setter
    def instrument(self, v: Any) -> None:
        self._instrument = v
        self.update_needed = True

    @property
    def refinements(self) -> np.ndarray:
        return self._refinements

    @refinements.setter
    def refinements(self, v: list[bool] | np.ndarray) -> None:
        self._refinements = np.asarray(v)

    @property
    def refinements_with_labels(self) -> list[tuple[str, bool]]:
        ret = []
        for label, refine in zip(self.refinement_labels, self.refinements):
            ret.append((label, refine))
        return ret

    @property
    def hkls(self) -> dict[str, list[Any]]:
        return {
            key: np.array(val.get('hkls', [])).tolist()
            for key, val in self.data.items()
        }

    @property
    def data(self) -> dict[str, Any]:
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
    def highlights(self) -> list[Any]:
        return self._highlights

    @highlights.setter
    def highlights(self, v: list[Any]) -> None:
        self._highlights = v

    @property
    def has_highlights(self) -> bool:
        return bool(self.highlights)

    def clear_highlights(self) -> None:
        self._highlights.clear()

    def path_to_hkl_data(self, detector_key: str, hkl: np.ndarray) -> tuple[str, str | None, int]:
        data_key = self.data_key
        detector_data = self.data[detector_key]
        ind = array_index_in_list(hkl, detector_data['hkls'])
        if ind == -1:
            raise Exception(f'Failed to find path to hkl: {hkl}')

        return (detector_key, data_key, ind)

    def highlight_hkl(self, detector_key: str, hkl: np.ndarray) -> None:
        path = self.path_to_hkl_data(detector_key, hkl)
        self.highlights.append(path)

    @property
    def is_powder(self) -> bool:
        return self.type == OverlayType.powder

    @property
    def is_laue(self) -> bool:
        return self.type == OverlayType.laue

    @property
    def is_rotation_series(self) -> bool:
        return self.type == OverlayType.rotation_series

    @property
    def is_const_chi(self) -> bool:
        return self.type == OverlayType.const_chi

    def on_new_images_loaded(self) -> None:
        # Do nothing by default. Subclasses can re-implement.
        pass

    @property
    def calibration_picks(self) -> dict[str, Any]:
        return self._calibration_picks

    @calibration_picks.setter
    def calibration_picks(self, picks: dict[str, Any]) -> None:
        self._validate_picks(picks)

        self.reset_calibration_picks()
        self.calibration_picks.update(picks)

    def _validate_picks(self, picks: dict[str, Any]) -> None:
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

    def reset_calibration_picks(self) -> None:
        # Make an empty list for each detector
        self._calibration_picks.clear()

    def pad_picks_data(self) -> None:
        # Subclasses only need to override this if they actually need it
        pass
