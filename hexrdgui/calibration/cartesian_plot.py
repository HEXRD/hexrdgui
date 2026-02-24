from __future__ import annotations

import h5py
import os
import copy
import itertools
from typing import Any, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from hexrd.instrument import HEDMInstrument
import psutil

from hexrd.gridutil import cellIndices

from hexrdgui.constants import ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays import update_overlay_data
from hexrdgui.utils import format_memory_int

from skimage import transform as tf

from .display_plane import DisplayPlane


def cartesian_viewer() -> 'InstrumentViewer':
    return InstrumentViewer()


def get_xray_propagation_sign(instr: HEDMInstrument) -> Any:
    return np.sign(instr.beam_vector[2])


class InstrumentViewer:

    def __init__(self) -> None:
        self.type = ViewType.cartesian
        self.instr = create_hedm_instrument()
        self.images_dict = HexrdConfig().images_dict

        # Set invalid pixels to be nan
        HexrdConfig().apply_panel_buffer_to_images(self.images_dict)

        self.img: np.ma.MaskedArray | None = None

        # Perform some checks before proceeding
        self.check_keys_match()
        self.check_angles_feasible()

        self.pixel_size = HexrdConfig().cartesian_pixel_size
        self.warp_dict: dict[str, Any] = {}
        self.detector_corners: dict[str, Any] = {}

        dist = HexrdConfig().cartesian_virtual_plane_distance
        sgn = get_xray_propagation_sign(self.instr)
        dplane_tvec = np.array([0.0, 0.0, sgn * dist])

        rotate_x = HexrdConfig().cartesian_plane_normal_rotate_x
        rotate_y = HexrdConfig().cartesian_plane_normal_rotate_y

        dplane_tilt = np.radians(np.array(([rotate_x, rotate_y, 0.0])))

        self.dplane = DisplayPlane(tvec=dplane_tvec, tilt=dplane_tilt)
        self.update_panel_sizes()
        self.make_dpanel()

        # Check that the image size won't be too big...
        self.check_size_feasible()

        self.plot_dplane()

    def check_keys_match(self) -> None:
        # Make sure each key in the image dict is in the panel_ids
        if self.images_dict.keys() != self.instr._detectors.keys():
            msg = (
                'Images do not match the panel ids!\n'
                f'Images: {str(list(self.images_dict.keys()))}\n'
                f'PanelIds: {str(list(self.instr._detectors.keys()))}'
            )
            raise Exception(msg)

    def check_angles_feasible(self) -> None:
        max_angle = 120.0

        # Check all combinations of detectors. If any have an angle
        # between them that is greater than the max, raise an exception.
        combos = itertools.combinations(self.instr._detectors.items(), 2)
        bad_combos = []
        acos = np.arccos
        norm = np.linalg.norm
        for x, y in combos:
            n1, n2 = x[1].normal, y[1].normal
            angle = np.degrees(acos(np.dot(n1, n2) / norm(n1) / norm(n2)))
            if angle > max_angle:
                bad_combos.append(((x[0], y[0]), angle))

        if bad_combos:
            msg = 'Cartesian plot not feasible\n'
            msg += 'Angle between detectors is too large\n'
            msg += '\n'.join([f'{x[0]}: {x[1]}' for x in bad_combos])
            raise Exception(msg)

    def check_size_feasible(self) -> None:
        available_mem = psutil.virtual_memory().available
        img_dtype = np.float64
        dtype_size = np.dtype(img_dtype).itemsize

        mem_usage = self.dpanel.rows * self.dpanel.cols * dtype_size
        # Extra memory we probably need for other things...
        mem_extra_buffer = 1e7
        mem_usage += mem_extra_buffer
        if mem_usage > available_mem:
            msg = 'Not enough memory for Cartesian plot\n'
            msg += f'Memory available: {format_memory_int(available_mem)}\n'
            msg += f'Memory required: {format_memory_int(mem_usage)}'
            raise Exception(msg)

    def update_panel_sizes(self) -> None:
        self.dpanel_sizes = self.dplane.panel_size(self.instr)

    def make_dpanel(self) -> None:
        self.dpanel = self.dplane.display_panel(
            self.dpanel_sizes,  # type: ignore[arg-type]
            self.pixel_size,
            self.instr.beam_vector,
            self.instr.source_distance,
        )
        self.dpanel.name = 'dpanel'
        self.dpanel._distortion = FakeDistortionObject(self.dpanel, self.instr)

    @property
    def extent(self) -> tuple[float, float, float, float]:
        # We might want to use self.dpanel.col_edge_vec and
        # self.dpanel.row_edge_vec here instead.
        # !!! recall that extents are (left, right, bottom, top)
        x_lim = self.dpanel.col_dim / 2
        y_lim = self.dpanel.row_dim / 2
        return -x_lim, x_lim, -y_lim, y_lim

    @property
    def images_dict(self) -> dict[str, Any]:
        return self._images_dict

    @images_dict.setter
    def images_dict(self, v: dict[str, Any]) -> None:
        self._images_dict = v

        # Cache the image min and max for later use
        self.min = min(x.min() for x in v.values())
        self.max = max(x.max() for x in v.values())

    def update_overlay_data(self) -> None:
        if not HexrdConfig().show_overlays:
            # Nothing to do
            return

        # must update self.dpanel from HexrdConfig
        self.pixel_size = HexrdConfig().cartesian_pixel_size
        self.make_dpanel()

        # The overlays for the Cartesian view are made via a fake
        # instrument with a single detector.
        # Make a copy of the instrument and modify.
        temp_instr = copy.deepcopy(self.instr)
        temp_instr._detectors.clear()
        temp_instr._detectors['dpanel'] = self.dpanel

        update_overlay_data(temp_instr, self.type)

    def plot_dplane(self) -> None:
        # Create the warped image for each detector
        for detector_id in self.images_dict.keys():
            self.create_warped_image(detector_id)

        # Generate the final image
        self.generate_image()

    def detector_borders(self, det: str) -> list[tuple[list[Any], list[Any]]]:
        corners = self.detector_corners.get(det, [])

        # These corners are in pixel coordinates. Convert to Cartesian.
        # Swap x and y first.
        corners = [[y, x] for x, y in corners]
        corners = self.dpanel.pixelToCart(corners)

        x_vals = [x[0] for x in corners]
        y_vals = [x[1] for x in corners]

        if x_vals and y_vals:
            # Double each set of points.
            # This is so that if a point is moved, it won't affect the
            # other line sharing this point.
            x_vals = [x for x in x_vals for _ in (0, 1)]
            y_vals = [y for y in y_vals for _ in (0, 1)]

            # Move the first point to the back to complete the line
            x_vals += [x_vals.pop(0)]
            y_vals += [y_vals.pop(0)]

            # Make sure all points are inside the frame.
            # If there are points outside the frame, move them inside.
            extent = self.extent
            x_range = (extent[0], extent[1])
            y_range = (extent[2], extent[3])

            def out_of_frame(p: list[float]) -> bool:
                # Check if point p is out of the frame
                return (
                    not x_range[0] <= p[0] <= x_range[1]
                    or not y_range[0] <= p[1] <= y_range[1]
                )

            def move_point_into_frame(p: list[float], p2: list[float]) -> None:
                # Make sure we don't divide by zero
                if p2[0] == p[0]:
                    return

                # Move point p into the frame via its line equation
                # y = mx + b
                m = (p2[1] - p[1]) / (p2[0] - p[0])
                b = p[1] - m * p[0]
                if p[0] < x_range[0]:
                    p[0] = x_range[0]
                    p[1] = m * p[0] + b
                elif p[0] > x_range[1]:
                    p[0] = x_range[1]
                    p[1] = m * p[0] + b

                if p[1] < y_range[0]:
                    p[1] = y_range[0]
                    p[0] = (p[1] - b) / m
                elif p[1] > y_range[1]:
                    p[1] = y_range[1]
                    p[0] = (p[1] - b) / m

            i = 0
            while i < len(x_vals) - 1:
                # We look at pairs of points at a time
                p1 = [x_vals[i], y_vals[i]]
                p2 = [x_vals[i + 1], y_vals[i + 1]]

                if out_of_frame(p1):
                    # Move the point into the frame via its line equation
                    move_point_into_frame(p1, p2)
                    x_vals[i], y_vals[i] = p1[0], p1[1]

                    # Insert a pair of Nones to disconnect the drawing
                    x_vals.insert(i, None)
                    y_vals.insert(i, None)
                    i += 1

                if out_of_frame(p2):
                    # Move the point into the frame via its line equation
                    move_point_into_frame(p2, p1)
                    x_vals[i + 1], y_vals[i + 1] = p2[0], p2[1]

                i += 2

        # The border drawer expects a list of lines.
        # We only have one line here.
        return [(x_vals, y_vals)]

    @property
    def all_detector_borders(self) -> dict[str, list[tuple[list[Any], list[Any]]]]:
        borders = {}
        for det in self.images_dict.keys():
            borders[det] = self.detector_borders(det)

        return borders

    def create_warped_image(self, detector_id: str) -> np.ndarray:
        img = self.images_dict[detector_id]
        panel = self.instr._detectors[detector_id]

        # map corners
        corners = np.vstack(
            [
                panel.corner_ll,
                panel.corner_lr,
                panel.corner_ur,
                panel.corner_ul,
            ]
        )
        mp = panel.map_to_plane(corners, self.dplane.rmat, self.dplane.tvec)

        col_edges = self.dpanel.col_edge_vec
        row_edges = self.dpanel.row_edge_vec
        j_col = cellIndices(col_edges, mp[:, 0])
        i_row = cellIndices(row_edges, mp[:, 1])

        src = np.vstack([j_col, i_row]).T

        # Save detector corners in pixel coordinates
        self.detector_corners[detector_id] = src

        dst = panel.cartToPixel(corners, pixels=True)
        dst = dst[:, ::-1]

        tform3 = tf.ProjectiveTransform.from_estimate(src, dst)

        res = tf.warp(
            img,
            tform3,
            output_shape=(self.dpanel.rows, self.dpanel.cols),
            preserve_range=True,
            cval=np.nan,
        )
        nan_mask = np.isnan(res)

        self.warp_dict[detector_id] = np.ma.masked_array(
            res,
            mask=nan_mask,
            fill_value=0,
        )

        return res

    @property
    def display_img(self) -> Any:
        return self.img

    def generate_image(self) -> None:
        img = np.zeros((self.dpanel.rows, self.dpanel.cols))
        always_nan = np.ones(img.shape, dtype=bool)
        for key in self.images_dict.keys():
            # Use zeros when summing, but identify pixels that
            # are nans in all images and set those to nan.
            warp_img = self.warp_dict[key]
            img += warp_img.filled(0)
            always_nan = np.logical_and(always_nan, warp_img.mask)

        img[always_nan] = np.nan

        # In case there were any nans...
        nan_mask = np.isnan(img)
        self.img = np.ma.masked_array(img, mask=nan_mask, fill_value=0.0)

    def update_images_dict(self) -> None:
        if HexrdConfig().any_intensity_corrections:
            self.images_dict = HexrdConfig().images_dict

    def update_detectors(self, detectors: list[str]) -> None:
        # If there are intensity corrections and the detector transform
        # has been modified, we need to update the images dict.
        self.update_images_dict()

        # First, convert to the "None" angle convention
        iconfig = HexrdConfig().instrument_config_none_euler_convention

        for det in detectors:
            t_conf = iconfig['detectors'][det]['transform']
            self.instr.detectors[det].tvec = t_conf['translation']
            self.instr.detectors[det].tilt = t_conf['tilt']

        # If the panel size has increased, re-create the display panel.
        # This is so that interactively moving detectors outside of the
        # image will trigger a resize.
        new_panel_size = self.dplane.panel_size(self.instr)
        if (
            self.dpanel_sizes[0] < new_panel_size[0]
            or self.dpanel_sizes[1] < new_panel_size[1]
        ):
            # The panel size has increased. Let's re-create the display panel
            # We will only increase the panel size in this function.
            # Also bump up the sizes by 15% as well for better interaction.
            self.dpanel_sizes = (
                int(max(self.dpanel_sizes[0], new_panel_size[0]) * 1.15),
                int(max(self.dpanel_sizes[1], new_panel_size[1]) * 1.15),
            )
            self.make_dpanel()
            # Re-create all images
            self.plot_dplane()
        else:
            # Update the individual detector images
            for det in detectors:
                self.create_warped_image(det)

        # Generate the final image
        self.generate_image()

    def write_image(self, filename: str = 'cartesian_image.npz') -> None:
        # Prepare the data to write out
        data: dict[str, Any] = {
            'intensities': self.img,
        }

        # Delete the file if it already exists
        if os.path.exists(filename):
            os.remove(filename)

        # Check the file extension
        _, ext = os.path.splitext(filename)
        ext = ext.lower()

        if ext == '.npz':
            # If it looks like npz, save as npz
            np.savez(filename, **data)
        else:
            # Default to HDF5 format
            with h5py.File(filename, 'w') as f:
                for key, value in data.items():
                    f.create_dataset(key, data=value)


class FakeDistortionObject:
    """A fake distortion object for our fake instrument

    This maps the xys to the correct panel and applies the distortion
    """

    def __init__(self, dpanel: Any, instr: HEDMInstrument) -> None:
        self.dpanel = dpanel
        self.instr = instr

    def apply(self, xys: np.ndarray) -> np.ndarray:
        if all(x.distortion is None for x in self.instr.detectors.values()):
            # No changes
            return xys

        # First, convert to angles
        xys = xys.copy()
        angs, _ = self.dpanel.cart_to_angles(xys)

        # Project these angles on the instrument panels
        for panel in self.instr.detectors.values():
            if panel.distortion is None:
                continue

            # Convert to real panel cartesian
            these_xys = panel.angles_to_cart(angs)
            these_xys, valid = panel.clip_to_panel(these_xys)

            # Apply the distortion
            these_xys = panel.distortion.apply(these_xys)

            # Push back to angles, and then xys on the fake dpanel
            these_angs, _ = panel.cart_to_angles(these_xys)
            xys[valid] = self.dpanel.angles_to_cart(these_angs)

        return xys

    def apply_inverse(self, xys: np.ndarray) -> np.ndarray:
        if all(x.distortion is None for x in self.instr.detectors.values()):
            # No changes
            return xys

        # First, convert to angles
        xys = xys.copy()
        angs, _ = self.dpanel.cart_to_angles(xys)

        # Project these angles on the instrument panels
        for panel in self.instr.detectors.values():
            if panel.distortion is None:
                continue

            # Convert to real panel cartesian
            these_xys = panel.angles_to_cart(angs)
            these_xys, valid = panel.clip_to_panel(these_xys)

            # Apply the distortion
            these_xys = panel.distortion.apply_inverse(these_xys)

            # Push back to angles, and then xys on the fake dpanel
            these_angs, _ = panel.cart_to_angles(these_xys)
            xys[valid] = self.dpanel.angles_to_cart(these_angs)

        return xys
