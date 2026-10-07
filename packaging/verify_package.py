"""Check that a packaged HEXRDGUI install actually works.

Run it with the bundled Python after CPack, for example:

    QT_QPA_PLATFORM=offscreen package/bin/python -I verify_package.py

It loads an image through the GUI and renders the polar view. If anything
hangs (including an error dialog nobody can click), a watchdog prints every
thread's stack and fails the run.
"""

import faulthandler
import sys
import tempfile
import time
from pathlib import Path

# Importing main applies the startup environment, just like the app does
import hexrdgui.main  # noqa: F401

# Cross-built packages (osx-arm64) are not import tested by conda-build
import hexrd.core.extensions.inverse_distortion  # noqa: F401
import hexrd.core.extensions.transforms  # noqa: F401
import hexrd.core.extensions.transforms_c_api  # noqa: F401

import h5py
import hdf5plugin
import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_file_manager import ImageFileManager
from hexrdgui.image_load_manager import ImageLoadManager
from hexrdgui.main_window import MainWindow

faulthandler.dump_traceback_later(300, exit=True)

# Keep these settings separate from a real install's
QCoreApplication.setApplicationName('hexrd-verify-package')
app = QApplication(sys.argv[:1])
window = MainWindow()
window.confirm_application_close = False
window.show()

# The loaded image keeps image.h5 open, and Windows can't delete open files
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    # An image for the default instrument, using an hdf5plugin filter
    (det,) = HexrdConfig().detectors.values()
    shape = (1, det['pixels']['rows'], det['pixels']['columns'])
    image = np.random.default_rng(0).integers(0, 1000, shape, dtype=np.uint16)
    image_path = str(Path(tmp) / 'image.h5')
    with h5py.File(image_path, 'w') as f:
        f.create_dataset('images/data', data=image, **hdf5plugin.Bitshuffle())

    # Uses the same background thread and progress dialog as the GUI
    ImageFileManager().path = ['images', 'data']
    ImageLoadManager().read_data([[image_path]], ui_parent=window.ui)

    # Stop writing output to the closed progress dialog
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__

window.image_mode_widget.set_image_mode_widget_tab(ViewType.polar)
canvas = window.ui.image_tab_widget.image_canvases[0]
while not canvas.axes_images:
    QCoreApplication.processEvents()
    time.sleep(0.05)

canvas.draw()
polar = np.ma.filled(canvas.axes_images[0].get_array(), np.nan)
assert np.isfinite(polar).any(), 'polar view is empty'
print(f'OK: loaded an image and rendered the polar view {polar.shape}')
