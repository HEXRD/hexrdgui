import signal
import sys

from PySide2.QtCore import QCoreApplication, Qt
from PySide2.QtGui import QIcon, QPixmap
from PySide2.QtWidgets import QApplication

from hexrd.ui import resource_loader
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.main_window import MainWindow
import hexrd.ui.resources.icons


def main():
    # Kill the program when ctrl-c is used
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    QCoreApplication.setOrganizationName('hexrd')
    QCoreApplication.setApplicationName('hexrd')

    app = QApplication(sys.argv)

    # Initialize the HexrdConfig object so that it will parse arguments
    # and exit early if needed.
    HexrdConfig()

    data = resource_loader.load_resource(hexrd.ui.resources.icons,
                                         'hexrd.ico', binary=True)
    pixmap = QPixmap()
    pixmap.loadFromData(data, 'ico')
    icon = QIcon(pixmap)
    app.setWindowIcon(icon)

    window = MainWindow()
    window.set_icon(icon)
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
