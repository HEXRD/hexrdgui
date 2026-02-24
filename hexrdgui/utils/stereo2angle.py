import numpy as np

from hexrd.constants import lab_x
from hexrd.transforms.xfcapi import make_beam_rmat, angles_to_dvec


def ij2xy(ij: np.ndarray, stereo_size: int) -> np.ndarray:
    """
    simple routine to convert pixel
    coordinates to normalized coordinates

    Parameters
    ----------
    ij : numpy.ndarray
        (nx2) size of pixel coordinates
    stereo_size: int
        size of stereographic projection
        in pixels

    Returns
    -------
     numpy.ndarray
        size is same as ij. Values outside
        stereographic circle are nans
    """
    r = 0.5 * (stereo_size - 1)
    res = (ij - r) / r
    mask = np.sum(res**2, axis=1) > 1.0
    res[mask, :] = np.nan
    return res


def xy2ij(xy: np.ndarray, stereo_size: int) -> np.ndarray:
    """
    simple routine to convert normalized
    coordinate on stereo projection to
    the floating point pixel coordinate

    Parameters
    ----------
    xy : numpy.ndarray
        (nx2) size of stereographic coordinates
    stereo_size: int
        size of stereographic projection
        in pixels

    Returns
    -------
     numpy.ndarray
        size is same as xy.
    """
    r = 0.5 * (stereo_size - 1)
    return (xy + 1.0) * r


def xy2v3d(xy: np.ndarray) -> np.ndarray:
    """
    simple function to convert xy
    normalized coordinates to the
    3d vector in the lab frame

    Parameters
    ----------
    xy : numpy.ndarray
        stereographic coordinates of unit vector
        size is (nx2)

    Returns
    -------
    numpy.ndarray
        unit vector
        size is (nx3)
    """
    xy2 = np.sum(xy**2, axis=1)
    den = 1 + xy2

    vx = 2.0 * xy[:, 0] / den
    vy = 2.0 * xy[:, 1] / den
    vz = -(1.0 - xy2) / den
    return np.array([vx, vy, vz]).T


def v3d2xy(vec: np.ndarray) -> np.ndarray:
    """
    simple function to convert 3d vector
    to normalized stereographic coordinates

    Parameters
    ----------
    vec : numpy.ndarray
        stereographic coordinates of unit vector
        size is (nx3)

    Returns
    -------
    numpy.ndarray
        stereographic coordinates
        size is (nx2)
    """
    den = np.tile(1 + np.abs(vec[:, 2]), [2, 1]).T
    return vec[:, 0:2] / den


def ij2ang(ij: np.ndarray, stereo_size: int, bvec: np.ndarray) -> np.ndarray:
    """
    simple routine to convert pixel
    coordinates to angles in the beam
    frame

    Parameters
    ----------
    ij : numpy.ndarray
        pixel coordinates in sterepgraphic image
        size is (nx2)
    stereo_size : int
        size of stereographi image in pixels
    bvec: numpy.ndarray
        shape (1x3)
        can be found in HEDMInstrument.beam_vector

    Returns
    -------
    numpy.ndarray
        (tth, eta) angular coodinates (IN RADIANS)
        size is (nx2)
        NOTE: eta is returned in [0, 360] range which
        can be mapped back to whatever range the user
        specifies.

    """
    ij_cp = np.atleast_2d(ij)
    vhat_l = xy2v3d(ij2xy(ij_cp, stereo_size))

    tth = np.squeeze(np.arccos(np.dot(bvec, vhat_l.T)))

    rm = make_beam_rmat(bvec, lab_x)

    vx, vy = np.dot(rm[:, 0:2].T, vhat_l.T)
    # vx = np.dot(rm[:,0], vhat_l.T)
    # vy = np.dot(rm[:,1], vhat_l.T)
    eta = np.mod(np.squeeze(np.arctan2(vy, vx)), 2 * np.pi)

    return np.array([tth, eta]).T


def ang2ij(angs: np.ndarray, stereo_size: int, bvec: np.ndarray) -> np.ndarray:
    """
    simple routine to convert angle in beam
    frame to the pixel coordinates in the
    stereographic image

    Parameters
    ----------
    angs : numpy.ndarray
        angular coodinates (tth, eta) [IN RADIANS]
        size is (nx2)
    stereo_size : int
        size of stereographi image in pixels
    bvec: numpy.ndarray
        shape (1x3)
        can be found in HEDMInstrument.beam_vector

    Returns
    -------
    numpy.ndarray
        (tth, eta) angular coodinates
        size is (nx2)
    """
    angs_cp = np.atleast_2d(angs)
    zrs = np.zeros((angs_cp.shape[0], 1))
    vhat_l = angles_to_dvec(np.hstack((angs_cp, zrs)), beam_vec=bvec)
    return xy2ij(v3d2xy(vhat_l), stereo_size)


if __name__ == '__main__':
    """
    Example code
    """
    from matplotlib import pyplot as plt

    stereo_size = 1001

    # this variable is available in
    # HEDMInstrument.beam_vector

    bvec = np.atleast_2d(np.array([4.84809620e-01, 0.0, -8.74619707e-01]))

    i = np.linspace(0, 1000, 1001)
    X, Y = np.meshgrid(i, i)

    X = np.reshape(X, (np.prod(X.shape),))
    Y = np.reshape(Y, (np.prod(Y.shape),))

    ij = np.vstack((X, Y)).T

    # very fast code
    ang = np.degrees(ij2ang(ij, stereo_size, bvec))

    tth = np.reshape(ang[:, 0], [stereo_size, stereo_size])
    eta = np.reshape(ang[:, 1], [stereo_size, stereo_size])

    plt.figure()
    plt.imshow(tth)

    plt.figure()
    plt.imshow(eta)

    # slower one since it uses angles_to_dvec
    ij = ang2ij(ang, stereo_size, bvec)

    plt.show()
