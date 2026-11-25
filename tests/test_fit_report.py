from typing import Any

import numpy as np

from hexrd.core.instrument import HEDMInstrument
from hexrd.fitting.calibration import StructurelessCalibrator

from hexrdgui.calibration.fit_report_dialog import FitReportDialog, TABLE_COLUMNS
from hexrdgui.hexrd_config import HexrdConfig


def test_structureless_fit_report_dialog(qtbot: Any) -> None:
    instr = HEDMInstrument()
    det_key, panel = next(iter(instr.detectors.items()))
    ceria = HexrdConfig().material('CeO2')

    # Pick the CeO2 (111) and (200) rings, and shift the (200) ring by
    # 0.05 degrees so it is offset from the material.
    d_spacings = np.asarray(ceria.planeData.getPlaneSpacings())[:2]
    ceria_tths = np.degrees(2 * np.arcsin(instr.beam_wavelength / (2 * d_spacings)))
    rng = np.random.default_rng(0)
    etas = np.linspace(-170, 170, 25)
    picked_tths = []
    picks = []
    for tth, shift in zip(ceria_tths, [0, 0.05]):
        picked = tth + shift + rng.normal(0, 0.005, len(etas))
        angles = np.radians(np.column_stack([picked, etas]))
        picks.append({det_key: panel.angles_to_cart(angles)})
        picked_tths.append(picked)

    calibrator = StructurelessCalibrator(instr, {'XRS1': picks})
    dialog = FitReportDialog(calibrator)
    qtbot.addWidget(dialog.ui)

    table = dialog.ui.table

    def column(name: str) -> list[str]:
        j = TABLE_COLUMNS.index(name)
        return [table.item(i, j).text() for i in range(table.rowCount())]

    # The fitted ring means are the reference by default
    assert column('Ring') == ['1', '2']
    assert column('Points') == ['25', '25']
    assert column('Detectors') == [det_key, det_key]
    assert table.isColumnHidden(TABLE_COLUMNS.index('hkl'))
    fit_tths = [calibrator.params[f'DS_ring_{i}'].value for i in range(2)]
    assert column('Fit 2θ (°)') == [f'{x:.3f}' for x in fit_tths]
    assert column('σ (°)') == [f'{x.std():.4f}' for x in picked_tths]

    # Now compare to the CeO2 hkls
    dialog.ui.material.setCurrentIndex(dialog.ui.material.findData('CeO2'))
    assert not table.isColumnHidden(TABLE_COLUMNS.index('hkl'))
    assert column('hkl') == ['1 1 1', '2 0 0']
    assert column('hkl 2θ (°)') == [f'{x:.3f}' for x in ceria_tths]
    offsets = [x.mean() - y for x, y in zip(picked_tths, ceria_tths)]
    assert column('Offset (°)') == [f'{x:+.3f}' for x in offsets]
    assert abs(offsets[1] - 0.05) < 0.005
    assert 'CeO2' in dialog.fig.get_suptitle()
    assert len(dialog.fig.axes) == 3

    # The display options should only redraw, and not change the data
    dialog.ui.bounds.setValue(0.01)
    dialog.ui.histogram_bins.setValue(7)
    assert column('Offset (°)') == [f'{x:+.3f}' for x in offsets]
