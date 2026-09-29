from pathlib import Path
from shutil import copyfile

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from hexrd.powder.cake import CakeMatrix
from hexrd.core.projections.polar import PolarView
from hexrd.core.utils.panel_buffer import panel_buffer_as_2d_array

from hexrdgui.calibration.polar_plot import polar_viewer
from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.main_window import MainWindow


def test_gui_export_matches_ceria_polar_view(
    tmp_path: Path,
    example_repo_path: Path,
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    message_boxes: list[str],
) -> None:
    # Copy because loading an older state can migrate it in place.
    state = tmp_path / 'ceria.h5'
    copyfile(
        example_repo_path / 'eiger/first_ceria/eiger_ceria_calibrated_gui_state.h5',
        state,
    )
    main_window.load_state_file(state)
    QApplication.processEvents()
    config = HexrdConfig()
    config.disable_all_intensity_corrections()
    QApplication.processEvents()
    config.config['image']['polar'].update(
        tth_min=2.0,
        tth_max=8.0,
        pixel_size_tth=0.1,
        pixel_size_eta=5.0,
        apply_snip1d=False,
    )
    # The hidden test window does not render a new viewer when changing modes.
    viewer = polar_viewer()
    monkeypatch.setattr(main_window.active_canvas, 'iviewer', viewer)
    main_window.image_mode = ViewType.polar
    main_window.update_image_mode_enable_states()

    path = tmp_path / 'ceria.hexrdcake'
    monkeypatch.setattr(
        'hexrdgui.main_window.QFileDialog.getSaveFileName',
        lambda *args: (str(path), ''),
    )
    action = main_window.ui.action_export_cake_matrix
    assert action.isEnabled()
    action.trigger()
    assert any('Wrote ceria.hexrdcake' in message for message in message_boxes)
    message_boxes.clear()

    matrix = CakeMatrix(path)
    assert len(matrix.instrument.detectors) == 32
    # Use floating point interpolation, with static buffers excluded, as in
    # cake-data. The saved GUI images themselves have an integer dtype.
    images = {
        name: image.astype(float) for name, image in config.raw_images_dict.items()
    }
    actual = matrix.apply(images)
    for name, panel in matrix.instrument.detectors.items():
        images[name][~panel_buffer_as_2d_array(panel)] = np.nan
    reference = PolarView(
        (2, 8),
        viewer.instr,
        eta_min=np.degrees(viewer.pv.eta_min),
        eta_max=np.degrees(viewer.pv.eta_max),
        pixel_size=(0.1, 5),
    ).warp_image(images, pad_with_nans=True)
    np.testing.assert_allclose(
        actual.filled(np.nan),
        reference,
        equal_nan=True,
    )
