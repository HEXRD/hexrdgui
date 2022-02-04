from hexrd.ui.constants import OverlayType

from . import compatibility
from .laue_overlay import LaueOverlay
from .overlay import Overlay
from .powder_overlay import PowderOverlay
from .rotation_series_overlay import RotationSeriesOverlay

type_dict = {
    OverlayType.laue: LaueOverlay,
    OverlayType.powder: PowderOverlay,
    OverlayType.rotation_series: RotationSeriesOverlay,
}


def create_overlay(material_name, type, **kwargs):
    if type not in type_dict:
        raise Exception(f'Unknown overlay type: {type}')

    return type_dict[type](material_name, **kwargs)


def to_dict(overlay):
    # Route the call through the compatibilty module to take care
    # of versioning.
    return compatibility.to_dict(overlay)


def from_dict(d):
    type = OverlayType(d.pop('type'))
    if type not in type_dict:
        raise Exception(f'Unknown overlay type: {type}')

    cls = type_dict[type]
    # Route the call through the compatibilty module to take care
    # of versioning.
    return compatibility.from_dict(cls, d)


def update_overlay_data(instr, display_mode):
    from hexrd.ui.hexrd_config import HexrdConfig

    if not HexrdConfig().show_overlays:
        # Nothing to do
        return

    for overlay in HexrdConfig().overlays:
        if not overlay.visible:
            # Skip over invisible overlays
            continue

        overlay.instrument = instr
        overlay.display_mode = display_mode
        overlay.update_needed = True


__all__ = [
    'LaueOverlay',
    'Overlay',
    'PowderOverlay',
    'RotationSeriesOverlay',
]
