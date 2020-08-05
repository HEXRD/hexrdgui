import numpy as np

from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 unused import
import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure

from PySide2.QtCore import QSignalBlocker, QSortFilterProxyModel
from PySide2.QtWidgets import QSizePolicy

import hexrd.ui.constants
from hexrd.matrixutil import vecMVToSymm
from hexrd.ui.indexing.fit_grains_results_model import FitGrainsResultsModel
from hexrd.ui.ui_loader import UiLoader


class FitGrainsResultsDialog:

    def __init__(self, data, parent=None):
        self.ax = None
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.data = data
        self.data_model = FitGrainsResultsModel(data)
        self.canvas = None
        self.fig = None

        loader = UiLoader()
        self.ui = loader.load_file('fit_grains_results_dialog.ui', parent)
        self.ui.splitter.setStretchFactor(0, 1)
        self.ui.splitter.setStretchFactor(1, 10)

        self.setup_tableview()

        # Add column for equivalent strain
        ngrains = self.data.shape[0]
        eqv_strain = np.zeros(ngrains)
        for i in range(ngrains):
            emat = vecMVToSymm(self.data[i, 15:21], scale=False)
            eqv_strain[i]= 2.*np.sqrt(np.sum(emat*emat))/3.
        np.append(self.data, eqv_strain)

        self.setup_selectors()
        self.setup_plot()
        self.on_colorby_changed()

    def on_colorby_changed(self):
        column = self.ui.plot_color_option.currentData()
        colors = self.data[:, column]

        xs = data[:, 6]
        ys = data[:, 7]
        zs = data[:, 8]
        sz = matplotlib.rcParams['lines.markersize'] ** 3

        self.ax.clear()
        self.ax.scatter3D(xs, ys, zs, c=colors, cmap=self.cmap, s=sz)
        self.fig.canvas.draw()

    def on_sort_indicator_changed(self, index, order):
        """Shows sort indicator for columns 0-2, hides for all others."""
        if index < 3:
            self.ui.table_view.horizontalHeader().setSortIndicatorShown(True)
            self.ui.table_view.horizontalHeader().setSortIndicator(index, order)
        else:
            self.ui.table_view.horizontalHeader().setSortIndicatorShown(False)

    def setup_plot(self):
        # Create the figure and axes to use
        canvas = FigureCanvas(Figure(tight_layout=True))

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        fig = canvas.figure
        ax = fig.add_subplot(111, projection='3d')
        ax.set_xlabel('X')
        ax.set_ylabel('Y')
        ax.set_zlabel('Z')
        self.ui.canvas_layout.addWidget(canvas)

        self.fig = fig
        self.ax = ax
        self.canvas = canvas

    def setup_selectors(self):
        # Build combo boxes in code to assign columns in grains data
        blocker = QSignalBlocker(self.ui.plot_color_option)  # noqa: F841
        self.ui.plot_color_option.clear()
        self.ui.plot_color_option.addItem('Completeness', 1)
        self.ui.plot_color_option.addItem('Goodness of Fit', 2)
        self.ui.plot_color_option.addItem('Equivalent Strain', -1)
        self.ui.plot_color_option.addItem('XX Strain', 15)
        self.ui.plot_color_option.addItem('YY Strain', 16)
        self.ui.plot_color_option.addItem('ZZ Strain', 17)
        self.ui.plot_color_option.addItem('YZ Strain', 18)
        self.ui.plot_color_option.addItem('XZ Strain', 19)
        self.ui.plot_color_option.addItem('XY Strain', 20)
        self.ui.plot_color_option.setCurrentIndex(0)
        self.ui.plot_color_option.currentIndexChanged.connect(self.on_colorby_changed)

    def setup_tableview(self):
        view = self.ui.table_view

        # Subclass QSortFilterProxyModel to restrict sorting by column
        class GrainsTableSorter(QSortFilterProxyModel):
            def sort(self, column, order):
                if column > 2:
                    return
                else:
                    super().sort(column, order)

        proxy_model = GrainsTableSorter(self.ui)
        proxy_model.setSourceModel(self.data_model)
        view.verticalHeader().hide()
        view.setModel(proxy_model)
        view.resizeColumnToContents(0)

        view.setSortingEnabled(True)
        view.horizontalHeader().sortIndicatorChanged.connect(self.on_sort_indicator_changed)
        view.sortByColumn(0, Qt.AscendingOrder)
        self.ui.table_view.horizontalHeader().setSortIndicatorShown(False)


if __name__ == '__main__':
    import sys
    from PySide2.QtCore import QCoreApplication, Qt
    from PySide2.QtWidgets import QApplication

    # User specifies grains.out file
    if (len(sys.argv) < 2):
        print()
        print('Load grains.out file and display as table')
        print('Usage: python fit_grains_resuls_model.py  <path-to-grains.out>')
        print()
        sys.exit(-1)

    # print(sys.argv)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)

    data = np.loadtxt(sys.argv[1])
    # print(data)

    dialog = FitGrainsResultsDialog(data)
    dialog.ui.resize(1200, 800)
    dialog.ui.show()
    app.exec_()
