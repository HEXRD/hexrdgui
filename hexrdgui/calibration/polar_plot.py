from pathlib import Path
from typing import Any

import h5py
import numpy as np

from .polarview import PolarView

from hexrdgui.calibration.utils.maud_headers import header0, header, block_hdr
from hexrdgui.constants import PolarXAxisType, ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.overlays import update_overlay_data
from hexrdgui.utils.conversions import tth_to_q


def polar_viewer() -> 'InstrumentViewer':
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self) -> None:
        self.type = ViewType.polar
        self.instr = create_hedm_instrument()

        self.draw_polar()

    @property
    def all_detector_borders(self) -> Any:
        return self.pv.all_detector_borders

    @property
    def angular_grid(self) -> Any:
        return self.pv.angular_grid

    @property
    def raw_img(self) -> np.ma.MaskedArray | None:
        return self.pv.raw_img

    @property
    def warp_mask(self) -> np.ndarray:
        return self.pv.warp_mask

    @property
    def snipped_img(self) -> np.ndarray | None:
        return self.pv.snipped_img

    @property
    def img(self) -> np.ndarray:
        img = self.pv.img
        assert img is not None
        return img

    @property
    def display_img(self) -> np.ndarray:
        display_img = self.pv.display_img
        assert display_img is not None
        return display_img

    @property
    def snip_background(self) -> np.ndarray | None:
        return self.pv.snip_background

    @property
    def erosion_mask(self) -> np.ndarray | None:
        return self.pv.erosion_mask

    def update_angular_grid(self) -> None:
        self.pv.update_angular_grid()

    def update_image(self) -> None:
        self.pv.generate_image()

    def reapply_masks(self) -> None:
        self.pv.reapply_masks()

    def draw_polar(self) -> None:
        """show polar view of rings"""
        self.pv = PolarView(self.instr)
        self.pv.warp_all_images()

        '''
        tth_min = HexrdConfig().polar_res_tth_min
        tth_max = HexrdConfig().polar_res_tth_max
        eta_min = HexrdConfig().polar_res_eta_min
        eta_max = HexrdConfig().polar_res_eta_max

        self._extent = [tth_min, tth_max, eta_max, eta_min]  # l, r, b, t
        '''
        self._extent = np.degrees(self.pv.extent)  # l, r, b, t

    def update_overlay_data(self) -> None:
        update_overlay_data(self.instr, self.type)

    def update_detectors(self, detectors: Any) -> None:
        self.pv.update_detectors(detectors)

    def write_image(self, filename: str | Path = 'polar_image.npz') -> None:
        filename = Path(filename)

        data = HexrdConfig().last_unscaled_azimuthal_integral_data
        assert data is not None
        tth, intensities = data

        # Remove any nan values
        mask = intensities.mask
        tth = tth[~mask]
        intensities = intensities.data[~mask]
        azimuthal_integration = np.array((tth, intensities))

        if HexrdConfig().polar_x_axis_type == PolarXAxisType.q:
            # Convert to Q
            azimuthal_integration[0] = tth_to_q(
                azimuthal_integration[0], self.instr.beam_energy
            )

        # Re-format the data so that it is in 2 columns
        azimuthal_integration = azimuthal_integration.T

        # Lineout suffixes and their delimiters
        lineout_suffixes = {
            '.csv': ',',
            '.xy': ' ',
        }
        if filename.suffix in lineout_suffixes:
            # Just save the lineout
            delimiter = lineout_suffixes[filename.suffix]

            # Delete the file if it already exists
            if filename.exists():
                filename.unlink()

            np.savetxt(filename, azimuthal_integration, delimiter=delimiter)
            return

        intensities = self.img
        if np.ma.is_masked(intensities):
            intensities = np.ma.MaskedArray(intensities).filled(np.nan)  # type: ignore[assignment]

        raw_intensities = self.raw_img
        if np.ma.is_masked(raw_intensities):
            raw_intensities = np.ma.MaskedArray(raw_intensities).filled(np.nan)  # type: ignore[assignment]

        eta, tth = np.degrees(self.angular_grid)

        # Prepare the data to write out
        data = {
            'intensities': intensities,
            'azimuthal_integration': azimuthal_integration,
            'extent': self._extent,
            'eta_coordinates': eta,
            'tth_coordinates': tth,
            'q_coordinates': tth_to_q(tth, self.instr.beam_energy),
            'raw_intensities': raw_intensities,
            'warp_mask': self.warp_mask,
            # FIXME: add intensity corrections too later
        }

        if self.snip_background is not None:
            # Add the snip background if it was used
            data['snip_background'] = self.snip_background
            if self.erosion_mask is not None:
                # Also add the erosion mask if it was used
                data['erosion_mask'] = self.erosion_mask

        if HexrdConfig().polar_tth_distortion:
            # Add the tth distortion correction field
            data['tth_corr_field'] = self.pv.create_corr_field_polar()

        # Add polar mask data if we have any
        for name, mask in MaskManager().masks.items():
            if mask.type == MaskType.threshold:
                continue

            if mask.visible:
                data[f'visible_mask_{name}'] = mask.get_masked_arrays(
                    self.type,
                )  # type: ignore[call-arg]
            elif mask.show_border:
                data[f'border_mask_{name}'] = mask.get_masked_arrays(
                    self.type,
                )  # type: ignore[call-arg]
            elif mask.highlight:
                data[f'highlight_mask_{name}'] = mask.get_masked_arrays(
                    self.type,
                )  # type: ignore[call-arg]

        keep_detectors = HexrdConfig().azimuthal_lineout_detectors
        if (
            keep_detectors is not None
            and keep_detectors != HexrdConfig().detector_names
        ):
            keep_str = '; '.join(keep_detectors)
            data['detectors_used_in_azimuthal_integration'] = keep_str

        # Delete the file if it already exists
        if filename.exists():
            filename.unlink()

        # Check the file extension
        if filename.suffix.lower() == '.npz':
            # If it looks like npz, save as npz
            np.savez(filename, **data)
        else:
            # Default to HDF5 format
            with h5py.File(filename, 'w') as f:
                for key, value in data.items():
                    f.create_dataset(key, data=value)

    def write_maud(self, filename: str | Path = 'polar_to_maud.esg') -> None:
        filename = Path(filename)

        with open(filename, 'w') as fid:
            eta_vec = np.degrees(self.angular_grid[0])
            intensities = self.img
            first_block = True
            for i, eta in enumerate(np.average(eta_vec, axis=1).flatten()):
                if np.all(np.isnan(intensities[i])):
                    # Skip this block
                    continue

                if first_block:
                    hstr = header0 % (i, np.linalg.norm(self.pv.tvec_s), eta)
                    first_block = False
                else:
                    hstr = header % (i, eta)

                fid.write(hstr)
                fid.write(block_hdr)
                integral_data = HexrdConfig().last_unscaled_azimuthal_integral_data
                assert integral_data is not None
                tth = integral_data[0]
                for rho, inten in zip(tth, intensities[i]):
                    if np.isnan(inten):
                        continue

                    vals = f' {rho}  {inten}\n'
                    fid.write(vals)
