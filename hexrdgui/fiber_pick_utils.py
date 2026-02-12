import numpy as np

from hexrd import constants as cnst
from hexrd.rotations import discreteFiber
from hexrd.transforms import xfcapi


def _pick_to_fiber(
    pick_coords,
    eta_ome_maps,
    map_index,
    step=0.5,
    beam_vec=None,
    chi=0.0,
    as_expmap=True,
):
    """
    Returns the orientations for the specified fiber parameters.

    Parameters
    ----------
    pick_coords : array_like
        The (2, ) list/vector containing the pick coordinates as (eta, omega)
        in DEGREES.  This corresponds to the (column, row) or (x, y) dimensions
        on the map.
    eta_ome_maps : hexrd.xrdutil.utils.EtaOmeMaps
        The eta-omega maps.
    map_index : int
        The index of the current map.
    step : scalar, optional
        The step size along the fiber in DEGREES.  The default is 0.5.
    chi : scalar, optional
        The chi angle from the associated instrument (specifically,
        `instr.chi`).  The default is 0.
    beam_vec : array_like, optional
        The beam vector of the associated instrument (specifically,
        `instr.beam_vector`).  The default is None (giving [0, 0, -1]).
    as_expmap : bool, optional
        Flag for converting the output from qauternions to exponential map.
        The default is True.

    Returns
    -------
    qfib : numpy.ndarray
        The array containing the fiber points as quaternions or exponential
        map parameters, according to the `as_expmap` kwarg.

    """
    pick_coords = np.atleast_1d(pick_coords).flatten()

    if beam_vec is None:
        beam_vec = cnst.beam_vec

    ndiv = int(np.round(360.0 / float(step)))

    # grab the planeData instance from the maps
    # !!! this should have a copy of planeData that has hkls consistent with
    #     the map data.
    pd = eta_ome_maps.planeData
    bmat = pd.latVecOps['B']

    # the crystal direction (plane normal)
    crys_dir = pd.hkls[:, map_index].reshape(3, 1)

    # the sample direction
    tth = pd.getTTh()[map_index]  # !!! in radians
    angs = np.atleast_2d(np.hstack([tth, np.radians(pick_coords)]))
    samp_dir = xfcapi.angles_to_gvec(angs, beam_vec=beam_vec, chi=chi).reshape(3, 1)

    # make the fiber
    qfib = discreteFiber(
        crys_dir, samp_dir, B=bmat, ndiv=ndiv, invert=False, csym=pd.q_sym, ssym=None
    )[0]

    if as_expmap:
        phis = 2.0 * np.arccos(qfib[0, :])
        ns = xfcapi.unit_vector(qfib[1:, :].T)
        expmaps = phis * ns.T
        return expmaps.T  # (3, ndiv)
    else:
        return qfib.T  # (4, ndiv)


def _angles_from_orientation(instr, eta_ome_maps, orientation):
    """
    Return the (eta, omega) angles for a specified orientation consistent with
    input EtaOmeMaps.

    Parameters
    ----------
    instr : hexrd.instrument.HEDMInstrument
        The instrument instance used to generate the EtaOmeMaps.
    eta_ome_maps : hexrd.xrdutil.utils.EtaOmeMaps
        The eta-omega maps.
    orientation : array_like
        Either a (3, ) or (4, ) element vector specifying an orientation.

    Raises
    ------
    RuntimeError
        If orientation has more than 4 elements.

    Returns
    -------
    simulated_angles : list
        A list with length = len(eta_ome_maps.dataStore) containing the angular
        coordinates of all valid reflections for each map.  If no valid points
        exist for a particular map, the entry contains `None`.  Otherwise,
        the entry is a (2, p) array of the (eta, omega) coordinates in DEGREES
        for the p valid reflections.

    """
    plane_data = eta_ome_maps.planeData
    excl_indices = np.where(~plane_data.exclusions)[0]
    hklDataList_reduced = np.array(plane_data.hklDataList)[excl_indices]

    # angle ranges from maps
    eta_range = (eta_ome_maps.etaEdges[0], eta_ome_maps.etaEdges[-1])
    ome_range = (eta_ome_maps.omeEdges[0], eta_ome_maps.omeEdges[-1])
    ome_period = eta_ome_maps.omeEdges[0] + np.r_[0.0, 2 * np.pi]

    # need the hklids
    hklids = [i['hklID'] for i in hklDataList_reduced]

    expmap = np.atleast_1d(orientation).flatten()
    if len(expmap) == 4:
        # have a quat; convert here
        phi = 2.0 * np.arccos(expmap[0])
        n = xfcapi.unit_vector(expmap[1:])
        expmap = phi * n
    elif len(expmap) > 4:
        raise RuntimeError("orientation must be a single exponential map or quaternion")

    grain_param_list = [
        np.hstack([expmap, cnst.zeros_3, cnst.identity_6x1]),
    ]
    sim_dict = instr.simulate_rotation_series(
        plane_data,
        grain_param_list,
        eta_ranges=[
            eta_range,
        ],
        ome_ranges=[
            ome_range,
        ],
        ome_period=ome_period,
        wavelength=None,
    )

    rids = []
    angs = []
    for sim in sim_dict.values():
        rids.append(sim[0][0])
        angs.append(sim[2][0])
    rids = np.hstack(rids)
    angs = np.vstack(angs)

    simulated_angles = []
    for rid in hklids:
        this_idx = rids == rid
        if np.any(this_idx):
            simulated_angles.append(np.degrees(np.atleast_2d(angs[this_idx, 1:])))
        else:
            simulated_angles.append(np.empty((0,)))

    return simulated_angles
