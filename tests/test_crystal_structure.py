import os
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
import pytest

os.environ.setdefault(
    'NUMBA_CACHE_DIR',
    os.path.join(tempfile.gettempdir(), 'hexrdgui-numba-cache'),
)

from hexrd.material import Material

from hexrdgui.crystal_structure import crystal_structure_scene, lattice_vectors


def make_material(
    name: str,
    sgnum: int,
    lattice_parameters: list[float],
    atom_types: list[int] | None = None,
    atom_positions: list[list[float]] | None = None,
) -> Material:
    material = Material(name)
    material.name = name
    material.sgnum = sgnum
    material.latticeParameters = lattice_parameters

    if atom_types is None:
        atom_types = [28]

    if atom_positions is None:
        atom_positions = [[0.0, 0.0, 0.0, 1.0]]

    material._set_atomdata(
        atom_types,
        atom_positions,
        [Material.DFLT_U[0]] * len(atom_types),
        ['0'] * len(atom_types),
    )
    return material


@pytest.mark.parametrize(
    ('label', 'sgnum', 'lattice_parameters', 'expected_atoms'),
    [
        ('cubic', 225, [3.6, 3.6, 3.6, 90.0, 90.0, 90.0], 14),
        ('tetragonal', 123, [3.0, 3.0, 5.0, 90.0, 90.0, 90.0], 8),
        ('orthorhombic', 47, [3.0, 4.0, 5.0, 90.0, 90.0, 90.0], 8),
        ('triclinic', 2, [3.0, 4.0, 5.0, 70.0, 80.0, 75.0], 8),
    ],
)
def test_crystal_structure_scene_for_representative_crystal_classes(
    label,
    sgnum,
    lattice_parameters,
    expected_atoms,
):
    material = make_material(label, sgnum, lattice_parameters)

    scene = crystal_structure_scene(material)

    assert scene.material_name == label
    assert scene.cell_vectors.shape == (3, 3)
    assert scene.cell_vertices.shape == (8, 3)
    assert len(scene.cell_edges) == 12
    assert len(scene.atoms) == expected_atoms
    assert np.all(np.isfinite(scene.points))
    assert scene.extent > 0

    for atom in scene.atoms:
        assert atom.symbol == 'Ni'
        assert np.all(atom.fractional_position >= 0.0)
        assert np.all(atom.fractional_position <= 1.0)
        assert atom.style.radius > 0.0


def test_corner_atom_is_displayed_at_all_unit_cell_translations():
    material = make_material(
        'corner',
        1,
        [3.0, 4.0, 5.0, 90.0, 90.0, 90.0],
        atom_positions=[[0.0, 0.0, 0.0, 1.0]],
    )

    scene = crystal_structure_scene(material)
    positions = {tuple(atom.fractional_position) for atom in scene.atoms}

    assert positions == {
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 1.0, 0.0),
        (0.0, 1.0, 1.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 1.0),
        (1.0, 1.0, 0.0),
        (1.0, 1.0, 1.0),
    }


def test_interior_atom_is_not_translated_outside_unit_cell():
    material = make_material(
        'interior',
        1,
        [3.0, 4.0, 5.0, 90.0, 90.0, 90.0],
        atom_positions=[[0.5, 0.5, 0.5, 1.0]],
    )

    scene = crystal_structure_scene(material)

    assert len(scene.atoms) == 1
    assert np.allclose(scene.atoms[0].fractional_position, [0.5, 0.5, 0.5])


def test_periodic_bonds_add_atoms_outside_unit_cell():
    material = make_material(
        'periodic_molecule',
        1,
        [2.0, 2.0, 2.0, 90.0, 90.0, 90.0],
        atom_types=[6, 1],
        atom_positions=[
            [0.9, 0.5, 0.5, 1.0],
            [0.2, 0.5, 0.5, 1.0],
        ],
    )

    scene = crystal_structure_scene(material, include_bonds=True)

    assert scene.bonds
    assert any(np.any(atom.fractional_position > 1.0) for atom in scene.atoms)
    assert any(np.any(atom.fractional_position < 0.0) for atom in scene.atoms)
    assert any(
        np.isclose(bond.distance, 0.6)
        for bond in scene.bonds
        if {scene.atoms[bond.atom1_index].symbol, scene.atoms[bond.atom2_index].symbol}
        == {'C', 'H'}
    )


def test_metal_metal_bonds_are_disabled_by_default():
    material = make_material(
        'ni',
        225,
        [3.6, 3.6, 3.6, 90.0, 90.0, 90.0],
    )

    scene = crystal_structure_scene(material, include_bonds=True)

    assert len(scene.atoms) == 14
    assert scene.bonds == ()


def test_lattice_vectors_preserve_triclinic_angles():
    a, b, c = 3.0, 4.0, 5.0
    alpha, beta, gamma = 70.0, 80.0, 75.0

    vectors = lattice_vectors(a, b, c, alpha, beta, gamma)

    assert np.allclose(np.linalg.norm(vectors, axis=1), [a, b, c])
    assert angle_between(vectors[1], vectors[2]) == pytest.approx(alpha)
    assert angle_between(vectors[0], vectors[2]) == pytest.approx(beta)
    assert angle_between(vectors[0], vectors[1]) == pytest.approx(gamma)


def test_atom_style_overrides_by_symbol_and_atomic_number():
    material = make_material(
        'mixed',
        1,
        [3.0, 4.0, 5.0, 90.0, 90.0, 90.0],
        atom_types=[26, 8],
        atom_positions=[
            [0.0, 0.0, 0.0, 1.0],
            [0.5, 0.5, 0.5, 0.5],
        ],
    )

    scene = crystal_structure_scene(
        material,
        atom_colors={'Fe': (1, 2, 3), 8: (4, 5, 6)},
        atom_radii={'Fe': 0.7, 8: 0.2},
    )

    styles = {atom.symbol: atom.style for atom in scene.atoms}
    assert styles['Fe'].color == (1, 2, 3)
    assert styles['Fe'].radius == 0.7
    assert styles['O'].color == (4, 5, 6)
    assert styles['O'].radius == 0.2


def test_view_menu_contains_crystal_structure_action():
    ui_file = os.path.join(
        os.path.dirname(__file__),
        '..',
        'hexrdgui',
        'resources',
        'ui',
        'main_window.ui',
    )

    tree = ET.parse(ui_file)
    root = tree.getroot()
    menu_view = root.find(".//widget[@class='QMenu'][@name='menu_view']")
    assert menu_view is not None

    action_names = [
        action.attrib['name']
        for action in menu_view.findall('addaction')
        if 'name' in action.attrib
    ]
    assert 'action_view_crystal_structure' in action_names


def angle_between(v1: np.ndarray, v2: np.ndarray) -> float:
    cosine = np.dot(v1, v2) / np.linalg.norm(v1) / np.linalg.norm(v2)
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))
