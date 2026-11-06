"""Bridge the map viewers and saved archives to HEXRD's numeric map model."""

import copy
from os import PathLike

import numpy as np

from hexrd.core.constants import sigma_to_fwhm
from hexrd.core.material.crystallography import PlaneData as LegacyPlaneData
from hexrd.core.material.material_data import PlaneData
from hexrd.core.valunits import valWUnit
from hexrd.hedm.find_orientations import EtaOmegaMaps, _filter_maps


def normalize_filter_config(config: dict) -> None:
    """Translate the GUI's saved Gaussian sigma to the library's FWHM."""
    value = config.get('filter_maps', False)
    if value is not None and not isinstance(value, bool):
        config['filter_maps'] = bool(value)
        config['filter_fwhm'] = float(value) * sigma_to_fwhm if value else None


class EtaOmeMaps:
    """Map data with the accessors used by the viewers and picking tools.

    The archive schema remains compatible with existing HEXRD map files.
    Scientific stages receive an EtaOmegaMaps through ``to_maps()``.
    """

    dataStore: np.ndarray
    iHKLList: np.ndarray
    etaEdges: np.ndarray
    omeEdges: np.ndarray
    etas: np.ndarray
    omegas: np.ndarray

    def __init__(self, filename: str | PathLike[str]) -> None:
        with np.load(filename, allow_pickle=True) as archive:
            self.planeData = LegacyPlaneData(
                archive['planeData_hkls'], *archive['planeData_args']
            )
            self.planeData.exclusions = archive['planeData_excl']
            for name in (
                'dataStore',
                'iHKLList',
                'etaEdges',
                'omeEdges',
                'etas',
                'omegas',
            ):
                setattr(self, name, archive[name])
        self._eta_step = float(self.etas[1] - self.etas[0])

    @classmethod
    def from_maps(cls, maps: EtaOmegaMaps, plane_data: LegacyPlaneData) -> 'EtaOmeMaps':
        result = cls.__new__(cls)
        result.planeData = copy.deepcopy(plane_data)
        result.dataStore = maps.ring_maps
        numeric_plane_data = maps.plane_data or PlaneData.from_plane_data(plane_data)
        result.iHKLList = numeric_plane_data.master_hkl_ids[maps.ring_ids]
        result.etaEdges = maps.eta_edges
        result.omeEdges = maps.omega_edges
        result.etas = maps.eta_edges[:-1] + 0.5 * maps.eta_step
        # Subtracting adjacent centers loses precision and can change which
        # generated trial orientations are considered duplicates.
        result._eta_step = maps.eta_step
        result.omegas = maps.omegas
        return result

    def to_maps(self) -> EtaOmegaMaps:
        plane_data = PlaneData.from_plane_data(self.planeData)
        ring_of_hkl = {h: i for i, h in enumerate(plane_data.master_hkl_ids)}
        ring_ids = np.array([ring_of_hkl[h] for h in self.iHKLList], dtype=np.intp)
        tths = plane_data.two_thetas[~plane_data.exclusions][ring_ids]
        width = self.planeData.tThWidth
        half_width = (width if width is not None else np.radians(0.25)) / 2
        return EtaOmegaMaps(
            np.asarray(self.dataStore, dtype=np.float64),
            self.etaEdges,
            self.omeEdges,
            self.omegas,
            self.omeEdges[0] + np.array([0.0, 2 * np.pi]),
            np.column_stack((tths - half_width, tths + half_width)),
            ring_ids,
            self._eta_step,
            plane_data,
        )

    def save_eta_ome_maps(self, filename: str | PathLike[str]) -> None:
        args = np.array(self.planeData.getParams(), dtype=object)[:4]
        args[2] = valWUnit('wavelength', 'length', args[2], 'angstrom')
        np.savez_compressed(
            filename,
            dataStore=self.dataStore,
            etas=self.etas,
            etaEdges=self.etaEdges,
            iHKLList=self.iHKLList,
            omegas=self.omegas,
            omeEdges=self.omeEdges,
            planeData_args=args,
            planeData_hkls=np.vstack(
                [entry['hkl'] for entry in self.planeData.hklDataList]
            ).T,
            planeData_excl=self.planeData.exclusions,
        )


def filter_maps(maps: EtaOmeMaps, config: dict) -> None:
    config = config.copy()
    normalize_filter_config(config)
    numeric_maps = maps.to_maps()
    _filter_maps(
        numeric_maps, bool(config.get('filter_maps')), config.get('filter_fwhm')
    )
    maps.dataStore = numeric_maps.ring_maps
