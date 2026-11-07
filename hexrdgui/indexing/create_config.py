from __future__ import annotations

import copy
import os

import numpy as np

from typing import Any

from hexrd.core.imageseries import ImageSeries
from hexrd.core.imageseries.omega import OmegaImageSeries
from hexrd.core.imageseries.process import ProcessedImageSeries
from hexrd.hedm.experiment import HedmExperiment

from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig


def get_indexing_material() -> Any:
    indexing_config = HexrdConfig().indexing_config
    available_materials = list(HexrdConfig().materials)
    selected_material = indexing_config.get('_selected_material')

    if selected_material is None or selected_material not in available_materials:
        raise Exception(f'Selected material {selected_material} not available')

    return HexrdConfig().material(selected_material)


def create_indexing_config() -> HedmExperiment:
    """Snapshot the GUI's in-memory inputs as an HEDM experiment."""

    material = get_indexing_material()

    # Make a copy to modify
    indexing_config = copy.deepcopy(HexrdConfig().indexing_config)

    if HexrdConfig().max_cpus is not None:
        # Set the max number of CPUs
        indexing_config['multiprocessing'] = HexrdConfig().max_cpus

    # Make sure exclusions are not reset
    fit_grains_config = indexing_config.setdefault('fit_grains', {})
    disable_exclusions_reset(fit_grains_config)

    # Set the active material on the config
    material_config = indexing_config.setdefault('material', {})
    material_config['active'] = material.name
    disable_exclusions_reset(material_config)

    tth_width = material.planeData.tThWidth
    if tth_width is not None:
        material_config['tth_width'] = np.degrees(tth_width)

    find_orientations = indexing_config['find_orientations']
    direct_search = find_orientations.get('direct_search')
    if direct_search is not None:
        if direct_search.get('point_group_number') is None:
            direct_search['point_group_number'] = material.pgnum
        # The GUI always keeps seed search settings, but HEXRD rejects
        # them alongside a direct search.
        find_orientations.pop('seed_search', None)

    omega_series = HexrdConfig().omega_imageseries_dict
    if omega_series is None:
        # Add an early error that is easier to understand...
        raise OmegasNotFoundError('Omegas not found!')

    # HEXRD's streaming adapter expects a base ImageSeries. The GUI also
    # supplies ProcessedImageSeries (ROI crops, flips, dark subtraction).
    # Wrap those without discarding their processing or copying the frames.
    ims_dict = {}
    for panel, series in omega_series.items():
        source = series
        while isinstance(source, OmegaImageSeries):
            source = source._adapter
        ims_dict[panel] = (
            ImageSeries(series) if isinstance(source, ProcessedImageSeries) else series
        )

    validate_config(indexing_config)
    return HedmExperiment.from_objects(
        create_hedm_instrument(),
        ims_dict,
        copy.deepcopy(material.planeData),
        indexing_config,
    )


def validate_config(config: dict) -> None:
    # Perform any modifications to make sure this is a valid config
    working_dir = config.get('working_dir')
    if working_dir is None:
        config['working_dir'] = os.getcwd()
    elif not os.path.isdir(working_dir):
        # This working directory does not exist. Set it to the cwd.
        print(
            f'Warning: {config.get("working_dir")} does not exist.',
            f'Changing working directory to {os.getcwd()}',
        )
        config['working_dir'] = os.getcwd()

        # Make sure future configs use the new working dir as well...
        HexrdConfig().indexing_config['working_dir'] = os.getcwd()


class OmegasNotFoundError(Exception):
    pass


def disable_exclusions_reset(config: dict) -> None:
    # Disable exclusions reset for the provided config
    config['reset_exclusions'] = False

    # Set these to None so we don't get a warning message
    set_to_none = [
        'min_sfac_ratio',
        'dmin',
        'dmax',
        'tthmin',
        'tthmax',
        'sfacmin',
        'sfacmax',
        'pintmin',
        'pintmax',
    ]

    for key in set_to_none:
        config[key] = None
