from __future__ import annotations

from typing import Any, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from hexrd.instrument import HEDMInstrument
    from hexrd.material import Material

from hexrd import constants
from hexrd.rotations import make_rmat_euler
from hexrd.transforms.xfcapi import angles_to_gvec, angles_to_dvec, gvec_to_xy
from hexrd.xrdutil.utils import _project_on_detector_cylinder, _dvec_to_angs


def calc_chi(
    sample_tilt: np.ndarray,
    panel: Any,
    instr_tilt: int = 0,
    origin: np.ndarray = constants.zeros_3,
) -> np.ndarray:

    rmat = make_rmat_euler(sample_tilt, 'xyz', extrinsic=True)

    nhat = np.dot(rmat, constants.lab_z)

    gvecs = get_panel_gvec(panel, chi=instr_tilt, origin=origin)

    dp = np.dot(gvecs, nhat)

    mask = np.abs(dp) > 1
    dp[mask] = np.sign(dp[mask])
    chi = np.degrees(np.arccos(dp))

    return chi.reshape(panel.shape)


def get_panel_gvec(
    panel: Any,
    chi: float = 0.0,
    origin: np.ndarray = constants.zeros_3,
) -> np.ndarray:

    ang = panel.pixel_angles(origin=origin)
    angs = np.vstack(
        (ang[0].flatten(), ang[1].flatten(), np.zeros(ang[0].flatten().shape))
    ).T

    g_vec = angles_to_gvec(
        angs, beam_vec=panel.bvec, eta_vec=panel.evec, chi=chi, rmat_c=None
    )

    return g_vec


def angles_to_chi_vecs(
    const_chi: float,
    sample_tilt: np.ndarray,
    panel: Any,
) -> np.ndarray:

    eta = np.linspace(-np.pi, np.pi, 720)
    chi = np.array([np.radians(const_chi)] * eta.shape[0])
    omg = np.zeros(eta.shape)
    angs = np.vstack((chi, eta, omg)).T

    chivec = angles_to_dvec(angs, beam_vec=constants.lab_z, eta_vec=constants.lab_x)

    return chivec


def chi_vecs_to_gvecs(
    chivec: np.ndarray,
    sample_tilt: np.ndarray,
    origin: np.ndarray = constants.zeros_3,
) -> np.ndarray:
    rmat = make_rmat_euler(sample_tilt, 'xyz', extrinsic=True)
    gvec = np.dot(rmat, chivec.T).T
    return gvec


def gvec_to_ang(
    gvec: np.ndarray,
    panel: Any,
    wavelength: float,
    origin: np.ndarray = constants.zeros_3,
) -> np.ndarray:

    bvec = panel.bvec
    sth = -np.dot(bvec, gvec.T)

    dvecs = (
        np.tile(panel.bvec / wavelength, [sth.shape[0], 1])
        + gvec * np.tile((2 * sth) / wavelength, [3, 1]).T
    )

    dvecs = dvecs / np.tile(np.linalg.norm(dvecs, axis=1), [3, 1]).T
    tth, eta = _dvec_to_angs(dvecs, panel.bvec, panel.evec)

    omg = np.zeros(
        [
            tth.shape[0],
        ]
    )

    return np.vstack((tth, eta, omg)).T


def chi_to_angs(
    const_chi: float,
    sample_tilt: np.ndarray,
    panel: Any,
    wavelength: float,
    origin: np.ndarray = constants.zeros_3,
) -> np.ndarray:

    chivecs = angles_to_chi_vecs(const_chi, sample_tilt, panel)

    gvecs = chi_vecs_to_gvecs(chivecs, sample_tilt, origin=origin)

    angs = gvec_to_ang(gvecs, panel, wavelength, origin=origin)

    return angs


def calc_chi_map(
    sample_tilt: np.ndarray, instr: HEDMInstrument
) -> dict[str, np.ndarray]:

    chi = {}
    for det_name, panel in instr.detectors.items():
        chi[det_name] = calc_chi(
            sample_tilt, panel, instr_tilt=instr.chi, origin=instr.tvec
        )

    return chi


def generate_ring_points_chi(
    const_chi: float,
    sample_tilt: np.ndarray,
    instr: HEDMInstrument,
) -> dict[str, np.ndarray]:

    xys: dict[str, np.ndarray] = {}

    for det_name, panel in instr.detectors.items():

        if panel.detector_type == 'planar':

            chivecs = angles_to_chi_vecs(const_chi, sample_tilt, panel)

            gvecs = chi_vecs_to_gvecs(chivecs, sample_tilt)

            xy_det = gvec_to_xy(
                gvecs,
                rmat_d=panel.rmat,
                rmat_s=constants.identity_3x3,
                rmat_c=constants.identity_3x3,
                tvec_d=panel.tvec,
                tvec_s=instr.tvec,
                tvec_c=constants.zeros_3,
                beam_vec=panel.bvec,
            )

        elif panel.detector_type == 'cylindrical':

            angs = chi_to_angs(const_chi, sample_tilt, panel, instr.beam_wavelength)

            xy_det, rMat_ss, valid_mask = _project_on_detector_cylinder(
                angs,
                0,
                panel.tvec,
                panel.caxis,
                panel.paxis,
                panel.radius,
                panel.physical_size,
                panel.angle_extent,
                panel.distortion,
                beamVec=panel.bvec,
                etaVec=panel.evec,
                tVec_s=instr.tvec,
                rmat_s=constants.identity_3x3,
                tVec_c=constants.zeros_3x1,
            )

        xy_det, mask = panel.clip_to_panel(xy_det, buffer_edges=False)

        xys[det_name] = xy_det

    return xys


def calc_angles_for_fiber(mat: Material, fiber_direction: Any) -> dict[str, np.ndarray]:
    sym_fib_dir = mat.unitcell.CalcStar(fiber_direction, 'r')
    nsym = sym_fib_dir.shape[0]
    hkls = mat.planeData.getHKLs()
    n = hkls.shape[0]
    n = np.min([n, 7])
    hkls = hkls[0:n, :]

    angles = np.zeros(
        [
            nsym,
        ]
    )
    angle_dict = {}
    for j in range(n):
        v = np.squeeze(hkls[j, :])
        vstr = str(v).strip('[]').replace(' ', '')
        for i in range(nsym):
            u = np.squeeze(sym_fib_dir[i, :])
            angles[i] = np.round(np.degrees(mat.unitcell.CalcAngle(u, v, 'r')), 2)
        angle_dict[vstr] = np.unique(angles)
    return angle_dict


if __name__ == '__main__':

    import cProfile
    from importlib.resources import read_text
    import pstats

    import matplotlib.pyplot as plt
    import yaml

    from hexrd import resources
    from hexrd.instrument import HEDMInstrument
    from hexrd.material import Material

    text = read_text(resources, 'tardis_reference_config.yml')
    conf = yaml.safe_load(text)

    instr = HEDMInstrument(instrument_config=conf)

    m = Material()
    angles = calc_angles_for_fiber(m, [1, 1, 0])

    const_chi = 45
    sample_tilt = np.array([0, 0, 0])

    profiler = cProfile.Profile()
    profiler.enable()

    xy = generate_ring_points_chi(const_chi, sample_tilt, instr)

    chi = calc_chi_map(sample_tilt, instr)

    profiler.disable()

    pstats.Stats(profiler).sort_stats('tottime').print_stats(3)
    pstats.Stats(profiler).sort_stats('cumtime').print_stats(3)

    '''
    %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
    DEBUGGING CODE
    %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
    '''

    for det_name, panel in instr.detectors.items():
        pix = panel.cartToPixel(xy[det_name], pixels=True)
        chi[det_name][pix[:, 0], pix[:, 1]] = np.nan

        mask = np.abs(chi[det_name] - const_chi) < 0.05
        chi[det_name][mask] = 0

    fig, ax = plt.subplots(nrows=len(instr.detectors), ncols=1)

    for ii, det_name in enumerate(instr.detectors):
        if len(instr.detectors) > 1:
            ax[ii].imshow(chi[det_name])
        else:
            ax.imshow(chi[det_name])

    plt.show()
