"""Tests for rescaling powder intensity to a chosen material in the
reflections table, mirroring the existing structure-factor rescaling.
"""

from typing import Generator

import pytest

from hexrd.material import Material

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.reflections_table import ReflectionsTable


MAT_A = 'powder_rescale_test_a'
MAT_B = 'powder_rescale_test_b'


@pytest.fixture
def table(qtbot) -> Generator[ReflectionsTable, None, None]:
    config = HexrdConfig()
    config.add_material(MAT_A, Material())
    config.add_material(MAT_B, Material())
    t = ReflectionsTable(config.material(MAT_A))
    qtbot.addWidget(t.ui)
    try:
        yield t
    finally:
        # Disconnect the long-lived HexrdConfig signals before removing the
        # test materials, so the table doesn't react to materials_removed
        # after qtbot has torn down its widget.
        t._disconnect_hexrd_config()
        config.remove_materials([MAT_A, MAT_B])


def test_powder_intensity_rescaled_to_0_100(table: ReflectionsTable) -> None:
    # Relative to the same material, the powder intensity spans 0..100.
    table.relative_scale_powder_material_name = MAT_A

    rescaled = table.rescaled_powder_intensity
    assert rescaled.min() == pytest.approx(0.0)
    assert rescaled.max() == pytest.approx(100.0)


def test_powder_selector_independent_of_structure_factor(
    table: ReflectionsTable,
) -> None:
    table.relative_scale_material_name = MAT_A
    table.relative_scale_powder_material_name = MAT_B

    # The two selectors are independent.
    assert table.relative_scale_material_name == MAT_A
    assert table.relative_scale_powder_material_name == MAT_B
