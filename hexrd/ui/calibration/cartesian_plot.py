import numpy as np
import warnings

from hexrd import instrument
from hexrd.gridutil import cellIndices

from hexrd.ui.hexrd_config import HexrdConfig

from skimage import transform as tf
from skimage.exposure import equalize_adapthist
from skimage.exposure import equalize_hist
from skimage.exposure import rescale_intensity

from .display_plane import DisplayPlane


def cartesian_viewer():
    iconfig = HexrdConfig().instrument_config
    images_dict = HexrdConfig().current_images_dict()
    plane_data = HexrdConfig().active_material.planeData
    pixel_size = HexrdConfig().cartesian_pixel_size

    rme = HexrdConfig().rotation_matrix_euler()
    instr = instrument.HEDMInstrument(instrument_config=iconfig,
                                      tilt_calibration_mapping=rme)

    # Make sure each key in the image dict is in the panel_ids
    if images_dict.keys() != instr._detectors.keys():
        msg = ('Images do not match the panel ids!\n' +
               'Images: ' + str(list(images_dict.keys())) + '\n' +
               'PanelIds: ' + str(list(instr._detectors.keys())))
        raise Exception(msg)

    return InstrumentViewer(instr, images_dict, plane_data, pixel_size)


class InstrumentViewer:

    def __init__(self, instr, images_dict, plane_data, pixel_size):
        self.type = 'cartesian'
        self.instr = instr
        self.images_dict = images_dict
        self.plane_data = plane_data
        self.pixel_size = pixel_size

        self.dplane = DisplayPlane()
        self.make_dpanel()
        self.plot_dplane()

    def make_dpanel(self):
        dpanel_sizes = self.dplane.panel_size(self.instr)
        self.dpanel = self.dplane.display_panel(dpanel_sizes, self.pixel_size)

    def clear_rings(self):
        self.ring_data = []
        self.rbnd_data = []
        self.rbnd_indices = []

    def add_rings(self):
        self.clear_rings()
        if not HexrdConfig().show_rings:
            # We are not supposed to add rings
            return self.ring_data

        selected_rings = HexrdConfig().selected_rings
        delta_tth = np.degrees(self.plane_data.tThWidth)

        # must update self.dpanel from HexrdConfig
        self.pixel_size = HexrdConfig().cartesian_pixel_size
        self.make_dpanel()
        if selected_rings:
            # We should only get specific values
            tth = self.plane_data.getTTh()
            tth = [tth[i] for i in selected_rings]

            ring_angs, ring_xys = self.dpanel.make_powder_rings(
                tth, delta_tth=delta_tth, delta_eta=1)

        else:
            ring_angs, ring_xys = self.dpanel.make_powder_rings(
                self.plane_data, delta_eta=1)

        for ring in ring_xys:
            self.ring_data.append(self.dpanel.cartToPixel(ring))

        if HexrdConfig().show_ring_ranges:
            indices, ranges = self.plane_data.getMergedRanges()
            if selected_rings:
                ranges = [ranges[i] for i in selected_rings]

            r_lower = [r[0] for r in ranges]
            r_upper = [r[1] for r in ranges]
            l_angs, l_xyz = self.dpanel.make_powder_rings(
                r_lower, delta_tth=delta_tth, delta_eta=1)
            u_angs, u_xyz = self.dpanel.make_powder_rings(
                r_upper, delta_tth=delta_tth, delta_eta=1)
            for l, u in zip(l_xyz, u_xyz):
                self.rbnd_data.append(self.dpanel.cartToPixel(l))
                self.rbnd_data.append(self.dpanel.cartToPixel(u))
            self.rbnd_indices = []
            for ind in indices:
                self.rbnd_indices.append(ind)
                self.rbnd_indices.append(ind)

        return self.ring_data

    def plot_dplane(self):
        nrows_map = self.dpanel.rows
        ncols_map = self.dpanel.cols
        warped = np.zeros((nrows_map, ncols_map))
        for detector_id in self.images_dict.keys():
            img = self.images_dict[detector_id]

            max_int = np.percentile(img, 99.95)
            pbuf = 10
            img[:, :pbuf] = max_int
            img[:, -pbuf:] = max_int
            img[:pbuf, :] = max_int
            img[-pbuf:, :] = max_int
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
            dst = panel.cartToPixel(corners, pixels=True)
            dst = dst[:, ::-1]

            tform3 = tf.ProjectiveTransform()
            tform3.estimate(src, dst)

            warped += tf.warp(img, tform3,
                              output_shape=(self.dpanel.rows,
                                            self.dpanel.cols))

        """
        IMAGE PLOTTING AND LIMIT CALCULATION
        """
        img = warped
        #if np.issubdtype(warped.dtype, np.floating):
            # Floating types must be between -1 and 1 for equalize_adapthist
            # Negative values will not show up in the GUI for some reason
        #    warped = rescale_intensity(warped, out_range=(0., 1.))

        #with warnings.catch_warnings():
        #    warnings.simplefilter("ignore")
        #    img = equalize_adapthist(warped, clip_limit=0.1, nbins=2**16)
        img = equalize_hist(warped, nbins=2**8)

        # Rescale the data to match the scale of the original dataset
        # TODO: try to get create_calibration_image to not rescale the
        # result to be between 0 and 1 in the first place so this will
        # not be necessary.
        images = self.images_dict.values()
        minimum = min([x.min() for x in images])
        maximum = max([x.max() for x in images])
        self.img = np.interp(img, (img.min(), img.max()), (minimum, maximum))
