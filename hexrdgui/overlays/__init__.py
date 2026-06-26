from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hexrd.instrument import HEDMInstrument

from hexrdgui.constants import OverlayType

from . import compatibility
from .const_chi_overlay import ConstChiOverlay
from .laue_overlay import LaueOverlay
from .overlay import Overlay
from .powder_overlay import PowderOverlay
from .rotation_series_overlay import RotationSeriesOverlay

type_dict = {
    OverlayType.const_chi: ConstChiOverlay,
    OverlayType.laue: LaueOverlay,
    OverlayType.powder: PowderOverlay,
    OverlayType.rotation_series: RotationSeriesOverlay,
}


def create_overlay(material_name: str, type: Any, **kwargs: Any) -> Any:
    if type not in type_dict:
        raise Exception(f'Unknown overlay type: {type}')

    return type_dict[type](material_name, **kwargs)


def to_dict(overlay: Any) -> dict:
    # Route the call through the compatibilty module to take care
    # of versioning.
    return compatibility.to_dict(overlay)


def from_dict(d: Any) -> Any:
    type = OverlayType(d.pop('type'))
    if type not in type_dict:
        raise Exception(f'Unknown overlay type: {type}')

    cls = type_dict[type]
    # Route the call through the compatibilty module to take care
    # of versioning.
    return compatibility.from_dict(cls, d)


def overlays_with_custom_energy(overlays: Any) -> list:
    """Return powder overlays that are visualizing at a custom beam energy."""
    return [
        o for o in overlays
        if isinstance(o, PowderOverlay) and o.has_custom_energy
    ]


def reject_overlays_with_custom_energy(
    overlays: Any,
    operation: str = 'This operation',
) -> None:
    """Raise if any of the overlays use a custom beam energy.

    Custom beam energies are a visualization-only feature (for example, to
    check for harmonics), so analysis routines must refuse them rather than
    silently produce incorrect results.
    """
    bad = overlays_with_custom_energy(overlays)
    if not bad:
        return

    names = ', '.join(o.name for o in bad)
    raise Exception(
        f'{operation} does not support powder overlays with a custom beam '
        f'energy.\n\nThe following overlays use a custom energy: {names}.\n\n'
        'Re-check "Use energy from instrument?" for these overlays before '
        'continuing.'
    )


def update_overlay_data(instr: HEDMInstrument, display_mode: Any) -> None:
    from hexrdgui.hexrd_config import HexrdConfig

    def flag_update(overlay: Any) -> None:
        overlay.instrument = instr
        overlay.display_mode = display_mode
        overlay.update_needed = True

    # First, if there is a polar tth distortion overlay, make sure
    # that is flagged for updating.
    # Even if this isn't visible, we must update it if it is using to
    # compute the distortion.
    overlay = HexrdConfig().polar_tth_distortion_overlay
    if overlay:
        flag_update(overlay)

    if not HexrdConfig().show_overlays:
        # Nothing to do
        return

    for overlay in HexrdConfig().overlays:
        if not overlay.visible:
            # Skip over invisible overlays
            continue

        flag_update(overlay)


__all__ = [
    'ConstChiOverlay',
    'LaueOverlay',
    'Overlay',
    'PowderOverlay',
    'RotationSeriesOverlay',
    'overlays_with_custom_energy',
    'reject_overlays_with_custom_energy',
]
