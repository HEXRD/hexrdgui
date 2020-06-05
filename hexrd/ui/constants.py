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
