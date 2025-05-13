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
    const_chi = 'const_chi'


class PolarXAxisType:
    # Two theta
    tth = 'tth'
    # Q scattering vector
    q = 'q'


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

DOCUMENTATION_URL = 'https://hexrdgui.readthedocs.io/'

FIDDLE_HDF5_PATH = [
    'ATTRIBUTES/SHOT_IMAGE/ATTRIBUTES/FRAME_IMAGESFRAME_IMAGES/0/DATA',
    'DATA'
]

KNOWN_HDF5_PATHS = [
    ['ATTRIBUTES/TARGET_ORIENTED_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/PINHOLE_ORIENTED_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/PSL_FADE_CORR_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/HDR_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/CORR_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/TIME_ADJUSTED_IMAGE/DATA', 'DATA'],
    ['ATTRIBUTES/PSL_IMAGE/DATA', 'DATA'],
    ['DATA', 'DATA'],
    FIDDLE_HDF5_PATH,
]

DEFAULT_LIMITED_CMAPS = [
    'Greys', 'inferno', 'plasma', 'viridis', 'magma', 'Reds', 'Blues']
ALL_CMAPS = sorted(i[:-2] for i in dir(cm) if i.endswith('_r'))


class LLNLTransform:
    IP2 = UI_TRANS_INDEX_FLIP_HORIZONTALLY
    IP3 = UI_TRANS_INDEX_FLIP_VERTICALLY
    IP4 = UI_TRANS_INDEX_FLIP_VERTICALLY
    PXRDIP = UI_TRANS_INDEX_FLIP_HORIZONTALLY
    FIDDLE = UI_TRANS_INDEX_FLIP_HORIZONTALLY


KNOWN_DETECTOR_NAMES = {
    'TARDIS': [
        'IMAGE-PLATE-2',
        'IMAGE-PLATE-3',
        'IMAGE-PLATE-4',
    ],
    'PXRDIP': [
        'IMAGE-PLATE-B',
        'IMAGE-PLATE-D',
        'IMAGE-PLATE-L',
        'IMAGE-PLATE-R',
        'IMAGE-PLATE-U',
    ],
    'FIDDLE': [
        'CAMERA-02',
        'CAMERA-03',
        'CAMERA-05',
        'CAMERA-07',
        'CAMERA-08',
    ],
    'DEXELAS_COMPOSITE': [
        'ff1_0_0',
        # There are others, but let's just check the first one
    ],
    'EIGER_COMPOSITE': [
        'eiger_0_0',
        # There are others, but let's just check the first one
    ]
}

KEY_ROTATE_ANGLE_FINE = 0.00175
KEY_ROTATE_ANGLE_COARSE = 0.01
KEY_TRANSLATE_DELTA = 0.5


TRANSFORM_OPTIONS = [
    "None",
    "Mirror about Vertical",
    "Mirror about Horizontal",
    "Transpose",
    "Rotate 90°",
    "Rotate 180°",
    "Rotate 270°"
]

FIDDLE_FRAMES = 4

'''these are the coordinates of markers in the FIDDLE barrel
as measured on the CMM machine. the coordinates of the
corners of the detectors are defined with respect to these
coordinates
'''
FIDDLE_SMR_CMM = np.array([
[43.972019, -106.1935, 64.037102],
[-81.404037,-81.252281, 63.97414],
[-0.052700002, 0.0232, 45.5084],
[43.992062, 106.41276, 64.018463],
[-81.384537, 81.431839, 63.94804],
])

'''corners of the icarus sensors
'''
FIDDLE_ICARUS_CORNERS = np.array([
# CAMERA-2
[31.937,  5.6820002,   -8.5372839],
[57.692001,   5.5879998,   -8.6448994],
[57.737,  18.537001,   -8.5957537],
[31.987,  18.629999,   -8.488966],
# CAMERA-3
[20.086, -17.768, -8.4924898],
[45.838001,   -17.684, -8.6409159],
[45.794998,   -4.7360001,  -8.5523138],
[20.045,  -4.8189998,  -8.4037161],
# CAMERA-5
[-18.223, -53.772999,  -8.6976423],
[-5.276,  -53.859001,  -8.6674118],
[-5.0999999,  -28.108999,  -8.4557629],
[-18.051001,  -28.018, -8.485177],
# CAMERA-7
[-58.099998,  5.6259999,   -8.5679913],
[-32.348, 5.573,   -8.2579985],
[-32.321999,  18.521999,   -8.2983227],
[-58.073002,  18.573999,   -8.6142473],
# CAMERA-8
[-58.043999,  28.996,  -8.6096296],
[-32.297001,  28.989,  -8.2864666],
[-32.291, 41.937,  -8.3263569],
[-58.040001,  41.943001,   -8.6484022],
])