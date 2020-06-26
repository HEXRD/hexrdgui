import copy

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure

import numpy as np

from PySide2.QtCore import Signal, QObject, QSignalBlocker, Qt
from PySide2.QtWidgets import QFileDialog, QSizePolicy

from hexrd.instrument import GenerateEtaOmeMaps

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui.ui_loader import UiLoader
import hexrd.ui.constants


class OmeMapsViewerDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, data, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('ome_maps_viewer_dialog.ui', parent)

        self.data = data
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.norm = None

        self.setup_plot()
        self.setup_color_map()

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.active_hkl.currentIndexChanged.connect(self.update_plot)
        self.ui.export_button.pressed.connect(self.on_export_button_pressed)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def show(self):
        self.ui.show()

    def on_accepted(self):
        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

    def update_hkl_options(self):
        # This won't trigger a re-draw. Can change in the future if needed.
        hkl_indices = self.data.iHKLList
        all_hkls = self.data.planeData.getHKLs(asStr=True)
        hkls = [all_hkls[i] for i in hkl_indices]

        blocker = QSignalBlocker(self.ui.active_hkl)  # noqa: F841
        self.ui.active_hkl.clear()
        self.ui.active_hkl.addItems(hkls)

    def setup_plot(self):
        # Create the figure and axes to use
        canvas = FigureCanvas(Figure(tight_layout=True))

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        fig = canvas.figure
        ax = fig.add_subplot()
        ax.set_title('Eta Omega Maps')
        ax.set_xlabel(r'$\eta$ ($\deg$)')
        ax.set_ylabel(r'$\omega$ ($\deg$)')
        fig.canvas.set_window_title('HEXRD')
        self.ui.canvas_layout.addWidget(canvas)

        self.toolbar = NavigationToolbar(canvas, self.ui, False)
        self.ui.canvas_layout.addWidget(self.toolbar)

        # Center the toolbar
        self.ui.canvas_layout.setAlignment(self.toolbar, Qt.AlignCenter)

        self.fig = fig
        self.ax = ax
        self.canvas = canvas

    def setup_color_map(self):
        self.color_map_editor = ColorMapEditor(self, self.ui)
        self.ui.grid_layout.addWidget(self.color_map_editor.ui, 0, 0, -1, 1)
        self.update_cmap_bounds()

    def exec_(self):
        self.update_plot()
        self.ui.exec_()

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, d):
        if hasattr(self, '_data') and d == self._data:
            return

        self._data = d
        self.update_extent()
        self.update_cmap_bounds()

    @property
    def image_data(self):
        return self.data.dataStore[self.current_hkl_index]

    def update_extent(self):
        etas = np.degrees(self.data.etas)
        omes = np.degrees(self.data.omegas)
        self.extent = (etas[0], etas[-1], omes[0], omes[-1])

    def update_cmap_bounds(self):
        if not hasattr(self, 'color_map_editor'):
            return

        self.color_map_editor.update_bounds(self.image_data)

    def update_plot(self):
        fig = self.fig
        ax = self.ax

        data = self.image_data
        if isinstance(self.norm, matplotlib.colors.LogNorm):
            # The log norm can't handle NaNs. Set them to -1.
            data = copy.deepcopy(data)
            data[np.isnan(data)] = -1

        if not hasattr(self, 'im'):
            im = ax.imshow(data)
            self.im = im
        else:
            im = self.im
            im.set_data(data)

        im.set_cmap(self.cmap)
        im.set_norm(self.norm)

        im.set_extent(self.extent)
        ax.relim()
        ax.autoscale_view()
        ax.axis('auto')

        fig.canvas.draw()

    @property
    def current_hkl_index(self):
        return self.ui.active_hkl.currentIndex()

    def set_cmap(self, cmap):
        self.cmap = cmap
        self.update_plot()

    def set_norm(self, norm):
        self.norm = norm
        self.update_plot()

    def on_export_button_pressed(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export Eta Omega Maps', HexrdConfig().working_dir,
            'NPZ files (*.npz)')

        if selected_file:
            if not selected_file.endswith('.npz'):
                selected_file += '.npz'

            self.data.save(selected_file)

    def update_config(self):
        # Update all of the config with their settings from the widgets
        pass

    def update_gui(self):
        # Updates all of the widgets with their settings from the config
        self.update_hkl_options()
