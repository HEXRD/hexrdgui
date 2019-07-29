import signal
import sys
from PySide2.QtCore import QCoreApplication, Qt
from PySide2.QtWidgets import QApplication

from hexrd.ui.main_window import MainWindow


def main():
    # Kill the program when ctrl-c is used
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)

    window = MainWindow()
    window.ui.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
