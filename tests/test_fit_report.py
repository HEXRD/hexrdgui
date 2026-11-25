import copy
from typing import Any

import numpy as np

from hexrd.core.instrument import HEDMInstrument
from hexrd.core.material import Material
from hexrd.fitting.calibration import (
    InstrumentCalibrator,
    LaueCalibrator,
    PowderCalibrator,
    StructurelessCalibrator,
)

from hexrdgui.calibration.fit_report_dialog import FitReportDialog, TABLE_COLUMNS
from hexrdgui.hexrd_config import HexrdConfig


def table_column(dialog: FitReportDialog, name: str) -> list[str]:
    table = dialog.ui.table
    j = TABLE_COLUMNS.index(name)
    return [table.item(i, j).text() for i in range(table.rowCount())]


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
        return table_column(dialog, name)

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


def test_composite_fit_report_dialog(qtbot: Any) -> None:
    instr = HEDMInstrument()
    det_key, panel = next(iter(instr.detectors.items()))

    def powder_calibrator(material: Material, shifts: dict) -> PowderCalibrator:
        # Pick each hkl ring, shifted by some degrees
        bmat = material.planeData.latVecOps['B']
        etas = np.radians(np.linspace(-170, 170, 15))
        picks = {}
        for hkl, shift in shifts.items():
            dsp = 1 / np.linalg.norm(bmat @ np.array(hkl.split(), dtype=float))
            tth = 2 * np.arcsin(instr.beam_wavelength / (2 * dsp))
            tth += np.radians(shift) + rng.normal(0, np.radians(0.005), len(etas))
            picks[hkl] = panel.angles_to_cart(np.column_stack([tth, etas])).tolist()

        return PowderCalibrator(
            instr,
            material,
            {det_key: None},
            calibration_picks={det_key: picks},
        )

    rng = np.random.default_rng(0)
    # Copy so the GUI's material is not modified
    ceria = copy.deepcopy(HexrdConfig().material('CeO2'))
    nickel = Material()
    ceria_calibrator = powder_calibrator(ceria, {'1 1 1': 0, '2 0 0': 0})
    calibrators = [
        ceria_calibrator,
        powder_calibrator(nickel, {'1 1 1': 0, '2 0 0': 0.05}),
        LaueCalibrator(
            instr,
            nickel,
            np.array([0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0]),
            euler_convention=HexrdConfig().euler_angle_convention,
        ),
    ]
    names = ['ceria powder', 'nickel powder', 'nickel laue']
    dialog = FitReportDialog(
        InstrumentCalibrator(*calibrators),
        calibrator_names=names,
    )
    qtbot.addWidget(dialog.ui)

    # The reference is always the material of each calibrator
    assert not dialog.ui.material.isVisibleTo(dialog.ui)
    assert dialog.ui.note.isVisibleTo(dialog.ui)
    assert 'nickel laue' in dialog.ui.note.text()

    def column(name: str) -> list[str]:
        return table_column(dialog, name)

    def hidden(name: str) -> bool:
        return dialog.ui.table.isColumnHidden(TABLE_COLUMNS.index(name))

    assert column('Overlay') == ['ceria powder'] * 2 + ['nickel powder'] * 2
    assert column('Ring') == ['1 1 1', '2 0 0'] * 2
    assert column('Points') == ['15'] * 4
    assert all(hidden(x) for x in ['hkl', 'Fit 2θ (°)'])
    assert not any(hidden(x) for x in ['Overlay', 'hkl 2θ (°)'])

    offsets = np.array(column('Offset (°)'), dtype=float)
    assert np.allclose(offsets, [0, 0, 0, 0.05], atol=0.005)

    legend = dialog.fig.axes[2].get_legend()
    assert legend.get_texts()[3].get_text() == 'nickel powder 2 0 0'

    # A single powder calibrator, as in fast powder calibration
    dialog = FitReportDialog(
        InstrumentCalibrator(ceria_calibrator),
        calibrator_names=['ceria powder'],
    )
    qtbot.addWidget(dialog.ui)
    assert not dialog.ui.note.isVisibleTo(dialog.ui)
    assert dialog.ui.table.isColumnHidden(TABLE_COLUMNS.index('Overlay'))
    assert dialog.fig.get_suptitle() == 'Residuals from the ceria powder hkls'
