from enum import Enum

from hexrd import constants

from matplotlib import cm

# Wavelength to kilo electron volt conversion
WAVELENGTH_TO_KEV = constants.keVToAngstrom(1.)
KEV_TO_WAVELENGTH = constants.keVToAngstrom(1.)
MAXIMUM_OMEGA_RANGE = 360

DEFAULT_CMAP = 'Greys'

UI_DARK_INDEX_NONE = 0
UI_DARK_INDEX_MEDIAN = 1
UI_DARK_INDEX_EMPTY_FRAMES = 2
UI_DARK_INDEX_AVERAGE = 3
UI_DARK_INDEX_MAXIMUM = 4
UI_DARK_INDEX_FILE = 5

UI_TRANS_INDEX_NONE = 0
UI_TRANS_INDEX_FLIP_VERTICALLY = 1
UI_TRANS_INDEX_FLIP_HORIZONTALLY = 2
UI_TRANS_INDEX_TRANSPOSE = 3
UI_TRANS_INDEX_ROTATE_90 = 4
UI_TRANS_INDEX_ROTATE_180 = 5
UI_TRANS_INDEX_ROTATE_270 = 6

UI_AGG_INDEX_NONE = 0
UI_AGG_INDEX_MAXIMUM = 1
UI_AGG_INDEX_MEDIAN = 2
UI_AGG_INDEX_AVERAGE = 3

UI_THRESHOLD_LESS_THAN = 0
UI_THRESHOLD_GREATER_THAN = 1
UI_THRESHOLD_EQUAL_TO = 2

YAML_EXTS = ['.yaml', '.yml']


class ViewType:
    raw = 'raw'
    cartesian = 'cartesian'
    polar = 'polar'
    stereo = 'stereo'


class OverlayType(Enum):
    powder = 'powder'
    laue = 'laue'
    rotation_series = 'rotation_series'


DEFAULT_EULER_ANGLE_CONVENTION = {
    'axes_order': 'xyz',
    'extrinsic': True
}

DEFAULT_WPPF_PLOT_STYLE = {
    'marker': 'o',
    's': 30,
    'facecolors': '#ffffff',
    'edgecolors': '#ff0000',
}

HEXRD_DIRECTORY_SUFFIX = '.hexrd'

BUFFER_KEY = 'buffer'

# Used to access matplotlib internals in backend_bases and
# determine which mode has been set by the navigation bar
ZOOM = 'zoom rect'
PAN = 'pan/zoom'

DOCUMENTATION_URL = 'https://hexrd-canonical.readthedocs.io/'

KNOWN_HDF5_PATHS = [
    ['ATTRIBUTES/TARGET_ORIENTED_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/PINHOLE_ORIENTED_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/PSL_FADE_CORR_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/HDR_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/CORR_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/TIME_ADJUSTED_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/PSL_IMAGE/DATA', 'DATA'],
    ['DATA', 'DATA'],
]

DEFAULT_LIMITED_CMAPS = [
    'Greys', 'inferno', 'plasma', 'viridis', 'magma', 'Reds', 'Blues']
ALL_CMAPS = sorted(i[:-2] for i in dir(cm) if i.endswith('_r'))


class LLNLTransform:
    IP2 = UI_TRANS_INDEX_FLIP_HORIZONTALLY
    IP3 = UI_TRANS_INDEX_FLIP_VERTICALLY
    IP4 = UI_TRANS_INDEX_FLIP_VERTICALLY
    PXRDIP = UI_TRANS_INDEX_FLIP_HORIZONTALLY
