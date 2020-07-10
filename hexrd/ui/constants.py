from hexrd import constants

# Wavelength to kilo electron volt conversion
WAVELENGTH_TO_KEV = constants.keVToAngstrom(1.)
KEV_TO_WAVELENGTH = constants.keVToAngstrom(1.)

DEFAULT_CMAP = 'plasma'

UI_DARK_INDEX_MEDIAN = 0
UI_DARK_INDEX_EMPTY_FRAMES = 1
UI_DARK_INDEX_AVERAGE = 2
UI_DARK_INDEX_MAXIMUM = 3
UI_DARK_INDEX_FILE = 4
UI_DARK_INDEX_NONE = 5

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

UI_ETA_MIN_DEGREES = -180.0
UI_ETA_MAX_DEGREES = 180.0

UI_THRESHOLD_LESS_THAN = 0
UI_THRESHOLD_GREATER_THAN = 1
UI_THRESHOLD_EQUAL_TO = 2

DEFAULT_EULER_ANGLE_CONVENTION = {
    'axes_order': 'xyz',
    'extrinsic': True
}

DEFAULT_POWDER_STYLE = {
    'data': {
        'c': '#00ffff',  # Cyan
        'ls': 'solid',
        'lw': 1.0
    },
    'ranges': {
        'c': '#00ff00',  # Green
        'ls': 'dotted',
        'lw': 1.0
    }
}

DEFAULT_LAUE_STYLE = {
    'data': {
        'c': '#00ffff',  # Cyan
        'marker': 'o',
        's': 2.0
    },
    'ranges': {
        'c': '#00ff00',  # Green
        'ls': 'dotted',
        'lw': 1.0
    }
}

DEFAULT_MONO_ROTATION_SERIES_STYLE = {
    'data': {
        'c': '#00ffff',  # Cyan
        'marker': 'o',
        's': 2.0
    },
    'ranges': {
        'c': '#00ff00',  # Green
        'ls': 'dotted',
        'lw': 1.0
    }
}

WORKFLOW_HEDM = 'HEDM'
WORKFLOW_LLNL = 'LLNL'
WORKFLOWS = [WORKFLOW_HEDM, WORKFLOW_LLNL]
