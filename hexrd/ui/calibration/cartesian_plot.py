import copy

import numpy as np

from hexrd.gridutil import cellIndices

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import PowderLineOverlay

from skimage import transform as tf

from .display_plane import DisplayPlane


def cartesian_viewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = 'cartesian'
        self.instr = create_hedm_instrument()
        self.images_dict = HexrdConfig().current_images_dict()

        # Make sure each key in the image dict is in the panel_ids
        if self.images_dict.keys() != self.instr._detectors.keys():
            msg = ('Images do not match the panel ids!\n' +
                   'Images: ' + str(list(self.images_dict.keys())) + '\n' +
                   'PanelIds: ' + str(list(self.instr._detectors.keys())))
            raise Exception(msg)

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
        self.plot_dplane()

    def make_dpanel(self):
        self.dpanel_sizes = self.dplane.panel_size(self.instr)
        self.dpanel = self.dplane.display_panel(self.dpanel_sizes,
                                                self.pixel_size)

    def clear_rings(self):
        self.ring_data = {}

    def add_rings(self):
        self.clear_rings()

        if not HexrdConfig().show_overlays:
            # Nothing to do
            return self.ring_data

        # must update self.dpanel from HexrdConfig
        self.pixel_size = HexrdConfig().cartesian_pixel_size
        self.make_dpanel()

        for name in HexrdConfig().visible_material_names:
            mat = HexrdConfig().material(name)

            if not mat:
                # Print a warning, as this shouldn't happen
                print('Warning in InstrumentViewer.add_rings():',
                      name, 'is not a valid material')
                continue

            # The overlays for the Cartesian view are made via a fake
            # instrument with a single detector.
            # Make a copy of the instrument and modify.
            temp_instr = copy.deepcopy(self.instr)
            temp_instr._detectors.clear()
            temp_instr._detectors['dpanel'] = self.dpanel

            overlay = PowderLineOverlay(mat.planeData, temp_instr)
            self.ring_data[name] = overlay.overlay('cartesian')

        return self.ring_data

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
            x_range = (0, self.dpanel.cols)
            y_range = (0, self.dpanel.rows)

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

        # Rescale the data to match the scale of the original dataset
        # TODO: try to get create_calibration_image to not rescale the
        # result to be between 0 and 1 in the first place so this will
        # not be necessary.
        self.img = np.interp(img, (img.min(), img.max()), (self.min, self.max))

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
