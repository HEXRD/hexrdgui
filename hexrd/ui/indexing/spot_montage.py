#!/usr/bin/env python

"""
Created on Wed Apr 19 15:29:27 2017

@author: bernier2
"""

import h5py
from matplotlib import pyplot as plt
import numpy as np

from hexrd.instrument import centers_of_edge_vec


"""
# UNCOMMENT IF YOU HAVE A SANE LATEX ENV AND WANT NICE FIG LABELS
#
# Options
params = {'text.usetex': True,
          'font.size': 14,
          'font.family': 'mathrm',
          'text.latex.unicode': True,
          'pgf.texsystem': 'pdflatex'
          }
plt.rcParams.update(params)
"""


def montage(X, colormap=plt.cm.inferno, show_borders=True,
            title=None, xlabel=None, ylabel=None,
            threshold=None, filename=None):
    m, n, count = np.shape(X)
    img_data = np.log(X - np.min(X) + 1)
    if threshold is None:
        threshold = 0.
    else:
        threshold = np.log(threshold - np.min(X) + 1)
    mm = int(np.ceil(np.sqrt(count)))
    nn = mm
    M = np.zeros((mm * m, nn * n))

    # colormap
    colormap.set_under('b')

    fig, ax = plt.subplots()
    fig.canvas.manager.set_window_title(title)
    image_id = 0
    for j in range(mm):
        sliceM = j * m
        ax.plot()
        for k in range(nn):
            if image_id >= count:
                img = np.nan*np.ones((m, n))
            else:
                img = img_data[:, :, image_id]
            sliceN = k * n
            M[sliceM:sliceM + m, sliceN:sliceN + n] = img
            image_id += 1
    # M = np.sqrt(M + np.min(M))
    im = ax.imshow(M, cmap=colormap, vmin=threshold, interpolation='nearest')
    if show_borders:
        xs = np.vstack(
            [np.vstack([[n*i, n*i] for i in range(nn+1)]),
             np.tile([0, nn*n], (mm+1, 1))]
        )
        ys = np.vstack(
            [np.tile([0, mm*m], (nn+1, 1)),
             np.vstack([[m*i, m*i] for i in range(mm+1)])]
        )
        for xp, yp in zip(xs, ys):
            ax.plot(xp, yp, 'c:')
    if xlabel is None:
        ax.set_xlabel(r'$2\theta$', FontSize=14)
    else:
        ax.set_xlabel(xlabel, FontSize=14)
    if ylabel is None:
        ax.set_ylabel(r'$\eta$', FontSize=14)
    else:
        ax.set_ylabel(ylabel, FontSize=14)
    ax.axis('auto')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    cbar_ax = fig.add_axes([0.875, 0.155, 0.025, 0.725])
    cbar = fig.colorbar(im, cax=cbar_ax)
    cbar.set_label(r"$\ln(intensity)$", labelpad=5)
    ax.set_xticks([])
    ax.set_yticks([])
    if title is not None:
        ax.set_title(title, FontSize=18)
    if filename is not None:
        fig.savefig(filename, bbox_inches='tight', dpi=300)
    plt.show()
    return M


def create_labels(det_key, tth_crd, eta_crd, peak_id, hkl):
    tth_crd = np.degrees(tth_crd)
    eta_crd = np.degrees(eta_crd)

    hkl_str = ' '.join([f'{int(x):^3}' for x in hkl])
    labels = {}
    labels['title'] = f"Spot {peak_id}, detector '{det_key}' ({hkl_str})"
    labels['xlabel'] = rf'$2\theta\in({tth_crd[0]:.3f}, {tth_crd[-1]:.3f})$'
    labels['ylabel'] = rf'$2\eta\in({eta_crd[0]:.3f}, {eta_crd[-1]:.3f})$'
    return labels


def extract_hkls_from_spots_data(all_spots):
    data_map = SPOTS_DATA_MAP

    hkls = {}
    for grain_id, spots in all_spots.items():
        for det_key, spot_output in spots[1].items():
            for spot_id, data in enumerate(spot_output):
                hkl_id = int(data[data_map['hkl_id']])
                if hkl_id in hkls:
                    continue

                hkl = data[data_map['hkl']]
                hkl_str = ' '.join([f'{int(x):^3}' for x in hkl])
                hkls[hkl_id] = hkl_str

    return hkls


def plot_gvec_from_spots_data(all_spots, gvec_id, threshold=0.):
    data_map = SPOTS_DATA_MAP

    breakpoint()
    for grain_id, spots in all_spots.items():
        for det_key, spot_output in spots[1].items():
            for spot_id, data in enumerate(spot_output):
                if data[data_map['hkl_id']] != gvec_id:
                    continue

                tth_edges = data[data_map['tth_edges']]
                eta_edges = data[data_map['eta_edges']]

                kwargs = {
                    'det_key': det_key,
                    'tth_crd': centers_of_edge_vec(tth_edges),
                    'eta_crd': centers_of_edge_vec(eta_edges),
                    'peak_id': data[data_map['peak_id']],
                    'hkl': data[data_map['hkl']],
                }
                labels = create_labels(**kwargs)

                intensities = np.transpose(
                    data[data_map['patch_data']],
                    (1, 2, 0)
                )

                # make montage
                montage(intensities, threshold=threshold, **labels)


def plot_gvec_from_hdf5(fname, gvec_id, threshold=0.):
    """
    """
    with h5py.File(fname, 'r') as f:
        for det_key, panel_data in f['reflection_data'].items():
            for spot_id, spot_data in panel_data.items():
                attrs = spot_data.attrs
                if attrs['hkl_id'] != gvec_id:
                    continue

                kwargs = {
                    'det_key': det_key,
                    'tth_crd': spot_data['tth_crd'],
                    'eta_crd': spot_data['eta_crd'],
                    'peak_id': attrs['peak_id'],
                    'hkl': attrs['hkl'],
                }
                labels = create_labels(**kwargs)

                intensities = np.transpose(
                        np.array(spot_data['intensities']),
                        (1, 2, 0)
                )

                # make montage
                montage(intensities, threshold=threshold, **labels)


# Keep track of which list index is each piece of data
# This is for when the full data list gets returned
SPOTS_DATA_MAP = {
    'detector_id': 0,
    'iRefl': 1,
    'peak_id': 2,
    'hkl_id': 3,
    'hkl': 4,
    'tth_edges': 5,
    'eta_edges': 6,
    'ome_eval': 7,
    'xyc_arr': 8,
    'ijs': 9,
    'frame_indices': 10,
    'patch_data': 11,
    'ang_centers_i_pt': 12,
    'xy_centers_i_pt': 13,
    'meas_angs': 14,
    'meas_xy': 15,
}


# =============================================================================
# %% CMD LINE HOOK
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="Montage of spot data for a specifed G-vector family")

    parser.add_argument('hdf5_archive',
                        help="hdf5 archive filename",
                        type=str)
    parser.add_argument('gvec_id',
                        help="unique G-vector ID from PlaneData",
                        type=int)

    parser.add_argument('-t', '--threshold',
                        help="intensity threshold",
                        type=float, default=0.)

    args = parser.parse_args()

    h5file = args.hdf5_archive
    hklid = args.gvec_id
    threshold = args.threshold

    plot_gvec_from_hdf5(h5file, hklid, threshold=threshold)
