from types import SimpleNamespace

import numpy as np

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils.coverage_plot import CoveragePlotDialog
from utils import select_files_when_asked


def test_coverage_plot_cursor_coordinates(qtbot):
    dialog = CoveragePlotDialog()
    qtbot.addWidget(dialog)

    dialog.on_mouse_move(SimpleNamespace(inaxes=dialog.ax, xdata=12.345, ydata=67.89))

    assert dialog.coordinates_label.text() == 'tth=12.35,  coverage=67.9%'

    dialog.on_mouse_move(SimpleNamespace(inaxes=None))
    assert dialog.coordinates_label.text() == ''


def test_export_coverage_lineout(qtbot, tmp_path, monkeypatch):
    dialog = CoveragePlotDialog()
    qtbot.addWidget(dialog)
    dialog.coverage_line.set_data([1.25, 2.5], [75.0, 80.5])
    output_dir = tmp_path / 'output'
    output_dir.mkdir()
    output_path = output_dir / 'coverage'
    monkeypatch.setattr(HexrdConfig(), 'working_dir', str(tmp_path))

    with select_files_when_asked(output_path):
        dialog.export_button.click()

    saved_data = np.loadtxt(output_path.with_suffix('.xy'))
    np.testing.assert_allclose(saved_data, [[1.25, 75.0], [2.5, 80.5]])
    assert HexrdConfig().working_dir == str(output_dir)


class StreakPanel:
    def __init__(self, tth_degrees):
        self.tth_degrees = tth_degrees
        self.pixel_solid_angles = np.ones((2, 2))
        self.shape = self.pixel_solid_angles.shape
        self.panel_buffer = None

    def pixel_angles(self):
        tth = np.radians(self.tth_degrees)
        return tth, np.zeros_like(tth)


def test_streak_tth_range_updates(qtbot, monkeypatch):
    panel = StreakPanel([[12.0, 20.0], [15.0, 18.0]])
    raw_mask = np.ones((20, 2), dtype=bool)
    raw_mask[0, 0] = False
    raw_mask[:2, 1] = False
    polar_view = SimpleNamespace(
        instr=SimpleNamespace(detectors={'STREAK': panel}),
        raw_img=np.ma.array(np.ones((20, 2)), mask=raw_mask),
        angular_grid=(None, np.radians([[10.0, 20.0]])),
    )
    monkeypatch.setattr(
        CoveragePlotDialog, 'polar_view', property(lambda self: polar_view)
    )

    dialog = CoveragePlotDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'isVisible', lambda: True)

    dialog.update_plot()

    np.testing.assert_allclose(dialog.streak_line.get_xdata(), [12.0, 20.0])
    np.testing.assert_allclose(dialog.streak_line.get_ydata(), [0.0, 0.0])
    np.testing.assert_allclose(dialog.reference_8_line.get_ydata(), [8.0, 8.0])
    assert (
        dialog.fraction_above_reference_label.text()
        == 'Fraction of 2θ FOV with coverage > 8% = 50.0%'
    )
    assert dialog.streak_line.get_color() == 'r'
    assert dialog.streak_line.get_linestyle() == '-'
    assert dialog.streak_line.get_linewidth() == 2

    panel.tth_degrees = [[25.0, 35.0], [28.0, 30.0]]
    panel.panel_buffer = np.array([[False, True], [True, False]])
    HexrdConfig().detector_transforms_modified.emit(['STREAK'])

    np.testing.assert_allclose(dialog.streak_line.get_xdata(), [28.0, 35.0])
