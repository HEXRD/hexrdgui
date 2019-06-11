import numpy as np
import pickle

from hexrd.gridutil import cellIndices
from hexrd.xrd import transforms_CAPI as xfcapi
from hexrd import instrument

from hexrd.ui import resource_loader
import hexrd.ui.resources.materials

from skimage import transform as tf
from skimage.exposure import equalize_adapthist

tvec_DFLT = np.r_[0., 0., -1000.]
tilt_DFTL = np.zeros(3)

def load_pdata(data, key, tth_max=None):
    """
    tth_max is in DEGREES
    """
    # If the pickle file was created with python2, we must use
    # latin1 encoding to read it for some reason.
    matlist = pickle.loads(data, encoding='latin1')

    pd = dict(zip([i.name for i in matlist], matlist))[key].planeData
    if tth_max is not None:
        pd.exclusions = np.zeros_like(pd.exclusions, dtype=bool)
        pd.tThMax = np.radians(tth_max)
    return pd

def load_ceo2():
    materials = resource_loader.load_resource(hexrd.ui.resources.materials,
                                              'materials.hexrd', binary=True)
    return load_pdata(materials, 'ceo2')

def make_dpanel(dplane, instr, pixel_size=0.5):
    dpanel_sizes = dplane.panel_size(instr)
    dpanel = dplane.display_panel(dpanel_sizes, pixel_size)
    return dpanel

def add_rings(dpanel, plane_data):
    ring_angs, ring_xys = dpanel.make_powder_rings(
        plane_data, delta_eta=1)
    ring_data = []
    for ring in ring_xys:
        ring_data.append(dpanel.cartToPixel(ring))

    return ring_data

def plot_dplane(dpanel, images, panel_ids, instr, dplane):
    nrows_map = dpanel.rows
    ncols_map = dpanel.cols
    warped = np.zeros((nrows_map, ncols_map))
    for i, img in enumerate(images):
        detector_id = panel_ids[i]

        max_int = np.percentile(img, 99.95)
        pbuf = 10
        img[:, :pbuf] = max_int
        img[:, -pbuf:] = max_int
        img[:pbuf, :] = max_int
        img[-pbuf:, :] = max_int
        panel = instr._detectors[detector_id]

        # map corners
        corners = np.vstack(
            [panel.corner_ll,
             panel.corner_lr,
             panel.corner_ur,
             panel.corner_ul,
             ]
        )
        mp = panel.map_to_plane(corners, dplane.rmat, dplane.tvec)

        col_edges = dpanel.col_edge_vec
        row_edges = dpanel.row_edge_vec
        j_col = cellIndices(col_edges, mp[:, 0])
        i_row = cellIndices(row_edges, mp[:, 1])

        src = np.vstack([j_col, i_row]).T
        dst = panel.cartToPixel(corners, pixels=True)
        dst = dst[:, ::-1]

        tform3 = tf.ProjectiveTransform()
        tform3.estimate(src, dst)

        warped += tf.warp(img, tform3,
                          output_shape=(dpanel.rows,
                                        dpanel.cols))

    """
    IMAGE PLOTTING AND LIMIT CALCULATION
    """
    img = equalize_adapthist(warped, clip_limit=0.1, nbins=2**16)
    return img

def create_calibration_image(config, images):
    instr = instrument.HEDMInstrument(instrument_config=config)
    panel_ids = list(instr._detectors.keys())

    dplane = DisplayPlane(tvec=tvec_DFLT)
    dpanel = make_dpanel(dplane, instr)

    plane_data = load_ceo2()

    ring_data = add_rings(dpanel, plane_data)

    img = plot_dplane(dpanel, images, panel_ids, instr, dplane)

    return img, ring_data

class DisplayPlane(object):

    def __init__(self, tilt=tilt_DFTL, tvec=tvec_DFLT):
        self.tilt = tilt
        self.rmat = xfcapi.makeDetectorRotMat(self.tilt)
        self.tvec = tvec

    def panel_size(self, instr):
        """return bounding box of instrument panels in display plane"""
        xmin_i = ymin_i = np.inf
        xmax_i = ymax_i = -np.inf
        for detector_id in instr._detectors:
            panel = instr._detectors[detector_id]
            # find max extent
            corners = np.vstack(
                [panel.corner_ll,
                 panel.corner_lr,
                 panel.corner_ur,
                 panel.corner_ul,
                 ]
            )
            tmp = panel.map_to_plane(corners, self.rmat, self.tvec)
            xmin, xmax = np.sort(tmp[:, 0])[[0, -1]]
            ymin, ymax = np.sort(tmp[:, 1])[[0, -1]]

            xmin_i = min(xmin, xmin_i)
            ymin_i = min(ymin, ymin_i)
            xmax_i = max(xmax, xmax_i)
            ymax_i = max(ymax, ymax_i)
            pass

        del_x = 2*max(abs(xmin_i), abs(xmax_i))
        del_y = 2*max(abs(ymin_i), abs(ymax_i))

        return (del_x, del_y)

    def display_panel(self, sizes, mps):

        del_x = sizes[0]
        del_y = sizes[1]

        ncols_map = int(del_x/mps)
        nrows_map = int(del_y/mps)

        display_panel = instrument.PlanarDetector(
            rows=nrows_map, cols=ncols_map,
            pixel_size=(mps, mps),
            tvec=self.tvec, tilt=self.tilt)

        return display_panel
