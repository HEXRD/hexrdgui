import os

import numpy as np

from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 unused import
import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure

from PySide2.QtCore import (
    QObject, QSignalBlocker, QSortFilterProxyModel, Qt, Signal
)
from PySide2.QtWidgets import QFileDialog, QSizePolicy

import hexrd.ui.constants
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.matrixutil import vecMVToSymm
from hexrd.ui.indexing.fit_grains_results_model import FitGrainsResultsModel
from hexrd.ui.ui_loader import UiLoader


class FitGrainsResultsDialog(QObject):
    finished = Signal()

    def __init__(self, data, parent=None):
        super(FitGrainsResultsDialog, self).__init__()

        self.ax = None
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.data = data
        self.data_model = FitGrainsResultsModel(data)
        self.canvas = None
        self.fig = None
        self.scatter_artist = None
        self.colorbar = None

        loader = UiLoader()
        self.ui = loader.load_file('fit_grains_results_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)
        self.ui.splitter.setStretchFactor(0, 1)
        self.ui.splitter.setStretchFactor(1, 10)

        self.setup_tableview()

        # Add column for equivalent strain
        ngrains = self.data.shape[0]
        eqv_strain = np.zeros(ngrains)
        for i in range(ngrains):
            emat = vecMVToSymm(self.data[i, 15:21], scale=False)
            eqv_strain[i] = 2.*np.sqrt(np.sum(emat*emat))/3.
        np.append(self.data, eqv_strain)

        self.setup_selectors()
        self.setup_plot()
        self.setup_connections()
        self.on_colorby_changed()

    def clear_artists(self):
        # Colorbar must be removed before the scatter artist
        if self.colorbar is not None:
            self.colorbar.remove()
            self.colorbar = None

        if self.scatter_artist is not None:
            self.scatter_artist.remove()
            self.scatter_artist = None

    def on_colorby_changed(self):
        column = self.ui.plot_color_option.currentData()
        colors = self.data[:, column]

        xs = self.data[:, 6]
        ys = self.data[:, 7]
        zs = self.data[:, 8]
        sz = matplotlib.rcParams['lines.markersize'] ** 3

        # I could not find a way to update scatter plot marker colors and
        # the colorbar mappable. So we must re-draw both from scratch...
        self.clear_artists()
        self.scatter_artist = self.ax.scatter3D(
            xs, ys, zs, c=colors, cmap=self.cmap, s=sz)
        self.colorbar = self.fig.colorbar(self.scatter_artist, shrink=0.8)
        self.fig.canvas.draw()

    def on_export_button_pressed(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export Fit-Grains Results', HexrdConfig().working_dir,
            'Output files (*.out)|All files(*.*)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            name, ext = os.path.splitext(selected_file)
            if not ext:
                selected_file += '.out'

            self.data_model.save(selected_file)

    def on_sort_indicator_changed(self, index, order):
        """Shows sort indicator for columns 0-2, hides for all others."""
        if index < 3:
            self.ui.table_view.horizontalHeader().setSortIndicatorShown(True)
            self.ui.table_view.horizontalHeader().setSortIndicator(
                index, order)
        else:
            self.ui.table_view.horizontalHeader().setSortIndicatorShown(False)

    def setup_connections(self):
        self.ui.export_button.clicked.connect(self.on_export_button_pressed)
        self.ui.plot_color_option.currentIndexChanged.connect(
            self.on_colorby_changed)
        self.ui.finished.connect(self.finished)

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

        index = self.ui.plot_color_option.findData(-1)
        self.ui.plot_color_option.setCurrentIndex(index)

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
        view.horizontalHeader().sortIndicatorChanged.connect(
            self.on_sort_indicator_changed)
        view.sortByColumn(0, Qt.AscendingOrder)
        self.ui.table_view.horizontalHeader().setSortIndicatorShown(False)

    def show(self):
        self.ui.show()


if __name__ == '__main__':
    import sys
    from PySide2.QtCore import QCoreApplication
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
    dialog.finished.connect(app.quit)
    dialog.show()
    app.exec_()
