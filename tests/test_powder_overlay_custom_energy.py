"""Tests for the per-overlay custom beam energy (harmonic visualization).

A powder overlay can be drawn at a custom beam energy without modifying the
instrument or the material's persistent state. The override is applied only
while generating the overlay and is rejected by analysis routines.
"""

from pathlib import Path
from typing import Generator

import h5py
import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from hexrd.material import Material

from hexrdgui import state
from hexrdgui.constants import WAVELENGTH_TO_KEV
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays import reject_overlays_with_custom_energy
from hexrdgui.overlays.powder_overlay import PowderOverlay


MATERIAL_NAME = 'custom_energy_test_material'


@pytest.fixture
def powder_overlay(qapp: QApplication) -> Generator[PowderOverlay, None, None]:
    # HexrdConfig is a singleton that requires a QApplication (qapp).
    config = HexrdConfig()
    config.add_material(MATERIAL_NAME, Material())
    try:
        yield PowderOverlay(MATERIAL_NAME)
    finally:
        config.remove_material(MATERIAL_NAME)


def test_custom_energy_override_changes_and_restores(
    powder_overlay: PowderOverlay,
) -> None:
    plane_data = powder_overlay.plane_data
    original_wavelength = plane_data.wavelength
    original_tth = plane_data.getTTh().copy()

    # Visualize at the second harmonic (double the instrument energy).
    instrument_energy = WAVELENGTH_TO_KEV / original_wavelength
    powder_overlay.custom_energy = 2 * instrument_energy

    with powder_overlay.custom_energy_override():
        # The wavelength (and thus the 2theta) reflects the custom energy.
        assert not np.isclose(plane_data.wavelength, original_wavelength)
        assert not np.array_equal(plane_data.getTTh(), original_tth)

    # The shared plane data is restored exactly afterward.
    assert np.isclose(plane_data.wavelength, original_wavelength)
    assert np.array_equal(plane_data.getTTh(), original_tth)


def test_custom_energy_persists_through_state_file(
    powder_overlay: PowderOverlay,
    tmp_path: Path,
) -> None:
    # Exercise the real HDF5 state serialization used by save/load: overlays
    # are dictified into the config, dumped to YAML in the file, then read
    # back and reconstructed.
    config = HexrdConfig()
    saved_overlays = list(config.overlays)
    try:
        powder_overlay.custom_energy = 42.5
        instrument_energy_overlay = PowderOverlay(MATERIAL_NAME)  # None
        config.overlays = [powder_overlay, instrument_energy_overlay]

        snapshot = {'overlays_dictified': config.overlays_dictified}
        file_path = tmp_path / 'state.h5'
        with h5py.File(file_path, 'w') as f:
            state._save_config(f, snapshot)
        with h5py.File(file_path, 'r') as f:
            loaded = state._load_config(f)

        config.overlays_dictified = loaded['overlays_dictified']
        energies = [o.custom_energy for o in config.overlays]
        assert energies[0] == 42.5
        assert energies[1] is None
    finally:
        config.overlays = saved_overlays


def test_reject_overlays_with_custom_energy(powder_overlay: PowderOverlay) -> None:
    # No custom energy -> not flagged, does not raise.
    reject_overlays_with_custom_energy([powder_overlay], 'WPPF')

    powder_overlay.custom_energy = 75.0
    with pytest.raises(Exception, match='custom beam energy'):
        reject_overlays_with_custom_energy([powder_overlay], 'WPPF')
