import copy

from hexrd.ui.overlays.laue_diffraction import LaueSpotOverlay
from hexrd.ui.overlays.mono_rotation_series import (
    MonoRotationSeriesSpotOverlay
)
from hexrd.ui.overlays.powder_diffraction import PowderLineOverlay

from hexrd.ui import constants


def overlay_generator(overlay_type):
    generators = {
        'powder': PowderLineOverlay,
        'laue': LaueSpotOverlay,
        'mono_rotation_series': MonoRotationSeriesSpotOverlay
    }

    if overlay_type not in generators:
        raise Exception(f'Unknown overlay type: {overlay_type}')

    return generators[overlay_type]


def default_overlay_style(overlay_type):
    default_styles = {
        'powder': constants.DEFAULT_POWDER_STYLE,
        'laue': constants.DEFAULT_LAUE_STYLE,
        'mono_rotation_series': constants.DEFAULT_MONO_ROTATION_SERIES_STYLE
    }

    if overlay_type not in default_styles:
        raise Exception(f'Unknown overlay type: {overlay_type}')

    return copy.deepcopy(default_styles[overlay_type])
