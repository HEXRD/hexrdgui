import numpy as np

from skimage.filters.edges import binary_erosion
from skimage.morphology import footprint_rectangle
from skimage.transform import warp

from hexrd.transforms.xfcapi import mapAngle
from hexrd.utils.decorators import memoize
from hexrd.utils.warnings import ignore_warnings

from hexrd import constants as ct
from hexrd.xrdutil import (
    _project_on_detector_plane, _project_on_detector_cylinder
)
from hexrd import instrument

from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType
from hexrdgui.utils import SnipAlgorithmType, run_snip1d, snip_width_pixels

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

    eta_min and eta_max are in radians. If not provided, the ones on
    HexrdConfig() are used.
    """

    def __init__(self,
                 instrument,
                 distortion_instrument=None,
                 eta_min: float | None = None,
                 eta_max: float | None = None,
    ):

        if distortion_instrument is None:
            distortion_instrument = instrument

        if eta_min is None:
            eta_min = np.radians(HexrdConfig().polar_res_eta_min)

        if eta_max is None:
            eta_max = np.radians(HexrdConfig().polar_res_eta_max)

        self.instr = instrument
        self.distortion_instr = distortion_instrument
        self.eta_min = eta_min
        self.eta_max = eta_max

        if instrument is None:
            # This is a dummy polar view
            self._images_dict = None
        else:
            # Use an image dict with the panel buffers applied.
            # This keeps invalid pixels from bleeding out in the polar view
            self.images_dict = HexrdConfig().images_dict

            # Update the intensity corrections. They'll be used later.
            self.update_intensity_corrections()

        self.warp_dict = {}

        self.raw_img = None
        self.snipped_img = None
        self.computation_img = None
        self.display_image = None

        # Cache this and invalidate it when needed
        self._corr_field_polar_cached = None

        self.snip_background = None
        self.erosion_mask = None

        self.update_angular_grid()

        HexrdConfig().overlay_distortions_modified.connect(
            self.invalidate_corr_field_polar_cache)
        HexrdConfig().polar_tth_distortion_overlay_changed.connect(
            self.invalidate_corr_field_polar_cache)

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
        # This images_dict sometimes gets modified by external callers,
        # such as when a waterfall plot is created. So we need to make
        # sure that everything that needs to be updated gets updated
        # here.
        self._images_dict = v

        # 0 is a better fill value because it results in fewer nans in
        # the final image.
        HexrdConfig().apply_panel_buffer_to_images(self._images_dict, 0)

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
            angles, _ = panel.cart_to_angles(border, tvec_s=self.instr.tvec)
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
        for key in self.detectors:
            borders[key] = self.detector_borders(key)

        return borders

    def create_warp_image(self, det):
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

    def invalidate_corr_field_polar_cache(self):
        self._corr_field_polar_cached = None

    def create_corr_field_polar(self):
        if self._corr_field_polar_cached is not None:
            return self._corr_field_polar_cached

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

        self._corr_field_polar_cached = corr_field_polar
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
    def warp_mask(self):
        return self.raw_img.mask

    def apply_image_processing(self):
        img = self.raw_img.data
        img = self.apply_snip(img)

        # Always apply intensity corrections after snip
        img = self.apply_intensity_corrections(img)

        # cache this step so we can just re-apply masks if needed
        self.snipped_img = img

        # Apply the masks before the polar_tth_distortion, because the
        # masks should also be distorted as well.

        # We only apply "visible" masks to the display image
        img = self.apply_tth_distortion(img)
        disp_img = self.apply_visible_masks(img)
        self.display_image = disp_img

        # Both "visible" and "boundary" masks are applied to the
        # computational image
        comp_img = self.apply_boundary_masks(disp_img)
        self.computation_img = comp_img

    def apply_snip(self, img):
        # do SNIP if requested
        img = img.copy()
        if HexrdConfig().polar_apply_snip1d:
            # !!! Fast snip1d (ndimage) cannot handle nans
            no_nan_methods = [SnipAlgorithmType.Fast_SNIP_1D]

            if HexrdConfig().polar_snip1d_algorithm not in no_nan_methods:
                img[self.warp_mask] = np.nan

            # Perform the background subtraction
            self.snip_background = run_snip1d(img)
            img -= self.snip_background

            # FIXME: the erosion should be applied as a mask,
            #        NOT done inside snip computation!
            if HexrdConfig().polar_apply_erosion:
                niter = HexrdConfig().polar_snip1d_numiter
                structure = footprint_rectangle((
                    1,
                    int(np.ceil(2.25*niter*snip_width_pixels()))
                ))
                mask = binary_erosion(~self.raw_img.mask, structure)
                img[~mask] = np.nan
                self.erosion_mask = mask
            else:
                self.erosion_mask = None
        else:
            self.snip_background = None
            self.erosion_mask = None

        return img

    def apply_intensity_corrections(self, img):
        if not HexrdConfig().any_intensity_corrections:
            # No corrections
            return img

        # Warp the intensity corrections to polar, mean them, and apply
        intensity_corrections = HexrdConfig().intensity_corrections_dict

        output = {}
        for det_key, panel in self.detectors.items():
            corrections = intensity_corrections[det_key]
            output[det_key] = self.warp_image(corrections, panel)

        stacked = np.ma.stack(output.values()).filled(np.nan)

        # It's okay to have all nan-slices here, but it produces a warning.
        # Just ignore the warning.
        with ignore_warnings(RuntimeWarning):
            # In case there are overlapping detectors, we do nanmean for
            # the intensities instead of nansum. This would produce a
            # somewhat more reasonable intensity.
            correction_field = np.nanmean(stacked, axis=0)

        img *= correction_field

        if HexrdConfig().intensity_subtract_minimum:
            img -= np.nanmin(img)

        return img

    def apply_visible_masks(self, img):
        # Apply user-specified masks if they are present
        from hexrdgui.masking.mask_manager import MaskManager
        img = img.copy()
        total_mask = self.warp_mask
        for mask in MaskManager().masks.values():
            if mask.type == MaskType.threshold or not mask.visible:
                continue
            mask_arr = mask.get_masked_arrays(ViewType.polar, self.instr)
            total_mask = np.logical_or(total_mask, ~mask_arr)
        if (tm := MaskManager().threshold_mask) and tm.visible:
            lt_val, gt_val = tm.data
            lt_mask = img < lt_val
            gt_mask = img > gt_val
            mask = np.logical_or(lt_mask, gt_mask)
            total_mask = np.logical_or(total_mask, mask)
        img[total_mask] = np.nan

        return img

    def apply_boundary_masks(self, img):
        # Apply user-specified masks if they are present
        from hexrdgui.masking.mask_manager import MaskManager
        img = img.copy()
        total_mask = self.warp_mask
        for mask in MaskManager().masks.values():
            if mask.type == MaskType.threshold or not mask.show_border:
                continue
            mask_arr = mask.get_masked_arrays(ViewType.polar, self.instr)
            total_mask = np.logical_or(total_mask, ~mask_arr)
        img[total_mask] = np.nan

        return img

    def reapply_masks(self):
        # This will only re-run the final steps of the processing...
        if self.snipped_img is None:
            return

        # Apply the masks before the polar_tth_distortion, because the
        # masks should also be distorted as well.

        # We only apply "visible" masks to the display image
        img = self.apply_tth_distortion(self.snipped_img)
        disp_img = self.apply_visible_masks(img)
        self.display_image = disp_img

        # Both "visible" and "boundary" masks are applied to the
        # computational image
        comp_img = self.apply_boundary_masks(disp_img)
        self.computation_img = comp_img

    @property
    def img(self):
        return self.computation_img

    @property
    def display_img(self):
        return self.display_image

    def warp_all_images(self):
        self.reset_cached_distortion_fields()

        # Create the warped image for each detector
        for det in self.detectors:
            self.create_warp_image(det)

        # Generate the final image
        self.generate_image()

    def update_intensity_corrections(self):
        if HexrdConfig().any_intensity_corrections:
            HexrdConfig().create_intensity_corrections_dict()

    def update_detectors(self, detectors):
        self.reset_cached_distortion_fields()

        # If there are intensity corrections and the detector transform
        # has been modified, we need to update the intensity corrections.
        self.update_intensity_corrections()

        # First, convert to the "None" angle convention
        iconfig = HexrdConfig().instrument_config_none_euler_convention

        for det in detectors:
            t_conf = iconfig['detectors'][det]['transform']
            self.instr.detectors[det].tvec = t_conf['translation']
            self.instr.detectors[det].tilt = t_conf['tilt']

            # Update the individual detector image
            self.create_warp_image(det)

        # Generate the final image
        self.generate_image()

    def reset_cached_distortion_fields(self):
        # These are only reset so that other parts of the code
        # will not use them while we are generating new ones.
        # They are actually still cached elsewhere.
        HexrdConfig().polar_corr_field_polar = None
        HexrdConfig().polar_angular_grid = None


# `_project_on_detector_plane()` is one of the functions that takes the
# longest when generating the polar view.
# Memoize this so we can regenerate the polar view faster
@memoize(maxsize=16)
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
