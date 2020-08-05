from hexrd.ui.ui_loader import UiLoader

class FitGrainsResultsDialog:

    def __init__(self, parent=None):
        # super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('fit_grains_results_dialog.ui', parent)
        #self.ui.splitter.setSizes([200, 600])
        self.ui.splitter.setStretchFactor(0, 1)
        self.ui.splitter.setStretchFactor(1, 10)


if __name__ == '__main__':
    import os
    import sys
    import numpy as np
    from PySide2.QtWidgets import QApplication
    from fit_grains_results_model import FitGrainsResultsModel

    # User specifies grains.out file
    if (len(sys.argv) < 2):
        print()
        print('Load grains.out file and display as table')
        print('Usage: python fit_grains_resuls_model.py  <path-to-grains.out>')
        print()
        sys.exit(-1)

    # print(sys.argv)
    app = QApplication(sys.argv)

    data = np.loadtxt(sys.argv[1])
    # print(data)
    model = FitGrainsResultsModel(data)

    dialog = FitGrainsResultsDialog()
    view = dialog.ui.table_view
    view.verticalHeader().hide()
    view.setModel(model)
    view.resizeColumnToContents(0)

    dialog.ui.resize(1200, 800)
    dialog.ui.show()
    app.exec_()
