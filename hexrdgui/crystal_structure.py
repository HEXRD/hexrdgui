from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from hexrd.constants import ptableinverse


Color = tuple[int, int, int]


DEFAULT_ATOM_COLORS: dict[str, Color] = {
    'H': (255, 255, 255),
    'C': (60, 60, 60),
    'N': (48, 80, 248),
    'O': (255, 13, 13),
    'F': (144, 224, 80),
    'Na': (171, 92, 242),
    'Mg': (138, 255, 0),
    'Al': (191, 166, 166),
    'Si': (240, 200, 160),
    'P': (255, 128, 0),
    'S': (255, 255, 48),
    'Cl': (31, 240, 31),
    'K': (143, 64, 212),
    'Ca': (61, 255, 0),
    'Ti': (191, 194, 199),
    'Cr': (138, 153, 199),
    'Mn': (156, 122, 199),
    'Fe': (224, 102, 51),
    'Co': (240, 144, 160),
    'Ni': (80, 208, 80),
    'Cu': (200, 128, 51),
    'Zn': (125, 128, 176),
    'Br': (166, 41, 41),
    'Ag': (192, 192, 192),
    'I': (148, 0, 148),
    'Au': (255, 209, 35),
    'Pb': (87, 89, 97),
    'U': (0, 143, 255),
}

COVALENT_RADII: dict[int, float] = {
    1: 0.31,
    2: 0.28,
    3: 1.28,
    4: 0.96,
    5: 0.84,
    6: 0.76,
    7: 0.71,
    8: 0.66,
    9: 0.57,
    10: 0.58,
    11: 1.66,
    12: 1.41,
    13: 1.21,
    14: 1.11,
    15: 1.07,
    16: 1.05,
    17: 1.02,
    18: 1.06,
    19: 2.03,
    20: 1.76,
    21: 1.70,
    22: 1.60,
    23: 1.53,
    24: 1.39,
    25: 1.39,
    26: 1.32,
    27: 1.26,
    28: 1.24,
    29: 1.32,
    30: 1.22,
    31: 1.22,
    32: 1.20,
    33: 1.19,
    34: 1.20,
    35: 1.20,
    36: 1.16,
    37: 2.20,
    38: 1.95,
    39: 1.90,
    40: 1.75,
    41: 1.64,
    42: 1.54,
    43: 1.47,
    44: 1.46,
    45: 1.42,
    46: 1.39,
    47: 1.45,
    48: 1.44,
    49: 1.42,
    50: 1.39,
    51: 1.39,
    52: 1.38,
    53: 1.39,
    54: 1.40,
    55: 2.44,
    56: 2.15,
    57: 2.07,
    58: 2.04,
    59: 2.03,
    60: 2.01,
    61: 1.99,
    62: 1.98,
    63: 1.98,
    64: 1.96,
    65: 1.94,
    66: 1.92,
    67: 1.92,
    68: 1.89,
    69: 1.90,
    70: 1.87,
    71: 1.87,
    72: 1.75,
    73: 1.70,
    74: 1.62,
    75: 1.51,
    76: 1.44,
    77: 1.41,
    78: 1.36,
    79: 1.36,
    80: 1.32,
    81: 1.45,
    82: 1.46,
    83: 1.48,
    90: 2.06,
    92: 1.96,
}

METALS = {
    3,
    4,
    11,
    12,
    13,
    19,
    20,
    *range(21, 31),
    31,
    37,
    38,
    39,
    *range(40, 49),
    49,
    50,
    55,
    56,
    *range(57, 72),
    *range(72, 81),
    81,
    82,
    83,
    *range(87, 104),
}


@dataclass(frozen=True)
class AtomStyle:
    color: Color
    radius: float


@dataclass(frozen=True)
class CrystalAtom:
    symbol: str
    atomic_number: int
    fractional_position: np.ndarray
    cartesian_position: np.ndarray
    occupancy: float
    style: AtomStyle


@dataclass(frozen=True)
class CrystalBond:
    atom1_index: int
    atom2_index: int
    distance: float


@dataclass(frozen=True)
class CrystalStructureScene:
    material_name: str
    cell_vectors: np.ndarray
    cell_vertices: np.ndarray
    cell_edges: tuple[tuple[int, int], ...]
    atoms: tuple[CrystalAtom, ...]
    bonds: tuple[CrystalBond, ...]

    @property
    def points(self) -> np.ndarray:
        atom_points = [atom.cartesian_position for atom in self.atoms]
        return np.vstack([self.cell_vertices, *atom_points])

    @property
    def center(self) -> np.ndarray:
        return np.mean(self.cell_vertices, axis=0)

    @property
    def extent(self) -> float:
        centered = self.points - self.center
        return float(max(np.linalg.norm(centered, axis=1).max(), 1.0))


def crystal_structure_scene(
    material: Any,
    *,
    atom_colors: dict[str | int, Color] | None = None,
    atom_radii: dict[str | int, float] | None = None,
    radius_scale: float = 1.0,
    include_bonds: bool = False,
    bond_cutoff_scale: float = 1.15,
    bond_min_distance: float = 0.35,
    bond_pair_cutoffs: dict[tuple[str | int, str | int], float] | None = None,
    allow_metal_metal_bonds: bool = False,
) -> CrystalStructureScene:
    """Build render-ready crystal structure geometry from a HEXRD Material."""

    if material is None:
        raise ValueError('A material is required')

    cell_vectors = lattice_vectors_from_material(material)
    cell_vertices = unit_cell_vertices(cell_vectors)
    base_atoms = expanded_base_atoms(
        material,
        cell_vectors,
        atom_colors=atom_colors,
        atom_radii=atom_radii,
        radius_scale=radius_scale,
    )
    atoms = display_atoms_from_base_atoms(base_atoms, cell_vectors)
    bonds: tuple[CrystalBond, ...] = ()
    if include_bonds:
        bonds = tuple(
            detect_bonds(
                atoms,
                base_atoms,
                cell_vectors,
                cutoff_scale=bond_cutoff_scale,
                min_distance=bond_min_distance,
                pair_cutoffs=bond_pair_cutoffs,
                allow_metal_metal=allow_metal_metal_bonds,
            )
        )

    name = getattr(material, 'name', '') or 'Material'
    return CrystalStructureScene(
        name,
        cell_vectors,
        cell_vertices,
        CELL_EDGES,
        tuple(atoms),
        bonds,
    )


def lattice_vectors_from_material(material: Any) -> np.ndarray:
    values = lattice_parameters(material)
    a, b, c, alpha, beta, gamma = values
    return lattice_vectors(a, b, c, alpha, beta, gamma)


def lattice_parameters(
    material: Any,
) -> tuple[float, float, float, float, float, float]:
    params = getattr(material, 'latticeParameters', None)
    if params is None:
        params = getattr(material, 'lparms', None)

    if params is None or len(params) != 6:
        raise ValueError('Material must provide six lattice parameters')

    values = []
    for i, value in enumerate(params):
        unit = 'angstrom' if i < 3 else 'degrees'
        if hasattr(value, 'getVal'):
            value = value.getVal(unit)
        values.append(float(value))

    return tuple(values)  # type: ignore[return-value]


def lattice_vectors(
    a: float,
    b: float,
    c: float,
    alpha_deg: float,
    beta_deg: float,
    gamma_deg: float,
) -> np.ndarray:
    alpha = math.radians(alpha_deg)
    beta = math.radians(beta_deg)
    gamma = math.radians(gamma_deg)

    sin_gamma = math.sin(gamma)
    if abs(sin_gamma) < 1.0e-12:
        raise ValueError('Invalid lattice angle gamma')

    avec = np.array([a, 0.0, 0.0], dtype=float)
    bvec = np.array([b * math.cos(gamma), b * sin_gamma, 0.0], dtype=float)

    cx = c * math.cos(beta)
    cy = c * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / sin_gamma
    cz_sq = c * c - cx * cx - cy * cy
    cz = math.sqrt(max(cz_sq, 0.0))
    cvec = np.array([cx, cy, cz], dtype=float)

    return np.vstack([avec, bvec, cvec])


def unit_cell_vertices(cell_vectors: np.ndarray) -> np.ndarray:
    return FRACTIONAL_CORNERS @ cell_vectors


def expanded_atoms(
    material: Any,
    cell_vectors: np.ndarray,
    *,
    atom_colors: dict[str | int, Color] | None = None,
    atom_radii: dict[str | int, float] | None = None,
    radius_scale: float = 1.0,
) -> list[CrystalAtom]:
    base_atoms = expanded_base_atoms(
        material,
        cell_vectors,
        atom_colors=atom_colors,
        atom_radii=atom_radii,
        radius_scale=radius_scale,
    )
    return display_atoms_from_base_atoms(base_atoms, cell_vectors)


def expanded_base_atoms(
    material: Any,
    cell_vectors: np.ndarray,
    *,
    atom_colors: dict[str | int, Color] | None = None,
    atom_radii: dict[str | int, float] | None = None,
    radius_scale: float = 1.0,
) -> list[CrystalAtom]:
    atom_pos = np.asarray(getattr(material, 'atom_pos', []), dtype=float)
    atom_types = np.asarray(getattr(material, 'atom_type', []), dtype=int)

    if atom_pos.size == 0 or atom_types.size == 0:
        return []

    expanded_positions = symmetry_expanded_fractional_positions(material, atom_pos)
    atoms: list[CrystalAtom] = []
    seen: set[tuple[int, tuple[int, int, int]]] = set()

    for i, atomic_number in enumerate(atom_types):
        symbol = ptableinverse[int(atomic_number)]
        occupancy = float(atom_pos[i, 3]) if atom_pos.shape[1] > 3 else 1.0
        if occupancy <= 0:
            continue

        style = atom_style(
            symbol,
            int(atomic_number),
            atom_colors=atom_colors,
            atom_radii=atom_radii,
            radius_scale=radius_scale,
        )

        for frac in expanded_positions[i]:
            frac = normalize_fractional_position(frac)
            key = atom_position_key(int(atomic_number), frac)
            if key in seen:
                continue

            seen.add(key)
            atoms.append(
                create_atom(
                    symbol,
                    int(atomic_number),
                    frac,
                    cell_vectors,
                    occupancy,
                    style,
                )
            )

    return atoms


def display_atoms_from_base_atoms(
    base_atoms: list[CrystalAtom],
    cell_vectors: np.ndarray,
) -> list[CrystalAtom]:
    atoms: list[CrystalAtom] = []
    seen: set[tuple[int, tuple[int, int, int]]] = set()

    for atom in base_atoms:
        for display_frac in unit_cell_translated_positions(atom.fractional_position):
            key = atom_position_key(atom.atomic_number, display_frac)
            if key in seen:
                continue

            seen.add(key)
            atoms.append(
                create_atom(
                    atom.symbol,
                    atom.atomic_number,
                    display_frac,
                    cell_vectors,
                    atom.occupancy,
                    atom.style,
                )
            )

    return atoms


def create_atom(
    symbol: str,
    atomic_number: int,
    fractional_position: np.ndarray,
    cell_vectors: np.ndarray,
    occupancy: float,
    style: AtomStyle,
) -> CrystalAtom:
    return CrystalAtom(
        symbol=symbol,
        atomic_number=atomic_number,
        fractional_position=fractional_position,
        cartesian_position=fractional_position @ cell_vectors,
        occupancy=occupancy,
        style=style,
    )


def detect_bonds(
    atoms: list[CrystalAtom],
    base_atoms: list[CrystalAtom],
    cell_vectors: np.ndarray,
    *,
    cutoff_scale: float = 1.15,
    min_distance: float = 0.35,
    pair_cutoffs: dict[tuple[str | int, str | int], float] | None = None,
    allow_metal_metal: bool = False,
) -> list[CrystalBond]:
    bonds: list[CrystalBond] = []
    atom_by_key = {atom_key(atom): i for i, atom in enumerate(atoms)}
    seen_bonds: set[tuple[tuple[int, tuple[int, int, int]], ...]] = set()
    source_atom_count = len(atoms)

    for atom1_index in range(source_atom_count):
        atom1 = atoms[atom1_index]
        for atom2_base in base_atoms:
            cutoff = bond_cutoff(
                atom1,
                atom2_base,
                cutoff_scale=cutoff_scale,
                pair_cutoffs=pair_cutoffs,
                allow_metal_metal=allow_metal_metal,
            )
            if cutoff is None:
                continue

            for translation in NEIGHBOR_TRANSLATIONS:
                frac2 = atom2_base.fractional_position + translation
                cart2 = frac2 @ cell_vectors
                distance = float(np.linalg.norm(cart2 - atom1.cartesian_position))
                if distance < min_distance or distance > cutoff:
                    continue

                atom2 = create_atom(
                    atom2_base.symbol,
                    atom2_base.atomic_number,
                    frac2,
                    cell_vectors,
                    atom2_base.occupancy,
                    atom2_base.style,
                )
                key2 = atom_key(atom2)
                atom2_index = atom_by_key.get(key2)
                if atom2_index is None:
                    atom2_index = len(atoms)
                    atom_by_key[key2] = atom2_index
                    atoms.append(atom2)

                bond_key = tuple(sorted((atom_key(atom1), key2)))
                if bond_key in seen_bonds:
                    continue

                seen_bonds.add(bond_key)
                bonds.append(CrystalBond(atom1_index, atom2_index, distance))

    return bonds


def bond_cutoff(
    atom1: CrystalAtom,
    atom2: CrystalAtom,
    *,
    cutoff_scale: float,
    pair_cutoffs: dict[tuple[str | int, str | int], float] | None,
    allow_metal_metal: bool,
) -> float | None:
    override = pair_cutoff(atom1, atom2, pair_cutoffs)
    if override is not None:
        return override

    if (
        not allow_metal_metal
        and atom1.atomic_number in METALS
        and atom2.atomic_number in METALS
    ):
        return None

    return (
        covalent_radius(atom1.atomic_number) + covalent_radius(atom2.atomic_number)
    ) * cutoff_scale


def pair_cutoff(
    atom1: CrystalAtom,
    atom2: CrystalAtom,
    pair_cutoffs: dict[tuple[str | int, str | int], float] | None,
) -> float | None:
    if not pair_cutoffs:
        return None

    candidates = [
        (atom1.symbol, atom2.symbol),
        (atom2.symbol, atom1.symbol),
        (atom1.atomic_number, atom2.atomic_number),
        (atom2.atomic_number, atom1.atomic_number),
    ]
    for key in candidates:
        if key in pair_cutoffs:
            return pair_cutoffs[key]

    return None


def covalent_radius(atomic_number: int) -> float:
    radius = COVALENT_RADII.get(atomic_number)
    if radius is not None:
        return radius

    return 0.32 + 0.045 * atomic_number ** (1.0 / 3.0)


def atom_key(atom: CrystalAtom) -> tuple[int, tuple[int, int, int]]:
    return atom_position_key(atom.atomic_number, atom.fractional_position)


def atom_position_key(
    atomic_number: int,
    fractional_position: np.ndarray,
) -> tuple[int, tuple[int, int, int]]:
    return (
        atomic_number,
        tuple(np.round(fractional_position / 1.0e-6).astype(int)),
    )


def symmetry_expanded_fractional_positions(
    material: Any,
    atom_pos: np.ndarray,
) -> list[np.ndarray]:
    unitcell = getattr(material, 'unitcell', None)
    asym_pos = getattr(unitcell, 'asym_pos', None) if unitcell is not None else None

    if asym_pos is not None and len(asym_pos) == len(atom_pos):
        return [np.asarray(positions, dtype=float) for positions in asym_pos]

    return [np.asarray([row[:3]], dtype=float) for row in atom_pos]


def normalize_fractional_position(position: Any) -> np.ndarray:
    frac = np.mod(np.asarray(position, dtype=float), 1.0)
    frac[np.isclose(frac, 1.0, atol=1.0e-8)] = 0.0
    frac[np.isclose(frac, 0.0, atol=1.0e-8)] = 0.0
    return frac


def unit_cell_translated_positions(
    fractional_position: np.ndarray,
    tol: float = 1.0e-8,
) -> list[np.ndarray]:
    positions: list[np.ndarray] = []

    for translation in UNIT_CELL_TRANSLATIONS:
        translated = fractional_position + translation
        if np.all(translated <= 1.0 + tol):
            translated[np.isclose(translated, 1.0, atol=tol)] = 1.0
            positions.append(translated)

    return positions


def atom_style(
    symbol: str,
    atomic_number: int,
    *,
    atom_colors: dict[str | int, Color] | None = None,
    atom_radii: dict[str | int, float] | None = None,
    radius_scale: float = 1.0,
) -> AtomStyle:
    color = override_for_atom(atom_colors, symbol, atomic_number)
    if color is None:
        color = DEFAULT_ATOM_COLORS.get(symbol, generated_atom_color(atomic_number))

    radius = override_for_atom(atom_radii, symbol, atomic_number)
    if radius is None:
        radius = default_atom_radius(atomic_number) * radius_scale

    return AtomStyle(color=tuple(int(x) for x in color), radius=float(radius))


def override_for_atom(
    values: dict[str | int, Any] | None,
    symbol: str,
    atomic_number: int,
) -> Any:
    if not values:
        return None

    for key in (symbol, symbol.lower(), atomic_number):
        if key in values:
            return values[key]

    return None


def default_atom_radius(atomic_number: int) -> float:
    return 0.16 + 0.035 * atomic_number ** (1.0 / 3.0)


def generated_atom_color(atomic_number: int) -> Color:
    hue = (atomic_number * 47) % 360
    return hsv_to_rgb(hue, 0.58, 0.86)


def hsv_to_rgb(h: float, s: float, v: float) -> Color:
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c

    if h < 60:
        rgb = (c, x, 0)
    elif h < 120:
        rgb = (x, c, 0)
    elif h < 180:
        rgb = (0, c, x)
    elif h < 240:
        rgb = (0, x, c)
    elif h < 300:
        rgb = (x, 0, c)
    else:
        rgb = (c, 0, x)

    return tuple(int(round((channel + m) * 255)) for channel in rgb)


FRACTIONAL_CORNERS = np.array(
    [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 1.0, 0.0],
        [1.0, 0.0, 1.0],
        [0.0, 1.0, 1.0],
        [1.0, 1.0, 1.0],
    ],
    dtype=float,
)

UNIT_CELL_TRANSLATIONS = (
    np.array(np.meshgrid([0.0, 1.0], [0.0, 1.0], [0.0, 1.0], indexing='ij'))
    .reshape(3, -1)
    .T
)

NEIGHBOR_TRANSLATIONS = (
    np.array(
        np.meshgrid(
            [-1.0, 0.0, 1.0],
            [-1.0, 0.0, 1.0],
            [-1.0, 0.0, 1.0],
            indexing='ij',
        )
    )
    .reshape(3, -1)
    .T
)

CELL_EDGES = (
    (0, 1),
    (0, 2),
    (0, 3),
    (1, 4),
    (1, 5),
    (2, 4),
    (2, 6),
    (3, 5),
    (3, 6),
    (4, 7),
    (5, 7),
    (6, 7),
)
