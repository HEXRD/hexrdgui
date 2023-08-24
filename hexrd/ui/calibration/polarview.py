import numpy as np

from skimage.filters.edges import binary_erosion
from skimage.morphology import rectangle
from skimage.transform import warp

from hexrd.transforms.xfcapi import mapAngle

from hexrd import constants as ct
from hexrd.xrdutil import (
    _project_on_detector_plane, _project_on_detector_cylinder
)
from hexrd import instrument

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

    The distortion instrument is the instrument to use for tth distortion.
    It defaults to the instrument.
    """

    def __init__(self, instrument, distortion_instrument=None):

        self.instr = instrument

        if distortion_instrument is None:
            distortion_instrument = instrument

        self.distortion_instr = distortion_instrument

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
        return int(round(np.degrees(self.tth_range) / self.tth_pixel_size))

    @property
    def neta(self):
        return int(round(np.degrees(self.eta_range) / self.eta_pixel_size))

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
    def extent(self):
        ev, tv = self.angular_grid
        heps = np.radians(0.5*self.eta_pixel_size)
        htps = np.radians(0.5*self.tth_pixel_size)
        return [np.min(tv) - htps, np.max(tv) + htps,
                np.max(ev) + heps, np.min(ev) - heps]

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

        row_vec, col_vec = panel.row_edge_vec, panel.col_edge_vec

        # Create the borders in Cartesian
        borders = [
            np.vstack((col_vec, np.full(col_vec.shape, row_vec[0]))).T,
            np.vstack((col_vec, np.full(col_vec.shape, row_vec[-1]))).T,
            np.vstack((np.full(row_vec.shape, col_vec[0]), row_vec)).T,
            np.vstack((np.full(row_vec.shape, col_vec[-1]), row_vec)).T,
        ]

        # Convert each border to angles
        for i, border in enumerate(borders):
            angles, _ = panel.cart_to_angles(border)
            angles = angles.T
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
        for i, border in enumerate(borders):
            border_x = border[0]
            border_y = border[1]

            # Remove any points out of bounds
            in_range_x = np.logical_and(x_range[0] <= border_x,
                                        border_x <= x_range[1])
            in_range_y = np.logical_and(y_range[0] <= border_y,
                                        border_y <= y_range[1])
            in_range = np.logical_and(in_range_x, in_range_y)

            # Insert nans for points far apart
            border = np.asarray(border).T[in_range].T
            big_diff = np.argwhere(np.abs(np.diff(border[1])) > max_y_distance)
            if big_diff.size != 0:
                border = np.insert(border.T, big_diff.squeeze() + 1, np.nan,
                                   axis=0).T

            borders[i] = border

        return borders

    @property
    def all_detector_borders(self):
        borders = {}
        for key in self.images_dict.keys():
            borders[key] = self.detector_borders(key)

        return borders

    def create_warp_image(self, det):
        # lcount = 0
        img = self.images_dict[det]
        panel = self.detectors[det]

        self.warp_dict[det] = self.warp_image(img, panel)
        return self.warp_dict[det]

    def func_project_on_detector(self, detector):
        '''
        helper function to decide which function to
        use for mapping of g-vectors to detector
        '''
        if isinstance(detector, instrument.CylindricalDetector):
            return _project_on_detector_cylinder
        else:
            return _project_on_detector_plane

    def args_project_on_detector(self, detector):
        """
        prepare the arguments to be passed for
        mapping to plane or cylinder
        """
        kwargs = {'beamVec': detector.bvec}
        arg = (detector.rmat,
               ct.identity_3x3,
               self.chi,
               detector.tvec,
               tvec_c,
               self.tvec_s,
               detector.distortion)
        if isinstance(detector, instrument.CylindricalDetector):
            arg = (self.chi,
                   detector.tvec,
                   detector.caxis,
                   detector.paxis,
                   detector.radius,
                   detector.physical_size,
                   detector.angle_extent,
                   detector.distortion)
            kwargs = {'beamVec': detector.bvec,
                      'tVec_s': self.tvec_s,
                      'tVec_c': tvec_c,
                      'rmat_s': ct.identity_3x3}

        return arg, kwargs

    def warp_image(self, img, panel):
        # The first 3 arguments of this function get converted into
        # the first argument of `_project_on_detector_plane`, and then
        # the rest are just passed as *args and **kwargs.
        args, kwargs = self.args_project_on_detector(panel)
        func_projection = self.func_project_on_detector(panel)

        xypts = project_on_detector(
                    self.angular_grid,
                    self.ntth,
                    self.neta,
                    func_projection,
                    *args,
                    **kwargs)

        wimg = panel.interpolate_bilinear(
            xypts, img, pad_with_nans=True,
        ).reshape(self.shape)
        nan_mask = np.isnan(wimg)
        # Store as masked array
        return np.ma.masked_array(
            data=wimg, mask=nan_mask, fill_value=0.
        )

    def create_corr_field_polar(self):
        obj = HexrdConfig().polar_tth_distortion_object

        if obj.has_polar_pinhole_displacement_field:
            # Compute the polar tth displacement field directly
            eta, tth = self.angular_grid
            corr_field_polar = obj.create_polar_pinhole_displacement_field(
                self.distortion_instr, tth, eta
            )

            # Mask out nan values
            mask = np.isnan(corr_field_polar)
            corr_field_polar = np.ma.masked_array(corr_field_polar, mask=mask)
        else:
            # Get the tth displacement field for each detector, and then warp
            # them to the polar view.
            corr_field = obj.pinhole_displacement_field(self.distortion_instr)

            corr_field_polar_dict = {}
            for key in corr_field:
                panel = self.detectors[key]
                corr_field_polar_dict[key] = self.warp_image(corr_field[key],
                                                             panel)

            corr_field_polar = np.ma.sum(np.ma.stack(
                corr_field_polar_dict.values()), axis=0)

        return corr_field_polar

    def apply_tth_distortion(self, pimg):
        if not HexrdConfig().polar_tth_distortion:
            # We are not applying tth distortion. Return the same image.
            return pimg

        corr_field_polar = self.create_corr_field_polar()

        # Save these so that the overlay generator may use them
        HexrdConfig().polar_corr_field_polar = corr_field_polar
        HexrdConfig().polar_angular_grid = self.angular_grid

        nr, nc = pimg.shape
        row_coords, col_coords = np.meshgrid(np.arange(nr), np.arange(nc),
                                             indexing='ij')
        displ_field = np.array(
            [row_coords,
             col_coords - np.degrees(corr_field_polar) / self.tth_pixel_size]
        )

        # mask_warp = warp(pimg.mask, displ_field, mode='edge')
        image1_warp = warp(pimg, displ_field, mode='edge')

        return np.ma.array(image1_warp)  # , mask=mask_warp)

    def generate_image(self):
        self.reset_cached_distortion_fields()

        # sum masked images in self.warp_dict using np.ma ufuncs
        #
        # !!! checked that np.ma.sum is applying logical OR across masks (JVB)
        # !!! assignment to img fills NaNs with zeros
        # !!! NOTE: cannot set `data` attribute on masked_array,
        #           but can manipulate mask
        self.raw_img = np.ma.sum(np.ma.stack(self.warp_dict.values()), axis=0)
        self.apply_image_processing()

    @property
    def raw_mask(self):
        return self.raw_img.mask

    def apply_image_processing(self):
        img = self.raw_img.data
        img = self.apply_snip(img)
        # cache this step so we can just re-apply masks if needed
        self.snipped_img = img

        # Apply the masks before the polar_tth_distortion, because the
        # masks should also be distorted as well.
        img = self.apply_masks(img)

        img = self.apply_tth_distortion(img)

        self.processed_img = img

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

            # FIXME: the erosion should be applied as a mask,
            #        NOT done inside snip computation!
            if HexrdConfig().polar_apply_erosion:
                niter = HexrdConfig().polar_snip1d_numiter
                structure = rectangle(
                    1,
                    int(np.ceil(2.25*niter*snip_width_pixels()))
                )
                mask = binary_erosion(~self.raw_img.mask, structure)
                img[~mask] = np.nan

        else:
            self.snip_background = None

        return img

    def apply_masks(self, img):
        # Apply user-specified masks if they are present
        img = img.copy()
        total_mask = self.raw_mask
        for name in HexrdConfig().visible_masks:
            if name not in HexrdConfig().masks:
                continue
            mask = HexrdConfig().masks[name]
            total_mask = np.logical_or(total_mask, ~mask)
        if HexrdConfig().threshold_mask_status:
            lt_val, gt_val = HexrdConfig().threshold_values
            lt_mask = img < lt_val
            gt_mask = img > gt_val
            mask = np.logical_or(lt_mask, gt_mask)
            total_mask = np.logical_or(total_mask, mask)
        img[total_mask] = np.nan

        return img

    def reapply_masks(self):
        # This will only re-run the final steps of the processing...
        if self.snipped_img is None:
            return

        # Apply the masks before the polar_tth_distortion, because the
        # masks should also be distorted as well.
        img = self.apply_masks(self.snipped_img)

        img = self.apply_tth_distortion(img)

        self.processed_img = img

    @property
    def img(self):
        return self.processed_img

    def warp_all_images(self):
        self.reset_cached_distortion_fields()

        # Create the warped image for each detector
        for det in self.images_dict.keys():
            self.create_warp_image(det)

        # Generate the final image
        self.generate_image()

    def update_images_dict(self):
        if HexrdConfig().any_intensity_corrections:
            self.images_dict = HexrdConfig().images_dict

    def update_detector(self, det):
        self.reset_cached_distortion_fields()

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

    def reset_cached_distortion_fields(self):
        HexrdConfig().polar_corr_field_polar = None
        HexrdConfig().polar_angular_grid = None


# `_project_on_detector_plane()` is one of the functions that takes the
# longest when generating the polar view.
# Memoize this so we can regenerate the polar view faster
# @memoize(maxsize=16)
def project_on_detector(angular_grid,
                        ntth, neta,
                        func_projection,
                        *args, **kwargs):
    # This will take `angular_grid`, `ntth`, and `neta`, and make the
    # `gvec_angs` argument with them. Then, the `gvec_args` will be passed
    # first to `_project_on_detector_plane`, along with any extra args and
    # kwargs.
    dummy_ome = np.zeros((ntth * neta))

    gvec_angs = np.vstack([
            angular_grid[1].flatten(),
            angular_grid[0].flatten(),
            dummy_ome]).T

    xypts = np.nan * np.ones((len(gvec_angs), 2))
    valid_xys, rmats_s, on_plane = func_projection(
        gvec_angs, *args, **kwargs)
    xypts[on_plane] = valid_xys

    return xypts
