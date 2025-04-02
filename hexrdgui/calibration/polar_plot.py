from pathlib import Path

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


def polar_viewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = ViewType.polar
        self.instr = create_hedm_instrument()

        self.draw_polar()

    @property
    def all_detector_borders(self):
        return self.pv.all_detector_borders

    @property
    def angular_grid(self):
        return self.pv.angular_grid

    @property
    def raw_img(self):
        return self.pv.raw_img

    @property
    def warp_mask(self):
        return self.pv.warp_mask

    @property
    def snipped_img(self):
        return self.pv.snipped_img

    @property
    def img(self):
        return self.pv.img

    @property
    def display_img(self):
        return self.pv.display_img

    @property
    def snip_background(self):
        return self.pv.snip_background

    @property
    def erosion_mask(self):
        return self.pv.erosion_mask

    def update_angular_grid(self):
        self.pv.update_angular_grid()

    def update_image(self):
        self.pv.generate_image()

    def reapply_masks(self):
        self.pv.reapply_masks()

    def draw_polar(self):
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

    def update_overlay_data(self):
        update_overlay_data(self.instr, self.type)

    def update_detectors(self, detectors):
        self.pv.update_detectors(detectors)

    def write_image(self, filename='polar_image.npz'):
        filename = Path(filename)

        tth, intensities = (
            HexrdConfig().last_unscaled_azimuthal_integral_data
        )

        # Remove any nan values
        mask = intensities.mask
        tth = tth[~mask]
        intensities = intensities.data[~mask]
        azimuthal_integration = np.array((tth, intensities))

        if HexrdConfig().polar_x_axis_type == PolarXAxisType.q:
            # Convert to Q
            azimuthal_integration[0] = tth_to_q(azimuthal_integration[0],
                                                self.instr.beam_energy)

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
            intensities = intensities.filled(np.nan)

        raw_intensities = self.raw_img
        if np.ma.is_masked(raw_intensities):
            raw_intensities = raw_intensities.filled(np.nan)

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
                )
            elif mask.show_border:
                data[f'border_mask_{name}'] = mask.get_masked_arrays(
                    self.type,
                )

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

    def write_maud(self, filename='polar_to_maud.esg'):
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
                tth = HexrdConfig().last_unscaled_azimuthal_integral_data[0]
                for rho, inten in zip(tth, intensities[i]):
                    if np.isnan(inten):
                        continue

                    vals = f' {rho}  {inten}\n'
                    fid.write(vals)
