import signal
import sys

from PySide2.QtCore import QCoreApplication, Qt
from PySide2.QtGui import QIcon, QPixmap
from PySide2.QtWidgets import QApplication

from hexrd.ui import resource_loader
from hexrd.ui.argument_parser import ArgumentParser
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.main_window import MainWindow
import hexrd.ui.resources.icons


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

    # Apply parsed arguments to the HexrdConfig() object
    apply_parsed_args_to_hexrd_config(parsed_args)

    data = resource_loader.load_resource(hexrd.ui.resources.icons,
                                         'hexrd.ico', binary=True)
    pixmap = QPixmap()
    pixmap.loadFromData(data, 'ico')
    icon = QIcon(pixmap)
    app.setWindowIcon(icon)

    window = MainWindow()
    window.set_icon(icon)
    window.show()

    if parsed_args.state_file is not None:
        # Load the state file
        window.load_state_file(parsed_args.state_file)

    sys.exit(app.exec_())


def apply_parsed_args_to_hexrd_config(parsed_args):
    # Map some of the parsed arguments to attributes on the HexrdConfig object.
    to_set = {
        'ncpus': 'max_cpus',
    }

    hexrd_config = HexrdConfig()
    for k, v in to_set.items():
        setattr(hexrd_config, v, getattr(parsed_args, k))


if __name__ == '__main__':
    main()
