"""Regression coverage for the GUI boundary with HEXRD's staged workflow."""

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from scipy import ndimage
from PySide6.QtWidgets import QApplication

from hexrd.core import imageseries
from hexrd.core.constants import fwhm_to_sigma
from hexrd.core.imageseries.omega import OmegaImageSeries
from hexrd.core.imageseries.process import ProcessedImageSeries
from hexrd.core.instrument import HEDMInstrument
from hexrd.core.material import Material
from hexrd.core.material.material_data import PlaneData
from hexrd.hedm.experiment import HedmExperiment, OrientationMaps
from hexrd.hedm.find_orientations import EtaOmegaMaps, generate_orientation_grid

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.indexing import create_config
from hexrdgui.indexing.eta_omega_maps import (
    EtaOmeMaps,
    filter_maps,
)
from hexrdgui.indexing import run as indexing_run
from hexrdgui.indexing.ome_maps_viewer_dialog import OmeMapsViewerDialog
from hexrdgui.main_window import MainWindow


MapData = tuple[EtaOmeMaps, EtaOmegaMaps]
ExperimentInputs = tuple[
    HedmExperiment, Material, np.ndarray, np.ndarray, dict[str, Any], np.ndarray
]


@pytest.fixture
def map_data() -> MapData:
    pd = Material('test').planeData
    pd.tThWidth = np.radians(0.25)
    exclusions = pd.exclusions.copy()
    exclusions[1] = True
    pd.exclusions = exclusions
    numeric_pd = PlaneData.from_plane_data(pd)
    # Select a reordered subset so master HKL IDs cannot be mistaken for
    # either map indices or indices among the non-excluded reflections.
    rings = np.array([2, 0])
    tths = numeric_pd.two_thetas[~numeric_pd.exclusions][rings]
    eta_step = np.radians(0.25)
    maps = EtaOmegaMaps(
        np.arange(64, dtype=float).reshape(2, 4, 8),
        -np.pi + np.arange(9) * eta_step,
        np.linspace(0, np.pi, 5),
        np.linspace(np.pi / 8, 7 * np.pi / 8, 4),
        np.array([0, 2 * np.pi]),
        np.column_stack((tths - pd.tThWidth / 2, tths + pd.tThWidth / 2)),
        rings,
        eta_step,
    )
    maps.ring_maps[0, 0, 0] = np.nan
    return EtaOmeMaps.from_maps(maps, pd), maps


def test_map_snapshot_preserves_reflection_order_and_exclusions(
    map_data: MapData,
) -> None:
    gui_maps, original = map_data
    converted = gui_maps.to_maps()
    np.testing.assert_array_equal(converted.ring_ids, original.ring_ids)
    np.testing.assert_array_equal(converted.ring_maps, original.ring_maps)
    assert converted.eta_step == original.eta_step
    np.testing.assert_allclose(converted.two_theta_ranges, original.two_theta_ranges)
    np.testing.assert_array_equal(
        converted.plane_data.unexcluded_hkls[converted.ring_ids],
        gui_maps.planeData.getHKLs(*gui_maps.iHKLList),
    )


def test_existing_map_archive_round_trip(map_data: MapData, tmp_path: Path) -> None:
    gui_maps, original = map_data
    filename = tmp_path / 'maps.npz'
    gui_maps.save_eta_ome_maps(filename)
    loaded = EtaOmeMaps(filename)
    converted = loaded.to_maps()
    np.testing.assert_array_equal(converted.ring_maps, original.ring_maps)
    np.testing.assert_array_equal(converted.ring_ids, original.ring_ids)
    np.testing.assert_array_equal(converted.eta_edges, original.eta_edges)
    np.testing.assert_array_equal(converted.omega_edges, original.omega_edges)
    np.testing.assert_array_equal(
        loaded.planeData.exclusions, gui_maps.planeData.exclusions
    )
    loaded.planeData.exclusions = np.ones_like(loaded.planeData.exclusions)
    with pytest.raises(ValueError, match='Map HKL IDs are excluded or missing'):
        loaded.to_maps()


@pytest.mark.parametrize('setting', [False, True, 1.5])
def test_filter_preserves_legacy_fwhm_and_nan_gaps(
    map_data: MapData, setting: bool | float
) -> None:
    gui_maps, original = map_data
    preview = copy.deepcopy(gui_maps)
    expected = original.ring_maps.copy()
    if setting:
        for ring in expected:
            ring -= np.nanmedian(ring, axis=0)
            if not isinstance(setting, bool):
                missing = np.isnan(ring)
                ring[missing] = 0
                # Master's filter_maps_if_requested converts numeric FWHM
                # to sigma at the scipy boundary, exactly once.
                ring[:] = -ndimage.gaussian_laplace(ring, setting * fwhm_to_sigma)
                ring[missing] = np.nan
    filter_maps(preview, {'filter_maps': setting})
    np.testing.assert_allclose(preview.dataStore, expected)
    np.testing.assert_array_equal(gui_maps.dataStore, original.ring_maps)


@pytest.fixture
def experiment_inputs(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> ExperimentInputs:
    material = Material('test')
    material.planeData.tThWidth = np.radians(0.5)
    exclusions = material.planeData.exclusions.copy()
    exclusions[1] = True
    material.planeData.exclusions = exclusions
    instrument = HEDMInstrument(
        instrument_config={
            'beam': {
                'energy': 65.0,
                'vector': {'azimuth': 90.0, 'polar_angle': 90.0},
            },
            'oscillation_stage': {'chi': 0, 'translation': [0, 0, 0]},
            'detectors': {
                'panel': {
                    'pixels': {'rows': 4, 'columns': 4, 'size': [0.2, 0.2]},
                    'transform': {'tilt': [0, 0, 0], 'translation': [0, 0, -1000]},
                }
            },
        }
    )
    frames = np.arange(72, dtype=float).reshape(2, 6, 6)
    omega = np.array([[10, 11], [11, 12]])
    raw = imageseries.open(None, 'array', data=frames, meta={'omega': omega})
    processed = ProcessedImageSeries(
        raw,
        [
            ('rectangle', [[1, 5], [1, 5]]),
            ('dark', np.ones((4, 4))),
        ],
    )
    series = OmegaImageSeries(processed)
    monkeypatch.setattr(create_config, 'get_indexing_material', lambda: material)
    monkeypatch.setattr(create_config, 'create_hedm_instrument', lambda: instrument)
    monkeypatch.setattr(
        HexrdConfig, 'omega_imageseries_dict', property(lambda self: {'panel': series})
    )
    gui_config = HexrdConfig().indexing_config
    monkeypatch.setitem(gui_config, 'working_dir', str(tmp_path))
    monkeypatch.setitem(
        gui_config['find_orientations']['orientation_maps'], 'filter_maps', 1.5
    )
    experiment = create_config.create_indexing_config()
    return experiment, material, frames, omega, gui_config, exclusions


def test_experiment_preserves_processed_frames_and_angle_units(
    experiment_inputs: ExperimentInputs,
) -> None:
    experiment, material, frames, omega, gui_config, exclusions = experiment_inputs

    np.testing.assert_array_equal(
        experiment.image_series['panel'][1], frames[1, 1:5, 1:5] - 1
    )
    view = experiment.image_series_list[0]
    np.testing.assert_allclose(view.omega, np.radians(omega))
    # Exercise the actual streaming interface, which must support processed
    # ROI series as well as the library's file-backed image adapters.
    reconstructed = np.zeros((2, 4, 4))
    for ids, values, offsets, rows in view.pixel_chunks(np.arange(2)):
        for i, row in enumerate(rows):
            start, stop = offsets[i : i + 2]
            reconstructed[row].flat[ids[start:stop]] = values[start:stop]
    np.testing.assert_array_equal(reconstructed, frames[:, 1:5, 1:5] - 1)
    np.testing.assert_allclose(
        experiment.eta_ranges,
        np.radians(
            [
                [-85, 85],
                [95, 265],
            ]
        ),
    )
    snapshot = experiment.get_active_material().plane_data
    np.testing.assert_array_equal(snapshot.exclusions, exclusions)
    assert experiment.active_material.two_theta_width == pytest.approx(0.5)
    assert experiment.find_orientations.orientation_maps.filter_fwhm == 1.5
    assert gui_config['find_orientations']['orientation_maps']['filter_maps'] == 1.5
    material.planeData.exclusions = np.zeros_like(exclusions)
    np.testing.assert_array_equal(snapshot.exclusions, exclusions)


@pytest.mark.parametrize('new_file_placement', [False, True])
def test_quaternion_grid_scoring_export_and_reclustering(
    main_window: MainWindow,
    experiment_inputs: ExperimentInputs,
    map_data: MapData,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    new_file_placement: bool,
) -> None:
    experiment = experiment_inputs[0]
    experiment.config['new_file_placement'] = new_file_placement
    quaternions = np.array(
        [
            [1, np.cos(0.15), np.cos(0.5)],
            [0, np.sin(0.15), 0],
            [0, 0, np.sin(0.5)],
            [0, 0, 0],
        ]
    )
    np.save(tmp_path / 'trials.npy', quaternions)
    settings = experiment.config['find_orientations']
    settings['use_quaternion_grid'] = 'trials.npy'
    monkeypatch.setattr(indexing_run, 'create_indexing_config', lambda: experiment)
    monkeypatch.setitem(
        HexrdConfig().indexing_config['find_orientations'],
        '_write_scored_orientations',
        True,
    )
    runner = indexing_run.IndexingRunner(main_window.ui)
    runner.ome_maps = map_data[0]
    runner.orientation_maps = runner.ome_maps.to_maps()
    runner.generate_orientation_fibers(experiment)
    np.testing.assert_array_equal(runner.qfib, quaternions)
    assert not isinstance(runner.qfib, np.memmap)
    assert runner.qfib.flags.writeable
    (tmp_path / 'trials.npy').unlink()
    runner.run_indexer()
    assert runner.completeness.shape == (3,)
    assert np.all((runner.completeness >= 0) & (runner.completeness <= 1))
    with np.load(experiment.scored_orientations_file) as archive:
        np.testing.assert_array_equal(archive['test_quaternions'], quaternions)
        np.testing.assert_array_equal(archive['score'], runner.completeness)

    # Reuse scored trials, changing only clustering settings. No maps or
    # fibers should be regenerated, and the new threshold must take effect.
    runner.min_samples = 1
    runner.completeness = np.array([1.0, 0.9, 0.1])
    settings['clustering']['completeness'] = 0.85
    runner.run_cluster()
    assert runner.grains_table.shape == (2, 21)
    settings['clustering']['completeness'] = 0.95
    runner.run_cluster()
    assert runner.grains_table.shape == (1, 21)
    settings['clustering']['completeness'] = 1.0
    runner.run_cluster()
    assert runner.grains_table is None


def test_viewer_preserves_new_filter_settings_and_user_edits(
    main_window: MainWindow,
    map_data: MapData,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HexrdConfig().indexing_config['find_orientations']
    monkeypatch.setitem(settings['seed_search'], 'hkl_seeds', [0])
    monkeypatch.setitem(settings['orientation_maps'], 'filter_maps', True)
    monkeypatch.setitem(settings['orientation_maps'], 'filter_fwhm', 3.5)
    dialog = OmeMapsViewerDialog(map_data[0], main_window.ui)

    assert dialog.ui.filtering_apply_gaussian_laplace.isChecked()
    assert dialog.ui.filtering_fwhm.value() == pytest.approx(3.5)
    assert dialog.filter_maps == pytest.approx(3.5)
    expected = copy.deepcopy(map_data[0])
    filter_maps(expected, settings['orientation_maps'])
    np.testing.assert_allclose(dialog.data.dataStore, expected.dataStore)

    # Disabling LoG or all filtering must also clear the saved width, so
    # the exported workflow and the preview continue to use the same filter.
    dialog.ui.filtering_apply_gaussian_laplace.setChecked(False)
    for enabled in (True, False):
        dialog.ui.apply_filtering.setChecked(enabled)
        dialog.update_config()
        exported = dialog.config['find_orientations']['orientation_maps'].copy()
        parsed = OrientationMaps.from_dict(exported)
        assert parsed.filter_maps is enabled
        assert parsed.filter_fwhm is None


def test_direct_search_uses_material_point_group(
    main_window: MainWindow,
    experiment_inputs: ExperimentInputs,
    map_data: MapData,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = experiment_inputs[1]
    material.sgnum = 1  # Point group 1, but Laue group Ci has number 2.
    settings = experiment_inputs[4]['find_orientations']
    monkeypatch.setitem(settings, 'use_quaternion_grid', None)
    monkeypatch.setitem(settings, 'direct_search', {'average_angular_spacing': 30.0})
    monkeypatch.delitem(settings, 'seed_search')
    experiment = create_config.create_indexing_config()
    assert experiment.find_orientations.direct_search.point_group_number == 1
    runner = indexing_run.IndexingRunner(main_window.ui)
    runner.orientation_maps = map_data[0].to_maps()
    runner.generate_orientation_fibers(experiment)
    expected = generate_orientation_grid(
        experiment, PlaneData.from_plane_data(material.planeData, material.pgnum)
    )
    np.testing.assert_array_equal(runner.qfib, expected)
    settings['direct_search']['point_group_number'] = 2
    assert (
        create_config.create_indexing_config().find_orientations.direct_search.point_group_number
        == 2
    )


@pytest.mark.parametrize('method', ['grid_search', 'hand_picked'])
def test_export_non_seed_workflow_has_valid_hkl_selection(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    method: str,
) -> None:
    config = HexrdConfig()
    monkeypatch.setitem(
        config.indexing_config, '_selected_material', config.active_material_name
    )
    settings = config.indexing_config['find_orientations']
    monkeypatch.setitem(settings, '_quaternion_method', method)
    filename = tmp_path / 'workflow.yml'
    config.save_indexing_config(filename)
    saved = yaml.safe_load(filename.read_text())
    assert (
        OrientationMaps.from_dict(
            saved['find_orientations']['orientation_maps']
        ).active_hkls
        is None
    )


def test_grid_validation_uses_working_directory(
    main_window: MainWindow,
    map_data: MapData,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HexrdConfig().indexing_config['find_orientations']
    monkeypatch.setitem(settings['seed_search'], 'hkl_seeds', [0])
    np.save(tmp_path / 'trials.npy', np.array([[1.0], [0.0], [0.0], [0.0]]))
    dialog = OmeMapsViewerDialog(map_data[0], main_window.ui)
    dialog.working_dir = str(tmp_path)
    dialog.quaternion_method_name = 'grid_search'
    dialog.quaternion_grid_file = 'trials.npy'
    dialog.update_config()
    dialog.validate()
