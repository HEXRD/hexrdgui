from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from hexrd.instrument import HEDMInstrument
    from hexrd.instrument import Detector

from skimage.filters.edges import binary_erosion
from skimage.morphology import footprint_rectangle
from skimage.transform import warp

from hexrd.rotations import mapAngle
from hexrd.utils.decorators import memoize
from hexrd import constants as ct
from hexrd.xrdutil import _project_on_detector_plane, _project_on_detector_cylinder
from hexrd import instrument

from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.masking.constants import MaskType
from hexrdgui.masking.mask_manager import MaskManager
from hexrdgui.utils import SnipAlgorithmType, run_snip1d, snip_width_pixels

tvec_c = ct.zeros_3


def sqrt_scale_img(img: np.ndarray) -> np.ndarray:
    fimg = np.array(img, dtype=float)
    fimg = fimg - np.min(fimg)
    return np.sqrt(fimg)


def log_scale_img(img: np.ndarray) -> np.ndarray:
    fimg = np.array(img, dtype=float)
    fimg = fimg - np.min(fimg) + 1.0
    return np.log(fimg)


class PolarView:
    """Create (two-theta, eta) plot of detectors

    The distortion instrument is the instrument to use for tth distortion.
    It defaults to the instrument.

    eta_min and eta_max are in radians. If not provided, the ones on
    HexrdConfig() are used.
    """

    def __init__(
        self,
        instrument: HEDMInstrument | None,
        distortion_instrument: HEDMInstrument | None = None,
        eta_min: float | None = None,
        eta_max: float | None = None,
    ) -> None:

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
            self._images_dict: dict[str, np.ndarray] | None = None
        else:
            # Ensure the memoize cache is large enough for all detectors
            num_dets = len(instrument.detectors)
            project_on_detector.set_cache_maxsize(max(16, num_dets * 2))

            # Use an image dict with the panel buffers applied.
            # This keeps invalid pixels from bleeding out in the polar view
            self.images_dict = HexrdConfig().images_dict

            # Update the intensity corrections. They'll be used later.
            self.update_intensity_corrections()

        self.warp_dict: dict[str, np.ma.MaskedArray] = {}

        # Keep track of which polar view pixels are affected by each detector
        self.panel_has_data: dict[str, np.ndarray] = {}

        self.raw_img: np.ma.MaskedArray | None = None
        self.snipped_img: np.ndarray | None = None
        self.unmasked_min: float | None = None
        self.computation_img: np.ndarray | None = None
        self.display_image: np.ndarray | None = None

        # Cache this and invalidate it when needed
        self._corr_field_polar_cached: np.ma.MaskedArray | None = None
        self._pixel_lookup_cache: dict[
            str, tuple[np.ndarray, np.ndarray, np.ndarray]
        ] = {}

        self.snip_background: np.ndarray | None = None
        self.erosion_mask: np.ndarray | None = None

        self.update_angular_grid()

        HexrdConfig().overlay_distortions_modified.connect(
            self.invalidate_corr_field_polar_cache
        )
        HexrdConfig().polar_tth_distortion_overlay_changed.connect(
            self.invalidate_corr_field_polar_cache
        )

    @property
    def detectors(self) -> dict[str, Detector]:
        assert self.instr is not None
        return self.instr.detectors

    @property
    def chi(self) -> float:
        assert self.instr is not None
        return self.instr.chi

    @property
    def tvec_s(self) -> np.ndarray:
        assert self.instr is not None
        return self.instr.tvec

    @property
    def tth_min(self) -> float:
        return np.radians(HexrdConfig().polar_res_tth_min)

    @property
    def tth_max(self) -> float:
        return np.radians(HexrdConfig().polar_res_tth_max)

    @property
    def tth_range(self) -> float:
        return self.tth_max - self.tth_min

    @property
    def tth_pixel_size(self) -> float:
        return HexrdConfig().polar_pixel_size_tth

    def tth_to_pixel(self, tth: float) -> float:
        """
        convert two-theta value to pixel value (float) along two-theta axis
        """
        return np.degrees(tth - self.tth_min) / self.tth_pixel_size

    @property
    def eta_range(self) -> float:
        return self.eta_max - self.eta_min

    @property
    def eta_pixel_size(self) -> float:
        return HexrdConfig().polar_pixel_size_eta

    def eta_to_pixel(self, eta: float) -> float:
        """
        convert eta value to pixel value (float) along eta axis
        """
        return np.degrees(eta - self.eta_min) / self.eta_pixel_size

    @property
    def ntth(self) -> int:
        return int(round(np.degrees(self.tth_range) / self.tth_pixel_size))

    @property
    def neta(self) -> int:
        return int(round(np.degrees(self.eta_range) / self.eta_pixel_size))

    @property
    def shape(self) -> tuple[int, int]:
        return (self.neta, self.ntth)

    def update_angular_grid(self) -> None:
        tth_vec = (
            np.radians(self.tth_pixel_size * (np.arange(self.ntth)))
            + self.tth_min
            + 0.5 * np.radians(self.tth_pixel_size)
        )
        eta_vec = (
            np.radians(self.eta_pixel_size * (np.arange(self.neta)))
            + self.eta_min
            + 0.5 * np.radians(self.eta_pixel_size)
        )
        self._angular_grid = np.meshgrid(eta_vec, tth_vec, indexing='ij')

    @property
    def angular_grid(self) -> list[np.ndarray]:
        return self._angular_grid  # type: ignore[return-value]

    @property
    def extent(self) -> list[float]:
        ev, tv = self.angular_grid
        heps = np.radians(0.5 * self.eta_pixel_size)
        htps = np.radians(0.5 * self.tth_pixel_size)
        return [
            np.min(tv) - htps,
            np.max(tv) + htps,
            np.max(ev) + heps,
            np.min(ev) - heps,
        ]

    @property
    def eta_period(self) -> np.ndarray:
        return HexrdConfig().polar_res_eta_period

    @property
    def images_dict(self) -> dict[str, np.ndarray] | None:
        return self._images_dict

    @images_dict.setter
    def images_dict(self, v: dict[str, np.ndarray]) -> None:
        # This images_dict sometimes gets modified by external callers,
        # such as when a waterfall plot is created. So we need to make
        # sure that everything that needs to be updated gets updated
        # here.
        self._images_dict = v

        # 0 is a better fill value because it results in fewer nans in
        # the final image.
        if self._images_dict is not None:
            HexrdConfig().apply_panel_buffer_to_images(self._images_dict, 0)

        # Cache the image min and max for later use
        self.min = min(x.min() for x in v.values())
        self.max = max(x.max() for x in v.values())

    def detector_borders(self, det: str) -> list[np.ndarray]:
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
            angles, _ = panel.cart_to_angles(border, tvec_s=self.tvec_s)
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
            in_range_x = np.logical_and(x_range[0] <= border_x, border_x <= x_range[1])
            in_range_y = np.logical_and(y_range[0] <= border_y, border_y <= y_range[1])
            in_range = np.logical_and(in_range_x, in_range_y)

            # Insert nans for points far apart
            border = np.asarray(border).T[in_range].T
            big_diff = np.argwhere(np.abs(np.diff(border[1])) > max_y_distance)
            if big_diff.size != 0:
                border = np.insert(border.T, big_diff.squeeze() + 1, np.nan, axis=0).T

            borders[i] = border

        return borders

    @property
    def all_detector_borders(self) -> dict[str, list[np.ndarray]]:
        borders = {}
        for key in self.detectors:
            borders[key] = self.detector_borders(key)

        return borders

    def create_warp_image(self, det: str) -> np.ndarray:
        assert self.images_dict is not None
        img = self.images_dict[det]

        # Apply the threshold mask *before* warping, so the threshold operates
        # on raw detector intensities rather than on interpolated and
        # background-subtracted polar values (see HEXRD/hexrdgui#1689).
        # Thresholded pixels become NaN; `warp_image()` then folds them into
        # the warp mask, so they are handled by the same machinery as the
        # detector gaps (including the SNIP algorithms that cannot ingest
        # NaNs -- those see the masked `.data` fill value rather than a NaN).
        if (tm := MaskManager().threshold_mask) and tm.visible:
            lt_val, gt_val = tm.data
            # Copy so we never mutate the shared images dict.
            img = img.astype(float, copy=True)
            img[img < lt_val] = np.nan
            img[img > gt_val] = np.nan

        panel = self.detectors[det]
        self.warp_dict[det] = self.warp_image(img, panel)
        return self.warp_dict[det]

    def func_project_on_detector(self, detector: Detector) -> Callable[..., Any]:
        """
        helper function to decide which function to
        use for mapping of g-vectors to detector
        """
        if isinstance(detector, instrument.CylindricalDetector):
            return _project_on_detector_cylinder
        else:
            return _project_on_detector_plane

    def args_project_on_detector(
        self, detector: Detector
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """
        prepare the arguments to be passed for
        mapping to plane or cylinder
        """
        kwargs = {'beamVec': detector.bvec}
        arg: tuple[Any, ...] = (
            detector.rmat,
            ct.identity_3x3,
            self.chi,
            detector.tvec,
            tvec_c,
            self.tvec_s,
            detector.distortion,
        )
        if isinstance(detector, instrument.CylindricalDetector):
            arg = (
                self.chi,
                detector.tvec,
                detector.caxis,
                detector.paxis,
                detector.radius,
                detector.physical_size,
                detector.angle_extent,
                detector.distortion,
            )
            kwargs = {
                'beamVec': detector.bvec,
                'tVec_s': self.tvec_s,
                'tVec_c': tvec_c,
                'rmat_s': ct.identity_3x3,
            }

        # Add the distortion name and params to the cache key. The distortion
        # object is hashed by identity, but calibration mutates its params in
        # place, so without this the polar view returns a stale warp after a
        # refine. The name covers toggling off/switching functions. These keys
        # are popped before projecting (see `project_on_detector`).
        distortion = detector.distortion
        kwargs['_distortion_func_name'] = (
            distortion.maptype if distortion is not None else None
        )
        kwargs['_distortion_params'] = (
            np.asarray(distortion.params) if distortion is not None else None
        )

        return arg, kwargs

    def _compute_xypts(self, det_key: str) -> np.ndarray:
        panel = self.detectors[det_key]
        args, kwargs = self.args_project_on_detector(panel)
        func_projection = self.func_project_on_detector(panel)
        return project_on_detector(
            self.angular_grid, self.ntth, self.neta, func_projection, *args, **kwargs
        )

    def warp_image(self, img: np.ndarray, panel: Detector) -> np.ma.MaskedArray:
        # The first 3 arguments of this function get converted into
        # the first argument of `_project_on_detector_plane`, and then
        # the rest are just passed as *args and **kwargs.
        args, kwargs = self.args_project_on_detector(panel)
        func_projection = self.func_project_on_detector(panel)

        xypts = project_on_detector(
            self.angular_grid, self.ntth, self.neta, func_projection, *args, **kwargs
        )

        wimg = panel.interpolate_bilinear(
            xypts,
            img,
            pad_with_nans=True,
        ).reshape(self.shape)
        nan_mask = np.isnan(wimg)
        # Store as masked array
        return np.ma.masked_array(data=wimg, mask=nan_mask, fill_value=0.0)

    def _get_pixel_lookup(
        self, det_key: str
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Get cached (polar_idx, raw_rows, raw_cols) for a detector.

        These map polar pixel indices to raw detector pixel coordinates,
        reusable across all masks on the same detector.
        """
        if det_key not in self._pixel_lookup_cache:
            panel = self.detectors[det_key]
            xypts = self._compute_xypts(det_key)

            valid = ~np.isnan(xypts[:, 0])
            if not valid.any():
                empty = np.array([], dtype=int)
                self._pixel_lookup_cache[det_key] = (empty, empty, empty)
            else:
                pixel_coords = panel.cartToPixel(xypts[valid], pixels=True)
                rows = pixel_coords[:, 0]
                cols = pixel_coords[:, 1]
                idx = np.where(valid)[0]
                self._pixel_lookup_cache[det_key] = (idx, rows, cols)

        return self._pixel_lookup_cache[det_key]

    def warp_binary_mask(self, raw_mask: np.ndarray, det_key: str) -> np.ndarray:
        """Warp a binary mask from raw detector pixel space to polar.

        Uses nearest-neighbor sampling via the same coordinate mapping
        as warp_image (memoized in project_on_detector).
        """
        idx, rows, cols = self._get_pixel_lookup(det_key)

        result = np.ones(self.ntth * self.neta, dtype=bool)
        if len(idx) == 0:
            return result.reshape(self.shape)

        h, w = raw_mask.shape
        in_bounds = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)

        result[idx[in_bounds]] = raw_mask[rows[in_bounds], cols[in_bounds]]

        return result.reshape(self.shape)

    def create_polar_mask_from_raw_data(
        self,
        raw_data: list[tuple[str, np.ndarray]],
        apply_tth_distortion: bool = True,
    ) -> np.ndarray:
        """Create polar mask by rasterizing in raw space and warping.

        This avoids the coordinate-singularity bug that occurs when
        converting polygon perimeters through the beam center.

        Parameters
        ----------
        raw_data : list of (det_key, polygon_array) tuples
            Raw mask polygon data.
        apply_tth_distortion : bool
            Whether to apply tth distortion to the result.

        Returns
        -------
        np.ndarray
            Boolean array (True=unmasked, False=masked).
        """
        from hexrdgui.masking.create_raw_mask import create_raw_mask

        raw_masks = create_raw_mask(raw_data)
        polar_mask = np.ones(self.shape, dtype=bool)
        for det_key, raw_mask in raw_masks:
            if det_key not in self.detectors:
                continue
            if raw_mask.all():
                continue
            warped = self.warp_binary_mask(raw_mask, det_key)
            polar_mask &= warped

        if apply_tth_distortion and HexrdConfig().polar_tth_distortion:
            mask_float = (~polar_mask).astype(np.float64)
            distorted = self.apply_tth_distortion(mask_float)
            polar_mask = ~(np.ma.filled(distorted, 0) > 0.5)

        return polar_mask

    def invalidate_corr_field_polar_cache(self) -> None:
        self._corr_field_polar_cached = None

    def create_corr_field_polar(self) -> np.ma.MaskedArray:
        if self._corr_field_polar_cached is not None:
            return self._corr_field_polar_cached

        from hexrdgui.polar_distortion_object import PolarDistortionObject

        obj = HexrdConfig().polar_tth_distortion_object
        assert isinstance(obj, PolarDistortionObject)

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
                corr_field_polar_dict[key] = self.warp_image(corr_field[key], panel)

            corr_field_polar = np.ma.sum(
                np.ma.stack(list(corr_field_polar_dict.values())), axis=0
            )

        self._corr_field_polar_cached = corr_field_polar
        return corr_field_polar

    def apply_tth_distortion(self, pimg: np.ndarray) -> np.ndarray:
        if not HexrdConfig().polar_tth_distortion:
            # We are not applying tth distortion. Return the same image.
            return pimg

        corr_field_polar = self.create_corr_field_polar()

        # Save these so that the overlay generator may use them
        HexrdConfig().polar_corr_field_polar = corr_field_polar
        HexrdConfig().polar_angular_grid = self.angular_grid

        nr, nc = pimg.shape
        row_coords, col_coords = np.meshgrid(
            np.arange(nr), np.arange(nc), indexing='ij'
        )
        displ_field = np.array(
            [
                row_coords,
                col_coords - np.degrees(corr_field_polar) / self.tth_pixel_size,
            ]
        )

        # mask_warp = warp(pimg.mask, displ_field, mode='edge')
        image1_warp = warp(pimg, displ_field, mode='edge')

        return np.ma.array(image1_warp)  # , mask=mask_warp)

    def generate_image(self) -> None:
        self.reset_cached_distortion_fields()

        self.panel_has_data.clear()
        for det_key, array in self.warp_dict.items():
            self.panel_has_data[det_key] = np.asarray(~array.mask)

        # sum masked images in self.warp_dict using np.ma ufuncs
        #
        # !!! checked that np.ma.sum is applying logical OR across masks (JVB)
        # !!! assignment to img fills NaNs with zeros
        # !!! NOTE: cannot set `data` attribute on masked_array,
        #           but can manipulate mask
        self.raw_img = np.ma.sum(np.ma.stack(list(self.warp_dict.values())), axis=0)
        self.apply_image_processing()

    @property
    def warp_mask(self) -> np.ndarray:
        assert self.raw_img is not None
        return self.raw_img.mask  # type: ignore[return-value]

    def apply_image_processing(self) -> None:
        assert self.raw_img is not None
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
        self.unmasked_min = float(np.nanmin(img))
        disp_img = self.apply_visible_masks(img)
        self.display_image = disp_img

        # Both "visible" and "boundary" masks are applied to the
        # computational image
        comp_img = self.apply_boundary_masks(disp_img)
        self.computation_img = comp_img

    def apply_snip(self, img: np.ndarray) -> np.ndarray:
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
                structure = footprint_rectangle(
                    (1, int(np.ceil(2.25 * niter * snip_width_pixels())))
                )
                assert self.raw_img is not None
                mask = binary_erosion(~self.raw_img.mask, structure)
                img[~mask] = np.nan
                self.erosion_mask = mask
            else:
                self.erosion_mask = None
        else:
            self.snip_background = None
            self.erosion_mask = None

        return img

    def apply_intensity_corrections(self, img: np.ndarray) -> np.ndarray:
        if not HexrdConfig().any_intensity_corrections:
            # No corrections
            return img

        # Warp the intensity corrections to polar, mean them, and apply
        intensity_corrections = HexrdConfig().intensity_corrections_dict

        output = {}
        for det_key, panel in self.detectors.items():
            corrections = intensity_corrections[det_key]
            output[det_key] = self.warp_image(corrections, panel)

        stacked = np.ma.stack(list(output.values())).filled(np.nan)

        # In case there are overlapping detectors, we do nanmean for
        # the intensities instead of nansum.  All-NaN slices are expected
        # (detector gaps) and should produce NaN in the correction field.
        # We compute the mean manually instead of calling np.nanmean()
        # because the "Mean of empty slice" RuntimeWarning it emits could
        # not be reliably suppressed on all platforms (see PR #1941).
        valid_count = np.sum(~np.isnan(stacked), axis=0)
        with np.errstate(invalid='ignore', divide='ignore'):
            correction_field = np.nansum(stacked, axis=0) / valid_count

        img *= correction_field

        if HexrdConfig().intensity_subtract_minimum:
            img -= np.nanmin(img)

        return img

    @property
    def all_masks_pv_array(self) -> np.ndarray:
        return np.logical_or(
            self.visible_mask_pv_array,
            self.boundary_mask_pv_array,
        )

    @property
    def visible_mask_pv_array(self) -> np.ndarray:
        # NOTE: the threshold mask is intentionally NOT handled here. It is
        # applied to the raw detector images before warping (see
        # `create_warp_image()`), which folds it into the warp mask. That is
        # both more correct (it thresholds raw intensities) and avoids the
        # circular dependency on `self.img` that used to exist here.
        total_mask = np.zeros(self.shape, dtype=bool)
        for mask in MaskManager().masks.values():
            if mask.type == MaskType.threshold or not mask.visible:
                continue
            mask_arr = mask.get_masked_arrays(  # type: ignore[call-arg]
                ViewType.polar, self.instr, polar_view=self
            )
            total_mask = np.logical_or(total_mask, ~mask_arr)

        return total_mask

    @property
    def boundary_mask_pv_array(self) -> np.ndarray:
        total_mask = np.zeros(self.shape, dtype=bool)
        for mask in MaskManager().masks.values():
            if mask.type == MaskType.threshold or not mask.show_border:
                continue
            mask_arr = mask.get_masked_arrays(  # type: ignore[call-arg]
                ViewType.polar, self.instr, polar_view=self
            )
            total_mask = np.logical_or(total_mask, ~mask_arr)
        return total_mask

    def apply_visible_masks(self, img: np.ndarray) -> np.ndarray:
        # Apply user-specified masks if they are present
        total_mask = np.logical_or(self.warp_mask, self.visible_mask_pv_array)
        img = img.copy()
        img[total_mask] = np.nan
        return img

    def apply_boundary_masks(self, img: np.ndarray) -> np.ndarray:
        # Apply user-specified masks if they are present
        total_mask = np.logical_or(self.warp_mask, self.boundary_mask_pv_array)
        img = img.copy()
        img[total_mask] = np.nan
        return img

    def reapply_masks(self) -> None:
        # This will only re-run the final steps of the processing...
        if self.snipped_img is None:
            return

        if self.snipped_img.shape != self.shape:
            # The polar view settings changed since the last warp.
            # A full re-warp is needed; skip the stale cached images.
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
    def img(self) -> np.ndarray | None:
        return self.computation_img

    @property
    def display_img(self) -> np.ndarray | None:
        return self.display_image

    def warp_all_images(self) -> None:
        self.reset_cached_distortion_fields()

        # Create the warped image for each detector
        for det in self.detectors:
            self.create_warp_image(det)

        # Generate the final image
        self.generate_image()

    def update_intensity_corrections(self) -> None:
        if HexrdConfig().any_intensity_corrections:
            HexrdConfig().create_intensity_corrections_dict()

    def update_detectors(self, detectors: list[str]) -> None:
        self.reset_cached_distortion_fields()

        # If there are intensity corrections and the detector transform
        # has been modified, we need to update the intensity corrections.
        self.update_intensity_corrections()

        # First, convert to the "None" angle convention
        iconfig = HexrdConfig().instrument_config_none_euler_convention

        for det in detectors:
            t_conf = iconfig['detectors'][det]['transform']
            self.detectors[det].tvec = t_conf['translation']
            self.detectors[det].tilt = t_conf['tilt']

            # Update the individual detector image
            self.create_warp_image(det)

        # Invalidate the masks that match these detectors
        MaskManager().invalidate_detector_masks(detectors)

        # Generate the final image
        self.generate_image()

    def reset_cached_distortion_fields(self) -> None:
        # These are only reset so that other parts of the code
        # will not use them while we are generating new ones.
        # They are actually still cached elsewhere.
        HexrdConfig().polar_corr_field_polar = None
        HexrdConfig().polar_angular_grid = None


# `_project_on_detector_plane()` is one of the functions that takes the
# longest when generating the polar view.
# Memoize this so we can regenerate the polar view faster
@memoize(maxsize=16)
def project_on_detector(
    angular_grid: tuple[np.ndarray, np.ndarray],
    ntth: int,
    neta: int,
    func_projection: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> np.ndarray:
    # This will take `angular_grid`, `ntth`, and `neta`, and make the
    # `gvec_angs` argument with them. Then, the `gvec_args` will be passed
    # first to `_project_on_detector_plane`, along with any extra args and
    # kwargs.

    # These are only here to make the cache key distortion-aware (see
    # `args_project_on_detector`); the projection function doesn't accept them.
    kwargs.pop('_distortion_func_name', None)
    kwargs.pop('_distortion_params', None)

    dummy_ome = np.zeros((ntth * neta))

    gvec_angs = np.vstack(
        [angular_grid[1].flatten(), angular_grid[0].flatten(), dummy_ome]
    ).T

    xypts = np.nan * np.ones((len(gvec_angs), 2))
    valid_xys, rmats_s, on_plane = func_projection(gvec_angs, *args, **kwargs)
    xypts[on_plane] = valid_xys

    return xypts
