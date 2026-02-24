from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
from hexrd.rotations import mapAngle

from hexrdgui.constants import ViewType
from hexrdgui.create_hedm_instrument import (
    create_hedm_instrument,
    create_view_hedm_instrument,
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays import update_overlay_data
from hexrdgui.utils.conversions import angles_to_stereo, cart_to_angles

from .polarview import PolarView
from .stereo_project import stereo_project, stereo_projection_of_polar_view


def stereo_viewer() -> "InstrumentViewer":
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self) -> None:
        self.type = ViewType.stereo

        # This instrument is used to generate the overlays and other things
        self.instr = create_hedm_instrument()

        # This instrument has a VISAR view and is used to generate the image
        self.instr_pv = create_view_hedm_instrument()
        self.pv: PolarView | None = None
        self.img: np.ndarray | None = None

        self.draw_stereo()

    @property
    def extent(self) -> list[int]:
        return [0, self.stereo_size, 0, self.stereo_size]

    @property
    def raw_img_dict(self) -> dict:
        return HexrdConfig().masked_images_dict

    @property
    def stereo_size(self) -> int:
        return HexrdConfig().stereo_size

    @property
    def eta_period(self) -> np.ndarray:
        return HexrdConfig().polar_res_eta_period

    @property
    def project_from_polar(self) -> bool:
        return HexrdConfig().stereo_project_from_polar

    @property
    def display_img(self) -> np.ndarray | None:
        return self.img

    def detector_borders(self, det: str) -> list[np.ndarray]:
        panel = self.instr_pv.detectors[det]

        # First, create the polar view version of the borders
        # (this skips some things like trimming based upon
        # tth/eta min/max)
        row_vec, col_vec = panel.row_pixel_vec, panel.col_pixel_vec
        x_start, x_stop = col_vec[0], col_vec[-1]
        y_start, y_stop = row_vec[0], row_vec[-1]

        # Create the borders in Cartesian
        raw_borders: list[np.ndarray] = [
            np.array([[x, y_start] for x in col_vec]),
            np.array([[x, y_stop] for x in col_vec]),
            np.array([[x_start, y] for y in row_vec]),
            np.array([[x_stop, y] for y in row_vec]),
        ]

        # Convert each border to angles, then stereo
        borders: list[np.ndarray] = []
        for border in raw_borders:
            angles = np.radians(
                cart_to_angles(
                    border,
                    panel,
                    self.eta_period,
                    tvec_s=self.instr_pv.tvec,
                )
            )
            borders.append(angles_to_stereo(angles, self.instr_pv, self.stereo_size).T)

        return borders

    @property
    def all_detector_borders(self) -> dict[str, list[np.ndarray]]:
        borders = {}
        for key in self.instr_pv.detectors:
            borders[key] = self.detector_borders(key)

        return borders

    def draw_stereo(self) -> None:
        if self.project_from_polar:
            self.draw_stereo_from_polar()
        else:
            self.draw_stereo_from_raw()

        self.fill_image_with_nans()

    def draw_stereo_from_raw(self) -> None:
        self.img = stereo_project(
            **{
                'instr': self.instr_pv,
                'raw': self.raw_img_dict,
                'stereo_size': self.stereo_size,
            }
        )

    def prep_eta_grid(
        self, eta_grid: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        this function formats the eta grid in a
        range such that
        """
        eta_grid = mapAngle(eta_grid, (0, 360.0), units='degrees')
        idx = np.argsort(eta_grid)
        eta_grid = eta_grid[idx]

        mask = np.zeros(eta_grid.shape, dtype=bool)
        eta_grid, iduq = np.unique(eta_grid, return_index=True)
        mask[iduq] = True
        return eta_grid, idx, mask

    def pad_etas_pvarray(
        self, eta_grid: np.ndarray, polar_img: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        start = np.array([eta_grid[-1] - 360])
        end = np.array([360 + eta_grid[0]])

        start_padded = False
        end_padded = False

        padded = []
        if not np.isclose(start, eta_grid[0]):
            padded.append(start)
            start_padded = True

        padded.append(eta_grid)
        if not np.isclose(end, eta_grid[-1]):
            padded.append(end)
            end_padded = True

        if not start_padded and not end_padded:
            # No padding. Exit early
            return eta_grid, polar_img

        eta_grid = np.concatenate(padded)

        p_padded = []
        if start_padded:
            pstart = np.atleast_2d(polar_img[-1, :])
            p_padded.append(pstart)

        p_padded.append(polar_img)

        if end_padded:
            pstop = np.atleast_2d(polar_img[0, :])
            p_padded.append(pstop)

        polar_img = np.vstack(p_padded)
        return eta_grid, polar_img

    def draw_stereo_from_polar(self) -> None:
        # We need to make sure `self.pv` is always updated when it needs
        # to be. But that can be done elsewhere.
        if self.pv is None:
            # Don't redraw the polar view unless we have to
            self.draw_polar()

        assert self.pv is not None
        polar_img = self.pv.display_img
        assert polar_img is not None

        extent = np.degrees(self.pv.extent)
        tth_range = extent[:2]
        eta_range = np.sort(extent[2:])

        tth_grid = np.linspace(
            float(tth_range[0]),
            float(tth_range[1]),
            polar_img.shape[1],
        )
        eta_grid = np.linspace(
            float(eta_range[0]),
            float(eta_range[1]),
            polar_img.shape[0],
        )

        eta_grid, idx, mask = self.prep_eta_grid(eta_grid)

        polar_img = polar_img[idx, :]
        polar_img = polar_img[mask, :]

        eta_grid, polar_img = self.pad_etas_pvarray(eta_grid, polar_img)

        self.img = stereo_projection_of_polar_view(
            **{
                'pvarray': polar_img,
                'tth_grid': tth_grid,
                'eta_grid': eta_grid,
                'instr': self.instr_pv,
                'stereo_size': self.stereo_size,
            }
        )

    def draw_polar(self) -> None:
        self.pv = PolarView(
            self.instr_pv,
            distortion_instrument=self.instr,
            # Always use full eta range for the stereo view
            eta_min=0,
            eta_max=np.pi * 2,
        )
        self.pv.warp_all_images()

    def reapply_masks(self) -> None:
        if not self.pv or not self.project_from_polar:
            return

        self.pv.reapply_masks()
        self.draw_stereo()

    def fill_image_with_nans(self) -> None:
        # If the image is a masked array, fill it with nans
        if isinstance(self.img, np.ma.masked_array):
            self.img = self.img.filled(np.nan)

    def update_overlay_data(self) -> None:
        update_overlay_data(self.instr, self.type)

    def update_detectors(self, detectors: list[str]) -> None:
        if self.project_from_polar and self.pv is not None:
            self.pv.update_detectors(detectors)

        self.draw_stereo()

    def write_image(self, filename: str | Path) -> None:
        filename = Path(filename)

        assert self.img is not None

        # Prepare the data to write out
        data = {
            'intensities': self.img,
        }

        # Delete the file if it already exists
        if filename.exists():
            filename.unlink()

        # Check the file extension
        ext = filename.suffix.lower()

        if ext == '.npz':
            # If it looks like npz, save as npz
            np.savez(filename, **data)  # type: ignore[arg-type]
        else:
            # Default to HDF5 format
            with h5py.File(filename, 'w') as f:
                for key, value in data.items():
                    f.create_dataset(key, data=value)
