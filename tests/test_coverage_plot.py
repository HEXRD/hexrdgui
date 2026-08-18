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
