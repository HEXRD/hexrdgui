import h5py
import os
import copy
import itertools

import numpy as np
import psutil

from hexrd.gridutil import cellIndices

from hexrd.ui.constants import ViewType
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import update_overlay_data

from skimage import transform as tf

from .display_plane import DisplayPlane


def cartesian_viewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = ViewType.cartesian
        self.instr = create_hedm_instrument()
        self.images_dict = HexrdConfig().current_images_dict()

        # Perform some checks before proceeding
        self.check_keys_match()
        self.check_angles_feasible()

        self.pixel_size = HexrdConfig().cartesian_pixel_size
        self.warp_dict = {}
        self.detector_corners = {}

        dist = HexrdConfig().cartesian_virtual_plane_distance
        dplane_tvec = np.array([0., 0., -dist])

        rotate_x = HexrdConfig().cartesian_plane_normal_rotate_x
        rotate_y = HexrdConfig().cartesian_plane_normal_rotate_y

        dplane_tilt = np.radians(np.array(([rotate_x, rotate_y, 0.])))

        self.dplane = DisplayPlane(tvec=dplane_tvec, tilt=dplane_tilt)
        self.make_dpanel()

        # Check that the image size won't be too big...
        self.check_size_feasible()

        self.plot_dplane()

    def check_keys_match(self):
        # Make sure each key in the image dict is in the panel_ids
        if self.images_dict.keys() != self.instr._detectors.keys():
            msg = ('Images do not match the panel ids!\n'
                   f'Images: {str(list(self.images_dict.keys()))}\n'
                   f'PanelIds: {str(list(self.instr._detectors.keys()))}')
            raise Exception(msg)

    def check_angles_feasible(self):
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

    def check_size_feasible(self):
        available_mem = psutil.virtual_memory().available
        img_dtype = np.float64
        dtype_size = np.dtype(img_dtype).itemsize

        mem_usage = self.dpanel.rows * self.dpanel.cols * dtype_size
        # Extra memory we probably need for other things...
        mem_extra_buffer = 1e7
        mem_usage += mem_extra_buffer
        if mem_usage > available_mem:

            def format_size(size):
                sizes = [
                    ('TB', 1e12),
                    ('GB', 1e9),
                    ('MB', 1e6),
                    ('KB', 1e3),
                    ('B', 1)
                ]
                for s in sizes:
                    if size > s[1]:
                        return f'{round(size / s[1], 2)} {s[0]}'

            msg = 'Not enough memory for Cartesian plot\n'
            msg += f'Memory available: {format_size(available_mem)}\n'
            msg += f'Memory required: {format_size(mem_usage)}'
            raise Exception(msg)

    def make_dpanel(self):
        self.dpanel_sizes = self.dplane.panel_size(self.instr)
        self.dpanel = self.dplane.display_panel(self.dpanel_sizes,
                                                self.pixel_size,
                                                self.instr.beam_vector)

    @property
    def extent(self):
        # We might want to use self.dpanel.col_edge_vec and
        # self.dpanel.row_edge_vec here instead.
        # !!! recall that extents are (left, right, bottom, top)
        x_lim = self.dpanel.col_dim / 2
        y_lim = self.dpanel.row_dim / 2
        return -x_lim, x_lim, -y_lim, y_lim

    def update_overlay_data(self):
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

    def plot_dplane(self):
        # Cache the image max and min for later use
        images = self.images_dict.values()
        self.min = min([x.min() for x in images])
        self.max = max([x.max() for x in images])

        # Create the warped image for each detector
        for detector_id in self.images_dict.keys():
            self.create_warped_image(detector_id)

        # Generate the final image
        self.generate_image()

    def detector_borders(self, det):
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

            def out_of_frame(p):
                # Check if point p is out of the frame
                return (not x_range[0] <= p[0] <= x_range[1] or
                        not y_range[0] <= p[1] <= y_range[1])

            def move_point_into_frame(p, p2):
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
    def all_detector_borders(self):
        borders = {}
        for det in self.images_dict.keys():
            borders[det] = self.detector_borders(det)

        return borders

    def create_warped_image(self, detector_id):
        img = self.images_dict[detector_id]
        panel = self.instr._detectors[detector_id]

        if HexrdConfig().apply_pixel_solid_angle_correction:
            img = img / panel.pixel_solid_angles

        # map corners
        corners = np.vstack(
            [panel.corner_ll,
             panel.corner_lr,
             panel.corner_ur,
             panel.corner_ul,
             ]
        )
        mp = panel.map_to_plane(corners, self.dplane.rmat,
                                self.dplane.tvec)

        col_edges = self.dpanel.col_edge_vec
        row_edges = self.dpanel.row_edge_vec
        j_col = cellIndices(col_edges, mp[:, 0])
        i_row = cellIndices(row_edges, mp[:, 1])

        src = np.vstack([j_col, i_row]).T

        # Save detector corners in pixel coordinates
        self.detector_corners[detector_id] = src

        dst = panel.cartToPixel(corners, pixels=True)
        dst = dst[:, ::-1]

        tform3 = tf.ProjectiveTransform()
        tform3.estimate(src, dst)

        res = tf.warp(img, tform3,
                      output_shape=(self.dpanel.rows, self.dpanel.cols))
        self.warp_dict[detector_id] = res
        return res

    def generate_image(self):
        img = np.zeros((self.dpanel.rows, self.dpanel.cols))
        for key in self.images_dict.keys():
            img += self.warp_dict[key]

        # In case there were any nans...
        nan_mask = np.isnan(img)
        img = np.ma.masked_array(img, mask=nan_mask, fill_value=0.)

        # Rescale the data to match the scale of the original dataset
        # TODO: try to get create_calibration_image to not rescale the
        # result to be between 0 and 1 in the first place so this will
        # not be necessary.
        img = np.interp(img, (img.min(), img.max()), (self.min, self.max))

        # Re-mask...
        self.img = np.ma.masked_array(img, mask=nan_mask, fill_value=0.)

    def update_detector(self, det):
        # First, convert to the "None" angle convention
        iconfig = HexrdConfig().instrument_config_none_euler_convention

        t_conf = iconfig['detectors'][det]['transform']
        self.instr.detectors[det].tvec = t_conf['translation']
        self.instr.detectors[det].tilt = t_conf['tilt']

        # Update the individual detector image
        self.create_warped_image(det)

        # Generate the final image
        self.generate_image()

    def write_image(self, filename='cartesian_image.npz'):
        # Prepare the data to write out
        data = {
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
            f = h5py.File(filename, 'w')
            for key, value in data.items():
                f.create_dataset(key, data=value)
