from __future__ import annotations

from typing import Any

import numpy as np

from hexrdgui.overlays.powder_overlay import PowderOverlay


class _DiffractionAnglePlaneData:
    tThWidth = None

    def __init__(self, tth_values: np.ndarray) -> None:
        self._tth_values = tth_values

    def getTTh(self) -> np.ndarray:
        return np.radians(self._tth_values)

    def getHKLs(self) -> np.ndarray:
        # PowderOverlay keeps one HKL entry per ring. These contours have no
        # HKLs, but placeholder entries keep that one-to-one correspondence.
        return np.zeros((len(self._tth_values), 3), dtype=int)


class DiffractionAngleOverlay(PowderOverlay):
    """A powder-style overlay generated from explicit two-theta values."""

    def __init__(
        self,
        tth_start: float = 10.0,
        tth_max: float = 70.0,
        tth_step: float = 10.0,
        style: dict[str, Any] | None = None,
    ) -> None:
        self.tth_start = tth_start
        self.tth_max = tth_max
        self.tth_step = tth_step
        super().__init__(
            'Diffraction Angle Contour',
            name='Diffraction Angle Contour',
            style=style,
        )

    @property
    def material(self) -> None:
        return None

    @property
    def xray_source(self) -> str | None:
        # Unlike a material overlay, the contour follows whichever source is
        # active because its angles are not tied to a wavelength.
        from hexrdgui.hexrd_config import HexrdConfig

        return HexrdConfig().active_beam_name

    @xray_source.setter
    def xray_source(self, _value: str | None) -> None:
        pass

    @property
    def plane_data(self) -> _DiffractionAnglePlaneData:
        return _DiffractionAnglePlaneData(self.tth_values)

    @property
    def tth_values(self) -> np.ndarray:
        """Return requested values, including the maximum exactly once."""
        values = np.arange(self.tth_start, self.tth_max, self.tth_step)
        values = values[~np.isclose(values, self.tth_max)]
        return np.append(values, self.tth_max)

    @property
    def has_widths(self) -> bool:
        return False

    def generate_hkl_means(self, point_groups: dict) -> None:
        # These contours do not represent reflections and therefore should
        # not be added to the azimuthal powder lineout.
        self.hkl_means = {}
