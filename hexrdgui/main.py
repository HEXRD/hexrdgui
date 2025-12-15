import atexit
import gc
import os
import signal
import sys

if sys.platform.startswith('darwin'):
    # Prevent crashing when using OpenBLAS
    os.environ['OPENBLAS_NUM_THREADS'] = '1'

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from hexrdgui import resource_loader
from hexrdgui.argument_parser import ArgumentParser
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.macos_fix_app_name import macos_fix_app_name
from hexrdgui.main_window import MainWindow
import hexrdgui.resources.icons


def main():
    # Create the argument parser, and parse the args. This will cause the
    # program to exit early if `--help` is passed.
    parser = ArgumentParser()
    parsed_args = parser.parse_args()

    # Kill the program when ctrl-c is used
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    QCoreApplication.setOrganizationName('hexrd')
    QCoreApplication.setApplicationName('hexrd')

    app = QApplication(sys.argv)

    if sys.platform.startswith('darwin'):
        # Fix some osx-specific stuff
        macos_fix_app_name()

    # Apply parsed arguments to the HexrdConfig() object
    apply_parsed_args_to_hexrd_config(parsed_args)

    data = resource_loader.load_resource(hexrdgui.resources.icons,
                                         'hexrd.ico', binary=True)
    pixmap = QPixmap()
    pixmap.loadFromData(data, 'ico')
    icon = QIcon(pixmap)
    app.setWindowIcon(icon)

    window = MainWindow()
    window.set_icon(icon)
    window.show()

    if parsed_args.state_file is not None:
        # Load the entrypoint file
        window.load_entrypoint_file(parsed_args.state_file)

    sys.exit(app.exec())


def apply_parsed_args_to_hexrd_config(parsed_args):
    # Map some of the parsed arguments to attributes on the HexrdConfig object.
    to_set = {
        'ncpus': 'max_cpus',
    }

    hexrd_config = HexrdConfig()
    for k, v in to_set.items():
        setattr(hexrd_config, v, getattr(parsed_args, k))


def cleanup_widgets():
    """Clean up Qt widgets before Python shutdown

    This is necessary for newer versions of Qt (>= 6.8),
    because there are some kinds of conflicts between Qt and
    the Python's cleanup systems that can cause crashes.

    This fix ensures that all Qt objects are deleted and cleaned
    up before Python performs its cleanup.
    """
    app = QApplication.instance()
    if app:
        # Close all top-level widgets
        for widget in app.topLevelWidgets()[:]:
            try:
                widget.close()
                widget.deleteLater()
            except RuntimeError:
                # Already deleted by Qt - that's fine
                pass

        try:
            # Process events to ensure deleteLater() is executed
            app.processEvents()
        except RuntimeError:
            pass

        # Force garbage collection
        gc.collect()


# Register cleanup to run before Python's atexit handlers
atexit.register(cleanup_widgets)

if __name__ == '__main__':
    main()
