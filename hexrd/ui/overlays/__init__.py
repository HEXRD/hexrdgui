import copy

from hexrd import unitcell

from hexrd.ui.overlays.laue_diffraction import LaueSpotOverlay
from hexrd.ui.overlays.mono_rotation_series import (
    MonoRotationSeriesSpotOverlay
)
from hexrd.ui.overlays.powder_diffraction import PowderLineOverlay

from hexrd.ui import constants
from hexrd.ui.constants import OverlayType


def overlay_generator(overlay_type):
    generators = {
        OverlayType.powder: PowderLineOverlay,
        OverlayType.laue: LaueSpotOverlay,
        OverlayType.mono_rotation_series: MonoRotationSeriesSpotOverlay
    }

    if overlay_type not in generators:
        raise Exception(f'Unknown overlay type: {overlay_type}')

    return generators[overlay_type]


def default_overlay_style(overlay_type):
    default_styles = {
        OverlayType.powder: constants.DEFAULT_POWDER_STYLE,
        OverlayType.laue: constants.DEFAULT_LAUE_STYLE,
        OverlayType.mono_rotation_series: (
            constants.DEFAULT_MONO_ROTATION_SERIES_STYLE)
    }

    if overlay_type not in default_styles:
        raise Exception(f'Unknown overlay type: {overlay_type}')

    return copy.deepcopy(default_styles[overlay_type])


def default_overlay_options(overlay_type):
    default_options = {
        OverlayType.powder: constants.DEFAULT_POWDER_OPTIONS,
        OverlayType.laue: constants.DEFAULT_LAUE_OPTIONS,
        OverlayType.mono_rotation_series: (
            constants.DEFAULT_MONO_ROTATION_SERIES_OPTIONS)
    }

    if overlay_type not in default_options:
        raise Exception(f'Unknown overlay type: {overlay_type}')

    return copy.deepcopy(default_options[overlay_type])


def default_overlay_refinements(overlay):
    from hexrd.ui.hexrd_config import HexrdConfig

    material = HexrdConfig().material(overlay['material'])
    overlay_type = overlay['type']

    default_refinements = {
        OverlayType.powder: constants.DEFAULT_POWDER_REFINEMENTS,
        OverlayType.laue: constants.DEFAULT_CRYSTAL_REFINEMENTS,
        OverlayType.mono_rotation_series: constants.DEFAULT_CRYSTAL_REFINEMENTS
    }

    if overlay_type not in default_refinements:
        raise Exception(f'Unknown overlay type: {overlay_type}')

    refinements = copy.deepcopy(default_refinements[overlay_type])

    if overlay_type == OverlayType.powder:
        # Only give it the required indices
        indices = unitcell._rqpDict[material.unitcell.latticeType][0]
        refinements = [refinements[i] for i in indices]

    return refinements


def update_overlay_data(instr, display_mode):
    from hexrd.ui.hexrd_config import HexrdConfig

    if not HexrdConfig().show_overlays:
        # Nothing to do
        return

    for overlay in HexrdConfig().overlays:
        if not overlay['visible']:
            # Skip over invisible overlays
            continue

        if not overlay.get('update_needed', True):
            # If it doesn't need an update, skip it
            continue

        overlay['data'].clear()

        mat_name = overlay['material']
        mat = HexrdConfig().material(mat_name)

        if not mat:
            # Print a warning, as this shouldn't happen
            print('Warning in update_overlay_data():',
                  f'{mat_name} is not a valid material')
            continue

        type = overlay['type']
        kwargs = {
            'plane_data': mat.planeData,
            'instr': instr,
            'eta_period': HexrdConfig().polar_res_eta_period
        }
        # Add any options
        kwargs.update(overlay.get('options', {}))

        generator = overlay_generator(type)(**kwargs)
        overlay['data'] = generator.overlay(display_mode)
        overlay['update_needed'] = False
