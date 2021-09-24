import numpy as np

from skimage.exposure import rescale_intensity
from skimage.filters.edges import binary_erosion
from skimage.morphology import rectangle

from hexrd.transforms.xfcapi import detectorXYToGvec, mapAngle

from hexrd import constants as ct
from hexrd.xrdutil import _project_on_detector_plane

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.utils import SnipAlgorithmType, run_snip1d, snip_width_pixels

tvec_c = ct.zeros_3


def sqrt_scale_img(img):
    fimg = np.array(img, dtype=float)
    fimg = fimg - np.min(fimg)
    return np.sqrt(fimg)


def log_scale_img(img):
    fimg = np.array(img, dtype=float)
    fimg = fimg - np.min(fimg) + 1.
    return np.log(fimg)


class PolarView:
    """Create (two-theta, eta) plot of detectors
    """

    def __init__(self, instrument):

        self.instr = instrument

        self.images_dict = HexrdConfig().images_dict

        self.warp_dict = {}

        self.raw_img = None
        self.snipped_img = None
        self.processed_img = None

        self.snip_background = None

        self.update_angular_grid()

    @property
    def detectors(self):
        return self.instr.detectors

    @property
    def chi(self):
        return self.instr.chi

    @property
    def tvec_s(self):
        return self.instr.tvec

    @property
    def tth_min(self):
        return np.radians(HexrdConfig().polar_res_tth_min)

    @property
    def tth_max(self):
        return np.radians(HexrdConfig().polar_res_tth_max)

    @property
    def tth_range(self):
        return self.tth_max - self.tth_min

    @property
    def tth_pixel_size(self):
        return HexrdConfig().polar_pixel_size_tth

    def tth_to_pixel(self, tth):
        """
        convert two-theta value to pixel value (float) along two-theta axis
        """
        return np.degrees(tth - self.tth_min) / self.tth_pixel_size

    @property
    def eta_min(self):
        return np.radians(HexrdConfig().polar_res_eta_min)

    @property
    def eta_max(self):
        return np.radians(HexrdConfig().polar_res_eta_max)

    @property
    def eta_range(self):
        return self.eta_max - self.eta_min

    @property
    def eta_pixel_size(self):
        return HexrdConfig().polar_pixel_size_eta

    def eta_to_pixel(self, eta):
        """
        convert eta value to pixel value (float) along eta axis
        """
        return np.degrees(eta - self.eta_min) / self.eta_pixel_size

    @property
    def ntth(self):
        return int(np.degrees(self.tth_range) / self.tth_pixel_size)

    @property
    def neta(self):
        return int(np.degrees(self.eta_range) / self.eta_pixel_size)

    @property
    def shape(self):
        return (self.neta, self.ntth)

    def update_angular_grid(self):
        tth_vec = np.radians(self.tth_pixel_size * (np.arange(self.ntth)))\
            + self.tth_min + 0.5 * np.radians(self.tth_pixel_size)
        eta_vec = np.radians(self.eta_pixel_size * (np.arange(self.neta)))\
            + self.eta_min + 0.5 * np.radians(self.eta_pixel_size)
        self._angular_grid = np.meshgrid(eta_vec, tth_vec, indexing='ij')

    @property
    def angular_grid(self):
        return self._angular_grid

    @property
    def eta_period(self):
        return HexrdConfig().polar_res_eta_period

    @property
    def images_dict(self):
        return self._images_dict

    @images_dict.setter
    def images_dict(self, v):
        self._images_dict = v

        # Cache the image min and max for later use
        self.min = min(x.min() for x in v.values())
        self.max = max(x.max() for x in v.values())

    def detector_borders(self, det):
        panel = self.detectors[det]

        row_vec, col_vec = panel.row_pixel_vec, panel.col_pixel_vec
        x_start, x_stop = col_vec[0], col_vec[-1]
        y_start, y_stop = row_vec[0], row_vec[-1]

        # Create the borders in Cartesian
        borders = [
            [[x, y_start] for x in col_vec],
            [[x, y_stop] for x in col_vec],
            [[x_start, y] for y in row_vec],
            [[x_stop, y] for y in row_vec]
        ]

        # Convert each border to angles
        for i, border in enumerate(borders):
            angles, _ = detectorXYToGvec(
                border, panel.rmat, ct.identity_3x3,
                panel.tvec, ct.zeros_3, ct.zeros_3,
                beamVec=panel.bvec, etaVec=panel.evec)
            angles = np.array(angles)
            angles[1:, :] = mapAngle(
                angles[1:, :], np.radians(self.eta_period), units='radians'
            )
            # Convert to degrees, and keep them as lists for
            # easier modification later
            borders[i] = np.degrees(angles).tolist()

        # Here, we are going to remove points that are out-of-bounds,
        # and we are going to insert None in between points that are far
        # apart (in the y component), so that they are not connected in the
        # plot. This happens for detectors that are wrapped in the image.
        x_range = np.degrees((self.tth_min, self.tth_max))
        y_range = np.degrees((self.eta_min, self.eta_max))

        # "Far apart" is currently defined as half of the y range
        max_y_distance = abs(y_range[1] - y_range[0]) / 2.0
        for j in range(4):
            border_x, border_y = borders[j][0], borders[j][1]
            i = 0
            # These should be the same length, but just in case...
            while i < len(border_x) and i < len(border_y):
                x, y = border_x[i], border_y[i]
                if (not x_range[0] <= x <= x_range[1] or
                        not y_range[0] <= y <= y_range[1]):
                    # The point is out of bounds, remove it
                    del border_x[i], border_y[i]
                    continue

                if i != 0 and abs(y - border_y[i - 1]) > max_y_distance:
                    # Points are too far apart. Insert a None
                    border_x.insert(i, None)
                    border_y.insert(i, None)
                    i += 1

                i += 1

        return borders

    @property
    def all_detector_borders(self):
        borders = {}
        for key in self.images_dict.keys():
            borders[key] = self.detector_borders(key)

        return borders

    def create_warp_image(self, det):
        angpts = self.angular_grid
        dummy_ome = np.zeros((self.ntth * self.neta))

        # lcount = 0
        panel = self.detectors[det]
        img = self.images_dict[det]

        gvec_angs = np.vstack([
                angpts[1].flatten(),
                angpts[0].flatten(),
                dummy_ome]).T

        xypts = np.nan*np.ones((len(gvec_angs), 2))
        valid_xys, rmats_s, on_plane = _project_on_detector_plane(
                gvec_angs,
                panel.rmat, np.eye(3),
                self.chi,
                panel.tvec, tvec_c, self.tvec_s,
                panel.distortion,
                beamVec=panel.bvec)
        xypts[on_plane] = valid_xys

        wimg = panel.interpolate_bilinear(
            xypts, img, pad_with_nans=True,
        ).reshape(self.shape)
        nan_mask = np.isnan(wimg)

        # Store as masked array
        self.warp_dict[det] = np.ma.masked_array(
            data=wimg, mask=nan_mask, fill_value=0.
        )
        return self.warp_dict[det]

    def generate_image(self):
        # sum masked images in self.warp_dict using np.ma ufuncs
        #
        # !!! checked that np.ma.sum is applying logical OR across masks (JVB)
        # !!! assignment to img fills NaNs with zeros
        # !!! NOTE: cannot set `data` attribute on masked_array,
        #           but can manipulate mask
        self.raw_img = np.ma.sum(np.ma.stack(self.warp_dict.values()), axis=0)
        self.apply_image_processing()

    @property
    def raw_rescaled_img(self):
        return self.apply_rescale(self.raw_img.data)

    @property
    def raw_mask(self):
        return self.raw_img.mask

    def apply_image_processing(self):
        img = self.raw_rescaled_img
        img = self.apply_snip(img)
        # cache this step so we can just re-apply masks if needed
        self.snipped_img = img

        img = self.apply_masks(img)

        self.processed_img = img

    def apply_rescale(self, img):
        # Rescale the data to match the scale of the original dataset
        kwargs = {
            'image': img,
            'in_range': (np.nanmin(img), np.nanmax(img)),
            'out_range': (self.min, self.max),
        }
        return rescale_intensity(**kwargs)

    def apply_snip(self, img):
        # do SNIP if requested
        img = img.copy()
        if HexrdConfig().polar_apply_snip1d:
            # !!! Fast snip1d (ndimage) cannot handle nans
            no_nan_methods = [SnipAlgorithmType.Fast_SNIP_1D]

            if HexrdConfig().polar_snip1d_algorithm not in no_nan_methods:
                img[self.raw_mask] = np.nan

            # Perform the background subtraction
            self.snip_background = run_snip1d(img)
            img -= self.snip_background

            if HexrdConfig().polar_apply_erosion:
                niter = HexrdConfig().polar_snip1d_numiter
                structure = rectangle(
                    1,
                    int(2.1 * niter * snip_width_pixels()),
                )
                mask = binary_erosion(~self.raw_img.mask, structure)
                img[~mask] = 0

        else:
            self.snip_background = None

        return img

    def apply_masks(self, img):
        # Apply user-specified masks if they are present
        img = img.copy()
        total_mask = self.raw_mask
        for mask in HexrdConfig().visible_masks:
            total_mask = np.logical_or(total_mask, ~mask)
        img[total_mask] = np.nan

        return img

    def reapply_masks(self):
        # This will only re-run the final step of applying masks...
        if self.snipped_img is None:
            return

        self.processed_img = self.apply_masks(self.snipped_img)

    @property
    def img(self):
        return self.processed_img

    def warp_all_images(self):
        # Create the warped image for each detector
        for det in self.images_dict.keys():
            self.create_warp_image(det)

        # Generate the final image
        self.generate_image()

    def update_images_dict(self):
        if HexrdConfig().any_intensity_corrections:
            self.images_dict = HexrdConfig().images_dict

    def update_detector(self, det):
        # If there are intensity corrections and the detector transform
        # has been modified, we need to update the images dict.
        self.update_images_dict()

        # First, convert to the "None" angle convention
        iconfig = HexrdConfig().instrument_config_none_euler_convention

        t_conf = iconfig['detectors'][det]['transform']
        self.instr.detectors[det].tvec = t_conf['translation']
        self.instr.detectors[det].tilt = t_conf['tilt']

        # Update the individual detector image
        self.create_warp_image(det)

        # Generate the final image
        self.generate_image()
