import signal
import sys
import traceback

from PySide2.QtCore import QCoreApplication, Qt
from PySide2.QtGui import QIcon, QPixmap
from PySide2.QtWidgets import QApplication

from hexrd.ui import resource_loader
from hexrd.ui.main_window import MainWindow
from hexrd.ui.utils import regular_stdout_stderr
import hexrd.ui.resources.icons


def main():
    # Kill the program when ctrl-c is used
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    QCoreApplication.setOrganizationName('hexrd')
    QCoreApplication.setApplicationName('hexrd')

    app = QApplication(sys.argv)

    data = resource_loader.load_resource(hexrd.ui.resources.icons,
                                         'hexrd.ico', binary=True)
    pixmap = QPixmap()
    pixmap.loadFromData(data, 'ico')
    icon = QIcon(pixmap)
    app.setWindowIcon(icon)

    try:
        window = MainWindow()
        window.set_icon(icon)
        window.show()
    except Exception:
        # If an exception occurs, make sure we print it out to
        # regular stdout and stderr.
        with regular_stdout_stderr():
            traceback.print_exc()
        raise

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
