import numpy as np
import pytest

from hexrdgui.overlays.diffraction_angle_overlay import DiffractionAngleOverlay


@pytest.mark.parametrize(
    ('parameters', 'expected'),
    [
        ((10, 70, 10), [10, 20, 30, 40, 50, 60, 70]),
        ((10, 72, 10), [10, 20, 30, 40, 50, 60, 70, 72]),
        ((70, 70, 10), [70]),
    ],
)
def test_tth_values_include_maximum(
    parameters: tuple[float, float, float],
    expected: list[float],
    qapp,
) -> None:
    overlay = DiffractionAngleOverlay(*parameters)

    np.testing.assert_allclose(overlay.tth_values, expected)


def test_plane_data_returns_tth_values_in_radians(qapp) -> None:
    overlay = DiffractionAngleOverlay(10, 30, 10)

    np.testing.assert_allclose(
        overlay.plane_data.getTTh(),
        np.radians([10, 20, 30]),
    )
