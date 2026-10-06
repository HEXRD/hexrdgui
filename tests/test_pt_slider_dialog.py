import copy

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.pt_slider_dialog import PTSliderDialog


def test_unreachable_pt_state_is_rejected(
    qtbot: QtBot,
    message_boxes: list[str],
) -> None:
    material = copy.deepcopy(HexrdConfig().material('CeO2'))
    assert material is not None
    material.k0p = 4.0
    material.alpha_t = 3e-5
    dialog = PTSliderDialog(material)
    qtbot.addWidget(dialog.ui)
    dialog.update_gui()
    dialog.temperature = 2000
    lparms = material.lparms.copy()

    # Thermal expansion this large has no equation-of-state solution, so
    # both the temperature and the parameter change should be reverted
    dialog.temperature = 10000
    dialog.ui.alpha_t.setValue(3e-4)

    assert len(message_boxes) == 2
    message_boxes.clear()
    assert dialog.temperature == material.temperature == 2000
    assert dialog.ui.alpha_t.value() == pytest.approx(3e-5)
    assert material.alpha_t == pytest.approx(3e-5)
    np.testing.assert_allclose(material.lparms, lparms)
