"""Regression tests for the material combo box in the indexing dialogs.

Repopulating the material combo box (for example, when importing a materials
file) clears and refills it. QComboBox.clear() emits currentIndexChanged with
an empty selection, which used to drive selected_material_changed() with a
None material and crash when a reflections table was open:

    AttributeError: 'NoneType' object has no attribute 'name'
"""

import numpy as np

from hexrdgui.indexing.fit_grains_options_dialog import FitGrainsOptionsDialog
from hexrdgui.indexing.ome_maps_select_dialog import OmeMapsSelectDialog


def test_fit_grains_options_material_repopulation(main_window, qtbot):
    dialog = FitGrainsOptionsDialog(grains_table=np.zeros((1, 21)))
    qtbot.addWidget(dialog.ui)

    # Opening the reflections table is the precondition for the crash.
    table = dialog.reflections_table
    assert table is not None
    qtbot.addWidget(table.ui)

    # Repopulating the combo box (as happens when materials are imported)
    # clears it, which emits currentIndexChanged with an empty selection.
    # This must not raise.
    dialog.update_materials()

    # The reflections table should still track the selected material.
    assert dialog.material is not None
    assert dialog._table.material is dialog.material


def test_ome_maps_select_material_repopulation(main_window, qtbot):
    dialog = OmeMapsSelectDialog()
    qtbot.addWidget(dialog.ui)

    # Opening the reflections table is the precondition for the crash.
    dialog.choose_hkls()
    assert dialog._table is not None
    qtbot.addWidget(dialog._table.ui)

    # Must not raise (see module docstring).
    dialog.update_materials()

    assert dialog.material is not None
    assert dialog._table.material is dialog.material
