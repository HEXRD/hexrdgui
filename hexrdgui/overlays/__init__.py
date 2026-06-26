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
    return [o for o in overlays if isinstance(o, PowderOverlay) and o.has_custom_energy]


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


# Distinct (ring, range) color pairs cycled across powder overlays so that
# multiple overlays are easy to tell apart. The first pair matches the
# historical default (cyan rings, green ranges).
POWDER_OVERLAY_COLOR_CYCLE = [
    ('#00ffff', '#00ff00'),  # cyan / green
    ('#ff7f0e', '#ffbb78'),  # orange / light orange
    ('#1f77b4', '#aec7e8'),  # blue / light blue
    ('#d62728', '#ff9896'),  # red / light red
    ('#9467bd', '#c5b0d5'),  # purple / light purple
    ('#8c564b', '#c49c94'),  # brown / light brown
]


def assign_cycled_style(overlay: Any, existing_overlays: Any) -> None:
    """Give a newly-created powder overlay a distinct color pair.

    Picks the least-used (ring, range) color pair among the existing powder
    overlays, so multiple overlays are easy to tell apart. This is a no-op
    for other overlay types.
    """
    if not isinstance(overlay, PowderOverlay):
        return

    used = [
        (o.style['data']['c'], o.style['ranges']['c'])
        for o in existing_overlays
        if isinstance(o, PowderOverlay)
    ]
    counts = [used.count(pair) for pair in POWDER_OVERLAY_COLOR_CYCLE]
    ring_color, range_color = POWDER_OVERLAY_COLOR_CYCLE[counts.index(min(counts))]

    overlay.style['data']['c'] = ring_color
    overlay.style['ranges']['c'] = range_color


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
    'assign_cycled_style',
]
