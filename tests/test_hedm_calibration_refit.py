from unittest.mock import Mock

from lmfit import Parameters
import numpy as np
import pytest

from hexrdgui.calibration.hedm import calibration_dialog


def test_refit_uses_filtered_reflections(monkeypatch: pytest.MonkeyPatch) -> None:
    hkls = np.array([[1, 0, 0], [0, 1, 0]])
    picks = np.array([[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]])
    parsed = ({'det': [hkls]}, {'det': [picks]}, {'det': [np.ones(2, dtype=bool)]})
    filtered = ({'det': [hkls[:1]]}, {'det': [picks[:1]]}, {})
    monkeypatch.setattr(
        calibration_dialog, 'parse_spots_data', Mock(side_effect=[parsed, filtered])
    )
    monkeypatch.setattr(
        calibration_dialog,
        'compute_xyo',
        Mock(return_value={'det': [np.zeros((2, 3))]}),
    )
    config = Mock()
    config.image_series = {
        'det': Mock(metadata={'omega': np.array([[0.0, 1.0], [1.0, 2.0]])})
    }
    config.fit_grains.refit = None
    monkeypatch.setattr(
        calibration_dialog, 'create_indexing_config', Mock(return_value=config)
    )

    callbacks = Mock()
    callbacks.dialog.do_refit = True
    callbacks.dialog.advanced_options = {}
    callbacks.instr.detectors = {'det': Mock(pixel_size_col=1.0, pixel_size_row=1.0)}
    callbacks.calibrators = [Mock()]
    callbacks.calibrator.params = Parameters()
    refit = Mock(calibrators=[Mock()], params=Parameters())
    refit.run_calibration.return_value.params = refit.params
    callbacks.calibrator.__deepcopy__ = Mock(return_value=refit)

    calibration_dialog.HEDMCalibrationCallbacks.run_calibration(callbacks)

    assert refit.run_calibration.call_count == 2
    data = refit.calibrators[0].data_dict
    np.testing.assert_array_equal(data['hkls']['det'], hkls[:1])
    np.testing.assert_array_equal(data['pick_xys']['det'], picks[:1])
