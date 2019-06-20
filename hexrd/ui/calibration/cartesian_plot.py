import numpy as np
import pickle

from hexrd.gridutil import cellIndices
from hexrd import instrument

from hexrd.ui import resource_loader
from hexrd.ui.hexrd_config import HexrdConfig

import hexrd.ui.resources.materials

from skimage import transform as tf
from skimage.exposure import equalize_adapthist

from .display_plane import DisplayPlane


def cartesian_image():
    iconfig = HexrdConfig().instrument_config
    images_dict = HexrdConfig().images()
    plane_data = HexrdConfig().active_material.planeData

    instr = instrument.HEDMInstrument(instrument_config=iconfig)

    # Make sure each key in the image dict is in the panel_ids
    if images_dict.keys() != instr._detectors.keys():
        msg = ('Images do not match the panel ids!\n' +
               'Images: ' + str(list(images_dict.keys())) + '\n' +
               'PanelIds: ' + str(list(instr._detectors.keys())))
        raise Exception(msg)

    dplane = DisplayPlane()
    dpanel = make_dpanel(dplane, instr)

    ring_data = add_rings(dpanel, plane_data)

    img = plot_dplane(dpanel, images_dict, instr, dplane)

    # Rescale the data to match the scale of the original dataset
    # TODO: try to get create_calibration_image to not rescale the
    # result to be between 0 and 1 in the first place so this will
    # not be necessary.
    images = images_dict.values()
    minimum = min([x.min() for x in images])
    maximum = max([x.max() for x in images])
    img = np.interp(img, (img.min(), img.max()), (minimum, maximum))

    return img, ring_data


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
    ring_data = []
    if not HexrdConfig().show_rings:
        # We are not supposed to add rings
        return ring_data

    selected_rings = HexrdConfig().selected_rings
    if selected_rings:
        # We should only get specific values
        tth = plane_data.getTTh()
        tth = [tth[i] for i in selected_rings]
        delta_tth = np.degrees(plane_data.tThWidth)

        ring_angs, ring_xys = dpanel.make_powder_rings(
            tth, delta_tth=delta_tth, delta_eta=1)
    else:
        ring_angs, ring_xys = dpanel.make_powder_rings(
            plane_data, delta_eta=1)

    for ring in ring_xys:
        ring_data.append(dpanel.cartToPixel(ring))

    return ring_data


def plot_dplane(dpanel, images_dict, instr, dplane):
    nrows_map = dpanel.rows
    ncols_map = dpanel.cols
    warped = np.zeros((nrows_map, ncols_map))
    for detector_id in images_dict.keys():
        img = images_dict[detector_id]

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
