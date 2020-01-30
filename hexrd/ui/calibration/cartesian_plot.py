import warnings

import numpy as np

from hexrd import instrument
from hexrd.gridutil import cellIndices

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.utils import select_merged_rings

from skimage import transform as tf
from skimage.exposure import equalize_adapthist
from skimage.exposure import rescale_intensity

from .display_plane import DisplayPlane


def cartesian_viewer():
    images_dict = HexrdConfig().current_images_dict()
    pixel_size = HexrdConfig().cartesian_pixel_size

    # HEDMInstrument expects None Euler angle convention for the
    # config. Let's get it as such.
    iconfig = HexrdConfig().instrument_config_none_euler_convention
    rme = HexrdConfig().rotation_matrix_euler()
    instr = instrument.HEDMInstrument(instrument_config=iconfig,
                                      tilt_calibration_mapping=rme)

    # Make sure each key in the image dict is in the panel_ids
    if images_dict.keys() != instr._detectors.keys():
        msg = ('Images do not match the panel ids!\n' +
               'Images: ' + str(list(images_dict.keys())) + '\n' +
               'PanelIds: ' + str(list(instr._detectors.keys())))
        raise Exception(msg)

    return InstrumentViewer(instr, images_dict, pixel_size)


class InstrumentViewer:

    def __init__(self, instr, images_dict, pixel_size):
        self.type = 'cartesian'
        self.instr = instr
        self.images_dict = images_dict
        self.pixel_size = pixel_size
        self.warp_dict = {}

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

    def generate_rings(self, plane_data):
        rings = []
        rbnds = []
        rbnd_indices = []

        selected_rings = HexrdConfig().selected_rings
        delta_tth = np.degrees(plane_data.tThWidth)
        if HexrdConfig().show_rings:
            if selected_rings:
                # We should only get specific values
                tth = plane_data.getTTh()
                tth = [tth[i] for i in selected_rings]

                ring_angs, ring_xys = self.dpanel.make_powder_rings(
                    tth, delta_tth=delta_tth, delta_eta=1)

            else:
                ring_angs, ring_xys = self.dpanel.make_powder_rings(
                    plane_data, delta_eta=1)

            for ring in ring_xys:
                rings.append(self.dpanel.cartToPixel(ring))

        if HexrdConfig().show_ring_ranges:
            indices, ranges = plane_data.getMergedRanges()

            if selected_rings:
                # This ensures the correct ranges are selected
                indices, ranges = select_merged_rings(selected_rings, indices,
                                                      ranges)

            r_lower = [r[0] for r in ranges]
            r_upper = [r[1] for r in ranges]
            l_angs, l_xyz = self.dpanel.make_powder_rings(
                r_lower, delta_tth=delta_tth, delta_eta=1)
            u_angs, u_xyz = self.dpanel.make_powder_rings(
                r_upper, delta_tth=delta_tth, delta_eta=1)
            for l, u in zip(l_xyz, u_xyz):
                rbnds.append(self.dpanel.cartToPixel(l))
                rbnds.append(self.dpanel.cartToPixel(u))
            for ind in indices:
                rbnd_indices.append(ind)
                rbnd_indices.append(ind)

        return rings, rbnds, rbnd_indices

    def add_rings(self):
        self.clear_rings()

        if HexrdConfig().show_rings:
            # must update self.dpanel from HexrdConfig
            self.pixel_size = HexrdConfig().cartesian_pixel_size
            self.make_dpanel()

        materials_list = HexrdConfig().visible_material_names
        if HexrdConfig().selected_rings:
            # Only show the active material, if it is part of the list
            active = HexrdConfig().active_material_name
            materials_list = [active] if active in materials_list else []

        for name in materials_list:
            mat = HexrdConfig().material(name)

            if not mat:
                # Print a warning, as this shouldn't happen
                print('Warning in InstrumentViewer.add_rings():',
                      name, 'is not a valid material')
                continue

            rings, rbnds, rbnd_indices = self.generate_rings(mat.planeData)

            self.ring_data[name] = {
                'ring_data': rings,
                'rbnd_data': rbnds,
                'rbnd_indices': rbnd_indices
            }

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

    def create_warped_image(self, detector_id):
        img = self.images_dict[detector_id]
        panel = self.instr._detectors[detector_id]

        if HexrdConfig().show_detector_borders:
            # Draw a border around the detector panel
            max_int = np.percentile(img, 99.95)
            # 0.5% is big enough for cartesian mode
            pbuf = int(0.005 * np.mean(img.shape))
            img[:, :pbuf] = max_int
            img[:, -pbuf:] = max_int
            img[:pbuf, :] = max_int
            img[-pbuf:, :] = max_int

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
